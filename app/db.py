import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from flask import current_app, g

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS concepts(id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, display_order INTEGER, content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS problems(id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL, difficulty TEXT NOT NULL, url TEXT NOT NULL, concept_id TEXT NOT NULL REFERENCES concepts(id), learning_order INTEGER UNIQUE, grind_rank INTEGER UNIQUE, metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignments(problem_id TEXT PRIMARY KEY NOT NULL REFERENCES problems(id), baseline_date TEXT NOT NULL, scheduled_date TEXT NOT NULL, manual_override INTEGER NOT NULL DEFAULT 0 CHECK(manual_override IN (0,1)));
CREATE TRIGGER IF NOT EXISTS immutable_baseline BEFORE UPDATE OF baseline_date ON assignments WHEN NEW.baseline_date != OLD.baseline_date BEGIN SELECT RAISE(ABORT, 'baseline dates are immutable'); END;
CREATE TABLE IF NOT EXISTS progress(problem_id TEXT PRIMARY KEY NOT NULL REFERENCES problems(id), status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','attempted','hints','understood','needs_review')), first_attempt_at TEXT, first_understood_at TEXT, mastered INTEGER NOT NULL DEFAULT 0 CHECK(mastered IN (0,1)));
CREATE TABLE IF NOT EXISTS problem_notes(problem_id TEXT PRIMARY KEY NOT NULL REFERENCES problems(id), takeaway TEXT NOT NULL DEFAULT '', approach TEXT NOT NULL DEFAULT '', confidence INTEGER CHECK(confidence BETWEEN 1 AND 5), effort INTEGER CHECK(effort BETWEEN 0 AND 600));
CREATE TABLE IF NOT EXISTS concept_notes(concept_id TEXT PRIMARY KEY NOT NULL REFERENCES concepts(id), note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity_events(id TEXT PRIMARY KEY NOT NULL, problem_id TEXT REFERENCES problems(id), kind TEXT NOT NULL, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_state(problem_id TEXT PRIMARY KEY NOT NULL REFERENCES problems(id), stage INTEGER NOT NULL CHECK(stage BETWEEN 0 AND 3), next_due_date TEXT, last_result TEXT CHECK(last_result IN ('independent','hints','failed')));
CREATE TABLE IF NOT EXISTS review_events(id TEXT PRIMARY KEY NOT NULL, problem_id TEXT NOT NULL REFERENCES problems(id), at TEXT NOT NULL, result TEXT NOT NULL CHECK(result IN ('independent','hints','failed')), note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY NOT NULL, at TEXT NOT NULL);
'''
USER_TABLES = ('assignments','progress','problem_notes','concept_notes','activity_events','review_state','review_events','submissions')

def connect(path):
    if str(path).startswith(('postgres://', 'postgresql://')):
        from .postgres import PostgresDB
        return PostgresDB(path)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    return db

def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config.get('DATABASE_URL') or current_app.config['DATABASE'])
        if is_postgres(g.db):
            try:
                if g.db.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()[0] != '2':
                    raise RuntimeError('Database schema is not ready; run the documented migration command.')
            except Exception:
                g.db.close()
                g.pop('db', None)
                raise RuntimeError('Database schema is not ready; run the documented migration command.') from None
    return g.db

def close_db(_=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def initialize_sqlite(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0, 1):
        raise RuntimeError('Unsupported database version; preserve the database and upgrade the application.')
    db.executescript(SCHEMA)
    # Also harden databases created during earlier checkpoints without replacing data.
    for table, column in [('concepts','id'),('problems','id'),('settings','key')]+[(t, 'concept_id' if t=='concept_notes' else 'id' if t in ('activity_events','review_events','submissions') else 'problem_id') for t in USER_TABLES]:
        for action in ('INSERT','UPDATE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS nonnull_{table}_{action} BEFORE {action} ON {table} WHEN NEW.{column} IS NULL BEGIN SELECT RAISE(ABORT, 'identifier cannot be null'); END")
    problems = json.loads((ROOT/'data/grind75.json').read_text())
    concepts = json.loads((ROOT/'data/concepts.json').read_text())
    existing = {r[0] for r in db.execute('SELECT id FROM problems')}
    expected = {p['id'] for p in problems}
    if existing and existing != expected:
        raise RuntimeError('Dataset identities changed; refusing to modify personal progress.')
    with db:
        for c in concepts:
            db.execute('INSERT INTO concepts VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, content=excluded.content', (c['id'],c['name'],c['display_order'],json.dumps(c)))
        for p in problems:
            db.execute('INSERT INTO problems VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,difficulty=excluded.difficulty,url=excluded.url,metadata=excluded.metadata', (p['id'],p['title'],p['difficulty'],p['url'],p['primary_concept_id'],p['learning_order'],p['grind_rank'],json.dumps(p)))
            baseline = (date(2026,10,15)+timedelta(days=(p['learning_order']-1)//6)).isoformat()
            db.execute('INSERT OR IGNORE INTO assignments VALUES(?,?,?,0)', (p['id'],baseline,baseline))
            db.execute('INSERT OR IGNORE INTO progress(problem_id) VALUES(?)', (p['id'],))
            db.execute('INSERT OR IGNORE INTO problem_notes(problem_id) VALUES(?)', (p['id'],))
        for k,v in [('timezone','America/Chicago'),('daily_target','6'),('seed_version',problems[0]['source_version'])]:
            db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(k,v))
        db.execute('PRAGMA user_version=1')


CLOUD_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_state(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_throttle(key TEXT PRIMARY KEY NOT NULL, failures INTEGER NOT NULL, expires_at BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS safety_backups(id TEXT PRIMARY KEY NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
"""


def is_postgres(db):
    return getattr(db, 'backend', None) == 'postgresql'


def initialize(db):
    """Explicit schema setup. PG callers must invoke this from an operations script."""
    if not is_postgres(db):
        initialize_sqlite(db)
        db.executescript(CLOUD_SCHEMA)
        with db:
            db.execute("INSERT OR IGNORE INTO app_meta VALUES('schema_version','2')")
        return
    statements = '\n'.join(line for line in SCHEMA.splitlines() if not line.startswith('CREATE TRIGGER'))
    with db:
        for statement in (statements+CLOUD_SCHEMA).split(';'):
            if statement.strip(): db.execute(statement)
        version=db.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        if version and version[0]!='2':
            raise RuntimeError('Unsupported PostgreSQL schema version; no data changed.')
        db.execute("""CREATE OR REPLACE FUNCTION preserve_baseline() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.baseline_date IS DISTINCT FROM OLD.baseline_date THEN
                RAISE EXCEPTION 'baseline dates are immutable';
            END IF; RETURN NEW; END $$""")
        # Serialized by the advisory lock, so repeated setup is safe.
        if not db.execute("SELECT 1 FROM pg_trigger WHERE tgname='immutable_baseline' AND tgrelid='assignments'::regclass").fetchone():
            db.execute('CREATE TRIGGER immutable_baseline BEFORE UPDATE OF baseline_date ON assignments FOR EACH ROW EXECUTE FUNCTION preserve_baseline()')
        db.execute("INSERT INTO app_meta VALUES('schema_version','2') ON CONFLICT(key) DO NOTHING")
