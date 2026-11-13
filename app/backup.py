"""Validate backups against a disposable DB before any personal data is replaced."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app
from .db import USER_TABLES, connect, get_db, initialize, is_postgres
from .services import stamp, valid_date, STATUSES
from . import learning_records as lr

BACKUP_TABLES = USER_TABLES + ('learning_records',)
PLAN_BACKUP_TABLES = USER_TABLES + ('learning_records','settings','curriculum_versions','curriculum_days','curriculum_entries','curriculum_archive','assessment_events')


def export_data(db=None):
    db=db or get_db()
    has_records=lr.migration_ready(db)
    from . import plans
    has_plan=plans.ready(db)
    tables=PLAN_BACKUP_TABLES if has_plan else BACKUP_TABLES if has_records else USER_TABLES
    def collect():
        version=4 if has_plan else 3 if lr.solution_ready(db) else 2 if has_records else 1
        return dict(format='grind75-backup',version=version,seed_version=db.execute("SELECT value FROM settings WHERE key='seed_version'").fetchone()[0],exported_at=stamp(),tables={t:[dict(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in tables})
    # Reuse an enclosing restore transaction; SQLite's context manager is not nested.
    if db.in_transaction:
        return collect()
    # One consistent read transaction even if a second browser tab is writing.
    with db:
        if not is_postgres(db): db.execute('BEGIN')
        result=collect()
    return result

def _timestamp(value):
    if not isinstance(value,str):raise ValueError('Invalid timestamp.')
    try:
        dt=datetime.fromisoformat(value)
        if not dt.tzinfo or not 2020<=dt.year<=2100:raise ValueError()
    except (TypeError,ValueError):raise ValueError('Timestamps must include a valid timezone.') from None

def validate(payload):
    check=connect(':memory:')
    try:
        initialize(check)
        if isinstance(payload,dict) and payload.get('version') in (2,3,4):
            lr.migrate(check)
            if payload['version'] in (3,4):
                from .reference_solutions import migrate as migrate_solutions
                migrate_solutions(check)
            if payload['version']==4:
                from .curriculum_migration import apply,prepare
                apply(check,prepare(check,'2026-11-12'))
        expected_seed=check.execute("SELECT value FROM settings WHERE key='seed_version'").fetchone()[0]
        if not isinstance(payload,dict) or set(payload)!= {'format','version','seed_version','exported_at','tables'} or payload['format']!='grind75-backup' or type(payload['version']) is not int or payload['version'] not in (1,2,3,4) or payload['seed_version']!=expected_seed:
            raise ValueError('Unsupported backup format or dataset version.')
        _timestamp(payload['exported_at'])
        tables=payload['tables']
        expected_tables=PLAN_BACKUP_TABLES if payload['version']==4 else BACKUP_TABLES if payload['version'] in (2,3) else USER_TABLES
        if not isinstance(tables,dict) or set(tables)!=set(expected_tables):raise ValueError('Backup tables are incomplete.')
        originals={r['problem_id']:r['baseline_date'] for r in check.execute('SELECT * FROM assignments')}
        for table in expected_tables:
            columns={r[1] for r in check.execute(f'PRAGMA table_info({table})')}
            items=tables[table]
            if not isinstance(items,list) or len(items)>50000:raise ValueError('Invalid row collection.')
            for item in items:
                if not isinstance(item,dict) or set(item)!=columns:raise ValueError(f'Invalid columns in {table}.')
                identifier=('concept_id' if table=='concept_notes' else 'id' if table in ('activity_events','review_events','submissions','assessment_events')
                            else 'key' if table=='settings' else 'version' if table in ('curriculum_versions','curriculum_days','curriculum_entries','curriculum_archive') else 'problem_id')
                if not isinstance(item[identifier],str) or not item[identifier] or len(item[identifier])>100:raise ValueError('Invalid or missing row identifier.')
                for key,value in item.items():
                    if key in ('baseline_date','scheduled_date','next_due_date') and value is not None:valid_date(value)
                    if key in ('at','first_attempt_at','first_understood_at') and value is not None:_timestamp(value)
                    if key in ('mastered','stage','manual_override') and type(value) is not int:raise ValueError('Invalid numeric state.')
                    if key in ('confidence','effort') and value is not None and type(value) is not int:raise ValueError('Invalid numeric notes.')
                    if key in ('takeaway','approach','note') and (not isinstance(value,str) or len(value)>10000):raise ValueError('Invalid notes.')
                    if key in ('id','problem_id','concept_id','status','kind','payload','result') and value is not None and (not isinstance(value,str) or len(value)>100000):raise ValueError('Invalid text field.')
                if table=='activity_events':
                    if item['kind'] not in ('status','notes','reveal','review','move','catch_up','concept_note','review_schedule','learning_record_edit','learning_record_import','assessment','plan_advance'):raise ValueError('Unknown activity kind.')
                    event_payload=json.loads(item['payload'])
                    if not isinstance(event_payload,dict):raise ValueError('Invalid event payload.')
                    if item['kind']=='status':
                        for field in ('old','status'):
                            if not isinstance(event_payload.get(field),str) or event_payload[field] not in STATUSES:raise ValueError('Invalid status event payload.')
                        if type(event_payload.get('independent')) is not bool:raise ValueError('Invalid independence event payload.')
                    if item['kind']=='review':
                        if not isinstance(event_payload.get('result'),str) or event_payload['result'] not in ('independent','hints','failed'):raise ValueError('Invalid review event payload.')
                        if not isinstance(event_payload.get('note'),str) or len(event_payload['note'])>10000:raise ValueError('Invalid review event note.')
                    if item['kind']=='assessment':
                        if event_payload.get('assessment') not in ('green','yellow','red') or type(event_payload.get('green_attested')) is not bool or event_payload.get('context') not in ('first_pass','review'):raise ValueError('Invalid assessment activity payload.')
                        if event_payload['assessment']=='green' and not event_payload['green_attested']:raise ValueError('Green assessment requires its independence attestation.')
                    if item['kind']=='plan_advance':
                        from .plans import load as load_plan
                        active_days=[d['day'] for d in load_plan()['days'] if d['kind']=='active']
                        before,after=event_payload.get('from_day'),event_payload.get('to_day')
                        if type(before) is not int or type(after) is not int or before not in active_days or after not in active_days or active_days.index(after)!=active_days.index(before)+1:raise ValueError('Invalid active-day advancement history.')
                    if item['kind'] in ('learning_record_edit','learning_record_import'):
                        from .learning_records import ALL_FIELDS
                        if not isinstance(event_payload.get('fields'),list) or any(x not in ALL_FIELDS for x in event_payload['fields']):raise ValueError('Invalid learning record event.')
                if table=='assignments' and originals.get(item['problem_id'])!=item['baseline_date']:raise ValueError('Original assignment dates cannot change.')
                if table=='learning_records':
                    from .learning_records import FIELDS, MAX_FIELD
                    if item['problem_id'] not in originals:raise ValueError('Learning record references an unknown problem.')
                    for field in FIELDS:
                        value=item[field]
                        if not isinstance(value,str) or '\x00' in value or len(value)>MAX_FIELD:raise ValueError(f'Invalid learning-record field: {field}.')
                    if payload['version'] in (3,4):
                        from .reference_solutions import MAX_CODE
                        value=item['solution_code']
                        if not isinstance(value,str) or '\x00' in value or len(value)>MAX_CODE:raise ValueError('Invalid reference solution.')
                    _timestamp(item['updated_at'])
                if table=='assessment_events':
                    if item['assessment']=='green' and item['green_attested']!=1:raise ValueError('Green assessment requires attestation.')
                    if item['green_attested'] not in (0,1) or not isinstance(item['takeaway'],str) or len(item['takeaway'])>1000 or '\x00' in item['takeaway']:raise ValueError('Invalid assessment event data.')
                    if item['assessment']!='green' and item['green_attested']!=0:raise ValueError('Only Green assessments may include the independence attestation.')
                    if item['context'] not in ('first_pass','review'):raise ValueError('Invalid assessment context.')
                    if item['problem_id'] not in originals:raise ValueError('Assessment references an unknown problem.')
                if table=='settings' and item['key'] in ('active_study_day','daily_target'):
                    if not isinstance(item['value'],str) or not item['value'].isdigit():raise ValueError('Invalid numeric setting.')
                if table=='progress':
                    if item['status']!='not_started' and not item['first_attempt_at']:raise ValueError('Status requires an attempt.')
                    if item['first_understood_at'] and not item['first_attempt_at']:raise ValueError('Understanding requires attempt history.')
                    if item['status']=='understood' and not item['first_understood_at']:raise ValueError('Missing understanding history.')
                    if item['mastered'] and not item['first_attempt_at']:raise ValueError('Mastery requires attempt history.')
                    if item['first_understood_at'] and datetime.fromisoformat(item['first_understood_at']).astimezone(timezone.utc) < datetime.fromisoformat(item['first_attempt_at']).astimezone(timezone.utc):raise ValueError('Understanding precedes attempt.')
        with check:
            for table in reversed(expected_tables):check.execute(f'DELETE FROM {table}')
            for table in expected_tables:
                for item in tables[table]:
                    keys=list(item)
                    check.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[item[k] for k in keys])
            for table in ('assignments','progress','problem_notes'):
                if {r[0] for r in check.execute(f'SELECT problem_id FROM {table}')}!=set(originals):raise ValueError('Backup must retain every problem identity.')
            if payload['version']==4:
                from .plans import VERSION as PLAN_VERSION,load as load_plan
                plan=load_plan()
                expected_days=sorted([dict(version=PLAN_VERSION,day_number=d['day'],week=d['week'],active_index=d['active_index'],kind=d['kind'],topic=d['topic']) for d in plan['days']],key=lambda r:r['day_number'])
                actual_days=sorted([{k:r[k] for k in ('version','day_number','week','active_index','kind','topic')} for r in tables['curriculum_days']],key=lambda r:r['day_number'])
                expected_entries=sorted([dict(version=PLAN_VERSION,day_number=e['day_number'],slot=e['slot'],tracker_number=e['tracker_number'],problem_id=e['problem_id']) for e in plan['entries']],key=lambda r:(r['day_number'],r['slot']))
                actual_entries=sorted([{k:r[k] for k in ('version','day_number','slot','tracker_number','problem_id')} for r in tables['curriculum_entries']],key=lambda r:(r['day_number'],r['slot']))
                expected_archive=set(plan['archived_ids'])
                actual_archive={r['problem_id'] for r in tables['curriculum_archive']}
                version_rows=tables['curriculum_versions']
                if len(version_rows)!=1 or version_rows[0]['version']!=PLAN_VERSION or version_rows[0]['name']!=plan['name']:raise ValueError('Backup curriculum version/name is invalid.')
                if actual_days!=expected_days or actual_entries!=expected_entries or actual_archive!=expected_archive:raise ValueError('Backup curriculum order, day mapping, or archive differs from the approved application plan.')
                setting={r['key']:r['value'] for r in tables['settings']}
                active_days={d['day'] for d in plan['days'] if d['kind']=='active'}
                if setting.get('active_plan_version')!=PLAN_VERSION or setting.get('daily_target')!='5':raise ValueError('Backup plan settings do not match the active curriculum version.')
                if setting.get('active_study_day','1').isdigit() is False or int(setting.get('active_study_day','1')) not in active_days:raise ValueError('Backup active day must point to an active study day.')
                progress={r['problem_id']:r for r in tables['progress']}
                assessment_rows=tables['assessment_events'];review_events={(r['problem_id'],r['at']) for r in tables['review_events']}
                for event in assessment_rows:
                    attempt=progress[event['problem_id']]['first_attempt_at']
                    if not attempt:raise ValueError('Assessment requires an existing first attempt.')
                    if datetime.fromisoformat(event['at']).astimezone(timezone.utc)<datetime.fromisoformat(attempt).astimezone(timezone.utc):raise ValueError('Assessment precedes the first attempt.')
                    if event['context']=='review' and (event['problem_id'],event['at']) not in review_events:raise ValueError('Review assessment is missing its paired review event.')
                    if event['context']=='first_pass' and event['takeaway'] and not isinstance(event['takeaway'],str):raise ValueError('Invalid assessment takeaway.')
            if check.execute('SELECT count(*) FROM review_state r JOIN progress p USING(problem_id) WHERE p.first_attempt_at IS NULL').fetchone()[0]:raise ValueError('Review requires an initial attempt.')
            if check.execute('SELECT count(*) FROM review_events r JOIN progress p USING(problem_id) WHERE p.first_attempt_at IS NULL').fetchone()[0]:raise ValueError('Review history requires an attempt.')
            if check.execute("SELECT count(*) FROM review_state WHERE (stage=3 AND next_due_date IS NOT NULL) OR (stage<3 AND next_due_date IS NULL)").fetchone()[0]:raise ValueError('Invalid review stage/due date.')
    except (sqlite3.Error,KeyError,TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid backup data; nothing was changed.') from exc
    finally:check.close()
    return payload

def restore(payload, acknowledge_legacy_solution_loss=False):
    validate(payload)
    db=get_db()
    with db:
        if not is_postgres(db): db.execute('BEGIN IMMEDIATE')
        if payload['version']==3 and not lr.solution_ready(db):
            raise ValueError('This backup requires explicit migration4; nothing was changed.')
        if payload['version']<4 and _curriculum_v5_ready(db):
            # Legacy archives cannot describe v5 assessments or their attempt
            # and review evidence. Refuse a mixed-era replacement rather than
            # silently leaving assessment events detached from restored history.
            if db.execute('SELECT 1 FROM assessment_events LIMIT 1').fetchone():
                raise ValueError('This legacy backup predates curriculum assessments. Export and restore a current version4 backup to preserve the complete study history; nothing was changed.')
        if payload['version']==2 and lr.solution_ready(db) and db.execute("SELECT 1 FROM learning_records WHERE solution_code<>'' LIMIT 1").fetchone() and not acknowledge_legacy_solution_loss:
            raise ValueError('Legacy version2 restore clears Python solutions. Explicitly acknowledge this replacement; a safety copy will be kept.')
        snapshot_payload=export_data(db)
        snapshot_name='before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.json'
        if is_postgres(db):
            db.execute('INSERT INTO safety_backups VALUES(?,?,?)',(snapshot_name,stamp(),json.dumps(snapshot_payload)))
        else:
            directory=Path(current_app.config['DATABASE']).parent/'backups'
            directory.mkdir(exist_ok=True)
            snapshot=directory/snapshot_name
            snapshot.write_text(json.dumps(snapshot_payload,indent=2));snapshot.chmod(0o600)
        tables=PLAN_BACKUP_TABLES if payload['version']==4 else BACKUP_TABLES if payload['version'] in (2,3) else USER_TABLES
        incoming_ids={row['problem_id'] for row in payload['tables']['assignments']}
        # Older backup formats predate the seven replacement problem records and
        # versioned plan state. Keep those extra identities untouched when an
        # older archive is restored into a newer catalog.
        extension_rows={}
        if payload['version']<4:
            for table in tables:
                if table in ('assignments','progress','problem_notes','review_state','learning_records'):
                    extension_rows[table]=[dict(r) for r in db.execute(f'SELECT * FROM {table}') if r['problem_id'] not in incoming_ids]
                elif table in ('activity_events','review_events'):
                    extension_rows[table]=[dict(r) for r in db.execute(f'SELECT * FROM {table}') if r['problem_id'] is not None and r['problem_id'] not in incoming_ids]
        for table in reversed(tables):db.execute(f'DELETE FROM {table}')
        for table in tables:
            for item in payload['tables'][table]:
                keys=list(item)
                db.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[item[k] for k in keys])
        for table,rows in extension_rows.items():
            for item in rows:
                keys=list(item)
                db.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[item[k] for k in keys])
    return snapshot_name


def _curriculum_v5_ready(db):
    """Check migration5 without querying tables that may not exist."""
    if is_postgres(db):
        exists=db.execute("SELECT to_regclass('feature_migrations')").fetchone()[0]
    else:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_migrations'").fetchone()
    return bool(exists and db.execute('SELECT 1 FROM feature_migrations WHERE version=5').fetchone())
