import json
import secrets
import sqlite3
import psycopg
from datetime import date, timedelta
from urllib.parse import urlsplit
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for, Response
from .db import get_db, is_postgres, ROOT
from . import services as s
from .backup import export_data, restore
from . import learning_records as lr

bp=Blueprint('main',__name__)

def csrf():
    if 'csrf' not in session:session['csrf']=secrets.token_hex(24)
    return session['csrf']

@bp.app_context_processor
def context():
    def records_available():
        try:return lr.migration_ready()
        except (RuntimeError,sqlite3.Error,psycopg.Error):return False
    def versioned_curriculum_available():
        from . import plans
        try:return plans.ready(get_db())
        except (RuntimeError,sqlite3.Error,psycopg.Error):return False
    return dict(learning_records_available=records_available,versioned_curriculum_available=versioned_curriculum_available,statuses=s.STATUSES,csrf=csrf,token=lambda:secrets.token_hex(20),local_day=s.local_day,activity_description=s.activity_description,study_today=s.today())

@bp.route('/')
def today():
    from . import plans
    db=get_db()
    if plans.ready(db):
        day_number=plans.current_day(db);curriculum=plans.load()
        day=next(d for d in curriculum['days'] if d['day']==day_number)
        items=plans.entries_for_day(day_number,db)
        assessments=plans.latest_assessments(db)
        for item in items:
            assessment=assessments.get(item['problem_id'])
            item['assessment']=assessment['assessment'] if assessment else 'not_assessed'
            item['assessment_takeaway']=assessment['takeaway'] if assessment else ''
        attempted=sum(bool(p['curriculum_attempted']) for p in items)
        next_problem=next((p for p in items if not p['curriculum_attempted']),None)
        all_items=s.rows();counts=s.counts(all_items)
        due=sorted([p for p in all_items if p['next_due_date'] and p['next_due_date']<=s.today().isoformat()],key=lambda p:(p['next_due_date'],p['day_number'],p['slot']))
        following=plans.next_active_day(day_number,curriculum)
        archived=plans.archived_rows(db)
        for item in archived:
            item['id']=item.get('problem_id',item.get('id'));item['tracker_number']=None
        earlier=[p for p in archived if not p['first_attempt_at']]
        return render_template('today_v2.html',day=day,items=items,attempted=attempted,next_problem=next_problem,
            counts=counts,due=due,current_day=day_number,following=following,token=secrets.token_hex(20),
            all_complete=day['active_index']==15 and attempted==5,earlier=earlier)
    items=s.rows();eligible=s.queue(items);done=s.new_today(items)
    limit=max(0,6-done)
    due=sorted([p for p in items if p['next_due_date'] and p['next_due_date']<=s.today().isoformat()], key=lambda p:(p['next_due_date'],p['learning_order']))
    ahead=[]
    if request.args.get('ahead')=='1':
        shown={p['id'] for p in eligible[:limit]}
        ahead=[p for p in s.focus_items(items) if not p['first_attempt_at'] and p['id'] not in shown][:6]
    return render_template('today.html',earlier=s.earlier_unfinished(items),focus_active=s.focus_active(),items=eligible[:limit],overflow=max(0,len(eligible)-limit),ahead=ahead,due=due,done=done,counts=s.counts(items),pace=s.pace(items,date(2026,10,27)),fallback=s.pace(items,date(2026,11,1)))


@bp.route('/plan')
def plan():
    from . import plans
    db=get_db()
    if not plans.ready(db):return render_template('plan_unavailable.html')
    curriculum=plans.load();current=plans.current_day(db)
    try:selected=int(request.args.get('day',current))
    except (ValueError,TypeError):abort(404)
    day=next((d for d in curriculum['days'] if d['day']==selected),None)
    if not day:abort(404)
    items=plans.entries_for_day(selected,db)
    assessments=plans.latest_assessments(db)
    for item in items:
        assessment=assessments.get(item['problem_id'])
        item['assessment']=assessment['assessment'] if assessment else 'not_assessed'
    attempted=sum(bool(p['curriculum_attempted']) for p in items)
    days=[]
    for row in curriculum['days']:
        row=dict(row);row['attempted']=sum(bool(p['curriculum_attempted']) for p in plans.entries_for_day(row['day'],db)) if row['kind']=='active' else 0
        row['is_current']=row['day']==current;row['is_selected']=row['day']==selected;days.append(row)
    return render_template('plan.html',days=days,day=day,items=items,attempted=attempted,current_day=current,
        can_advance=selected==current and attempted==5 and plans.next_active_day(current,curriculum) is not None,
        following=plans.next_active_day(current,curriculum),finished=selected==current and attempted==5 and day['active_index']==15,
        token=secrets.token_hex(20))


@bp.route('/plan/advance',methods=['POST'])
def advance_plan():
    from . import plans
    try:
        day=s.advance_active_day(request.form.get('token'))
        if day==19 and plans.day_complete(day):flash('All 15 active study days are complete. Your history and assessments remain available.','success')
        else:flash(f'Active study day is now Day {day}.','success')
    except ValueError as exc:flash(str(exc),'error')
    return redirect(url_for('main.plan'))

@bp.route('/concepts')
@bp.route('/concepts/<cid>')
def concepts(cid=None):
    concepts=[dict(r) for r in get_db().execute('SELECT * FROM concepts ORDER BY display_order')]
    all_items=s.rows()
    for c in concepts:
        group=[p for p in all_items if p['concept_id']==c['id']]
        c['content']=json.loads(c['content']);c['counts']=s.counts(group);c['total']=len(group)
    if cid:
        concept=next((c for c in concepts if c['id']==cid),None)
        if not concept:abort(404)
        items=[p for p in s.rows() if p['concept_id']==cid]
        if request.args.get('difficulty'):items=[p for p in items if p['difficulty']==request.args['difficulty']]
        if request.args.get('status'):items=[p for p in items if p.get('assessment')==request.args['status']]
        note=get_db().execute('SELECT note FROM concept_notes WHERE concept_id=?',(cid,)).fetchone()
        return render_template('concept.html',concept=concept,items=items,note=note[0] if note else '')
    return render_template('concepts.html',concepts=concepts)

@bp.route('/cheatsheets')
def cheatsheets():
    items=s.rows();q=request.args.get('q','').casefold().strip()
    if q:items=[p for p in items if q in (p['title']+' '+p['concept_name']).casefold()]
    if request.args.get('personalized')=='1':
        if not lr.migration_ready(): items=[]
        else:
            saved={r[0] for r in get_db().execute('SELECT problem_id FROM learning_records')}
            items=[p for p in items if p['id'] in saved]
    if request.args.get('needs_review')=='1':items=[p for p in items if p['next_due_date'] and p['next_due_date']<=s.today().isoformat()]
    if lr.migration_ready():
        records={r['problem_id']:dict(r) for r in get_db().execute('SELECT * FROM learning_records')}
        for p in items:
            p['learning_record']=records.get(p['id'])
    else:
        for p in items:p['learning_record']=None
    return render_template('list.html',heading='Cheat Sheets',intro='Concept primers are always available. General guides and your personal learning records are kept separate.',items=items,search=True,learning_records_ready=lr.migration_ready())

@bp.route('/library')
def library():
    items=s.rows(include_archived=request.args.get('archived')=='1');q=request.args.get('q','').casefold().strip()
    if q:items=[p for p in items if q in (p['title']+' '+p['concept_name']).casefold()]
    difficulty=request.args.get('difficulty');assessment=request.args.get('assessment')
    if difficulty:items=[p for p in items if p['difficulty']==difficulty]
    if assessment:items=[p for p in items if p.get('assessment','not_assessed')==assessment]
    if request.args.get('due')=='1':items=[p for p in items if p.get('next_due_date') and p['next_due_date']<=s.today().isoformat()]
    saved={r[0] for r in get_db().execute('SELECT problem_id FROM learning_records')} if lr.migration_ready() else set()
    if request.args.get('saved')=='1':items=[p for p in items if p['id'] in saved]
    return render_template('library.html',items=items,query=request.args.get('q',''),difficulty=difficulty or '',assessment=assessment or '',learning_records_ready=lr.migration_ready())

@bp.route('/problem/<pid>')
def problem(pid):
    from . import plans
    ready=plans.ready(get_db())
    p=next((p for p in s.rows(include_archived=ready) if p['id']==pid),None)
    if p is None:abort(404)
    revealed=get_db().execute("SELECT 1 FROM activity_events WHERE problem_id=? AND kind='reveal' LIMIT 1",(pid,)).fetchone()
    unlocked=bool(p['first_attempt_at'] or revealed)
    guide=None
    if unlocked:
        guides=json.loads((ROOT/'data/problem_guides.json').read_text())
        additions=ROOT/'data/problem_guides_v2_additions.json'
        if additions.exists():guides.update(json.loads(additions.read_text(encoding='utf-8')))
        guide=guides.get(pid)
    history=[dict(r) for r in get_db().execute('SELECT * FROM activity_events WHERE problem_id=? ORDER BY at DESC,id DESC',(pid,))]
    reviews=[dict(r) for r in get_db().execute('SELECT * FROM review_events WHERE problem_id=? ORDER BY at DESC,id DESC',(pid,))]
    record=lr.get_record(get_db(),pid) if lr.migration_ready() else None
    curriculum_position=None
    if ready:
        curriculum_position=next((e for e in plans.load()['entries'] if e['problem_id']==pid),None)
        if curriculum_position:
            p['tracker_number']=curriculum_position['tracker_number'];p['day_number']=curriculum_position['day_number'];p['active_index']=curriculum_position['active_index'];p['topic']=curriculum_position['topic']
            p['assessment']=plans.latest_assessments(get_db()).get(pid,{}).get('assessment','not_assessed')
    return render_template('problem_v2.html' if ready else 'problem.html',p=p,guide=guide,history=history,reviews=reviews,learning_record=record,learning_records_ready=lr.migration_ready(),solutions_ready=lr.solution_ready(get_db()),curriculum_ready=ready,assessment=p.get('assessment','not_assessed'))


@bp.route('/problem/<pid>/assessment',methods=['POST'])
def record_assessment(pid):
    if not get_db().execute('SELECT 1 FROM problems WHERE id=?',(pid,)).fetchone():abort(404)
    color=request.form.get('assessment')
    try:
        if color=='not_assessed':
            raise ValueError('Assessment history is preserved. Choose Green, Yellow, or Red to record a new result.')
        s.assessment(pid,color,request.form.get('green_attested')=='yes',request.form.get('takeaway',''),request.form.get('token'),request.form.get('context','first_pass'))
        flash('Assessment saved. Existing status and mastery history remain intact.','success')
    except ValueError as exc:flash(str(exc),'error')
    return redirect(url_for('main.problem',pid=pid)+'#assessment')

def require_learning_records():
    if not lr.migration_ready():
        abort(503, description='Personal learning records are not enabled yet. Run the explicit documented database migration.')


@bp.route('/learning-records')
def learning_records():
    require_learning_records()
    db=get_db();items=s.rows()
    records={r['problem_id']:dict(r) for r in db.execute('SELECT * FROM learning_records')}
    # Presentation-only filters; record storage and export selection are unchanged.
    q=request.args.get('q','').casefold().strip()
    if q:items=[p for p in items if q in (p['title']+' '+p['concept_name']).casefold()]
    state=request.args.get('record_state')
    if state=='saved':items=[p for p in items if p['id'] in records]
    elif state=='empty':items=[p for p in items if p['id'] not in records]
    return render_template('learning_records.html',items=items,records=records)


@bp.route('/problem/<pid>/learning-record',methods=['POST'])
def save_learning_record(pid):
    require_learning_records();db=get_db()
    if not db.execute('SELECT 1 FROM problems WHERE id=?',(pid,)).fetchone():abort(404)
    values={field:request.form.get(field,'') for field in lr.FIELDS}
    for field,value in values.items():
        if len(value)>lr.MAX_FIELD or '\x00' in value:flash(f'{field} is too long or invalid.','error');return redirect(url_for('main.problem',pid=pid))
    with db:
        old=lr.get_record(db,pid)
        changes=[f for f in lr.FIELDS if (old or {}).get(f,'')!=values[f]]
        if changes:
            token=request.form.get('token')
            if not s.begin(db,token):return redirect(url_for('main.problem',pid=pid))
            cols=['problem_id',*lr.FIELDS,'updated_at']
            db.execute(f"INSERT INTO learning_records({','.join(cols)}) VALUES({','.join('?' for _ in cols)}) ON CONFLICT(problem_id) DO UPDATE SET {','.join(f'{f}=excluded.{f}' for f in lr.FIELDS)},updated_at=excluded.updated_at",[pid,*[values[f] for f in lr.FIELDS],s.stamp()])
            s.event(db,token,pid,'learning_record_edit',{'fields':changes})
    flash('Personal learning record saved.','success')
    return redirect(url_for('main.problem',pid=pid))


@bp.route('/problem/<pid>/solution',methods=['POST'])
def save_solution(pid):
    require_learning_records();db=get_db()
    if not lr.solution_ready(db):abort(503,description='Reference solutions require explicit migration4.')
    if not db.execute('SELECT 1 FROM problems WHERE id=?',(pid,)).fetchone():abort(404)
    value=request.form.get('solution_code','')
    if len(value)>lr.MAX_CODE or '\x00' in value:
        flash('Reference solution must be text of at most 65,536 characters, without null characters.','error')
        return redirect(url_for('main.problem',pid=pid)+'#reference-solution')
    with db:
        if not is_postgres(db):db.execute('BEGIN IMMEDIATE')
        old=lr.get_record(db,pid)
        if (old or {}).get('solution_code','')!=value and s.begin(db,request.form.get('token')):
            db.execute("INSERT INTO learning_records(problem_id,solution_code,updated_at) VALUES(?,?,?) ON CONFLICT(problem_id) DO UPDATE SET solution_code=excluded.solution_code,updated_at=excluded.updated_at",(pid,value,s.stamp()))
            s.event(db,request.form['token'],pid,'learning_record_edit',dict(fields=['solution_code']))
    flash('Python reference solution saved.','success')
    return redirect(url_for('main.problem',pid=pid)+'#reference-solution')


@bp.route('/learning-records/import',methods=['GET','POST'])
def learning_records_import():
    require_learning_records();db=get_db()
    if request.method=='POST' and request.form.get('action')=='parse':
        upload=request.files.get('file')
        if upload and upload.filename and not upload.filename.lower().endswith('.json'):
            flash('Choose a .json file or paste JSON text.','error')
            sample={'format':lr.FORMAT,'version':lr.VERSION,'records':[{'problem_id':'two-sum',**{field:'' for field in lr.fields_for(db)}}]}
            return render_template('learning_import.html',sample=json.dumps(sample,ensure_ascii=False,indent=2),json_text=request.form.get('json',''))
        raw=upload.read(lr.MAX_BYTES+1) if upload and upload.filename else request.form.get('json','').encode('utf-8')
        try:
            incoming=lr.parse(raw,db)
            with db:
                preview_token=lr.preview_token(db,incoming)
            return render_template('learning_import_preview.html',preview_token=preview_token,entries=lr.preview(db,incoming),incoming=incoming,stale=False)
        except ValueError as exc:
            flash(str(exc)+(' The uploaded file must be selected again.' if upload and upload.filename else ''),'error')
    if request.method=='POST' and request.form.get('action')=='confirm':
        token=request.form.get('preview_token','')
        with db:
            # SQLite deferred transactions allow a second writer to alter a record
            # after our snapshot check but before apply(). Lock before every read
            # so preview validation and its merge are one serialized operation.
            if not is_postgres(db):db.execute('BEGIN IMMEDIATE')
            stored=lr.load_preview(db,token)
            if not stored:
                flash('This preview expired. Import the JSON again.','error')
                return redirect(url_for('main.learning_records_import'))
            incoming=json.loads(stored['payload'])
            current=lr.snapshot(db,incoming)
            if current!=stored['snapshot_hash']:
                refreshed=lr.preview_token(db,incoming)
                db.execute('DELETE FROM learning_import_previews WHERE token_hash=?',(stored['token_hash'],))
                return render_template('learning_import_preview.html',preview_token=refreshed,entries=lr.preview(db,incoming),incoming=incoming,stale=True)
            skipped=set(request.form.getlist('skip'))
            replace_fields={}
            for item in incoming['records']:
                replace_fields[item['problem_id']]=set(request.form.getlist('replace_'+item['problem_id']))
            changed=lr.apply(db,incoming,replace_fields,skipped)
            db.execute('DELETE FROM learning_import_previews WHERE token_hash=?',(stored['token_hash'],))
        flash(f'Import complete. {len(changed)} personalized record(s) changed; progress and review states were untouched.','success')
        return redirect(url_for('main.learning_records'))
    sample={'format':lr.FORMAT,'version':lr.VERSION,'records':[{'problem_id':'two-sum',**{field:'' for field in lr.fields_for(db)}}]}
    return render_template('learning_import.html',sample=json.dumps(sample,ensure_ascii=False,indent=2),json_text=request.form.get('json',''))


@bp.route('/learning-records/export')
def learning_records_export():
    require_learning_records()
    selected=request.args.get('selected')=='1'
    ids=request.args.getlist('problem_id')
    if selected and not ids:
        flash('Select at least one record to export, or use Export all records.','error')
        return redirect(url_for('main.learning_records'))
    ids=ids or None
    if ids and any(not get_db().execute('SELECT 1 FROM problems WHERE id=?',(pid,)).fetchone() for pid in ids):abort(400)
    payload=lr.export(get_db(),ids)
    if ids:payload['records']=[r for r in payload['records'] if r['problem_id'] in ids]
    filename='grind75-learning-records-'+s.today().isoformat()+'.json'
    return Response(json.dumps(payload,ensure_ascii=False,indent=2),mimetype='application/json',headers={'Content-Disposition':f'attachment; filename={filename}'})


@bp.route('/review/<pid>')
def personalized_review(pid):
    if not lr.migration_ready():abort(404)
    from . import plans
    p=next((p for p in s.rows(include_archived=plans.ready(get_db())) if p['id']==pid),None)
    if p is None:abort(404)
    if plans.ready(get_db()):
        return render_template('personalized_review_v2.html',p=p,record=lr.get_record(get_db(),pid),solutions_ready=lr.solution_ready(get_db()))
    return render_template('personalized_review.html',p=p,record=lr.get_record(get_db(),pid),solutions_ready=lr.solution_ready(get_db()))

@bp.route('/problem/<pid>/<action>',methods=['POST'])
def update(pid,action):
    if not get_db().execute('SELECT 1 FROM problems WHERE id=?',(pid,)).fetchone():abort(404)
    token=request.form.get('token');db=get_db()
    try:
        if action=='status':
            from . import plans
            if plans.ready(db):raise ValueError('Use the Green, Yellow, or Red assessment on the problem page. Historical status remains unchanged.')
            s.set_status(pid,request.form.get('status'),request.form.get('independent')=='yes',token)
        elif action=='notes':s.save_notes(pid,request.form,token)
        elif action=='review':
            from . import plans
            if plans.ready(db):raise ValueError('Use the recall assessment on the problem page so Green is explicitly confirmed.')
            s.review(pid,request.form.get('result'),request.form.get('note',''),token)
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
    if items and 'assessment' in items[0]:
        index={p['id']:p['learning_order'] for p in items}
        due=sorted([p for p in items if p['next_due_date'] and p['next_due_date']<=day],key=lambda p:(p['next_due_date'],index[p['id']]))
        due_ids={p['id'] for p in due}
        weak=sorted([p for p in items if p['first_attempt_at'] and p['assessment'] in ('yellow','red') and p['id'] not in due_ids],key=lambda p:index[p['id']])
        weak_ids={p['id'] for p in weak}|due_ids
        future=sorted([p for p in items if p['next_due_date'] and p['next_due_date']>day and p['id'] not in weak_ids],key=lambda p:(p['next_due_date'],index[p['id']]))
        saved={r[0] for r in get_db().execute('SELECT problem_id FROM learning_records')} if lr.migration_ready() else set()
        for group in (due,weak,future):
            for p in group:p['has_learning_record']=p['id'] in saved
        by_concept={}
        for p in items:
            if p['assessment'] in ('yellow','red'):
                by_concept[p['concept_name']]=by_concept.get(p['concept_name'],0)+1
        weak_concepts=sorted([dict(name=name,count=count) for name,count in by_concept.items()],key=lambda c:(-c['count'],c['name']))
        return render_template('review_v2.html',due=due,weak=weak,future=future,weak_concepts=weak_concepts)
    due=sorted([p for p in items if p['next_due_date'] and p['next_due_date']<=day], key=lambda p:(p['next_due_date'],p['learning_order']))
    weak=[p for p in items if p['first_attempt_at'] and (p['status'] in ('hints','needs_review') or (p['confidence'] and p['confidence']<=2)) and p not in due]
    future=sorted([p for p in items if p['next_due_date'] and p['next_due_date']>day and p not in weak], key=lambda p:(p['next_due_date'],p['learning_order']))
    if lr.migration_ready():
        saved={r[0] for r in get_db().execute('SELECT problem_id FROM learning_records')}
        for group in (due,weak,future):
            for p in group:p['has_learning_record']=p['id'] in saved
    else:
        for group in (due,weak,future):
            for p in group:p['has_learning_record']=False
    return render_template('review.html',due=due,weak=weak,future=future)

@bp.route('/calendar')
def calendar():
    from . import plans
    if plans.ready(get_db()):
        events=[dict(r) for r in get_db().execute('''SELECT e.*,p.title FROM activity_events e LEFT JOIN problems p ON e.problem_id=p.id ORDER BY e.at DESC LIMIT 200''')]
        grouped={}
        for event in events:
            if event['at']:
                day=s.local_day(event['at']);grouped.setdefault(day,[]).append(event)
        due={}
        for item in s.rows(include_archived=True):
            if item['next_due_date']:due.setdefault(item['next_due_date'],[]).append(item)
        return render_template('calendar_v2.html',activity=sorted(grouped.items(),reverse=True),reviews=sorted(due.items()),today=s.today().isoformat(),current_day=plans.current_day(get_db()))
    items=s.rows();days={}
    events=[dict(r) for r in get_db().execute('SELECT e.*,p.title FROM activity_events e LEFT JOIN problems p ON e.problem_id=p.id ORDER BY at')]
    for offset in range(19):days[(date(2026,10,15)+timedelta(days=offset)).isoformat()]=dict(baseline=[],current=[],activity=[])
    for p in items:
        for key,col in [('baseline','baseline_date'),('current','scheduled_date')]:
            days.setdefault(p[col],dict(baseline=[],current=[],activity=[]))[key].append(p)
    for e in events:
        if e['kind'] in ('status','review'):
            day=s.local_day(e['at']);days.setdefault(day,dict(baseline=[],current=[],activity=[]))['activity'].append(e)
    reviews_by_day={}
    for p in items:
        if p['next_due_date']:
            day=p['next_due_date']
            days.setdefault(day,dict(baseline=[],current=[],activity=[]))
            reviews_by_day.setdefault(day,[]).append(p)
    return render_template('calendar.html',days=sorted(days.items()),reviews_by_day=reviews_by_day,today=s.today().isoformat())

@bp.route('/progress')
def progress():
    items=s.rows();concepts=[dict(r) for r in get_db().execute('SELECT id,name FROM concepts ORDER BY display_order')]
    for c in concepts:
        subset=[p for p in items if p['concept_id']==c['id']];c.update(s.counts(subset));c['total']=len(subset)
    counts=s.counts(items);due=sum(bool(p['next_due_date'] and p['next_due_date']<=s.today().isoformat()) for p in s.rows(include_archived=True))
    if items and 'assessment' in items[0]:
        return render_template('progress_v2.html',counts=counts,concepts=concepts,due=due,items=items)
    return render_template('progress.html',counts=counts,concepts=concepts,done=s.new_today(items),pace=s.pace(items,date(2026,10,27)),fallback=s.pace(items,date(2026,11,1)),due=due)

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
            saved=restore(payload,acknowledge_legacy_solution_loss=request.form.get('legacy_solution_loss')=='yes');flash('Restored successfully. A safety copy was saved: '+saved,'success')
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
