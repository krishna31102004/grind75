import copy
import json
import pytest
from app.db import get_db
from app import services as s
from app.backup import export_data,restore,validate


def test_backup_roundtrip(app):
    with app.app_context():
        s.set_status('two-sum','understood',True,'a'*20)
        s.save_notes('two-sum',dict(takeaway='<script>bad</script>',approach='map',confidence='5',effort='31'),'b'*20)
        s.review('two-sum','independent','saved review','c'*20)
        s.move('valid-anagram','2026-10-20','d'*20)
        payload=export_data();s.set_status('two-sum','needs_review',False,'e'*20)
        name=restore(payload)
        assert name.startswith('before-restore-')
        assert export_data()['tables']==payload['tables']


@pytest.mark.parametrize('corruption',['missing','duplicate','fk','date','status','columns','baseline','stage','text','number','version','attempt','review','json'])
def test_reject_atomic(app,corruption):
    with app.app_context():
        payload=export_data();before=copy.deepcopy(payload['tables']);t=payload['tables']
        if corruption=='missing':t['progress'].pop()
        if corruption=='duplicate':t['progress'].append(t['progress'][0])
        if corruption=='fk':t['problem_notes'][0]['problem_id']='missing'
        if corruption=='date':t['assignments'][0]['scheduled_date']='10-15-2026'
        if corruption=='status':t['progress'][0]['status']='complete'
        if corruption=='columns':t['progress'][0]['surprise']=1
        if corruption=='baseline':t['assignments'][0]['baseline_date']='2026-10-16'
        if corruption=='stage':t['review_state'].append(dict(problem_id='two-sum',stage=3,next_due_date='2026-10-20',last_result='independent'))
        if corruption=='text':t['problem_notes'][0]['takeaway']={'bad':'object'}
        if corruption=='number':t['problem_notes'][0]['effort']=True
        if corruption=='version':payload['version']=True
        if corruption=='attempt':t['progress'][0]['status']='understood'
        if corruption=='review':t['review_events'].append(dict(id='x',problem_id='two-sum',at=s.stamp(),result='independent',note=''))
        if corruption=='json':t['activity_events'].append(dict(id='x',problem_id=None,kind='catch_up',at=s.stamp(),payload='['))
        with pytest.raises(ValueError):restore(payload)
        assert export_data()['tables']==before


@pytest.mark.parametrize('attempt,understood,valid',[
 ('2026-10-15T10:00:00-05:00','2026-10-15T12:00:00+00:00',False),
 ('2026-10-15T12:00:00+00:00','2026-10-15T10:00:00-05:00',True),
])
def test_timestamp_offset_regression(app,attempt,understood,valid):
    with app.app_context():
        payload=export_data();p=payload['tables']['progress'][0]
        p.update(first_attempt_at=attempt,first_understood_at=understood,status='understood')
        if valid:validate(payload)
        else:
            with pytest.raises(ValueError,match='precedes'):validate(payload)


def test_foreign_keys_and_seed_identity_change(app):
    with app.app_context():
        from app.db import initialize
        db=get_db()
        assert db.execute('PRAGMA foreign_keys').fetchone()[0]==1
        db.execute("INSERT INTO problems VALUES('extra','extra','Easy','url','arrays',999,999,'{}')")
        with pytest.raises(RuntimeError,match='identities'):initialize(db)

@pytest.mark.parametrize('table',['assignments','progress','problem_notes','review_state','review_events','concept_notes','activity_events','submissions'])
def test_null_identifier_regression(app,table):
    with app.app_context():
        s.set_status('two-sum','understood',False,'a'*20)
        s.review('two-sum','independent','', 'b'*20)
        db=get_db();db.execute("INSERT INTO concept_notes VALUES('arrays','note')");db.commit()
        payload=export_data();before=copy.deepcopy(payload['tables'])
        identifier='concept_id' if table=='concept_notes' else 'id' if table in ('activity_events','review_events','submissions') else 'problem_id'
        payload['tables'][table][0][identifier]=None
        with pytest.raises(ValueError,match='identifier'):restore(payload)
        assert export_data()['tables']==before
        assert len(s.rows())==75


@pytest.mark.parametrize('kind,field,bad',[('status','old',[]),('status','status',{}),('review','result',[])])
def test_bad_history_payload_regression(app,kind,field,bad):
    with app.app_context():
        s.set_status('two-sum','understood',False,'history-backup-token1')
        s.review('two-sum','independent','', 'history-backup-token2')
        payload=export_data();before=copy.deepcopy(payload['tables'])
        event=next(e for e in payload['tables']['activity_events'] if e['kind']==kind)
        content=json.loads(event['payload']);content[field]=bad;event['payload']=json.dumps(content)
        with pytest.raises(ValueError,match='event payload'):restore(payload)
        assert export_data()['tables']==before
        # Defensive rendering also survives old/manual malformed rows.
        assert isinstance(s.activity_description(event),str)
