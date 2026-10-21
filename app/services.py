import json
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import current_app
from .db import get_db

STATUSES = {'not_started':'Not Started','attempted':'Attempted','hints':'Solved With Hints','understood':'Understood','needs_review':'Needs Review'}

def now():
    value = current_app.config.get('NOW')
    return datetime.fromisoformat(value) if value else datetime.now(timezone.utc)

def stamp():
    return now().astimezone(timezone.utc).isoformat()

def today():
    return now().astimezone(ZoneInfo('America/Chicago')).date()

def local_day(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo('America/Chicago')).date().isoformat() if value else None

def valid_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value or not 2020 <= parsed.year <= 2100:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise ValueError('Enter a valid date between 2020 and 2100.') from None

def rows():
    return [dict(r) for r in get_db().execute('''SELECT p.*, g.status,g.first_attempt_at,g.first_understood_at,g.mastered,
        a.baseline_date,a.scheduled_date,a.manual_override,n.takeaway,n.approach,n.confidence,n.effort,
        c.name AS concept_name,r.next_due_date,r.stage
        FROM problems p JOIN progress g ON p.id=g.problem_id JOIN assignments a ON p.id=a.problem_id
        JOIN problem_notes n ON p.id=n.problem_id JOIN concepts c ON p.concept_id=c.id
        LEFT JOIN review_state r ON p.id=r.problem_id ORDER BY p.learning_order,p.grind_rank,p.id''')]

def counts(items):
    return dict(attempted=sum(p['first_attempt_at'] is not None for p in items), understood=sum(p['status']=='understood' for p in items), mastered=sum(p['mastered'] for p in items), needs_review=sum(p['status']=='needs_review' for p in items), ever_understood=sum(p['first_understood_at'] is not None for p in items))

def pace(items, target):
    remaining = sum(p['first_attempt_at'] is None for p in items)
    days = max(0,(target-today()).days+1)
    return dict(remaining=remaining,days=days,average=round(remaining/days,2) if days else None,shortfall=max(0,remaining-days*6),target=target.isoformat())

def new_today(items):
    return sum(local_day(p['first_attempt_at'])==today().isoformat() for p in items)

def focus_active():
    from .curriculum import ANCHOR
    return today() >= ANCHOR


def earlier_unfinished(items):
    from .curriculum import order, FOCUS_POSITION
    earlier = set(order()[:FOCUS_POSITION-1])
    return [p for p in items if p['id'] in earlier and not p['first_attempt_at']] if focus_active() else []


def focus_items(items):
    from .curriculum import order, FOCUS_POSITION
    earlier = set(order()[:FOCUS_POSITION-1])
    return [p for p in items if p['id'] not in earlier] if focus_active() else items


def queue(items):
    eligible = [p for p in focus_items(items) if not p['first_attempt_at'] and p['scheduled_date']<=today().isoformat()]
    if focus_active():
        return sorted(eligible,key=lambda p:(p['learning_order'],p['grind_rank'],p['id']))
    return sorted(eligible,key=lambda p:(p['scheduled_date'],not p['manual_override'],p['learning_order'],p['grind_rank'],p['id']))


def begin(db, token):
    if not isinstance(token,str) or not 16 <= len(token) <= 100:
        raise ValueError('Invalid action token. Refresh the page and try again.')
    return db.execute('INSERT OR IGNORE INTO submissions VALUES(?,?)',(token,stamp())).rowcount == 1

def event(db,token,pid,kind,payload):
    db.execute('INSERT INTO activity_events VALUES(?,?,?,?,?)',(token,pid,kind,stamp(),json.dumps(payload)))

def set_status(pid,status,independent,token):
    if status not in STATUSES or (independent and status!='understood'):
        raise ValueError('Select a valid status; independent initial success requires Understood.')
    db=get_db()
    with db:
        if not begin(db,token): return
        old=db.execute('SELECT * FROM progress WHERE problem_id=?',(pid,)).fetchone()
        if old is None: raise ValueError('Unknown problem.')
        attempted=old['first_attempt_at'] or (stamp() if status!='not_started' else None)
        understood=old['first_understood_at'] or (stamp() if status=='understood' else None)
        mastered=1 if independent else (0 if status in ('needs_review','hints','not_started') else old['mastered'])
        db.execute('UPDATE progress SET status=?,first_attempt_at=?,first_understood_at=?,mastered=? WHERE problem_id=?',(status,attempted,understood,mastered,pid))
        event(db,token,pid,'status',dict(old=old['status'],status=status,independent=independent))
        if status=='understood':
            db.execute('INSERT OR IGNORE INTO review_state VALUES(?,0,?,NULL)',(pid,(today()+timedelta(days=1)).isoformat()))
        elif status in ('needs_review','hints'):
            db.execute('INSERT INTO review_state VALUES(?,0,?,NULL) ON CONFLICT(problem_id) DO UPDATE SET stage=0,next_due_date=excluded.next_due_date',(pid,(today()+timedelta(days=1)).isoformat()))

def save_notes(pid,form,token):
    takeaway=form.get('takeaway','');approach=form.get('approach','')
    if len(takeaway)>10000 or len(approach)>10000: raise ValueError('Notes must be at most 10,000 characters per field.')
    try:
        confidence=int(form['confidence']) if form.get('confidence') else None
        effort=int(form['effort']) if form.get('effort') else None
    except (ValueError,TypeError): raise ValueError('Confidence and minutes must be whole numbers.') from None
    if confidence is not None and not 1<=confidence<=5 or effort is not None and not 0<=effort<=600:
        raise ValueError('Confidence must be 1–5; minutes must be 0–600.')
    db=get_db()
    with db:
        if not begin(db,token): return
        db.execute('UPDATE problem_notes SET takeaway=?,approach=?,confidence=?,effort=? WHERE problem_id=?',(takeaway,approach,confidence,effort,pid))
        event(db,token,pid,'notes',dict(confidence=confidence,effort=effort))

def review(pid,result,note,token):
    if result not in ('independent','hints','failed') or len(note)>10000:
        raise ValueError('Select a valid review result and a note of at most 10,000 characters.')
    db=get_db()
    with db:
        if not begin(db,token): return
        state=db.execute('SELECT * FROM review_state WHERE problem_id=?',(pid,)).fetchone()
        progress=db.execute('SELECT * FROM progress WHERE problem_id=?',(pid,)).fetchone()
        if progress is None or not progress['first_attempt_at']:
            raise ValueError('Record an initial attempt before a review.')
        stage=(state['stage'] if state else 0)
        if result=='independent':
            stage=min(3,stage+1)
            due=(today()+timedelta(days=3 if stage==1 else 7)).isoformat() if stage<3 else None
            db.execute('UPDATE progress SET mastered=1 WHERE problem_id=?',(pid,))
        else:
            stage=0;due=(today()+timedelta(days=1)).isoformat()
            db.execute("UPDATE progress SET mastered=0,status='needs_review' WHERE problem_id=?",(pid,))
        db.execute('INSERT INTO review_state VALUES(?,?,?,?) ON CONFLICT(problem_id) DO UPDATE SET stage=excluded.stage,next_due_date=excluded.next_due_date,last_result=excluded.last_result',(pid,stage,due,result))
        db.execute('INSERT INTO review_events VALUES(?,?,?,?,?)',(token,pid,stamp(),result,note))
        event(db,token,pid,'review',dict(result=result,note=note))

def move(pid,value,token):
    value=valid_date(value).isoformat();db=get_db()
    with db:
        if not begin(db,token):return
        old=db.execute('SELECT scheduled_date FROM assignments WHERE problem_id=?',(pid,)).fetchone()[0]
        db.execute('UPDATE assignments SET scheduled_date=?,manual_override=1 WHERE problem_id=?',(value,pid))
        event(db,token,pid,'move',dict(old=old,new=value))

def catch_up(token,reset=False):
    db=get_db()
    with db:
        if not begin(db,token):return
        items=rows()
        candidates=focus_items(items)
        if reset:
            for p in candidates:
                if not p['first_attempt_at']:
                    db.execute('UPDATE assignments SET manual_override=0 WHERE problem_id=?',(p['id'],))
        pending=[p for p in candidates if not p['first_attempt_at'] and (reset or not p['manual_override'])]
        candidate_ids={p['id'] for p in candidates}
        fixed=[p for p in items if not p['first_attempt_at'] and (p['id'] not in candidate_ids or (p['manual_override'] and not reset))]
        occupancy={}
        for p in fixed:occupancy[p['scheduled_date']]=occupancy.get(p['scheduled_date'],0)+1
        occupancy[today().isoformat()]=occupancy.get(today().isoformat(),0)+new_today(items)
        day=today();changes=[]
        for p in pending:
            while occupancy.get(day.isoformat(),0)>=6:day+=timedelta(days=1)
            scheduled=day.isoformat();occupancy[scheduled]=occupancy.get(scheduled,0)+1
            db.execute('UPDATE assignments SET scheduled_date=? WHERE problem_id=?',(scheduled,p['id']))
            if p['scheduled_date']!=scheduled:changes.append(dict(id=p['id'],old=p['scheduled_date'],new=scheduled))
        event(db,token,None,'catch_up',dict(reset=reset,changes=changes))


def activity_description(event_row):
    """Render stored history as study language, keeping payload details in backups."""
    payload=json.loads(event_row['payload'])
    kind=event_row['kind']
    if kind=='status':
        before=STATUSES.get(payload.get('old'),'Previous status') if isinstance(payload.get('old'),str) else 'Previous status'
        after=STATUSES.get(payload.get('status'),'Updated status') if isinstance(payload.get('status'),str) else 'Updated status'
        return before+' → '+after+(' · Independent initial solve' if payload.get('independent') else '')
    if kind=='review':
        label={'independent':'Independent success','hints':'Needed hints','failed':'Failed / low confidence'}.get(payload.get('result'),'Review') if isinstance(payload.get('result'),str) else 'Review'
        return label+(' · '+str(payload['note']) if payload.get('note') else '')
    if kind=='notes':
        return 'Notes saved'+(' · Confidence '+str(payload['confidence'])+'/5' if payload.get('confidence') else '')+(' · '+str(payload['effort'])+' minutes' if payload.get('effort') is not None else '')
    if kind=='move':return 'Assignment moved: '+str(payload.get('old',''))+' → '+str(payload.get('new',''))
    if kind=='reveal':return 'Problem guide deliberately revealed'
    if kind=='review_schedule':return 'Review scheduled: '+str(payload.get('date',''))
    if kind=='catch_up':return 'Catch-up schedule saved'
    if kind=='concept_note':return 'Concept note saved'
    if kind in ('learning_record_edit','learning_record_import'):
        return 'Personal learning record saved ('+', '.join(payload.get('fields',[]))+')'
    return 'Study activity saved'
