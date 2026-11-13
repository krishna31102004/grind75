"""Versioned, date-independent study-plan catalog."""
from __future__ import annotations

import json
from pathlib import Path

from .db import ROOT, get_db, is_postgres

PLAN_PATH = ROOT / 'data/curriculum_v2.json'
ADDITIONS_PATH = ROOT / 'data/curriculum_v2_additions.json'
VERSION = 'personal-plan-2026-11-v1'
ARCHIVED_TITLES = {
    '01 Matrix',
    'Letter Combinations of a Phone Number',
    'Largest Rectangle in Histogram',
    'Spiral Matrix',
    'Basic Calculator',
    'Minimum Height Trees',
    'Maximum Profit in Job Scheduling',
}


def inventory():
    """Return the preserved 75-row source inventory plus seven new identities."""
    base = json.loads((ROOT / 'data/grind75.json').read_text(encoding='utf-8'))
    additions = json.loads(ADDITIONS_PATH.read_text(encoding='utf-8'))
    combined = base + additions
    ids = [row['id'] for row in combined]
    if len(ids) != 82 or len(set(ids)) != 82:
        raise ValueError('Problem catalog must contain 82 unique stable IDs.')
    return combined


def load():
    plan = json.loads(PLAN_PATH.read_text(encoding='utf-8'))
    if plan.get('version') != VERSION or plan.get('daily_target') != 5 or plan.get('timezone') != 'America/Chicago':
        raise ValueError('Unsupported personal curriculum version or settings.')
    days = plan.get('days')
    if not isinstance(days, list) or [d.get('day') for d in days] != list(range(1, 22)):
        raise ValueError('The curriculum must define calendar days 1 through 21 exactly once.')
    active = [d for d in days if d.get('kind') == 'active']
    flexible = [d for d in days if d.get('kind') == 'flexible']
    if len(active) != 15 or [d.get('active_index') for d in active] != list(range(1, 16)):
        raise ValueError('The plan must have 15 sequential active study days.')
    if [d['day'] for d in flexible] != [6, 7, 13, 14, 20, 21]:
        raise ValueError('Flexible days must remain days 6-7, 13-14, and 20-21.')
    catalog = {p['id']: p for p in inventory()}
    entries = []
    seen_ids, seen_numbers = set(), set()
    for day in days:
        if day.get('kind') not in ('active', 'flexible') or not isinstance(day.get('topic'), str):
            raise ValueError('Each plan day needs a supported kind and topic.')
        problems = day.get('problems')
        if not isinstance(problems, list) or (day['kind'] == 'active' and len(problems) != 5) or (day['kind'] == 'flexible' and problems):
            raise ValueError('Every active day must have five slots; flexible days must have none.')
        for slot, item in enumerate(problems, 1):
            pid, number = item.get('problem_id'), item.get('tracker_number')
            if pid not in catalog or pid in seen_ids:
                raise ValueError(f'Unknown or duplicate problem identity in plan: {pid!r}.')
            if type(number) is not int or not 1 <= number <= 75 or number in seen_numbers:
                raise ValueError(f'Invalid or duplicate tracker number: {number!r}.')
            seen_ids.add(pid); seen_numbers.add(number)
            entries.append(dict(version=VERSION, day_number=day['day'], week=day['week'],
                                active_index=day['active_index'], topic=day['topic'], slot=slot,
                                tracker_number=number, problem_id=pid))
    if len(entries) != 75 or seen_numbers != set(range(1, 76)):
        raise ValueError('The active curriculum must use all 75 tracker numbers exactly once.')
    old = json.loads((ROOT / 'data/grind75.json').read_text(encoding='utf-8'))
    archived = {p['id'] for p in old if p['title'] in ARCHIVED_TITLES}
    expected = {p['id'] for p in old} - archived | {p['id'] for p in json.loads(ADDITIONS_PATH.read_text(encoding='utf-8'))}
    if seen_ids != expected or len(archived) != 7:
        raise ValueError('Active plan/replacement set differs from the approved seven substitutions.')
    return {**plan, 'entries': entries, 'active_ids': seen_ids, 'archived_ids': archived, 'catalog': catalog}


def ready(db=None):
    db = db or get_db()
    if is_postgres(db):
        if db.execute("SELECT to_regclass('feature_migrations')").fetchone()[0] is None:return False
    elif db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_migrations'").fetchone() is None:
        return False
    marker = db.execute("SELECT 1 FROM feature_migrations WHERE version=5").fetchone()
    if marker is None:
        return False
    return db.execute('SELECT 1 FROM curriculum_versions WHERE version=?', (VERSION,)).fetchone() is not None


def current_day(db=None):
    db = db or get_db()
    row = db.execute("SELECT value FROM settings WHERE key='active_study_day'").fetchone()
    try:day=int(row[0]) if row else 1
    except (TypeError,ValueError):raise RuntimeError('Active study day state is invalid; stop and inspect the database.') from None
    active_days={d['day'] for d in load()['days'] if d['kind']=='active'}
    if day not in active_days:raise RuntimeError('Active study day points to a flexible or unknown day; stop and inspect the database.')
    return day


def entries_for_day(day_number, db=None):
    db = db or get_db()
    rows = [dict(r) for r in db.execute('''SELECT e.*,p.title,p.difficulty,p.url,p.concept_id,c.name AS concept_name,
        a.baseline_date,a.scheduled_date,a.manual_override,
        g.status,g.first_attempt_at,g.first_understood_at,g.mastered,n.takeaway,n.approach,n.confidence,n.effort,
        r.next_due_date,r.stage,EXISTS(SELECT 1 FROM assessment_events ae WHERE ae.problem_id=p.id AND ae.context='first_pass') AS curriculum_attempted
        FROM curriculum_entries e JOIN problems p ON p.id=e.problem_id
        JOIN concepts c ON c.id=p.concept_id JOIN progress g ON g.problem_id=p.id JOIN assignments a ON a.problem_id=p.id
        JOIN problem_notes n ON n.problem_id=p.id LEFT JOIN review_state r ON r.problem_id=p.id
        WHERE e.version=? AND e.day_number=? ORDER BY e.slot''', (VERSION, day_number))]
    for row in rows:
        row['id'] = row['problem_id']
    return rows


def active_rows(db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute('''SELECT p.*,e.tracker_number,e.day_number,d.week,d.active_index,e.slot,d.topic,
        g.status,g.first_attempt_at,g.first_understood_at,g.mastered,a.baseline_date,a.scheduled_date,a.manual_override,
        EXISTS(SELECT 1 FROM assessment_events ae WHERE ae.problem_id=p.id AND ae.context='first_pass') AS curriculum_attempted,
        n.takeaway,n.approach,n.confidence,n.effort,c.name AS concept_name,r.next_due_date,r.stage
        FROM curriculum_entries e JOIN problems p ON p.id=e.problem_id
        JOIN curriculum_days d ON d.version=e.version AND d.day_number=e.day_number
        JOIN progress g ON g.problem_id=p.id JOIN assignments a ON a.problem_id=p.id
        JOIN problem_notes n ON n.problem_id=p.id JOIN concepts c ON c.id=p.concept_id
        LEFT JOIN review_state r ON r.problem_id=p.id WHERE e.version=? ORDER BY e.day_number,e.slot''', (VERSION,))]


def archived_rows(db=None):
    db = db or get_db()
    return [dict(r) for r in db.execute('''SELECT p.*,g.status,g.first_attempt_at,g.first_understood_at,g.mastered,
        a.baseline_date,a.scheduled_date,a.manual_override,n.takeaway,n.approach,n.confidence,n.effort,
        c.name AS concept_name,r.next_due_date,r.stage
        FROM curriculum_archive x JOIN problems p ON p.id=x.problem_id JOIN progress g ON g.problem_id=p.id
        JOIN assignments a ON a.problem_id=p.id JOIN problem_notes n ON n.problem_id=p.id
        JOIN concepts c ON c.id=p.concept_id LEFT JOIN review_state r ON r.problem_id=p.id
        WHERE x.version=? ORDER BY p.learning_order,p.grind_rank,p.id''', (VERSION,))]


def latest_assessments(db=None):
    db = db or get_db()
    return {r['problem_id']: dict(r) for r in db.execute('''SELECT a.* FROM assessment_events a
        JOIN (SELECT problem_id,MAX(at || ':' || id) AS latest FROM assessment_events GROUP BY problem_id) x
        ON x.problem_id=a.problem_id AND x.latest=(a.at || ':' || a.id)''')}


def day_complete(day_number, db=None):
    rows = entries_for_day(day_number, db)
    return len(rows) == 5 and all(row['curriculum_attempted'] for row in rows)


def next_active_day(day_number, plan=None):
    plan = plan or load()
    return next((d['day'] for d in plan['days'] if d['day'] > day_number and d['kind'] == 'active'), None)
