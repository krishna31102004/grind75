"""Explicit curriculum operation. No startup writes and no schema migration.

Eligible #14+ assignments start at a fixed October20 anchor. Earlier entries,
attempted/manual rows and every original baseline stay fixed.
"""
import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from .db import ROOT, is_postgres


ANCHOR = date(2026, 10, 20)
FOCUS_POSITION = 14
DAILY_TARGET = 6

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
    history = [dict(r) for r in db.execute("SELECT * FROM activity_events WHERE kind IN ('status','review','move') ORDER BY id")]
    review_events = [dict(r) for r in db.execute('SELECT * FROM review_events ORDER BY id')]
    reviews = [dict(r) for r in db.execute('SELECT * FROM review_state ORDER BY problem_id')]
    attempted_history = {r['problem_id'] for r in review_events + reviews}
    moved_history = set()
    status_attempt_days = {}
    for event in history:
        pid = event['problem_id']
        if event['kind'] == 'move':
            moved_history.add(pid)
        elif event['kind'] == 'review':
            attempted_history.add(pid)
        else:
            try:
                payload = json.loads(event['payload'])
                valid_statuses = {'not_started','attempted','hints','understood','needs_review'}
                if not isinstance(payload, dict) or any(payload.get(k) not in valid_statuses for k in ('old','status')) or type(payload.get('independent')) is not bool:
                    raise ValueError()
                if payload['status'] != 'not_started' or payload['old'] != 'not_started' or payload['independent']:
                    attempted_history.add(pid)
                    # Conservatively reserve the earliest surviving status-evidence
                    # day if first_attempt_at is absent (even a later reset). This is
                    # a planning reservation, never a fabricated first-attempt count.
                    if payload['status'] != 'not_started' or payload['old'] != 'not_started' or payload['independent']:
                        evidenced = datetime.fromisoformat(event['at']).astimezone(ZoneInfo('America/Chicago')).date()
                        status_attempt_days[pid] = min(evidenced, status_attempt_days.get(pid, evidenced))
            except (ValueError, TypeError):
                attempted_history.add(pid)  # Unreadable evidence cannot authorize a move.
    excluded = []
    eligible = []
    for position, pid in enumerate(ids, 1):
        p, a = progress[pid], assignments[pid]
        reasons = []
        if position < FOCUS_POSITION: reasons.append('earlier curriculum entry; assignment retained')
        if p['first_attempt_at']: reasons.append('recorded first attempt')
        if p['status'] != 'not_started': reasons.append('status is not Not Started')
        if p['mastered']: reasons.append('mastery recorded')
        if p['first_understood_at']: reasons.append('understanding recorded')
        if a['manual_override']: reasons.append('manual date override')
        if pid in attempted_history: reasons.append('attempt/review history')
        if pid in moved_history: reasons.append('manual move history')
        if reasons:
            excluded.append(dict(id=pid, learning_order=position, scheduled_date=a['scheduled_date'], reasons=reasons))
        else:
            eligible.append(pid)
    # Reserve actual unique first attempts on their Chicago dates, and preserved
    # unattempted assignments on their fixed dates. Never count reviews as new work.
    occupancy = {}
    for pid in ids:
        p = progress[pid]
        day = None
        if p['first_attempt_at']:
            day = datetime.fromisoformat(p['first_attempt_at']).astimezone(ZoneInfo('America/Chicago')).date()
        elif pid in status_attempt_days:
            day = status_attempt_days[pid]
        elif pid not in eligible:
            day = date.fromisoformat(assignments[pid]['scheduled_date'])
        if day and day >= ANCHOR:
            occupancy[day.isoformat()] = occupancy.get(day.isoformat(), 0) + 1
    reserved = dict(occupancy)
    scheduled = {}
    day = ANCHOR
    for pid in eligible:
        while occupancy.get(day.isoformat(), 0) >= DAILY_TARGET:
            day += timedelta(days=1)
        scheduled[pid] = day.isoformat()
        occupancy[day.isoformat()] = occupancy.get(day.isoformat(), 0) + 1
    focus_id = ids[FOCUS_POSITION-1]
    conflicts = []
    if focus_id not in eligible:
        conflicts.append('#14 Diameter is protected by an attempt, status, review or manual assignment; clarification required.')
    elif scheduled[focus_id] != ANCHOR.isoformat():
        conflicts.append('Preserved assignments/actual attempts fill October20 capacity; #14 cannot safely start on its anchor.')
    mapping = [dict(id=p['id'], old=p['learning_order'], new=ids.index(p['id'])+1,
                    metadata_update=json.loads(p['metadata']).get('learning_order') != ids.index(p['id'])+1) for p in problems]
    changes = [dict(id=pid, old=assignments[pid]['scheduled_date'], new=scheduled[pid])
               for pid in eligible if scheduled[pid] != assignments[pid]['scheduled_date']]
    resulting = [dict(id=pid, learning_order=ids.index(pid)+1, scheduled_date=scheduled[pid]) for pid in eligible]
    earlier = [dict(id=pid, learning_order=ids.index(pid)+1, scheduled_date=assignments[pid]['scheduled_date'], status=progress[pid]['status'])
               for pid in ids[:FOCUS_POSITION-1] if not progress[pid]['first_attempt_at']]
    # History used for eligibility is fingerprinted too; new evidence stales a plan.
    inputs = dict(problems=problems, assignments=assignments, progress=progress, curriculum=ids,
                  history=history, reviews=reviews, review_events=review_events,
                  policy='fixed-anchor-v2', anchor=ANCHOR.isoformat())
    return dict(version='personal-curriculum-fixed-anchor-v2', fingerprint=fingerprint(inputs),
                anchor=ANCHOR.isoformat(), timezone='America/Chicago', mapping=mapping,
                schedules=changes, eligible_count=len(eligible), exclusions=excluded,
                earlier_unfinished=earlier, reserved_capacity=reserved, resulting_schedule=resulting,
                next_questions=resulting[:12], focus=dict(id=focus_id, eligible=focus_id in eligible,
                    scheduled_date=scheduled.get(focus_id), eligible_for_anchor=scheduled.get(focus_id)==ANCHOR.isoformat()),
                applicable=not conflicts, conflicts=conflicts,
                rows_to_update=dict(problems=sum(p['old']!=p['new'] or p['metadata_update'] for p in mapping), assignments=len(changes)),
                write_set=['problems.learning_order','problems.metadata.learning_order','assignments.scheduled_date'],
                rule='Fixed October20 anchor, six/day less preserved capacity; exclude earlier entries, attempted/manual/history; protect all other data.')


def apply(db, approved):
    with db:
        if not is_postgres(db):
            db.execute('BEGIN IMMEDIATE')
        current = plan(db)  # Read only after obtaining the same lock as app writes.
        if approved != current:
            raise ValueError('Reviewed plan is stale or changed; create and review a fresh dry-run.')
        if not current['applicable']:
            raise ValueError('Curriculum focus conflict; no changes made. Review the dry-run exclusions and request clarification.')
        before = state(db)
        changes = [p for p in current['mapping'] if p['old'] != p['new']]
        # Free the UNIQUE learning_order range before assigning the permutation.
        for p in changes:
            db.execute('UPDATE problems SET learning_order=? WHERE id=?', (-p['new'], p['id']))
        for p in current['mapping']:
            if p['old'] == p['new'] and not p['metadata_update']: continue
            metadata = json.loads(next(r['metadata'] for r in before['problems'] if r['id'] == p['id']))
            metadata['learning_order'] = p['new']
            db.execute('UPDATE problems SET learning_order=?,metadata=? WHERE id=?',
                       (p['new'], json.dumps(metadata), p['id']))
        for p in current['schedules']:
            db.execute('UPDATE assignments SET scheduled_date=? WHERE problem_id=?', (p['new'], p['id']))
        after = state(db)
        # Verify exact permitted projection; every other field/table must match.
        expected = json.loads(json.dumps(before))
        changed_ids={p['id'] for p in current['mapping'] if p['old']!=p['new'] or p['metadata_update']}
        for p in expected['problems']:
            if p['id'] not in changed_ids: continue
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
