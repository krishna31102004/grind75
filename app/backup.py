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


def export_data(db=None):
    db=db or get_db()
    has_records=lr.migration_ready(db)
    tables=BACKUP_TABLES if has_records else USER_TABLES
    def collect():
        return dict(format='grind75-backup',version=2 if has_records else 1,seed_version=db.execute("SELECT value FROM settings WHERE key='seed_version'").fetchone()[0],exported_at=stamp(),tables={t:[dict(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in tables})
    # Reuse an enclosing restore transaction; SQLite's context manager is not nested.
    if not is_postgres(db) and db.in_transaction:
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
        if isinstance(payload,dict) and payload.get('version')==2:
            lr.migrate(check)
        expected_seed=check.execute("SELECT value FROM settings WHERE key='seed_version'").fetchone()[0]
        if not isinstance(payload,dict) or set(payload)!= {'format','version','seed_version','exported_at','tables'} or payload['format']!='grind75-backup' or type(payload['version']) is not int or payload['version'] not in (1,2) or payload['seed_version']!=expected_seed:
            raise ValueError('Unsupported backup format or dataset version.')
        _timestamp(payload['exported_at'])
        tables=payload['tables']
        expected_tables=BACKUP_TABLES if payload['version']==2 else USER_TABLES
        if not isinstance(tables,dict) or set(tables)!=set(expected_tables):raise ValueError('Backup tables are incomplete.')
        originals={r['problem_id']:r['baseline_date'] for r in check.execute('SELECT * FROM assignments')}
        for table in expected_tables:
            columns={r[1] for r in check.execute(f'PRAGMA table_info({table})')}
            items=tables[table]
            if not isinstance(items,list) or len(items)>50000:raise ValueError('Invalid row collection.')
            for item in items:
                if not isinstance(item,dict) or set(item)!=columns:raise ValueError(f'Invalid columns in {table}.')
                identifier='concept_id' if table=='concept_notes' else 'id' if table in ('activity_events','review_events','submissions') else 'problem_id'
                if not isinstance(item[identifier],str) or not item[identifier] or len(item[identifier])>100:raise ValueError('Invalid or missing row identifier.')
                for key,value in item.items():
                    if key in ('baseline_date','scheduled_date','next_due_date') and value is not None:valid_date(value)
                    if key in ('at','first_attempt_at','first_understood_at') and value is not None:_timestamp(value)
                    if key in ('mastered','stage','manual_override') and type(value) is not int:raise ValueError('Invalid numeric state.')
                    if key in ('confidence','effort') and value is not None and type(value) is not int:raise ValueError('Invalid numeric notes.')
                    if key in ('takeaway','approach','note') and (not isinstance(value,str) or len(value)>10000):raise ValueError('Invalid notes.')
                    if key in ('id','problem_id','concept_id','status','kind','payload','result') and value is not None and (not isinstance(value,str) or len(value)>100000):raise ValueError('Invalid text field.')
                if table=='activity_events':
                    if item['kind'] not in ('status','notes','reveal','review','move','catch_up','concept_note','review_schedule','learning_record_edit','learning_record_import'):raise ValueError('Unknown activity kind.')
                    event_payload=json.loads(item['payload'])
                    if not isinstance(event_payload,dict):raise ValueError('Invalid event payload.')
                    if item['kind']=='status':
                        for field in ('old','status'):
                            if not isinstance(event_payload.get(field),str) or event_payload[field] not in STATUSES:raise ValueError('Invalid status event payload.')
                        if type(event_payload.get('independent')) is not bool:raise ValueError('Invalid independence event payload.')
                    if item['kind']=='review':
                        if not isinstance(event_payload.get('result'),str) or event_payload['result'] not in ('independent','hints','failed'):raise ValueError('Invalid review event payload.')
                        if not isinstance(event_payload.get('note'),str) or len(event_payload['note'])>10000:raise ValueError('Invalid review event note.')
                    if item['kind'] in ('learning_record_edit','learning_record_import'):
                        from .learning_records import FIELDS
                        if not isinstance(event_payload.get('fields'),list) or any(x not in FIELDS for x in event_payload['fields']):raise ValueError('Invalid learning record event.')
                if table=='assignments' and originals.get(item['problem_id'])!=item['baseline_date']:raise ValueError('Original assignment dates cannot change.')
                if table=='learning_records':
                    from .learning_records import FIELDS, MAX_FIELD
                    if item['problem_id'] not in originals:raise ValueError('Learning record references an unknown problem.')
                    for field in FIELDS:
                        value=item[field]
                        if not isinstance(value,str) or '\x00' in value or len(value)>MAX_FIELD:raise ValueError(f'Invalid learning-record field: {field}.')
                    _timestamp(item['updated_at'])
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
            if check.execute('SELECT count(*) FROM review_state r JOIN progress p USING(problem_id) WHERE p.first_attempt_at IS NULL').fetchone()[0]:raise ValueError('Review requires an initial attempt.')
            if check.execute('SELECT count(*) FROM review_events r JOIN progress p USING(problem_id) WHERE p.first_attempt_at IS NULL').fetchone()[0]:raise ValueError('Review history requires an attempt.')
            if check.execute("SELECT count(*) FROM review_state WHERE (stage=3 AND next_due_date IS NOT NULL) OR (stage<3 AND next_due_date IS NULL)").fetchone()[0]:raise ValueError('Invalid review stage/due date.')
    except (sqlite3.Error,KeyError,TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid backup data; nothing was changed.') from exc
    finally:check.close()
    return payload

def restore(payload):
    validate(payload)
    db=get_db()
    with db:
        if not is_postgres(db): db.execute('BEGIN IMMEDIATE')
        snapshot_payload=export_data(db)
        snapshot_name='before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.json'
        if is_postgres(db):
            db.execute('INSERT INTO safety_backups VALUES(?,?,?)',(snapshot_name,stamp(),json.dumps(snapshot_payload)))
        else:
            directory=Path(current_app.config['DATABASE']).parent/'backups'
            directory.mkdir(exist_ok=True)
            snapshot=directory/snapshot_name
            snapshot.write_text(json.dumps(snapshot_payload,indent=2));snapshot.chmod(0o600)
        tables=BACKUP_TABLES if payload['version']==2 else USER_TABLES
        for table in reversed(tables):db.execute(f'DELETE FROM {table}')
        for table in tables:
            for item in payload['tables'][table]:
                keys=list(item)
                db.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[item[k] for k in keys])
    return snapshot_name
