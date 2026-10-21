"""Explicit curriculum operation. No startup writes and no schema migration.

Existing eligible date slots are permuted, not regenerated: attempted/manual rows
and every original baseline stay fixed. Receipts contain only IDs/dates/digests.
"""
import hashlib
import json
from .db import ROOT, is_postgres


def order():
    ids = json.loads((ROOT / 'data/curriculum.json').read_text())
    if len(ids) != 75 or len(set(ids)) != 75:
        raise ValueError('Curriculum must contain exactly75 unique stable IDs.')
    return ids


def tables(db):
    query = ("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
             if is_postgres(db) else "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return sorted(r[0] for r in db.execute(query))


def state(db):
    # Names originate from database catalog, still quote them as identifiers.
    return {t: [dict(r) for r in db.execute('SELECT * FROM "' + t.replace('"', '""') + '" ORDER BY 1')]
            for t in tables(db)}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def plan(db):
    ids = order()
    seed = {p['id']: p for p in json.loads((ROOT / 'data/grind75.json').read_text())}
    problems = [dict(r) for r in db.execute('SELECT * FROM problems ORDER BY learning_order')]
    if len(problems) != 75 or {p['id'] for p in problems} != set(ids) or set(seed) != set(ids):
        raise ValueError('Inventory identity mismatch; no changes permitted.')
    if sorted(p['learning_order'] for p in problems) != list(range(1, 76)):
        raise ValueError('Existing curriculum positions are not a complete1–75 permutation.')
    for p in problems:
        expected = seed[p['id']]
        for column, key in [('title','title'), ('url','url'), ('difficulty','difficulty'),
                            ('concept_id','primary_concept_id'), ('grind_rank','grind_rank')]:
            if p[column] != expected[key]:
                raise ValueError('Problem metadata identity mismatch; no changes permitted.')
        metadata = json.loads(p['metadata'])
        if {k:v for k,v in metadata.items() if k != 'learning_order'} != {k:v for k,v in expected.items() if k != 'learning_order'}:
            raise ValueError('Problem metadata differs from the frozen inventory.')
    assignments = {r['problem_id']: dict(r) for r in db.execute('SELECT * FROM assignments')}
    progress = {r['problem_id']: dict(r) for r in db.execute('SELECT * FROM progress')}
    if set(assignments) != set(ids) or set(progress) != set(ids):
        raise ValueError('Assignment/progress identities are incomplete; no changes permitted.')
    eligible = [pid for pid in ids if not progress[pid]['first_attempt_at']
                and progress[pid]['status'] == 'not_started' and not progress[pid]['mastered']
                and not progress[pid]['first_understood_at'] and not assignments[pid]['manual_override']]
    slots = sorted(assignments[pid]['scheduled_date'] for pid in eligible)
    scheduled = dict(zip(eligible, slots))
    mapping = [dict(id=p['id'], old=p['learning_order'], new=ids.index(p['id'])+1) for p in problems]
    changes = [dict(id=pid, old=assignments[pid]['scheduled_date'], new=scheduled[pid])
               for pid in eligible if scheduled[pid] != assignments[pid]['scheduled_date']]
    # A stale reviewed plan cannot be applied after progress or assignments change.
    inputs = dict(problems=problems, assignments=assignments, progress=progress, curriculum=ids)
    return dict(version='personal-curriculum-2026-10-20', fingerprint=fingerprint(inputs),
                mapping=mapping, schedules=changes, eligible_count=len(eligible),
                rule='Permute existing eligible date slots in curriculum order; preserve attempted/manual/baseline/review/history.')


def apply(db, approved):
    with db:
        if not is_postgres(db):
            db.execute('BEGIN IMMEDIATE')
        current = plan(db)  # Read only after obtaining the same lock as app writes.
        if approved != current:
            raise ValueError('Reviewed plan is stale or changed; create and review a fresh dry-run.')
        before = state(db)
        changes = [p for p in current['mapping'] if p['old'] != p['new']]
        # Free the UNIQUE learning_order range before assigning the permutation.
        for p in changes:
            db.execute('UPDATE problems SET learning_order=? WHERE id=?', (-p['new'], p['id']))
        for p in current['mapping']:
            metadata = json.loads(next(r['metadata'] for r in before['problems'] if r['id'] == p['id']))
            metadata['learning_order'] = p['new']
            db.execute('UPDATE problems SET learning_order=?,metadata=? WHERE id=?',
                       (p['new'], json.dumps(metadata), p['id']))
        for p in current['schedules']:
            db.execute('UPDATE assignments SET scheduled_date=? WHERE problem_id=?', (p['new'], p['id']))
        after = state(db)
        # Verify exact permitted projection; every other field/table must match.
        expected = json.loads(json.dumps(before))
        for p in expected['problems']:
            p['learning_order'] = order().index(p['id'])+1
            metadata = json.loads(p['metadata']); metadata['learning_order'] = p['learning_order']
            p['metadata'] = json.dumps(metadata)
        dates = {p['id']:p['new'] for p in current['schedules']}
        for a in expected['assignments']:
            a['scheduled_date'] = dates.get(a['problem_id'], a['scheduled_date'])
        if expected != after:
            raise ValueError('Preservation verification failed; transaction rolled back.')
        return dict(plan=current, before_digests={t:fingerprint(v) for t,v in before.items()},
                    after_digests={t:fingerprint(v) for t,v in after.items()},
                    verification='Only learning_order, its metadata copy, and listed eligible scheduled_date values changed.')
