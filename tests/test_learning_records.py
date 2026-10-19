import json
import sqlite3
import hashlib
import threading

import pytest

from app.db import connect, get_db, initialize
from app.learning_records import FIELDS, FORMAT, migrate, parse, preview_token
from app.services import rows


def setup_feature(app):
    with app.app_context():
        migrate(get_db())


def payload(pid='two-sum', **values):
    return json.dumps({'format': FORMAT, 'version': 1, 'records': [{'problem_id': pid, **values}]})


def csrf_token(client):
    client.get('/learning-records/import')
    with client.session_transaction() as session:return session['csrf']


def test_additive_migration_is_idempotent_and_preserves_tracker(app):
    with app.app_context():
        db=get_db()
        before={t:[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in ('problems','assignments','progress','problem_notes','activity_events','review_state','review_events')}
        migrate(db);migrate(db)
        after={t:[tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in before}
        assert before==after
        assert db.execute('SELECT count(*) FROM learning_records').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM feature_migrations WHERE version=3').fetchone()[0]==1


def test_explicit_migration_script_core_runs_without_flask_context(tmp_path):
    path=tmp_path/'standalone.sqlite3';db=connect(path);initialize(db);db.close()
    db=connect(path)
    try:
        migrate(db)
        assert db.execute('SELECT version FROM feature_migrations WHERE version=3').fetchone()[0]==3
    finally:db.close()


@pytest.mark.parametrize('raw',[
    '{"format":"grind75-learning-records","version":1,"records":[],"records":[]}',
    '{"format":"grind75-learning-records","version":1,"records":[{"problem_id":"two-sum","mistakes":"x","mistakes":"y"}]}',
    json.dumps({'format':FORMAT,'version':1,'records':[{'problem_id':'missing'}]}),
    json.dumps({'format':FORMAT,'version':1,'records':[{'problem_id':'two-sum','mastered':True}]}),
    json.dumps({'format':FORMAT,'version':1,'records':[{'problem_id':'two-sum','mistakes':[]}]}),
])
def test_parser_rejects_invalid_payloads_atomically(app,raw):
    setup_feature(app)
    with app.app_context(),pytest.raises(ValueError):parse(raw,get_db())
    with app.app_context():assert get_db().execute('SELECT count(*) FROM learning_records').fetchone()[0]==0


def test_parse_unicode_and_field_limits(app):
    setup_feature(app)
    data=json.loads(payload(mistakes='emoji 🧠\nsecond line'))
    with app.app_context():
        parsed=parse(json.dumps(data,ensure_ascii=False),get_db())
        assert parsed['records'][0]['mistakes']=='emoji 🧠\nsecond line'
        with pytest.raises(ValueError,match='8000'):
            parse(payload(mistakes='x'*8001),get_db())


def test_import_preview_defaults_to_preserve_and_confirm_isolated_from_progress(client,app):
    setup_feature(app)
    with app.app_context():
        db=get_db()
        with db:db.execute("INSERT INTO learning_records(problem_id,mistakes,updated_at) VALUES('two-sum','old','2026-10-15T00:00:00+00:00')")
        before=[tuple(r) for r in db.execute("SELECT status,first_attempt_at,first_understood_at,mastered FROM progress WHERE problem_id='two-sum'")]
        before_review=[tuple(r) for r in db.execute("SELECT * FROM review_state WHERE problem_id='two-sum'")]
    response=client.post('/learning-records/import',data={'csrf':csrf_token(client),'action':'parse','json':payload(mistakes='replace? ',interview_takeaway='keep this')})
    assert response.status_code==200 and b'conflict' in response.data
    with client.session_transaction() as session:token=session['csrf']
    import re
    preview_token=re.search(rb'name="preview_token" value="([^"]+)',response.data).group(1).decode()
    response=client.post('/learning-records/import',data={'csrf':token,'action':'confirm','preview_token':preview_token})
    assert response.status_code==302
    with app.app_context():
        db=get_db();record=db.execute("SELECT * FROM learning_records WHERE problem_id='two-sum'").fetchone()
        assert record['mistakes']=='old' and record['interview_takeaway']=='keep this'
        assert before==[tuple(r) for r in db.execute("SELECT status,first_attempt_at,first_understood_at,mastered FROM progress WHERE problem_id='two-sum'")]
        assert before_review==[tuple(r) for r in db.execute("SELECT * FROM review_state WHERE problem_id='two-sum'")]
        assert db.execute("SELECT count(*) FROM assignments WHERE problem_id='two-sum'").fetchone()[0]==1


def test_explicit_replace_and_empty_never_clears(app,client):
    setup_feature(app)
    with app.app_context():
        with get_db() as db:db.execute("INSERT INTO learning_records(problem_id,mistakes,updated_at) VALUES('two-sum','old','2026-10-15T00:00:00+00:00')")
    response=client.post('/learning-records/import',data={'csrf':csrf_token(client),'action':'parse','json':payload(mistakes='new',corrections='' )})
    import re
    token=re.search(rb'name="preview_token" value="([^"]+)',response.data).group(1).decode()
    with client.session_transaction() as session:csrf=session['csrf']
    response=client.post('/learning-records/import',data={'csrf':csrf,'action':'confirm','preview_token':token,'replace_two-sum':['mistakes']})
    assert response.status_code==302
    with app.app_context():
        row=get_db().execute("SELECT mistakes,corrections FROM learning_records WHERE problem_id='two-sum'").fetchone()
        assert tuple(row)==('new','')


def test_stale_preview_requires_fresh_confirmation(app,client):
    setup_feature(app)
    response=client.post('/learning-records/import',data={'csrf':csrf_token(client),'action':'parse','json':payload(interview_takeaway='from batch')})
    import re
    token=re.search(rb'name="preview_token" value="([^"]+)',response.data).group(1).decode()
    with app.app_context():
        with get_db() as db:db.execute("INSERT INTO learning_records(problem_id,interview_takeaway,updated_at) VALUES('two-sum','concurrent','2026-10-15T00:00:00+00:00')")
    with client.session_transaction() as session:csrf=session['csrf']
    response=client.post('/learning-records/import',data={'csrf':csrf,'action':'confirm','preview_token':token})
    assert b'changed after this preview' in response.data
    with app.app_context():assert get_db().execute("SELECT interview_takeaway FROM learning_records WHERE problem_id='two-sum'").fetchone()[0]=='concurrent'


def test_sqlite_import_confirmation_serializes_against_concurrent_writer(app,client,monkeypatch):
    setup_feature(app)
    with app.app_context():
        with get_db() as db:db.execute("INSERT INTO learning_records(problem_id,corrections,updated_at) VALUES('two-sum','original','2026-10-15T00:00:00+00:00')")
    response=client.post('/learning-records/import',data={'csrf':csrf_token(client),'action':'parse','json':payload(corrections='from import')})
    import re
    token=re.search(rb'name="preview_token" value="([^"]+)',response.data).group(1).decode()
    with client.session_transaction() as session:csrf=session['csrf']

    # Inject a second SQLite connection after the snapshot is read but before
    # the import merge. It must wait for confirmation's write lock, then win as
    # the later write; without BEGIN IMMEDIATE the import clobbers this edit.
    source_snapshot=__import__('app.learning_records',fromlist=['snapshot']).snapshot
    writer_started=threading.Event();writer_done=threading.Event();writer_errors=[]
    def race_snapshot(db,incoming):
        result=source_snapshot(db,incoming)
        def concurrent_edit():
            try:
                other=sqlite3.connect(app.config['DATABASE'],timeout=3)
                writer_started.set()
                other.execute("UPDATE learning_records SET corrections='concurrent edit' WHERE problem_id='two-sum'")
                other.commit();other.close()
            except Exception as exc:writer_errors.append(exc)
            finally:writer_done.set()
        threading.Thread(target=concurrent_edit,daemon=True).start()
        if not writer_started.wait(1):raise AssertionError('Concurrent writer did not start.')
        if writer_done.wait(.5):raise AssertionError('Concurrent writer completed while confirmation held its lock.')
        return result
    monkeypatch.setattr('app.routes.lr.snapshot',race_snapshot)
    response=client.post('/learning-records/import',data={'csrf':csrf,'action':'confirm','preview_token':token,'replace_two-sum':['corrections']})
    assert response.status_code==302
    assert writer_done.wait(3) and not writer_errors
    with app.app_context():
        assert get_db().execute("SELECT corrections FROM learning_records WHERE problem_id='two-sum'").fetchone()[0]=='concurrent edit'


def test_new_import_preview_prunes_expired_tokens_but_keeps_live_tokens(app):
    setup_feature(app)
    with app.app_context():
        db=get_db()
        with db:
            db.execute("INSERT INTO learning_import_previews VALUES(?,?,?,?,?)",('expired','{}','x','2026-10-15T00:00:00+00:00','2026-10-15T16:59:59+00:00'))
            db.execute("INSERT INTO learning_import_previews VALUES(?,?,?,?,?)",('live','{}','x','2026-10-15T00:00:00+00:00','2026-10-15T17:20:00+00:00'))
        incoming=parse(payload(recognition_clue='clue'),db)
        with db:raw=preview_token(db,incoming)
        hashes={row[0] for row in db.execute('SELECT token_hash FROM learning_import_previews')}
        assert 'expired' not in hashes and 'live' in hashes
        assert hashlib.sha256(raw.encode()).hexdigest() in hashes


def test_exports_and_versioned_backup_compatibility(app,client):
    setup_feature(app)
    with app.app_context():
        db=get_db()
        with db:db.execute("INSERT INTO learning_records(problem_id,recognition_clue,updated_at) VALUES('two-sum','hash map','2026-10-15T00:00:00+00:00')")
    one=client.get('/learning-records/export?problem_id=two-sum')
    assert one.status_code==200
    exported=json.loads(one.data);assert [r['problem_id'] for r in exported['records']]==['two-sum']
    full=client.get('/export')
    backup=json.loads(full.data);assert backup['version']==2 and 'learning_records' in backup['tables']
    from app.backup import restore,validate
    malformed=json.loads(json.dumps(backup));malformed['tables']['learning_records'][0]['mistakes']=123
    with pytest.raises(ValueError,match='Invalid learning-record field'):validate(malformed)
    malformed=json.loads(json.dumps(backup));malformed['tables']['learning_records'][0]['updated_at']=''
    with pytest.raises(ValueError,match='Timestamps'):validate(malformed)
    with app.app_context():
        db=get_db()
        legacy=dict(backup);legacy['version']=1;legacy['tables']={k:v for k,v in backup['tables'].items() if k!='learning_records'}
        restore(legacy)
        assert db.execute("SELECT recognition_clue FROM learning_records WHERE problem_id='two-sum'").fetchone()[0]=='hash map'
        restore(backup)
        assert db.execute("SELECT recognition_clue FROM learning_records WHERE problem_id='two-sum'").fetchone()[0]=='hash map'


def test_new_routes_require_csrf_and_public_context_does_not_leak(app,client):
    setup_feature(app)
    with app.app_context():
        with get_db() as db:db.execute("INSERT INTO learning_records(problem_id,mistakes,updated_at) VALUES('two-sum','private mistake','2026-10-15T00:00:00+00:00')")
    token=csrf_token(client)
    assert client.post('/problem/two-sum/learning-record',data={'mistakes':'bad'}).status_code==400
    response=client.post('/learning-records/import',data={'csrf':token,'action':'parse','json':payload(mistakes='bad')})
    assert response.status_code==200 and b'preview_token' in response.data
    assert b'private mistake' not in client.get('/study-context').data
    assert b'private mistake' not in client.get('/study-context').data


def test_manual_editor_saves_and_personal_review_is_recall_first(app,client):
    setup_feature(app)
    response=client.get('/problem/two-sum');assert b'MY LEARNING RECORD' in response.data
    assert b'<label for="learning-edge_cases">Edge cases and pitfalls</label>' in response.data
    assert b'<textarea id="learning-edge_cases" name="edge_cases"' in response.data
    with client.session_transaction() as session:csrf=session['csrf']
    fields={key:'value '+key for key in FIELDS}
    fields.update(csrf=csrf,token='manual-learning-record-token')
    response=client.post('/problem/two-sum/learning-record',data=fields)
    assert response.status_code==302
    response=client.get('/review/two-sum')
    assert b'value recall_question' in response.data
    assert b'<details class="panel"><summary>Reveal my previous mistakes' in response.data


def test_invalid_paste_is_retained_and_empty_group_export_is_explicit(app,client):
    setup_feature(app)
    token=csrf_token(client)
    response=client.post('/learning-records/import',data={'csrf':token,'action':'parse','json':'not valid json'})
    assert response.status_code==200 and b'not valid json' in response.data and b'Enter valid JSON' in response.data
    response=client.get('/learning-records/export?selected=1')
    assert response.status_code==302 and response.headers['Location'].endswith('/learning-records')


def test_learning_record_write_requires_authenticated_session(secured):
    setup_feature(secured)
    client=secured.test_client()
    assert client.get('/learning-records').status_code==302
    assert client.post('/problem/two-sum/learning-record',data={'mistakes':'anonymous'}).status_code==401
    assert client.post('/learning-records/import',data={'action':'parse','json':payload(mistakes='anonymous')}).status_code==401
    login=client.get('/login')
    assert login.status_code==200
    with client.session_transaction() as session:token=session['csrf']
    response=client.post('/login',data={'csrf':token,'username':'admin','password':'unit-test-only-password'})
    assert response.status_code==302
    assert client.post('/learning-records/import',data={'action':'parse','json':payload(mistakes='no-csrf')}).status_code==400
    record=client.get('/learning-records')
    assert record.status_code==200 and b'Import a ChatGPT batch' in record.data
