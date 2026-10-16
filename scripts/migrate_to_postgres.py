"""Explicit, all-or-none SQLite -> PostgreSQL cutover, with full-record verification.

Never called by the application or Vercel build. Source SQLite is opened read-only.
No connection strings or note contents are printed.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import ROOT, USER_TABLES, connect, initialize
from app.backup import validate
from dotenv import load_dotenv

TABLES=('settings','concepts','problems',*USER_TABLES)


def records(db):
    return {t:sorted([dict(r) for r in db.execute(f'SELECT * FROM {t}')],key=lambda r:str(next(iter(r.values())))) for t in TABLES}


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def source_data(path,backup=True):
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('Source SQLite file does not exist; no destination data changed.')
    original=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    snapshot=sqlite3.connect(':memory:')
    try:
        original.backup(snapshot)
        snapshot.row_factory=sqlite3.Row
        if snapshot.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or snapshot.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Source SQLite integrity check failed.')
        data=records(snapshot)
        canonical=connect(':memory:')
        try:
            initialize(canonical)
            for table in TABLES:
                expected={row[1] for row in canonical.execute(f'PRAGMA table_info({table})')}
                actual={row[1] for row in snapshot.execute(f'PRAGMA table_info({table})')}
                if actual!=expected:raise ValueError('Source schema differs from supported schema; no destination changes made.')
        finally:canonical.close()
        seed=json.loads((ROOT/'data/grind75.json').read_text())
        if {r['id'] for r in data['problems']}!={p['id'] for p in seed}:raise ValueError('Source must contain the frozen75 problem identities.')
        version=next((r['value'] for r in data['settings'] if r['key']=='seed_version'),None)
        payload=dict(format='grind75-backup',version=1,seed_version=version,exported_at=datetime.now(timezone.utc).isoformat(),tables={t:data[t] for t in USER_TABLES})
        validate(payload)
        if backup:
            directory=path.parent/'backups';directory.mkdir(exist_ok=True)
            target=directory/('migration-source-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
            copy=sqlite3.connect(target)
            try:
                snapshot.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Safety backup integrity check failed.')
            finally:copy.close()
            target.chmod(0o600)
        return data
    finally:original.close();snapshot.close()


def comparison(source,destination):
    mismatched=[t for t in TABLES if source[t]!=destination[t]]
    return dict(matched=not mismatched,mismatched_tables=mismatched,source_digest=digest(source),destination_digest=digest(destination),source_counts={t:len(source[t]) for t in TABLES},destination_counts={t:len(destination[t]) for t in TABLES})


def verify(sqlite_path,url):
    source=source_data(sqlite_path,backup=False);db=connect(url)
    try:
        with db:return comparison(source,records(db))
    finally:db.close()


def migrate(sqlite_path,url,mark_authority=True):
    source=source_data(sqlite_path);source_digest=digest(source);db=connect(url)
    try:
        with db:
            initialize(db)
            prior=db.execute("SELECT value FROM app_meta WHERE key='migration_digest'").fetchone()
            if prior:
                if prior[0]!=source_digest:raise ValueError('This destination was migrated from different source data. Refusing to overwrite cloud progress.')
                result=comparison(source,records(db));result['status']='already_migrated'
                # Cloud progress may have advanced: retry is deliberately a no-op.
            else:
                if any(db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in TABLES):
                    raise ValueError('Destination contains data. Refusing to overwrite it; use an empty dedicated database.')
                for table in TABLES:
                    for row in source[table]:
                        keys=list(row)
                        db.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[row[k] for k in keys])
                result=comparison(source,records(db))
                if not result['matched']:raise ValueError('Record verification failed; migration rolled back.')
                # Abort if the original changed while the copy was being applied.
                if digest(source_data(sqlite_path,backup=False))!=source_digest:raise ValueError('Source changed during migration. Stop local writes and retry; destination rolled back.')
                db.execute("INSERT INTO app_meta VALUES('migration_digest',?)",(source_digest,))
                db.execute("INSERT INTO app_meta VALUES('migration_verified_at',?)",(datetime.now(timezone.utc).isoformat(),))
                result['status']='migrated_and_verified'
        if mark_authority:
            path=Path(sqlite_path).resolve()
            marker=path.parent/'cloud-authority.json'
            marker.write_text(json.dumps(dict(source_name=path.name,source_digest=source_digest,authoritative='postgresql'),indent=2)+'\n')
            marker.chmod(0o600)
        return result
    finally:db.close()


def seed_empty(url):
    # Explicit choice for a fresh installation without an existing SQLite history.
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(temporary)/'empty.sqlite3';db=connect(path)
        try:initialize(db)
        finally:db.close()
        return migrate(path,url,mark_authority=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['migrate','verify','seed-empty'])
    parser.add_argument('--sqlite',type=Path)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env.local')
    args=parser.parse_args()
    load_dotenv(args.env_file,override=False)
    url=os.environ.get('DATABASE_URL','')
    if not url.startswith(('postgresql://','postgres://')):parser.error('Set DATABASE_URL privately in the chosen env file or environment.')
    if args.action!='seed-empty' and not args.sqlite:parser.error('--sqlite is required for migration/verification.')
    try:
        result=seed_empty(url) if args.action=='seed-empty' else (migrate(args.sqlite,url) if args.action=='migrate' else verify(args.sqlite,url))
        print(json.dumps(result,indent=2))
        if args.action=='verify' and not result['matched']:raise SystemExit(1)
    except (ValueError,sqlite3.Error) as exc:raise SystemExit(str(exc)) from None
    except Exception as exc:raise SystemExit('Operation failed ('+type(exc).__name__+'); source retained. Check connectivity/schema; no credentials printed.') from None

if __name__=='__main__':main()
