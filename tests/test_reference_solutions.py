"""Reference source is inert private text; every mutation uses disposable data."""
import io
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import create_app, learning_records as lr, reference_solutions as ref
from app.backup import export_data, restore, validate
from app.curriculum import state
from app.db import get_db

CODE = '\nclass Solution:\r\n    # 🧠 <script>window.SOURCE_RAN=1</script>\r\n    def solve(self):\r\n        return "<&>"  \r\n'


def populate_history(db):
    """Synthetic nonempty history exercises preservation beyond empty tables."""
    timestamp='2026-10-20T12:00:00+00:00'
    with db:
        db.execute("UPDATE progress SET status='understood',first_attempt_at=?,first_understood_at=?,mastered=1 WHERE problem_id='two-sum'",(timestamp,timestamp))
        db.execute("UPDATE problem_notes SET takeaway='exact 🧠\r\ntext  ',approach='synthetic approach',confidence=4,effort=25 WHERE problem_id='two-sum'")
        db.execute("UPDATE assignments SET scheduled_date='2026-10-23',manual_override=1 WHERE problem_id='two-sum'")
        db.execute("INSERT INTO review_state VALUES('two-sum',1,'2026-10-27','independent')")
        db.execute("INSERT INTO review_events VALUES('original-review','two-sum',?,'independent','keep original text  ')",(timestamp,))
        db.execute("INSERT INTO activity_events VALUES('original-activity','two-sum','notes',?,?)",(timestamp,json.dumps({'takeaway':'original'})))
        db.execute("INSERT INTO concept_notes VALUES('arrays','original concept note')")
        db.execute("INSERT INTO submissions VALUES('original-submission',?)",(timestamp,))
        db.execute("INSERT INTO security_state VALUES('synthetic-private-setting','keep exact')")

@pytest.fixture(params=['sqlite', 'postgresql'])
def feature(request, app, tmp_path):
    if request.param == 'postgresql':
        from app.db import connect, initialize
        from scripts.migrate_to_postgres import migrate
        source = tmp_path/'source.sqlite3'
        db = connect(source); initialize(db); db.close()
        url = request.getfixturevalue('pg_url')
        migrate(source, url, mark_authority=False)
        app = create_app({**app.config, 'DATABASE_URL': url})
    with app.app_context():
        lr.migrate(get_db()); ref.migrate(get_db())
    return app


def raw(records, version=2):
    return json.dumps(dict(format=lr.FORMAT, version=version, records=records), ensure_ascii=False)


def csrf(client, path='/problem/two-sum'):
    client.get(path)
    with client.session_transaction() as session: return session['csrf']


def preview(client, records, version=2, upload=False):
    data=dict(csrf=csrf(client),action='parse')
    if upload: data['file']=(io.BytesIO(raw(records, version).encode()), 'solutions.json')
    else: data['json']=raw(records, version)
    result=client.post('/learning-records/import',data=data)
    assert result.status_code == 200, result.data
    match=re.search(rb'name="preview_token" value="([^"]+)',result.data)
    assert match, result.data
    return match[1].decode()


def confirm(client, token, **extra):
    return client.post('/learning-records/import',data=dict(csrf=csrf(client),action='confirm',preview_token=token,**extra))


def protected(db):
    return {k:v for k,v in state(db).items() if k not in ('learning_records','activity_events','submissions','learning_import_previews')}


def test_migration_preserves_eleven_full_records_and_all_tables(app):
    with app.app_context():
        db=get_db();lr.migrate(db)
        ids=[r[0] for r in db.execute('SELECT id FROM problems ORDER BY learning_order LIMIT 11')]
        with db:
            for pid in ids:
                db.execute('INSERT INTO learning_records(problem_id,'+','.join(lr.FIELDS)+',updated_at) VALUES('+','.join('?' for _ in range(11))+')', [pid,*[f+'\r\n🧠  \n' for f in lr.FIELDS],'2026-10-20T12:00:00+00:00'])
        populate_history(db)
        before=state(db)
        result=ref.migrate(db)
        assert result['learning_records']==11 and result['verified']
        assert ref.preserved_state(db)==before
        assert all(r[0]=='' for r in db.execute('SELECT solution_code FROM learning_records'))
        first=state(db);ref.migrate(db);assert state(db)==first


def test_migration_idempotent_with_nonempty_source_and_restart(feature):
    with feature.app_context():
        db=get_db()
        with db:db.execute('INSERT INTO learning_records(problem_id,solution_code,updated_at) VALUES(?,?,?)',('two-sum',CODE,'2026-10-20T12:00:00+00:00'))
        before=state(db);ref.migrate(db);assert state(db)==before
    restarted=create_app(feature.config)
    with restarted.app_context():assert lr.get_record(get_db(),'two-sum')['solution_code']==CODE


def test_manual_editor_exact_text_and_no_study_side_effects(feature):
    client=feature.test_client()
    with feature.app_context():
        db=get_db()
        with db:db.execute("INSERT INTO learning_records(problem_id,mistakes,updated_at) VALUES('two-sum','unchanged nine-field content','2026-10-20T12:00:00+00:00')")
        before=protected(db)
    assert client.post('/problem/two-sum/solution', data={'solution_code':CODE}).status_code==400
    response=client.post('/problem/two-sum/solution',data=dict(csrf=csrf(client),token='solution-edit-test-token',solution_code=CODE))
    assert response.status_code==302
    with feature.app_context():
        db=get_db();row=lr.get_record(db,'two-sum')
        assert row['solution_code']==CODE and row['mistakes']=='unchanged nine-field content'
        assert protected(db)==before
        events=[dict(r) for r in db.execute('SELECT * FROM activity_events')]
        assert len(events)==1 and json.loads(events[0]['payload'])=={'fields':['solution_code']}
        assert CODE not in events[0]['payload']
    page=client.get('/problem/two-sum').get_data(as_text=True)
    assert 'solution-disclosure" open' not in page and 'data-copy-code="#python-reference-code"' in page
    assert '<script>window.SOURCE_RAN' not in page and '&lt;script&gt;window.SOURCE_RAN' in page
    assert page.index('id="my-learning-record"') < page.index('id="reference-solution"')
    assert client.post('/problem/two-sum/solution',data=dict(csrf=csrf(client),token='solution-invalid-token',solution_code='x'*(ref.MAX_CODE+1))).status_code==302
    with feature.app_context():assert lr.get_record(get_db(),'two-sum')['solution_code']==CODE


def test_solution_only_and_combined_import_conflicts_and_legacy(feature):
    client=feature.test_client()
    token=preview(client,[dict(problem_id='two-sum',solution_code=CODE,mistakes='original')])
    assert confirm(client,token).status_code==302
    token=preview(client,[dict(problem_id='two-sum',solution_code='replacement',mistakes='changed')])
    confirm(client,token)
    with feature.app_context():assert lr.get_record(get_db(),'two-sum')['solution_code']==CODE
    token=preview(client,[dict(problem_id='two-sum',solution_code='replacement',mistakes='changed')])
    confirm(client,token,**{'replace_two-sum':['solution_code']})
    token=preview(client,[dict(problem_id='two-sum',corrections='legacy addition')],version=1)
    confirm(client,token)
    token=preview(client,[dict(problem_id='two-sum',solution_code='')]);confirm(client,token)
    with feature.app_context():
        row=lr.get_record(get_db(),'two-sum')
        assert (row['solution_code'],row['mistakes'],row['corrections'])==('replacement','original','legacy addition')


def test_solution_edit_invalidates_stale_import_preview(feature):
    client=feature.test_client();token=preview(client,[dict(problem_id='two-sum',solution_code='batch source')])
    client.post('/problem/two-sum/solution',data=dict(csrf=csrf(client),token='stale-preview-editor',solution_code=CODE))
    response=confirm(client,token,**{'replace_two-sum':['solution_code']})
    assert b'changed after this preview' in response.data
    with feature.app_context():assert lr.get_record(get_db(),'two-sum')['solution_code']==CODE


def test_fourteen_uploaded_solutions_and_download_roundtrip(feature):
    client=feature.test_client()
    with feature.app_context():ids=[r[0] for r in get_db().execute('SELECT id FROM problems ORDER BY learning_order LIMIT 14')]
    records=[dict(problem_id=pid,solution_code=CODE+f'# {pid}') for pid in ids]
    token=preview(client,records,upload=True);assert confirm(client,token).status_code==302
    response=client.get('/learning-records/export')
    assert response.status_code==200 and 'attachment' in response.headers['Content-Disposition']
    exported=response.get_json()
    assert exported['version']==2 and len(exported['records'])==14
    with feature.app_context():
        db=get_db();parsed=lr.parse(json.dumps(exported),db)
        assert {r['problem_id']:r['solution_code'] for r in parsed['records']}=={r['problem_id']:r['solution_code'] for r in records}
        with db: assert lr.apply(db,parsed,{},set())==[]


def test_parser_limits_and_invalid_batch_atomic(feature):
    with feature.app_context():
        db=get_db();ids=[r[0] for r in db.execute('SELECT id FROM problems LIMIT 21')]
        assert len(lr.parse(raw([dict(problem_id=p,solution_code='x') for p in ids[:20]]),db)['records'])==20
        assert lr.parse(raw([dict(problem_id=ids[0],solution_code='x'*ref.MAX_CODE)]),db)
        for records in ([dict(problem_id=p,solution_code='x') for p in ids],
                        [dict(problem_id=ids[0],solution_code='x'*(ref.MAX_CODE+1))],
                        [dict(problem_id=ids[0],solution_code=None)],
                        [dict(problem_id=ids[0],solution_code='\x00')],
                        [dict(problem_id=ids[0],solution_code=CODE),dict(problem_id='absent',solution_code='x')]):
            with pytest.raises(ValueError):lr.parse(raw(records),db)
        assert db.execute('SELECT count(*) FROM learning_records').fetchone()[0]==0
        with pytest.raises(ValueError):lr.parse(raw([dict(problem_id=ids[0],solution_code=CODE)],version=1),db)


def legacy(payload, version):
    import copy
    result=copy.deepcopy(payload);result['version']=version
    if version==1: result['tables'].pop('learning_records')
    else:
        for row in result['tables']['learning_records']:row.pop('solution_code')
    return result


def test_backup_three_roundtrip_and_explicit_legacy_solution_loss(feature):
    client=feature.test_client()
    token=preview(client,[dict(problem_id='two-sum',solution_code=CODE,mistakes='nine unchanged')]);confirm(client,token)
    with feature.app_context():
        db=get_db();payload=export_data(db);assert payload['version']==3;validate(payload)
        restore(payload);assert lr.get_record(db,'two-sum')['solution_code']==CODE
        restore(legacy(payload,1));assert lr.get_record(db,'two-sum')['solution_code']==CODE
        before=state(db)
        with pytest.raises(ValueError,match='acknowledge'):restore(legacy(payload,2))
        assert state(db)==before
        name=restore(legacy(payload,2),acknowledge_legacy_solution_loss=True)
        assert lr.get_record(db,'two-sum')['solution_code']==''
        if feature.config['DATABASE_URL']:
            saved=json.loads(db.execute('SELECT payload FROM safety_backups WHERE id=?',(name,)).fetchone()[0])
        else:saved=json.loads((Path(feature.config['DATABASE']).parent/'backups'/name).read_text())
        assert saved['tables']['learning_records'][0]['solution_code']==CODE
        restore(saved);assert lr.get_record(db,'two-sum')['solution_code']==CODE


def test_unmigrated_v3_remains_functional_and_cannot_restore_v4(app):
    client=app.test_client()
    with app.app_context():lr.migrate(get_db())
    assert client.get('/problem/two-sum').status_code==200
    assert client.post('/problem/two-sum/solution',data=dict(csrf=csrf(client))).status_code==503
    with app.app_context():
        db=get_db();assert export_data(db)['version']==2
        with pytest.raises(ValueError,match='migration4'):lr.parse(raw([dict(problem_id='two-sum',solution_code='x')]),db)
        ref.migrate(db);payload=export_data(db)
        with db:
            db.execute('DELETE FROM feature_migrations WHERE version=4')
        before=state(db)
        with pytest.raises(ValueError,match='migration4'):restore(payload)
        assert state(db)==before


def test_private_solution_excluded_from_owner_and_public_context(secured):
    from test_cloud_security import login, form, BASE
    with secured.app_context():
        db=get_db();lr.migrate(db);ref.migrate(db)
        with db:db.execute('INSERT INTO learning_records(problem_id,solution_code,updated_at) VALUES(?,?,?)',('two-sum','PRIVATE_REFERENCE_SENTINEL','2026-10-20T12:00:00+00:00'))
    owner=secured.test_client();public=secured.test_client()
    assert public.post('/problem/two-sum/solution',base_url=BASE,data={'solution_code':'x'}).status_code==401
    assert public.get('/problem/two-sum',base_url=BASE).status_code==302
    login(owner)
    data=form(owner);data['action']='enable';result=owner.post('/study-context/sharing',base_url=BASE,data=data)
    url=re.search(r'value="(https://localhost/share/[A-Za-z0-9_-]+)"',result.get_data(as_text=True))[1]
    for client,path in [(owner,'/study-context'),(owner,'/study-context?format=json'),(public,url),(public,url+'?format=json')]:
        response=client.get(path,base_url=BASE)
        assert response.status_code==200
        assert b'PRIVATE_REFERENCE_SENTINEL' not in response.data and b'solution_code' not in response.data
    assert public.post(url,data={'solution_code':'x'}).status_code==405
    data=form(owner);data['action']='revoke';owner.post('/study-context/sharing',base_url=BASE,data=data)
    assert public.get(url).status_code==404


def test_sqlite_operator_readonly_apply_and_receipt(tmp_path):
    from app.db import connect,initialize
    path=tmp_path/'operator.sqlite3';db=connect(path);initialize(db);lr.migrate(db);db.close()
    import hashlib
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    base=[sys.executable,'scripts/migrate_reference_solutions.py','--sqlite',str(path)]
    result=subprocess.run([*base,'--check-only'],capture_output=True,text=True)
    assert result.returncode==0 and 'pending' in result.stdout
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    receipt=tmp_path/'receipt.json'
    result=subprocess.run([*base,'--apply','--receipt',str(receipt)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(receipt.read_text())['verified'] and receipt.stat().st_mode & 0o077==0
    result=subprocess.run([*base,'--check-only'],capture_output=True,text=True)
    assert result.returncode==0 and 'verified' in result.stdout


def test_wrong_marker_rolls_back_additive_column(app):
    with app.app_context():
        db=get_db();lr.migrate(db)
        with db:db.execute("INSERT INTO feature_migrations VALUES(4,'wrong','2026-10-20T12:00:00+00:00')")
        before=state(db)
        with pytest.raises(ValueError,match='identity mismatch'):ref.migrate(db)
        assert state(db)==before and not ref.column(db)


def test_pg_additive_eleven_records_and_operator(pg_url, tmp_path, monkeypatch, capsys):
    """Actual local PG DDL/backup/receipt. No cloud endpoint is ever used."""
    import os
    from app.db import connect,initialize
    from scripts.migrate_to_postgres import migrate
    from scripts import migrate_reference_solutions as ops
    source=tmp_path/'pg-source.sqlite3';db=connect(source);initialize(db);lr.migrate(db)
    with db:
        for pid in [r[0] for r in db.execute('SELECT id FROM problems LIMIT 11')]:
            db.execute('INSERT INTO learning_records(problem_id,'+','.join(lr.FIELDS)+',updated_at) VALUES('+','.join('?' for _ in range(11))+')',[pid,*[f+'\r\n🧠  \n' for f in lr.FIELDS],'2026-10-20T12:00:00+00:00'])
    populate_history(db)
    db.close();migrate(source,pg_url,mark_authority=False)
    db=connect(pg_url)
    with db:db.execute("INSERT INTO security_state VALUES('synthetic-private-setting','keep exact')")
    before=state(db);db.close()
    from scripts.backup_neon import pg_client_environment
    archive=tmp_path/'verified.dump'
    subprocess.run(['pg_dump','--format=custom',f'--file={archive}'],env=pg_client_environment(pg_url),check=True,capture_output=True)
    archive.chmod(0o600)
    receipt=tmp_path/'receipt.json'
    monkeypatch.setenv('DATABASE_URL_UNPOOLED',pg_url)
    args=['migrate_reference_solutions.py','--postgres','--expected-host','127.0.0.1','--expected-database','postgres','--backup',str(archive)]
    monkeypatch.setattr(sys,'argv',args+['--check-only']);ops.main()
    db=connect(pg_url);assert state(db)==before;db.close()
    monkeypatch.setattr(sys,'argv',args+['--apply','--acknowledge-postgres-backup','--receipt',str(receipt)]);ops.main()
    db=connect(pg_url)
    assert ref.ready(db) and ref.preserved_state(db)==before
    assert db.execute('SELECT count(*) FROM learning_records WHERE solution_code=\'\'').fetchone()[0]==11
    after=state(db);ref.migrate(db);assert state(db)==after
    db.close()
    assert json.loads(receipt.read_text())['learning_records']==11
    assert pg_url not in capsys.readouterr().out


def test_old_sqlite_cutover_fails_safely_on_new_feature(app):
    from scripts.migrate_to_postgres import source_data
    with app.app_context():
        lr.migrate(get_db());ref.migrate(get_db())
    with pytest.raises(ValueError,match='Source schema differs'):
        source_data(app.config['DATABASE'],backup=False)


def test_manual_clear_only_clears_source(feature):
    client=feature.test_client()
    confirm(client,preview(client,[dict(problem_id='two-sum',solution_code=CODE,mistakes='preserved')]))
    result=client.post('/problem/two-sum/solution',data=dict(csrf=csrf(client),token='clear-source-test-token',solution_code=''))
    assert result.status_code==302
    with feature.app_context():
        row=lr.get_record(get_db(),'two-sum')
        assert row['solution_code']=='' and row['mistakes']=='preserved'


def test_operator_refuses_remote_without_certificate_verification(monkeypatch,capsys):
    from scripts import migrate_reference_solutions as ops
    monkeypatch.setattr(sys,'argv',['op','--postgres','--check-only','--expected-host','ep-example.neon.tech','--expected-database','postgres'])
    monkeypatch.setenv('DATABASE_URL_UNPOOLED','postgresql://user:synthetic-secret@ep-example.neon.tech/postgres?sslmode=require')
    monkeypatch.setattr(ops,'inspect_postgres',lambda *_:pytest.fail('Must reject before connecting'))
    with pytest.raises(SystemExit,match='verify-full') as error:ops.main()
    assert 'synthetic-secret' not in str(error.value) and 'synthetic-secret' not in capsys.readouterr().out


def test_invalid_uploaded_batch_changes_no_records_or_history(feature):
    client=feature.test_client()
    confirm(client,preview(client,[dict(problem_id='two-sum',solution_code=CODE)]))
    with feature.app_context():before=state(get_db())
    response=client.post('/learning-records/import',data={'csrf':csrf(client),'action':'parse','file':(io.BytesIO(raw([dict(problem_id='two-sum',solution_code='replacement'),dict(problem_id='unknown',solution_code='bad')]).encode()),'invalid.json')})
    assert response.status_code==200 and b'unknown problem_id' in response.data
    with feature.app_context():assert state(get_db())==before


def test_one_mib_batch_limit_also_works_for_urlencoded_unicode_paste(feature):
    client=feature.test_client()
    with feature.app_context():ids=[r[0] for r in get_db().execute('SELECT id FROM problems LIMIT 20')]
    records=[dict(problem_id=pid,solution_code='# '+('🧠'*10000)) for pid in ids]
    # UTF-8 JSON stays under1 MiB, while ordinary form percent-encoding exceeds2.
    assert len(raw(records).encode())<lr.MAX_BYTES
    token=preview(client,records)
    assert token
