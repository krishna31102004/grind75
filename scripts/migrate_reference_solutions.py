#!/usr/bin/env python3
"""Explicit feature migration4 only. No startup/build/request migration.

Use --check-only first. Production apply requires exact target assertions, an
independently verified fresh private archive and a new private audit receipt.
Connection strings are read from private environment/dotenv only, never argv.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from app.db import connect
from app import reference_solutions as ref
from app.learning_records import migration_ready
from scripts.migrate_learning_records import direct_database_url,inspect_postgres,preflight_error_message,backup_sqlite
from scripts.reorder_curriculum import verify_backup
from app.curriculum import tables


def main():
    p=argparse.ArgumentParser(description=__doc__)
    target=p.add_mutually_exclusive_group(required=True)
    target.add_argument('--sqlite',help='Explicit existing local SQLite path; never initializes a new DB.')
    target.add_argument('--postgres',action='store_true')
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only',action='store_true',help='Read-only schema/target/TLS/optional backup check.')
    mode.add_argument('--apply',action='store_true',help='Explicitly add only solution_code and migration4 marker.')
    p.add_argument('--env-file');p.add_argument('--expected-host');p.add_argument('--expected-database')
    p.add_argument('--backup',help='Fresh independently verified custom PostgreSQL archive.')
    p.add_argument('--acknowledge-postgres-backup',action='store_true')
    p.add_argument('--receipt',help='New private JSON output path, required for apply.')
    a=p.parse_args();db=None
    try:
        if a.env_file:load_dotenv(a.env_file,override=False)
        if a.apply and (not a.receipt or Path(a.receipt).expanduser().exists()):raise ValueError('Apply requires a new private --receipt path.')
        safety=None;backup_hash=None
        if a.postgres:
            url,options=direct_database_url()
            if not a.expected_host or not a.expected_database or options.get('host')!=a.expected_host or options.get('dbname')!=a.expected_database:
                raise ValueError('Direct URL must exactly match independently verified --expected-host and --expected-database.')
            if options.get('host') not in ('127.0.0.1','localhost','::1') and options.get('sslmode')!='verify-full':
                raise ValueError('Migration4 requires sslmode=verify-full with trusted CA and hostname verification.')
            inspect_postgres(url,options)
            if a.apply and (not a.backup or not a.acknowledge_postgres_backup):raise ValueError('Apply requires a fresh verified --backup and --acknowledge-postgres-backup.')
            db=connect(url)
            if db.execute('SELECT current_database()').fetchone()[0]!=a.expected_database:raise ValueError('Connected database target mismatch.')
            if a.backup:backup_hash=verify_backup(a.backup,a.expected_database,tables(db))
        else:
            path=Path(a.sqlite).expanduser().resolve()
            if not path.is_file():raise ValueError('Explicit existing SQLite file required; no database initialized.')
            db=sqlite3.connect(path.as_uri()+'?mode='+('ro' if a.check_only else 'rw'),uri=True)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=5000')
        if not migration_ready(db):raise ValueError('Migration3 must already exist; this command does not run it.')
        base=db.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        marker3=db.execute('SELECT name FROM feature_migrations WHERE version=3').fetchone()
        if not base or base[0]!='2' or marker3[0]!='personal_learning_records':raise ValueError('Expected base schema2 and known migration3 identity.')
        marker4=db.execute('SELECT name FROM feature_migrations WHERE version=4').fetchone()
        if marker4 and (marker4[0]!=ref.NAME or not ref.column(db)):raise ValueError('Migration4 marker/column mismatch; stop for investigation.')
        if a.check_only:
            if a.postgres:
                with db.connection.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    available=ref.ready(db)
            else:available=ref.ready(db)
            print('Read-only check passed. Migration4 '+('verified; column/marker ready.' if available else 'pending; additive column/marker only.'))
            if backup_hash:print('Private backup hash verified: '+backup_hash)
            return
        # Reserve a private receipt before DDL; SQLite also creates a verified copy.
        with open(Path(a.receipt).expanduser(),'x',opener=lambda name,flags:os.open(name,flags,0o600)) as stream:
            if a.sqlite:safety=str(backup_sqlite(path))
            result=ref.migrate(db)
            result.update(applied_at=datetime.now(timezone.utc).isoformat(),backup_sha256=backup_hash,sqlite_safety_copy=safety)
            json.dump(result,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        print('Migration4 verified: solution_code TEXT NOT NULL DEFAULT empty; all preexisting study/learning values unchanged.')
        print('Private audit receipt written. No curriculum, status, notes or review values changed.')
    except Exception as exc:
        message=str(exc) if isinstance(exc,ValueError) and not isinstance(exc,json.JSONDecodeError) else preflight_error_message(exc)
        raise SystemExit(message) from None
    finally:
        if db is not None:db.close()


if __name__=='__main__':main()
