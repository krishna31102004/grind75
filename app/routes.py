import json
import secrets
from datetime import date, timedelta
from urllib.parse import urlsplit
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for, Response
from .db import get_db, ROOT
from . import services as s
from .backup import export_data, restore

bp=Blueprint('main',__name__)

def csrf():
    if 'csrf' not in session:session['csrf']=secrets.token_hex(24)
    return session['csrf']

@bp.app_context_processor
def context():
    return dict(statuses=s.STATUSES,csrf=csrf,token=lambda:secrets.token_hex(20),local_day=s.local_day,activity_description=s.activity_description,study_today=s.today())

@bp.route('/')
def today():
    items=s.rows();eligible=s.queue(items);done=s.new_today(items)
    limit=max(0,6-done)
    due=[p for p in items if p['next_due_date'] and p['next_due_date']<=s.today().isoformat()]
    ahead=[]
    if request.args.get('ahead')=='1':
        shown={p['id'] for p in eligible[:limit]}
        ahead=[p for p in items if not p['first_attempt_at'] and p['id'] not in shown][:6]
    return render_template('today.html',items=eligible[:limit],overflow=max(0,len(eligible)-limit),ahead=ahead,due=due,done=done,counts=s.counts(items),pace=s.pace(items,date(2026,10,27)),fallback=s.pace(items,date(2026,11,1)))

@bp.route('/concepts')
@bp.route('/concepts/<cid>')
def concepts(cid=None):
    concepts=[dict(r) for r in get_db().execute('SELECT * FROM concepts ORDER BY display_order')]
    for c in concepts:c['content']=json.loads(c['content']);c['counts']=s.counts([p for p in s.rows() if p['concept_id']==c['id']])
    if cid:
        concept=next((c for c in concepts if c['id']==cid),None)
        if not concept:abort(404)
        items=[p for p in s.rows() if p['concept_id']==cid]
        if request.args.get('difficulty'):items=[p for p in items if p['difficulty']==request.args['difficulty']]
        if request.args.get('status'):items=[p for p in items if p['status']==request.args['status']]
        note=get_db().execute('SELECT note FROM concept_notes WHERE concept_id=?',(cid,)).fetchone()
        return render_template('concept.html',concept=concept,items=items,note=note[0] if note else '')
    return render_template('concepts.html',concepts=concepts)

@bp.route('/cheatsheets')
def cheatsheets():
    items=s.rows();q=request.args.get('q','').casefold().strip()
    if q:items=[p for p in items if q in (p['title']+' '+p['concept_name']).casefold()]
    return render_template('list.html',heading='Cheat Sheets',intro='Concept primers are always available. Problem reasoning opens only after an attempt or an intentional reveal.',items=items,search=True)

@bp.route('/problem/<pid>')
def problem(pid):
    p=next((p for p in s.rows() if p['id']==pid),None)
    if p is None:abort(404)
    revealed=get_db().execute("SELECT 1 FROM activity_events WHERE problem_id=? AND kind='reveal' LIMIT 1",(pid,)).fetchone()
    unlocked=bool(p['first_attempt_at'] or revealed)
    guide=None
    if unlocked:
        guides=json.loads((ROOT/'data/problem_guides.json').read_text());guide=guides[pid]
    history=[dict(r) for r in get_db().execute('SELECT * FROM activity_events WHERE problem_id=? ORDER BY at DESC,id DESC',(pid,))]
    reviews=[dict(r) for r in get_db().execute('SELECT * FROM review_events WHERE problem_id=? ORDER BY at DESC,id DESC',(pid,))]
    return render_template('problem.html',p=p,guide=guide,history=history,reviews=reviews)

@bp.route('/problem/<pid>/<action>',methods=['POST'])
def update(pid,action):
    if not get_db().execute('SELECT 1 FROM problems WHERE id=?',(pid,)).fetchone():abort(404)
    token=request.form.get('token');db=get_db()
    try:
        if action=='status':s.set_status(pid,request.form.get('status'),request.form.get('independent')=='yes',token)
        elif action=='notes':s.save_notes(pid,request.form,token)
        elif action=='review':s.review(pid,request.form.get('result'),request.form.get('note',''),token)
        elif action=='move':s.move(pid,request.form.get('date'),token)
        elif action=='review_schedule':
            due=s.valid_date(request.form.get('date')).isoformat()
            with db:
                if s.begin(db,token):
                    if not db.execute('SELECT first_attempt_at FROM progress WHERE problem_id=?',(pid,)).fetchone()[0]:raise ValueError('Record an attempt first.')
                    db.execute('INSERT INTO review_state VALUES(?,0,?,NULL) ON CONFLICT(problem_id) DO UPDATE SET stage=0,next_due_date=excluded.next_due_date',(pid,due))
                    s.event(db,token,pid,'review_schedule',dict(date=due))
        elif action=='reveal':
            with db:
                if s.begin(db,token):s.event(db,token,pid,'reveal',{})
        else:abort(404)
        flash('Saved. Your progress is saved.','success')
    except ValueError as exc:flash(str(exc),'error')
    return redirect(url_for('main.problem',pid=pid))

@bp.route('/concepts/<cid>/notes',methods=['POST'])
def concept_notes(cid):
    db=get_db()
    if not db.execute('SELECT 1 FROM concepts WHERE id=?',(cid,)).fetchone():abort(404)
    try:
        note=request.form.get('note','')
        if len(note)>10000:raise ValueError('Concept note is too long.')
        with db:
            if s.begin(db,request.form.get('token')):
                db.execute('INSERT INTO concept_notes VALUES(?,?) ON CONFLICT(concept_id) DO UPDATE SET note=excluded.note',(cid,note))
                s.event(db,request.form['token'],None,'concept_note',dict(concept_id=cid))
        flash('Concept note saved.','success')
    except ValueError as exc:flash(str(exc),'error')
    return redirect(url_for('main.concepts',cid=cid))

@bp.route('/review')
def reviews():
    items=s.rows();day=s.today().isoformat()
    due=[p for p in items if p['next_due_date'] and p['next_due_date']<=day]
    weak=[p for p in items if p['first_attempt_at'] and (p['status'] in ('hints','needs_review') or (p['confidence'] and p['confidence']<=2)) and p not in due]
    future=[p for p in items if p['next_due_date'] and p['next_due_date']>day and p not in weak]
    return render_template('review.html',due=due,weak=weak,future=future)

@bp.route('/calendar')
def calendar():
    items=s.rows();days={}
    events=[dict(r) for r in get_db().execute('SELECT e.*,p.title FROM activity_events e LEFT JOIN problems p ON e.problem_id=p.id ORDER BY at')]
    for offset in range(19):days[(date(2026,10,15)+timedelta(days=offset)).isoformat()]=dict(baseline=[],current=[],activity=[])
    for p in items:
        for key,col in [('baseline','baseline_date'),('current','scheduled_date')]:
            days.setdefault(p[col],dict(baseline=[],current=[],activity=[]))[key].append(p)
    for e in events:
        if e['kind'] in ('status','review'):
            day=s.local_day(e['at']);days.setdefault(day,dict(baseline=[],current=[],activity=[]))['activity'].append(e)
    return render_template('calendar.html',days=sorted(days.items()),today=s.today().isoformat())

@bp.route('/progress')
def progress():
    items=s.rows();concepts=[dict(r) for r in get_db().execute('SELECT id,name FROM concepts ORDER BY display_order')]
    for c in concepts:
        subset=[p for p in items if p['concept_id']==c['id']];c.update(s.counts(subset));c['total']=len(subset)
    return render_template('progress.html',counts=s.counts(items),concepts=concepts,done=s.new_today(items),pace=s.pace(items,date(2026,10,27)),fallback=s.pace(items,date(2026,11,1)),due=sum(bool(p['next_due_date'] and p['next_due_date']<=s.today().isoformat()) for p in items))

@bp.route('/reschedule',methods=['POST'])
def reschedule():
    try:s.catch_up(request.form.get('token'),request.form.get('reset')=='yes');flash('Unattempted assignments rescheduled. Original dates and history preserved.','success')
    except ValueError as exc:flash(str(exc),'error')
    return redirect(url_for('main.calendar'))

@bp.route('/backup',methods=['GET','POST'])
def backup():
    if request.method=='POST':
        try:
            if request.form.get('confirm')!='REPLACE':raise ValueError('Type REPLACE to confirm replacement of current progress.')
            file=request.files.get('backup')
            if not file:raise ValueError('Choose a JSON backup file.')
            # Duplicate JSON keys must not silently overwrite earlier values.
            def unique(pairs):
                result={}
                for k,v in pairs:
                    if k in result:raise ValueError('Duplicate JSON keys are not allowed.')
                    result[k]=v
                return result
            payload=json.load(file,object_pairs_hook=unique)
            saved=restore(payload);flash('Restored successfully. A safety copy was saved: '+saved,'success')
            return redirect(url_for('main.backup'))
        except (ValueError,UnicodeError,RecursionError) as exc:flash('Import rejected: '+str(exc),'error')
    return render_template('backup.html',safety_copies=[dict(r) for r in get_db().execute('SELECT id,created_at FROM safety_backups ORDER BY created_at DESC')])

@bp.route('/export')
def export():
    return Response(json.dumps(export_data(),indent=2),mimetype='application/json',headers={'Content-Disposition':'attachment; filename=grind75-backup-'+s.today().isoformat()+'.json'})

@bp.after_app_request
def headers(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer' if request.path.startswith('/share/') else 'same-origin'
    response.headers['X-Robots-Tag']='noindex, nofollow, nosnippet'
    if current_app.config['PRODUCTION']: response.headers['Strict-Transport-Security']='max-age=31536000'
    response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    return response
