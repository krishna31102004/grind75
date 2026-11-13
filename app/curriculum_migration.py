"""Explicit additive migration to the 15-active-day curriculum (version 5)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import plans
from .db import ROOT, is_postgres

NAME = 'versioned_15_day_curriculum'
VERSION = 5
PLAN_TABLES = ('curriculum_versions', 'curriculum_days', 'curriculum_entries', 'curriculum_archive', 'assessment_events')
TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS curriculum_versions(version TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS curriculum_days(version TEXT NOT NULL REFERENCES curriculum_versions(version), day_number INTEGER NOT NULL CHECK(day_number BETWEEN 1 AND 21), week INTEGER NOT NULL CHECK(week BETWEEN 1 AND 3), active_index INTEGER CHECK(active_index BETWEEN 1 AND 15), kind TEXT NOT NULL CHECK(kind IN ('active','flexible')), topic TEXT NOT NULL, PRIMARY KEY(version,day_number), UNIQUE(version,active_index))",
    "CREATE TABLE IF NOT EXISTS curriculum_entries(version TEXT NOT NULL, day_number INTEGER NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5), tracker_number INTEGER NOT NULL CHECK(tracker_number BETWEEN 1 AND 75), problem_id TEXT NOT NULL REFERENCES problems(id), PRIMARY KEY(version,day_number,slot), UNIQUE(version,problem_id), UNIQUE(version,tracker_number), FOREIGN KEY(version,day_number) REFERENCES curriculum_days(version,day_number))",
    "CREATE TABLE IF NOT EXISTS curriculum_archive(version TEXT NOT NULL REFERENCES curriculum_versions(version), problem_id TEXT NOT NULL REFERENCES problems(id), reason TEXT NOT NULL, archived_at TEXT NOT NULL, PRIMARY KEY(version,problem_id))",
    "CREATE TABLE IF NOT EXISTS assessment_events(id TEXT PRIMARY KEY NOT NULL, problem_id TEXT NOT NULL REFERENCES problems(id), assessment TEXT NOT NULL CHECK(assessment IN ('green','yellow','red')), green_attested INTEGER NOT NULL CHECK(green_attested IN (0,1)), takeaway TEXT NOT NULL DEFAULT '', at TEXT NOT NULL, context TEXT NOT NULL CHECK(context IN ('first_pass','review')), CHECK((assessment='green' AND green_attested=1) OR (assessment!='green' AND green_attested=0)))",
)


def _tables(db):
    query = ("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()" if is_postgres(db)
             else "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return sorted(r[0] for r in db.execute(query))


def _rows(db, table):
    return [dict(r) for r in db.execute(f'SELECT * FROM "{table}" ORDER BY 1')]


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _state(db):
    return {table: _rows(db, table) for table in _tables(db)}


def _legacy_ids():
    return {p['id'] for p in json.loads((ROOT / 'data/grind75.json').read_text(encoding='utf-8'))}


def _markers(db):
    if not db.execute("SELECT 1 FROM feature_migrations WHERE version=3").fetchone():
        raise ValueError('Explicit learning-record migration3 is required before curriculum migration5.')
    if not db.execute("SELECT 1 FROM feature_migrations WHERE version=4").fetchone():
        raise ValueError('Explicit reference-solution migration4 is required before curriculum migration5.')


def prepare(db, assignment_date=None):
    """Build a deterministic no-write plan; callers may pass the reviewed date on apply."""
    curriculum = plans.load()
    _markers(db)
    assignment_date = assignment_date or datetime.now(ZoneInfo('America/Chicago')).date().isoformat()
    from .services import valid_date
    try:parsed=valid_date(assignment_date)
    except ValueError:raise ValueError('New problem assignment date must use YYYY-MM-DD between 2020 and 2100.') from None
    if parsed.isoformat()!=assignment_date:raise ValueError('New problem assignment date must use YYYY-MM-DD between 2020 and 2100.')

    current_ids = {r[0] for r in db.execute('SELECT id FROM problems')}
    existing_marker = db.execute('SELECT name FROM feature_migrations WHERE version=5').fetchone()
    if current_ids not in (_legacy_ids(), set(curriculum['catalog'])):
        raise ValueError('Problem catalog is neither the exact legacy 75 nor the migrated 82; no changes permitted.')
    if existing_marker and existing_marker[0] != NAME:
        raise ValueError('Migration5 marker has an unexpected identity; stop for investigation.')
    if not existing_marker and current_ids != _legacy_ids():
        raise ValueError('Migration marker is absent but the catalog is already changed; stop for investigation.')
    if existing_marker:
        if current_ids != set(curriculum['catalog']) or not plans.ready(db):
            raise ValueError('Migration5 marker/catalog mismatch; stop for investigation.')
    for table in ('assignments', 'progress', 'problem_notes'):
        present = {r[0] for r in db.execute(f'SELECT problem_id FROM {table}')}
        if present != current_ids:
            raise ValueError(f'{table} does not match the existing problem catalog; no changes permitted.')
    concept_ids = {r[0] for r in db.execute('SELECT id FROM concepts')}
    if any(p['primary_concept_id'] not in concept_ids for p in curriculum['catalog'].values()):
        raise ValueError('New problem references a concept that is not present.')
    before = _state(db)
    known = set(before)
    if existing_marker and not set(PLAN_TABLES) <= known:
        raise ValueError('Migration5 tables are incomplete; stop for investigation.')
    source_ids = current_ids
    added = sorted(set(curriculum['catalog']) - source_ids)
    if existing_marker and added:
        raise ValueError('Applied migration has missing problem rows; stop for investigation.')
    old_problems = [dict(r) for r in db.execute('SELECT id,title,learning_order,grind_rank FROM problems ORDER BY id')]
    old_state = {table: before.get(table, []) for table in ('assignments', 'progress', 'problem_notes', 'activity_events', 'review_state', 'review_events', 'learning_records') if table in before}
    return {
        'operation': 'curriculum-v2-explicit-migration', 'migration_version': VERSION, 'migration_name': NAME,
        'curriculum_version': plans.VERSION, 'fingerprint': _digest(before), 'assignment_date_for_new_questions': assignment_date,
        'source_problem_count': len(current_ids), 'active_problem_count': len(curriculum['active_ids']),
        'archived_problem_count': len(curriculum['archived_ids']), 'added_problem_ids': added,
        'archived_problem_ids': sorted(curriculum['archived_ids']), 'plan_entries': curriculum['entries'],
        'days': [{k: day[k] for k in ('day', 'week', 'active_index', 'kind', 'topic')} for day in curriculum['days']],
        'prior_problems_digest': _digest(before.get('problems', [])),
        'prior_user_data_digests': {table: _digest(rows) for table, rows in old_state.items()},
        'prior_learning_records_count': len(before.get('learning_records', [])),
        'prior_problem_ids': sorted(current_ids), 'old_identity_projection': old_problems,
        'already_applied': bool(existing_marker),
        'write_set': (['add 7 new problem catalog rows and empty assignment/progress/note rows',
                       'add plan version, 21 day rows, 75 ordered entries, 7 archive rows, empty assessment-event table',
                       'set settings.active_plan_version and settings.active_study_day=1',
                       'change settings.daily_target to 5', 'insert feature_migrations version 5'] if not existing_marker else []),
        'preservation_contract': 'No existing problem, assignment, progress, note, concept note, activity, review, submission, learning-record, reference-solution, security, share, or timestamp row is updated or deleted. Existing baseline/scheduled dates are unchanged.',
    }


def apply(db, approved):
    """Apply the reviewed operation in one transaction; exact prior state is asserted."""
    if not is_postgres(db) and db.in_transaction:
        raise ValueError('Apply requires a clean SQLite connection with no pending transaction.')
    with db:
        if not is_postgres(db):
            db.execute('BEGIN IMMEDIATE')
        marker = db.execute('SELECT name FROM feature_migrations WHERE version=5').fetchone()
        if marker:
            stored = db.execute("SELECT value FROM settings WHERE key='curriculum_migration5_plan_digest'").fetchone()
            if marker[0] != NAME or not stored or stored[0] != _digest(approved):
                raise ValueError('Migration5 was already applied from a different plan; no changes permitted.')
            expected = plans.load()
            actual_entries = [dict(r) for r in db.execute('''SELECT e.version,e.day_number,d.week,d.active_index,d.topic,e.slot,e.tracker_number,e.problem_id
                FROM curriculum_entries e JOIN curriculum_days d ON d.version=e.version AND d.day_number=e.day_number
                WHERE e.version=? ORDER BY e.day_number,e.slot''', (plans.VERSION,))]
            if actual_entries != expected['entries'] or {r[0] for r in db.execute('SELECT problem_id FROM curriculum_archive WHERE version=?', (plans.VERSION,))} != expected['archived_ids']:
                raise ValueError('Applied curriculum/archive state no longer matches the approved plan; stop for investigation.')
            return {'plan': approved, 'verification': 'Migration5 was already applied; no rows changed.'}
        current = prepare(db, approved.get('assignment_date_for_new_questions'))
        if current != approved:
            raise ValueError('Reviewed migration plan is stale or changed; create and review a new dry-run.')
        if current['already_applied']:
            return {'plan': current, 'verification': 'Migration5 was already applied; no rows changed.'}
        curriculum = plans.load()
        before = _state(db)
        db.execute(TABLE_SQL[0], ())
        for statement in TABLE_SQL[1:]:
            db.execute(statement, ())
        now = datetime.now(timezone.utc).isoformat()
        db.execute('INSERT INTO curriculum_versions(version,name,created_at) VALUES(?,?,?)',
                   (plans.VERSION, curriculum['name'], now))
        for pid in current['added_problem_ids']:
            p = curriculum['catalog'][pid]
            db.execute('INSERT INTO problems(id,title,difficulty,url,concept_id,learning_order,grind_rank,metadata) VALUES(?,?,?,?,?,?,?,?)',
                       (p['id'],p['title'],p['difficulty'],p['url'],p['primary_concept_id'],None,None,json.dumps(p,ensure_ascii=False)))
            db.execute('INSERT INTO assignments(problem_id,baseline_date,scheduled_date,manual_override) VALUES(?,?,?,0)',
                       (pid,current['assignment_date_for_new_questions'],current['assignment_date_for_new_questions']))
            db.execute('INSERT INTO progress(problem_id) VALUES(?)', (pid,))
            db.execute('INSERT INTO problem_notes(problem_id) VALUES(?)', (pid,))
        for day in curriculum['days']:
            db.execute('INSERT INTO curriculum_days(version,day_number,week,active_index,kind,topic) VALUES(?,?,?,?,?,?)',
                       (plans.VERSION, day['day'], day['week'], day['active_index'], day['kind'], day['topic']))
        for row in curriculum['entries']:
            db.execute('INSERT INTO curriculum_entries(version,day_number,slot,tracker_number,problem_id) VALUES(?,?,?,?,?)',
                       (plans.VERSION, row['day_number'], row['slot'], row['tracker_number'], row['problem_id']))
        for pid in sorted(curriculum['archived_ids']):
            db.execute('INSERT INTO curriculum_archive(version,problem_id,reason,archived_at) VALUES(?,?,?,?)',
                       (plans.VERSION, pid, 'Removed from the active plan by owner-approved curriculum v2; history retained.', now))
        db.execute("INSERT INTO settings(key,value) VALUES('active_plan_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (plans.VERSION,))
        db.execute("INSERT INTO settings(key,value) VALUES('active_study_day','1') ON CONFLICT(key) DO UPDATE SET value='1'")
        db.execute("INSERT INTO settings(key,value) VALUES('daily_target','5') ON CONFLICT(key) DO UPDATE SET value='5'")
        db.execute("INSERT INTO settings(key,value) VALUES('curriculum_migration5_plan_digest',?)", (_digest(current),))
        db.execute('INSERT INTO feature_migrations(version,name,applied_at) VALUES(?,?,?)', (VERSION, NAME, now))
        after = _state(db)
        # Existing rows in every legacy table are immutable during the migration.
        for table, old_rows in before.items():
            if table in ('problems','assignments','progress','problem_notes','settings'):
                current_rows = after.get(table, [])
                old_by_key = {str(next(iter(row.values()))): row for row in old_rows}
                new_by_key = {str(next(iter(row.values()))): row for row in current_rows}
                for key, row in old_by_key.items():
                    if table == 'settings' and row['key'] == 'daily_target':
                        continue
                    if new_by_key.get(key) != row:
                        raise ValueError(f'Preservation verification failed for existing {table} row; transaction rolled back.')
                if table == 'settings':
                    old_target = next((r for r in old_rows if r['key'] == 'daily_target'), None)
                    new_target = next(r for r in current_rows if r['key'] == 'daily_target')
                    if old_target and new_target['value'] != '5':
                        raise ValueError('Daily target did not update to the approved five-question setting.')
                    for row in old_rows:
                        if row['key'] == 'daily_target':
                            continue
                        if next(r for r in current_rows if r['key'] == row['key']) != row:
                            raise ValueError('Preservation verification failed for an existing setting.')
                elif table in ('problems','assignments','progress','problem_notes'):
                    if len(current_rows) != len(old_rows) + len(current['added_problem_ids']):
                        raise ValueError(f'Unexpected row count in {table}; transaction rolled back.')
            elif table == 'feature_migrations':
                if after.get(table, [])[:-1] != old_rows or after.get(table, [])[-1].get('version') != 5:
                    raise ValueError('Preservation verification failed for feature migration markers.')
            elif after.get(table) != old_rows:
                raise ValueError(f'Preservation verification failed for {table}; transaction rolled back.')
        for table in ('problems','assignments','progress','problem_notes'):
            if len(after.get(table, [])) != 82:
                raise ValueError(f'Expected 82 rows in {table}; transaction rolled back.')
        if is_postgres(db):
            if db.execute('''SELECT count(*) FROM curriculum_entries e LEFT JOIN problems p ON p.id=e.problem_id
                WHERE e.version=? AND p.id IS NULL''', (plans.VERSION,)).fetchone()[0]:
                raise ValueError('Curriculum foreign-key verification failed.')
        else:
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Curriculum foreign-key verification failed.')
        if not plans.ready(db):
            raise ValueError('Curriculum marker verification failed.')
        return {'plan': current, 'prior_table_digests': {table:_digest(rows) for table,rows in before.items()},
                'post_table_digests': {table:_digest(rows) for table,rows in after.items()},
                'verification':'Existing rows unchanged; only the approved additive catalog/plan/archive, assessment schema, and target settings were written.'}
