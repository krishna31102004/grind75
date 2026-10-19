#!/usr/bin/env python3
"""Explicit additive schema migration; never invoked by Flask startup/build."""
import argparse
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import connect, is_postgres
from app.learning_records import migrate, migration_ready
from app.services import stamp
from app.postgres import conninfo_to_dict
from dotenv import load_dotenv


def digest(db):
    result = {}
    for table in ('concepts','problems','assignments','progress','problem_notes','concept_notes','activity_events','review_state','review_events','submissions','settings'):
        rows = db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
        result[table] = hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()
    return result


def backup_sqlite(path):
    source = sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True)
    directory = Path(path).resolve().parent / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ('pre-learning-records-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        check = target.execute('PRAGMA integrity_check').fetchone()[0]
        if check != 'ok':
            raise RuntimeError('SQLite safety backup did not pass integrity_check.')
    finally:
        target.close(); source.close()
    destination.chmod(0o600)
    return destination


def direct_database_url():
    """Read the operations-only direct URL from the environment, never argv."""
    url = os.environ.get('DATABASE_URL_UNPOOLED')
    if not url:
        raise ValueError('Set DATABASE_URL_UNPOOLED privately; the pooled app URL is not accepted for operations.')
    options = conninfo_to_dict(url)
    host = options.get('host', '')
    local = host in ('127.0.0.1', 'localhost', '::1')
    if not options.get('dbname'):
        raise ValueError('DATABASE_URL_UNPOOLED must identify a database.')
    if local:
        return url, options
    if not host.endswith('.neon.tech') or '-pooler' in host:
        raise ValueError('DATABASE_URL_UNPOOLED must be a direct Neon endpoint (not a pooled endpoint).')
    if options.get('sslmode') not in ('require', 'verify-ca', 'verify-full'):
        raise ValueError('DATABASE_URL_UNPOOLED must require TLS (sslmode=require or stronger).')
    return url, options


class PreflightFailure(RuntimeError):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def client_tls_active(db):
    """Read TLS state from this client socket through libpq, not a server view."""
    try:
        return bool(db.connection.pgconn.ssl_in_use)
    except Exception:
        raise PreflightFailure('tls', 'Could not determine client-side TLS state from libpq.') from None


def inspect_postgres(url, options):
    """Read-only target/version/TLS preflight for an operator-selected database."""
    try:
        db = connect(url)
    except Exception:
        raise PreflightFailure('connection', 'Could not connect using the configured direct PostgreSQL URL; connection details omitted.') from None
    try:
        try:
            row = db.execute("SELECT current_database() AS database, current_setting('server_version') AS server_version").fetchone()
        except Exception:
            raise PreflightFailure('metadata', 'Connected, but could not read target database/server metadata.') from None
        tls = client_tls_active(db)
        if options.get('host') not in ('127.0.0.1', 'localhost', '::1') and not tls:
            raise PreflightFailure('tls', 'Libpq reports that the remote client connection is not using TLS.')
        client_majors = {}
        for executable in ('pg_dump', 'pg_restore'):
            path = shutil.which(executable)
            if path:
                try:
                    version = subprocess.run([path, '--version'], capture_output=True, text=True, check=True).stdout.strip()
                except Exception:
                    raise PreflightFailure('client-version', f'Could not determine the installed {executable} version.') from None
                print(version)
                major = client_major(version)
                if major is not None:
                    client_majors[executable] = major
            else:
                raise PreflightFailure('client-version', f'{executable} is unavailable.')
        server_major = int(row['server_version'].split('.', 1)[0])
        if client_majors.get('pg_dump', 0) < server_major:
            raise PreflightFailure('client-version', 'Installed pg_dump is older than the server; install a matching or newer PostgreSQL client before backup/migration.')
        if client_majors.get('pg_restore') != client_majors.get('pg_dump'):
            raise PreflightFailure('client-version', 'pg_dump and pg_restore client major versions must match for this release procedure.')
        print(f"Target check passed: host={options.get('host')} database={row['database']} server={row['server_version']} tls={'on' if tls else 'local-test'} sslmode={options.get('sslmode', 'require')}")
    finally:
        db.close()


def client_major(version):
    """Extract a PostgreSQL major from both distro and Homebrew version strings."""
    match = re.search(r'\(PostgreSQL\)\s+(\d+)(?:\.\d+)*', version)
    return int(match.group(1)) if match else None


def sanitized_target_error(exc):
    # Database drivers can include connection details in exception context.
    return f'Preflight failed [unexpected]: database operation failed; connection details omitted.'


def preflight_error_message(exc):
    if isinstance(exc, PreflightFailure):
        return f'Preflight failed [{exc.category}]: {exc}'
    return sanitized_target_error(exc)


def verify_postgres_schema(url):
    db = connect(url)
    try:
        base = db.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        if not base or base[0] != '2':
            raise RuntimeError('Expected base PostgreSQL schema version 2 was not found.')
        if not migration_ready(db):
            raise RuntimeError('Learning-record migration version 3 is not present.')
        expected = {'learning_records', 'learning_import_previews', 'feature_migrations'}
        present = {row[0] for row in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")}
        if not expected <= present:
            raise RuntimeError('One or more version 3 tables are missing.')
        marker = db.execute('SELECT name FROM feature_migrations WHERE version=3').fetchone()
        if marker[0] != 'personal_learning_records':
            raise RuntimeError('Version 3 marker does not match this release.')
        count = db.execute('SELECT count(*) AS count FROM learning_records').fetchone()['count']
        if count > 75:
            raise RuntimeError('Learning-record count exceeds the frozen Grind 75 inventory.')
        print(f'Verified base schema version 2 and additive feature migration version 3; learning_records={count}.')
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite', help='Explicit SQLite database path. Do not omit or use your active data file casually.')
    parser.add_argument('--postgres', action='store_true', help='Use DATABASE_URL_UNPOOLED; only after independently verifying a full database backup.')
    parser.add_argument('--check-postgres', action='store_true', help='Read-only direct Neon target/TLS/server/client-version preflight.')
    parser.add_argument('--verify-postgres', action='store_true', help='Read-only verification of base schema and feature migration version 3.')
    parser.add_argument('--env-file', help='Optional private dotenv file to load (values are never printed).')
    parser.add_argument('--acknowledge-postgres-backup', action='store_true', help='Confirm a verified pg_dump backup exists before additive DDL.')
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    modes = sum((bool(args.sqlite), bool(args.postgres), bool(args.check_postgres), bool(args.verify_postgres)))
    if modes != 1:
        parser.error('Specify exactly one of --sqlite PATH, --postgres, --check-postgres, or --verify-postgres.')
    if args.postgres or args.check_postgres or args.verify_postgres:
        try:
            url, options = direct_database_url()
        except Exception as exc:
            parser.error(sanitized_target_error(exc) if not isinstance(exc, ValueError) else str(exc))
        if args.check_postgres:
            try:
                inspect_postgres(url, options)
            except Exception as exc:
                raise SystemExit(preflight_error_message(exc)) from None
            return
        if args.verify_postgres:
            try:
                inspect_postgres(url, options)
                verify_postgres_schema(url)
            except Exception as exc:
                raise SystemExit(preflight_error_message(exc)) from None
            return
        if not args.acknowledge_postgres_backup:
            parser.error('Create and verify a private pg_dump backup using DATABASE_URL_UNPOOLED first, then pass --acknowledge-postgres-backup.')
        try:
            # Display and validate the actual destination before any DDL.
            inspect_postgres(url, options)
            db = connect(url)
        except Exception as exc:
            raise SystemExit(preflight_error_message(exc)) from None
        backup = 'operator-verified external PostgreSQL backup'
    else:
        path = Path(args.sqlite).expanduser().resolve()
        if not path.is_file():
            parser.error('SQLite file does not exist; refusing to initialize an arbitrary/new database.')
        backup = backup_sqlite(path)
        db = connect(path)
    try:
        before = digest(db)
        if migration_ready(db):
            print('Migration already applied (version 3); no changes made.')
        else:
            migrate(db)
        after = digest(db)
        if before != after:
            raise RuntimeError('Base study data changed during additive migration; investigate immediately.')
        if not migration_ready(db):
            raise RuntimeError('Migration verification failed.')
        print('Migration version 3 verified. All original study-table digests match.')
        print(f'Safety backup: {backup}')
    finally:
        db.close()


if __name__ == '__main__':
    main()
