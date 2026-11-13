#!/usr/bin/env python3
"""Plan or explicitly apply the additive 15-active-day curriculum migration.

No migration runs during app startup or Vercel builds. PostgreSQL operations use
DATABASE_URL_UNPOOLED only; secrets never appear in command-line arguments.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from app import curriculum_migration as migration
from app.db import connect, is_postgres
from scripts.migrate_learning_records import direct_database_url, inspect_postgres, preflight_error_message, backup_sqlite
from scripts.reorder_curriculum import verify_backup, private_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--sqlite', help='Explicit existing SQLite file; never initializes one.')
    target.add_argument('--postgres', action='store_true', help='Use the private DATABASE_URL_UNPOOLED direct URL.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='Read-only plan; no migration writes.')
    mode.add_argument('--apply', action='store_true', help='Explicit transactional apply of the reviewed plan.')
    parser.add_argument('--env-file', help='Private dotenv path; its contents are never printed.')
    parser.add_argument('--expected-host', help='Independently verified direct Neon production endpoint.')
    parser.add_argument('--expected-database', help='Database name on the verified Neon Production branch.')
    parser.add_argument('--assignment-date', help='Explicit YYYY-MM-DD date for the seven new baseline rows; defaults to Chicago today on dry-run.')
    parser.add_argument('--plan', required=True, help='New private dry-run JSON path, or reviewed plan input for apply.')
    parser.add_argument('--backup', help='Fresh private custom-format PostgreSQL archive required for PostgreSQL apply.')
    parser.add_argument('--acknowledge-production-update', action='store_true')
    parser.add_argument('--receipt', help='New private receipt path required for apply.')
    args = parser.parse_args()
    db = None
    try:
        if args.env_file:
            load_dotenv(args.env_file, override=False)
        plan_path = Path(args.plan).expanduser()
        if args.dry_run and plan_path.exists():
            raise ValueError('Dry-run plan path already exists; choose a new private filename.')
        if args.apply and (not args.receipt or Path(args.receipt).expanduser().exists()):
            raise ValueError('Apply requires a new private --receipt path.')
        backup_sha = None
        if args.postgres:
            url, options = direct_database_url()
            if not args.expected_host or not args.expected_database:
                raise ValueError('Specify the direct endpoint and database independently verified from the intended Neon Production branch.')
            if options.get('host') != args.expected_host or options.get('dbname') != args.expected_database:
                raise ValueError('Direct URL target does not match the independently verified expected host/database.')
            if options.get('sslmode') != 'verify-full':
                raise ValueError('Curriculum migration requires sslmode=verify-full with a trusted CA and hostname validation.')
            inspect_postgres(url, options)
            db = connect(url)
            if db.execute('SELECT current_database()').fetchone()[0] != args.expected_database:
                raise ValueError('Connected database target mismatch.')
            if args.apply:
                if not args.backup or not args.acknowledge_production_update:
                    raise ValueError('PostgreSQL apply requires a fresh verified backup and explicit production-update acknowledgement.')
            if args.backup:
                backup_sha = verify_backup(args.backup, args.expected_database, migration._tables(db))
        else:
            path = Path(args.sqlite).expanduser().resolve()
            if not path.is_file():
                raise ValueError('Explicit existing SQLite file required; this command never creates a database.')
            db = sqlite3.connect(path.as_uri() + '?mode=' + ('ro' if args.dry_run else 'rw'), uri=True)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA busy_timeout=5000')
            if args.apply:
                safety = backup_sqlite(path)
            else:
                safety = None

        assignment_date = args.assignment_date
        if args.apply:
            approved = json.loads(plan_path.read_text(encoding='utf-8'))
            if assignment_date and assignment_date != approved.get('assignment_date_for_new_questions'):
                raise ValueError('Apply assignment date differs from the reviewed plan.')
            assignment_date = approved.get('assignment_date_for_new_questions')
            if args.postgres:
                if verify_backup(args.backup, args.expected_database, migration._tables(db)) != backup_sha:
                    raise ValueError('Backup changed during preflight; no writes permitted.')
            receipt_path = Path(args.receipt).expanduser()
            with open(receipt_path, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as receipt:
                result = migration.apply(db, approved)
                result.update(applied_at=datetime.now(timezone.utc).isoformat(), backup_sha256=backup_sha,
                              sqlite_safety_copy=str(safety) if safety else None)
                json.dump(result, receipt, indent=2); receipt.write('\n'); receipt.flush(); os.fsync(receipt.fileno())
            print('Curriculum migration5 verified transactionally. Existing user data was preserved; only the reviewed additive set and target settings changed.')
            print('Private migration receipt written.')
            return

        if args.postgres:
            with db.connection.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                result = migration.prepare(db, assignment_date)
        else:
            with db:
                db.execute('BEGIN')
                result = migration.prepare(db, assignment_date)
        private_json(plan_path, result)
        print('Read-only plan created: '+str(plan_path))
        print(f"Current problems: {result['source_problem_count']}; active: {result['active_problem_count']}; archived: {result['archived_problem_count']}; new identities: {len(result['added_problem_ids'])}.")
        print(f"Schedule: 15 active days × 5; six flexible days; Chicago timezone; new baseline rows use {result['assignment_date_for_new_questions']}.")
        print('Active and archived identity changes:')
        for row in result['old_identity_projection']:
            print(f"preserve {row['id']} · {row['title']}")
        print('New problem identities: '+', '.join(result['added_problem_ids']))
        print('Archived from active plan: '+', '.join(result['archived_problem_ids']))
        print('No existing progress, learning, review, assignment, note, solution or history row is in the write set.')
        print('No production operation was applied.')
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else preflight_error_message(exc)
        raise SystemExit(message) from None
    finally:
        if db is not None:
            db.close()


if __name__ == '__main__':
    main()
