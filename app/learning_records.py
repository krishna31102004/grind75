"""Personal learning records and explicitly versioned additive migrations."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from .db import get_db, is_postgres
from .services import stamp

FORMAT = 'grind75-learning-records'
VERSION = 2
FIELDS = (
    'brute_force', 'optimized_reasoning', 'optimal_complexity', 'recognition_clue',
    'mistakes', 'corrections', 'edge_cases', 'interview_takeaway', 'recall_question',
)
ALL_FIELDS = FIELDS + ('solution_code',)
from .reference_solutions import ready as solution_ready, MAX_CODE

def fields_for(db):
    return ALL_FIELDS if solution_ready(db) else FIELDS

MAX_FIELD = 8000
LEGACY_MAX_BYTES = 256 * 1024
MAX_BYTES = 1024 * 1024
MAX_RECORDS = 20


def migration_ready(db=None):
    db = db or get_db()
    if is_postgres(db):
        if not db.execute("SELECT to_regclass('feature_migrations')").fetchone()[0]:
            return False
    elif not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_migrations'").fetchone():
        return False
    return db.execute("SELECT version FROM feature_migrations WHERE version=3").fetchone() is not None


def migrate(db):
    """Add the feature schema only when called by the explicit operations command."""
    statements = [
        "CREATE TABLE IF NOT EXISTS feature_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_records(problem_id TEXT PRIMARY KEY NOT NULL REFERENCES problems(id), brute_force TEXT NOT NULL DEFAULT '', optimized_reasoning TEXT NOT NULL DEFAULT '', optimal_complexity TEXT NOT NULL DEFAULT '', recognition_clue TEXT NOT NULL DEFAULT '', mistakes TEXT NOT NULL DEFAULT '', corrections TEXT NOT NULL DEFAULT '', edge_cases TEXT NOT NULL DEFAULT '', interview_takeaway TEXT NOT NULL DEFAULT '', recall_question TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_import_previews(token_hash TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL, snapshot_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)",
    ]
    with db:
        if not is_postgres(db):
            db.execute('BEGIN IMMEDIATE')
        for statement in statements:
            db.execute(statement)
        db.execute("INSERT INTO feature_migrations VALUES(3,'personal_learning_records',?) ON CONFLICT(version) DO NOTHING", (datetime.now(timezone.utc).isoformat(),))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def parse(raw, db=None):
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            raise ValueError('Import is larger than 1 MiB.')
        try:
            raw = raw.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError('Import must be UTF-8 JSON.') from None
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Import is larger than 1 MiB.')
    try:
        data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Invalid JSON number.')))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Enter valid JSON.') from exc
    if not isinstance(data, dict) or set(data) != {'format', 'version', 'records'} or data.get('format') != FORMAT or type(data.get('version')) is not int or data['version'] not in (1, VERSION):
        raise ValueError('Unsupported learning-record format or version.')
    if data['version']==1 and len(raw.encode('utf-8'))>LEGACY_MAX_BYTES:
        raise ValueError('Legacy version1 import is larger than 256 KiB.')
    records = data['records']
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError(f'Provide between 1 and {MAX_RECORDS} records per batch.')
    db = db or get_db()
    active_fields = fields_for(db)
    allowed_fields = FIELDS if data['version']==1 else ALL_FIELDS
    known = {r[0] for r in db.execute('SELECT id FROM problems')}
    seen = set()
    normalized = []
    for index, item in enumerate(records, 1):
        if not isinstance(item, dict) or 'problem_id' not in item or set(item) - ({'problem_id'} | set(allowed_fields)):
            raise ValueError(f'Record {index} has an invalid shape or unknown field.')
        pid = item['problem_id']
        if not isinstance(pid, str) or pid not in known:
            raise ValueError(f'Record {index} has an unknown problem_id.')
        if pid in seen:
            raise ValueError(f'Duplicate problem_id: {pid}.')
        seen.add(pid)
        row = {'problem_id': pid}
        if 'solution_code' in item and 'solution_code' not in active_fields:
            raise ValueError('Python reference solutions require the explicit migration4 first.')
        for field in active_fields:
            value = item.get(field, '')
            limit = MAX_CODE if field=='solution_code' else MAX_FIELD
            if not isinstance(value, str) or '\x00' in value or len(value) > limit:
                raise ValueError(f'{pid}.{field} must be text of at most {limit} characters.')
            row[field] = value
        normalized.append(row)
    return {'format': FORMAT, 'version': data['version'], 'records': normalized}


def get_record(db, pid):
    row = db.execute('SELECT * FROM learning_records WHERE problem_id=?', (pid,)).fetchone()
    return dict(row) if row else None


def export(db, ids=None):
    if ids is None:
        rows = db.execute('SELECT * FROM learning_records ORDER BY problem_id').fetchall()
    else:
        rows = []
        for pid in ids:
            row = db.execute('SELECT * FROM learning_records WHERE problem_id=?', (pid,)).fetchone()
            if row:
                rows.append(row)
    fields = fields_for(db)
    return {'format': FORMAT, 'version': VERSION if 'solution_code' in fields else 1, 'records': [{k: dict(row)[k] for k in ('problem_id',) + fields} for row in rows]}


def fingerprint(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(db, incoming):
    current = {r['problem_id']: get_record(db, r['problem_id']) for r in incoming['records']}
    return fingerprint(current)


def preview(db, incoming):
    fields = fields_for(db)
    current = {r['problem_id']: get_record(db, r['problem_id']) for r in incoming['records']}
    problems = {r['id']: r['title'] for r in db.execute('SELECT id,title FROM problems')}
    entries = []
    for item in incoming['records']:
        old = current[item['problem_id']]
        old_values = old or {field: '' for field in fields}
        changes = []
        for field in fields:
            before, after = old_values[field], item.get(field, '')
            kind = 'same' if before == after else 'new' if not before and after else 'ignored-empty' if before and not after else 'conflict'
            changes.append({'field': field, 'before': before, 'after': after, 'kind': kind})
        entries.append({'problem_id': item['problem_id'], 'title': problems[item['problem_id']], 'existing': old, 'incoming': item, 'changes': changes})
    return entries


def apply(db, incoming, replace_fields, skipped):
    fields = fields_for(db)
    changed = []
    for item in incoming['records']:
        pid = item['problem_id']
        if pid in skipped:
            continue
        old = get_record(db, pid)
        values = old or {'problem_id': pid}
        updates = {}
        for field in fields:
            new = item.get(field, '')
            before = values.get(field, '')
            if new and new != before and (not before or field in replace_fields.get(pid, ())):
                updates[field] = new
        if not updates:
            continue
        merged = {field: updates.get(field, values.get(field, '')) for field in fields}
        merged['updated_at'] = stamp()
        columns = ['problem_id', *fields, 'updated_at']
        db.execute(f"INSERT INTO learning_records({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) ON CONFLICT(problem_id) DO UPDATE SET {','.join(f'{f}=excluded.{f}' for f in fields)},updated_at=excluded.updated_at", [pid, *[merged[f] for f in fields], merged['updated_at']])
        event_id = secrets.token_hex(16)
        db.execute('INSERT INTO activity_events VALUES(?,?,?,?,?)', (event_id, pid, 'learning_record_import', stamp(), json.dumps({'fields': sorted(updates)})))
        changed.append(pid)
    return changed


def preview_token(db, incoming):
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    created = stamp()
    configured = current_app.config.get('NOW')
    now = datetime.fromisoformat(configured) if configured else datetime.now(timezone.utc)
    expires = now + timedelta(minutes=20)
    # Prune expired previews when issuing a new token so abandoned uploads do not
    # accumulate indefinitely on a persistent PostgreSQL database.
    db.execute('DELETE FROM learning_import_previews WHERE expires_at <= ?', (now.isoformat(),))
    db.execute('INSERT INTO learning_import_previews VALUES(?,?,?,?,?)', (token_hash, json.dumps(incoming, ensure_ascii=False), snapshot(db, incoming), created, expires.isoformat()))
    return raw


def load_preview(db, token):
    if not isinstance(token, str) or len(token) > 100:
        return None
    row = db.execute('SELECT * FROM learning_import_previews WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row:
        return None
    from datetime import datetime, timezone
    expires = datetime.fromisoformat(row['expires_at'])
    now = datetime.fromisoformat(current_app.config['NOW']) if current_app.config.get('NOW') else datetime.now(timezone.utc)
    if expires <= now:
        db.execute('DELETE FROM learning_import_previews WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        return None
    return dict(row)
