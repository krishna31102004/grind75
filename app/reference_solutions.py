"""Explicit additive feature migration4. Never called during app startup/requests."""
from datetime import datetime, timezone
from .db import is_postgres

NAME = 'python_reference_solutions'
VERSION = 4
MAX_CODE = 65536  # Unicode characters, independent of the nine 8000-char fields.


def column(db):
    if is_postgres(db):
        row = db.execute("SELECT data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='learning_records' AND column_name='solution_code'").fetchone()
        return bool(row and row[0]=='text' and row[1]=='NO' and row[2]=="''::text")
    row = next((r for r in db.execute('PRAGMA table_info(learning_records)') if r[1]=='solution_code'), None)
    return bool(row and row[2].upper()=='TEXT' and row[3]==1 and row[4]=="''")


def ready(db):
    from .learning_records import migration_ready
    if not migration_ready(db): return False
    marker = db.execute('SELECT name FROM feature_migrations WHERE version=4').fetchone()
    return bool(marker and marker[0]==NAME and column(db))


def preserved_state(db):
    """Exclude only the new empty column/new marker; preserve every existing value."""
    from .curriculum import state
    result = state(db)
    for row in result.get('learning_records', []): row.pop('solution_code', None)
    result['feature_migrations'] = [r for r in result.get('feature_migrations', []) if r['version']!=4]
    return result


def migrate(db):
    from .learning_records import migration_ready
    from .curriculum import fingerprint
    with db:
        if not is_postgres(db): db.execute('BEGIN IMMEDIATE')
        if not migration_ready(db): raise ValueError('Existing migration3 is required; this command never runs it.')
        base = db.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        marker3 = db.execute('SELECT name FROM feature_migrations WHERE version=3').fetchone()
        if not base or base[0]!='2' or marker3[0]!='personal_learning_records':
            raise ValueError('Expected base schema2 and known migration3 identity; no changes committed.')
        before = preserved_state(db)
        if is_postgres(db):
            exists = db.execute("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='learning_records' AND column_name='solution_code'").fetchone()
        else:
            exists = any(r[1]=='solution_code' for r in db.execute('PRAGMA table_info(learning_records)'))
        original_code = {r[0]:r[1] for r in db.execute('SELECT problem_id,solution_code FROM learning_records')} if exists else {r[0]:'' for r in db.execute('SELECT problem_id FROM learning_records')}
        if not exists:
            db.execute("ALTER TABLE learning_records ADD COLUMN solution_code TEXT NOT NULL DEFAULT ''")
        if not column(db): raise ValueError('Unexpected solution_code column definition; transaction rolled back.')
        marker = db.execute('SELECT name FROM feature_migrations WHERE version=4').fetchone()
        if marker and marker[0]!=NAME: raise ValueError('Migration4 identity mismatch; no changes committed.')
        if not marker:
            db.execute('INSERT INTO feature_migrations VALUES(4,?,?)', (NAME,datetime.now(timezone.utc).isoformat()))
        after = preserved_state(db)
        actual_code = {r[0]:r[1] for r in db.execute('SELECT problem_id,solution_code FROM learning_records')}
        if before != after or actual_code != original_code or not ready(db): raise ValueError('Migration4 preservation verification failed; transaction rolled back.')
        return dict(version=4,verified=True,preserved_digests={t:fingerprint(v) for t,v in before.items()},
                    learning_records=len(before['learning_records']))
