#!/usr/bin/env python3
"""Explicit read-only plan / transactional curriculum apply. Never run on startup.

URLs are read only from DATABASE_URL_UNPOOLED or a private dotenv file.
Production apply requires a reviewed plan, exact target, and verified backup.
"""
import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import curriculum
from app.db import connect
from dotenv import load_dotenv
from scripts.migrate_learning_records import direct_database_url, inspect_postgres, preflight_error_message


def private_json(path, value):
    with open(Path(path).expanduser(), 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        json.dump(value, stream, indent=2); stream.write('\n')


def verify_backup(path, expected_database, expected_tables):
    path = Path(path).expanduser()
    if not path.is_file() or not path.stat().st_size or path.stat().st_mode & 0o077:
        raise ValueError('Backup must be a nonempty private file (mode600).')
    age = time.time() - path.stat().st_mtime
    if not -300 <= age <= 24*60*60:
        raise ValueError('Backup must be freshly created within24 hours; verify its source independently.')
    result = subprocess.run(['pg_restore','--list',str(path)], capture_output=True, text=True)
    if result.returncode or not any(line and not line.startswith(';') for line in result.stdout.splitlines()):
        raise ValueError('Backup archive-list verification failed; details omitted.')
    database = re.search(r'^;\s*dbname:\s*(.+?)\s*$', result.stdout, re.MULTILINE)
    archived_tables = set(re.findall(r'\bTABLE DATA \S+ (\S+)', result.stdout))
    if not database or database.group(1) != expected_database or not set(expected_tables) <= archived_tables:
        raise ValueError('Backup database name or required table-data entries do not match this target.')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    dbmode = parser.add_mutually_exclusive_group(required=True)
    dbmode.add_argument('--sqlite', help='Explicit existing SQLite path; never initializes a database.')
    dbmode.add_argument('--postgres', action='store_true')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--env-file', help='Private dotenv file; secrets never printed.')
    parser.add_argument('--expected-host', help='Exact Neon production direct hostname (no credentials).')
    parser.add_argument('--expected-database', help='Exact database name from the Neon production branch.')
    parser.add_argument('--plan', required=True, help='Dry-run: new private output; apply: reviewed input.')
    parser.add_argument('--backup', help='Fresh verified custom-format PostgreSQL archive, required for PostgreSQL apply.')
    parser.add_argument('--acknowledge-production-update', action='store_true')
    parser.add_argument('--receipt', help='Required new private output path for apply audit receipt.')
    args = parser.parse_args()
    db = None
    try:
        if args.env_file: load_dotenv(args.env_file, override=False)
        if args.apply and (not args.receipt or Path(args.receipt).expanduser().exists()):
            raise ValueError('Apply requires a new --receipt path.')
        if args.postgres:
            url, options = direct_database_url()
            if not args.expected_host or not args.expected_database:
                raise ValueError('Specify --expected-host and --expected-database from the intended Neon production branch.')
            if options.get('host') != args.expected_host or options.get('dbname') != args.expected_database:
                raise ValueError('Configured direct URL does not match the independently selected target.')
            inspect_postgres(url, options)
            if args.apply:
                if not args.acknowledge_production_update or not args.backup:
                    raise ValueError('Apply requires owner approval and a fresh verified --backup archive.')

            db = connect(url)
            actual = db.execute('SELECT current_database()').fetchone()[0]
            if actual != args.expected_database: raise ValueError('Connected database does not match the expected target.')
            if args.apply:
                backup_sha = verify_backup(args.backup, actual, curriculum.tables(db))
        else:
            path = Path(args.sqlite).expanduser().resolve()
            if not path.is_file(): raise ValueError('Explicit SQLite file does not exist.')
            # Dry-run cannot write or create a SQLite file.
            db = sqlite3.connect(path.as_uri()+'?mode='+('ro' if args.dry_run else 'rw'), uri=True)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA busy_timeout=5000')
            backup_sha = None
            if args.apply:
                from scripts.migrate_learning_records import backup_sqlite
                backup_sqlite(path)
        if args.dry_run:
            if args.postgres:
                with db.connection.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    result = curriculum.plan(db)
            else:
                with db:
                    db.execute('BEGIN')
                    result = curriculum.plan(db)
            private_json(args.plan, result)
            for row in result['mapping']: print(f"{row['old']:02} -> {row['new']:02} {row['id']}")
            print('Eligible schedule changes:')
            for row in result['schedules']: print(f"{row['id']}: {row['old']} -> {row['new']}")
            print(f"Read-only plan written; {len(result['schedules'])} eligible dates change. Review the complete plan before approval.")
        else:
            approved = json.loads(Path(args.plan).expanduser().read_text())
            # Reserve a writable private receipt before any database mutation.
            with open(Path(args.receipt).expanduser(), 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
                result = curriculum.apply(db, approved)
                result.update(applied_at=datetime.now(timezone.utc).isoformat(), backup_sha256=backup_sha)
                json.dump(result, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            print('Curriculum verified:75 exact positions. All protected fields/table digests verified; receipt written.')
    except Exception as exc:
        # Database/JSON/driver exceptions may carry private source text: never echo.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc,json.JSONDecodeError) else preflight_error_message(exc)
        raise SystemExit(message) from None
    finally:
        if db is not None: db.close()


if __name__ == '__main__':
    main()
