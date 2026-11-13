"""Whitelisted study facts only; never serialize database rows or private notes."""
import hashlib
import json
import re
import secrets
from datetime import date
from flask import Blueprint, abort, current_app, jsonify, render_template, request, url_for
from .db import get_db
from . import services as s

context_bp=Blueprint('context',__name__)


def snapshot():
    items=s.rows();day=s.today().isoformat();db=get_db()
    from . import plans
    if plans.ready(db):
        curriculum=plans.load();current=plans.current_day(db)
        current_config=next(d for d in curriculum['days'] if d['day']==current)
        all_assessments=plans.latest_assessments(db)
        def public_question(p):
            assessment=all_assessments.get(p['id'],{}).get('assessment','not_assessed')
            return dict(id=p['id'],learning_order=p.get('tracker_number'),title=p['title'],url=p['url'],
                tracker_path=url_for('main.problem',pid=p['id']),concept=p['concept_name'],status=assessment.replace('_',' ').title(),
                assessment=assessment,attempted=bool(p['first_attempt_at']),first_attempt_date=s.local_day(p['first_attempt_at']),
                understood=assessment=='green',independently_mastered=assessment=='green',required_hints=assessment=='yellow',
                needs_review=assessment in ('yellow','red'),review_due=p['next_due_date'],study_day=p.get('day_number'))
        lookup={p['id']:public_question(p) for p in items}
        today_rows=plans.entries_for_day(current,db) if current_config['kind']=='active' else []
        next_rows=[p for p in today_rows if not p['curriculum_attempted']]
        upcoming=[]
        for config in curriculum['days']:
            if (config.get('active_index') or 0)>(current_config.get('active_index') or 0):
                upcoming.extend(plans.entries_for_day(config['day'],db))
        archived=[p for p in plans.archived_rows(db) if not p['first_attempt_at']]
        questions=list(lookup.values())
        concepts=[]
        for cid in dict.fromkeys(p['concept_id'] for p in items):
            group=[p for p in items if p['concept_id']==cid]
            weak=sum(lookup[p['id']]['needs_review'] for p in group)
            concepts.append(dict(name=group[0]['concept_name'],total=len(group),**s.counts(group),weak=weak))
        due=sorted([p for p in questions if p['review_due'] and p['review_due']<=day],key=lambda p:(p['review_due'],p['learning_order'] or 0))
        return dict(date=day,timezone='America/Chicago',daily_target=5,total=75,versioned_plan=True,
            curriculum_focus=dict(current_active_day=current,current_topic=current_config['topic'],anchor='explicit active-day state'),
            counts=s.counts(items),new_attempts_today=sum(bool(p['curriculum_attempted']) for p in today_rows),
            today_assignments=[lookup[p['id']] for p in today_rows],next_questions=[lookup[p['id']] for p in next_rows],
            upcoming_questions=[public_question(p) for p in upcoming if not p['curriculum_attempted']][:15],
            attempted_questions=[p for p in questions if p['attempted']],understood_questions=[p for p in questions if p['understood']],
            mastered_questions=[p for p in questions if p['independently_mastered']],hinted_questions=[p for p in questions if p['required_hints']],
            weak_concepts=[c for c in concepts if c['weak']],concepts=concepts,reviews_due=due,
            overdue_reviews=[p for p in due if p['review_due']<day],earlier_unfinished=[public_question(p) for p in archived])
    hinted=set()
    for event in db.execute("SELECT problem_id,kind,payload FROM activity_events WHERE kind IN ('status','review')"):
        payload=json.loads(event['payload'])
        if payload.get('status')=='hints' or payload.get('result')=='hints':hinted.add(event['problem_id'])
    questions=[]
    for p in items:
        questions.append(dict(
            id=p['id'],learning_order=p['learning_order'],title=p['title'],url=p['url'],tracker_path=url_for('main.problem',pid=p['id']),
            concept=p['concept_name'],status=s.STATUSES[p['status']],
            attempted=bool(p['first_attempt_at']),first_attempt_date=s.local_day(p['first_attempt_at']),
            understood=p['status']=='understood',independently_mastered=bool(p['mastered']),
            required_hints=p['id'] in hinted or p['status']=='hints',
            needs_review=p['status']=='needs_review' or p['status']=='hints' or bool(p['confidence'] and p['confidence']<=2),
            original_assignment=p['baseline_date'],scheduled_date=p['scheduled_date'],review_due=p['next_due_date'],
        ))
    lookup={p['id']:p for p in questions}
    next_items=s.queue(items)[:max(0,6-s.new_today(items))]
    concepts=[]
    for cid in dict.fromkeys(p['concept_id'] for p in items):
        group=[p for p in items if p['concept_id']==cid]
        weak=sum(lookup[p['id']]['needs_review'] for p in group)
        concepts.append(dict(name=group[0]['concept_name'],total=len(group),**s.counts(group),weak=weak))
    due=sorted([p for p in questions if p['review_due'] and p['review_due']<=day],key=lambda p:(p['review_due'],p['learning_order']))
    return dict(date=day,timezone='America/Chicago',daily_target=6,total=75,
        curriculum_focus=dict(start_position=14,anchor='2026-10-20',active=s.focus_active()),
        earlier_unfinished=[lookup[p['id']] for p in s.earlier_unfinished(items)],
        counts=s.counts(items),new_attempts_today=s.new_today(items),
        milestones=dict(first_pass='2026-10-27',revision_end='2026-11-01',readiness='2026-11-02'),
        first_pass_pace=s.pace(items,date(2026,10,27)),fallback_pace=s.pace(items,date(2026,11,1)),
        today_assignments=[p for p in questions if p['scheduled_date']==day],
        next_questions=[lookup[p['id']] for p in next_items],
        upcoming_questions=[lookup[p['id']] for p in sorted(s.focus_items(items),key=lambda p:(p['scheduled_date'],not p['manual_override'],p['learning_order'],p['grind_rank'],p['id'])) if not p['first_attempt_at'] and p['scheduled_date']>day][:12],
        attempted_questions=[p for p in questions if p['attempted']],
        understood_questions=[p for p in questions if p['understood']],
        mastered_questions=[p for p in questions if p['independently_mastered']],
        hinted_questions=[p for p in questions if p['required_hints']],
        weak_concepts=[c for c in concepts if c['weak']],concepts=concepts,
        reviews_due=due,overdue_reviews=[p for p in due if p['review_due']<day],
    )


def enabled():
    return bool(get_db().execute("SELECT 1 FROM security_state WHERE key='study_share_hash'").fetchone())


def render_context(shared=False,one_time_url=None):
    data=snapshot()
    if request.args.get('format')=='json' and request.method=='GET':
        return jsonify(data)
    template='study_context_v2.html' if data.get('versioned_plan') else 'study_context.html'
    return render_template(template,data=data,shared=shared,sharing_enabled=False if shared else enabled(),one_time_url=one_time_url)


@context_bp.route('/study-context')
def study_context():
    return render_context()


@context_bp.route('/study-context/sharing',methods=['POST'])
def sharing():
    action=request.form.get('action')
    if action not in ('enable','regenerate','revoke'):abort(400)
    db=get_db();url=None
    with db:
        if s.begin(db,request.form.get('token')):
            if action=='revoke':
                db.execute("DELETE FROM security_state WHERE key='study_share_hash'")
            else:
                token=secrets.token_urlsafe(32)
                digest=hashlib.sha256(token.encode()).hexdigest()
                db.execute("INSERT INTO security_state VALUES('study_share_hash',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(digest,))
                url=url_for('context.shared',token=token,_external=True)
    return render_context(one_time_url=url)


@context_bp.route('/share/<token>',methods=['GET'])
def shared(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):abort(404)
    row=get_db().execute("SELECT value FROM security_state WHERE key='study_share_hash'").fetchone()
    digest=hashlib.sha256(token.encode()).hexdigest()
    if not row or not secrets.compare_digest(row[0],digest):abort(404)
    return render_context(shared=True)


@context_bp.route('/backup/safety/<backup_id>')
def safety_backup(backup_id):
    from flask import Response
    row=get_db().execute('SELECT payload FROM safety_backups WHERE id=?',(backup_id,)).fetchone()
    if not row:abort(404)
    return Response(row[0],mimetype='application/json',headers={'Content-Disposition':'attachment; filename=safety-backup.json'})
