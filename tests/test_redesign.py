"""UI contracts and complete-content fidelity, using disposable fixtures only."""
import html
import json
import re

import pytest
from werkzeug.datastructures import MultiDict

from app.db import get_db
from app.learning_records import FIELDS, FORMAT, apply, migrate, parse


IDS = ['two-sum','valid-anagram','ransom-note','contains-duplicate','valid-palindrome','binary-search']


def full_value(prefix, key, length=1500):
    block = f'\n{prefix} {key}: Unicode 🧠 café 漢字, punctuation <>&"\'\n\n```python\nfor i in range(n):\n    print(i)\n```\n  Keep whitespace.  \n'
    return (block * (length // len(block) + 1))[:length-5] + '\nEnd '


def batch(prefix='incoming'):
    return {'format':FORMAT,'version':1,'records':[{'problem_id':pid, **{f:full_value(prefix+' '+pid,f) for f in FIELDS}} for pid in IDS]}


def prepare(app, client):
    with app.app_context():migrate(get_db())
    client.get('/learning-records/import')
    with client.session_transaction() as session:return session['csrf']


def preview(client, csrf, data):
    response=client.post('/learning-records/import',data={'csrf':csrf,'action':'parse','json':json.dumps(data,ensure_ascii=False)})
    assert response.status_code==200
    token=re.search(r'name="preview_token" value="([^"]+)"',response.text)[1]
    return response,token


def study_state(db):
    return {table:[tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY 1')] for table in ['assignments','progress','problem_notes','review_state','review_events']}


def test_six_records_all_nine_full_strings_preview_confirm_restart_export(app, client):
    from app import create_app
    csrf=prepare(app,client);data=batch()
    with app.app_context():before=study_state(get_db())
    response,token=preview(client,csrf,data)
    for record in data['records']:
        for field in FIELDS:assert record[field] in html.unescape(response.text)
    assert b'54</strong> new fields' in response.data
    assert client.post('/learning-records/import',data={'csrf':csrf,'action':'confirm','preview_token':token}).status_code==302
    exported=client.get('/learning-records/export').get_json()
    assert {r['problem_id']:r for r in exported['records']}=={r['problem_id']:r for r in data['records']}
    with app.app_context():assert before==study_state(get_db())
    restarted=create_app(dict(TESTING=True,DATABASE=app.config['DATABASE'],DATABASE_URL=None,AUTH_REQUIRED=False,SECRET_KEY='isolated-ui-fidelity-restart-key-long-enough'))
    assert restarted.test_client().get('/learning-records/export').get_json()==exported


def test_full_existing_and_incoming_conflicts_inspectable_and_explicit_replacements(app,client):
    csrf=prepare(app,client);existing=batch('existing');incoming=batch('replacement')
    with app.app_context():
        with get_db() as db:apply(db,existing,{},set())
    response,token=preview(client,csrf,incoming)
    assert b'54</strong> conflicts kept by default' in response.data
    assert response.text.count('data-existing')==54 and response.text.count('data-incoming')==54
    for record in existing['records']+incoming['records']:
        for field in FIELDS:assert record[field] in html.unescape(response.text)
    # Default confirmation preserves every original character.
    client.post('/learning-records/import',data={'csrf':csrf,'action':'confirm','preview_token':token})
    assert client.get('/learning-records/export').get_json()['records']==sorted(existing['records'],key=lambda r:r['problem_id'])
    response,token=preview(client,csrf,incoming)
    fields=MultiDict([('csrf',csrf),('action','confirm'),('preview_token',token)])
    for record in incoming['records']:
        for key in FIELDS:fields.add('replace_'+record['problem_id'],key)
    client.post('/learning-records/import',data=fields)
    assert client.get('/learning-records/export').get_json()['records']==sorted(incoming['records'],key=lambda r:r['problem_id'])


def test_manual_editor_exact_max_unicode_full_content_and_selected_exports(app,client):
    csrf=prepare(app,client)
    fields={key:full_value('editor',key,8000) for key in FIELDS}
    assert all(len(value)==8000 for value in fields.values())
    response=client.post('/problem/two-sum/learning-record',data={**fields,'csrf':csrf,'token':'exact-max-character-ui-test'})
    assert response.status_code==302
    expected={'problem_id':'two-sum',**fields}
    assert client.get('/learning-records/export?selected=1&problem_id=two-sum').get_json()['records']==[expected]
    page=client.get('/problem/two-sum').text
    for key in FIELDS:assert fields[key] in html.unescape(page)
    assert 'data-exact-record' in page and 'data-character-limit="8000"' in page
    response=client.post('/problem/two-sum/learning-record',data={**fields,'mistakes':'x'*8001,'csrf':csrf,'token':'reject-ui-overflow-test'})
    assert response.status_code==302
    assert client.get('/learning-records/export').get_json()['records']==[expected]


def test_library_filters_and_selection_do_not_change_records_or_progress(app,client):
    csrf=prepare(app,client)
    with app.app_context():
        with get_db() as db:apply(db,batch(),{},set())
        before=study_state(get_db())
    saved=client.get('/learning-records?record_state=saved&q=two+sum').text
    assert 'Two Sum' in saved and 'Valid Anagram' not in saved
    empty=client.get('/learning-records?record_state=empty').text
    assert 'Valid Anagram' not in empty and 'Flood Fill' in empty
    selected=client.get('/learning-records/export?selected=1&problem_id=two-sum&problem_id=valid-anagram').get_json()
    assert {r['problem_id'] for r in selected['records']}=={'two-sum','valid-anagram'}
    assert all(set(r)=={'problem_id',*FIELDS} for r in selected['records'])
    with app.app_context():assert before==study_state(get_db())


def test_sidebar_active_destination_and_no_broken_legacy_feature_link(client,app):
    page=client.get('/').text
    assert 'class="nav-disclosure"' in page and 'href="/" aria-current="page"' in page
    assert 'href="/learning-records"' not in page
    prepare(app,client)
    page=client.get('/learning-records/import').text
    assert 'href="/learning-records" aria-current="page"' in page
    assert 'aria-current="step"' in page


def test_calendar_presented_review_dates_do_not_change_schedule(app,client):
    from app import services as s
    with app.app_context():
        s.set_status('two-sum','understood',False,'calendar-ui-known-status')
        before=study_state(get_db())
    page=client.get('/calendar').text
    assert 'Reviews due' in page and '2026-10-16' in page
    with app.app_context():assert before==study_state(get_db())


@pytest.mark.parametrize('count',[12,13])
def test_ui_import_record_limits_unchanged(app,client,count):
    prepare(app,client)
    with app.app_context():
        ids=[r[0] for r in get_db().execute('SELECT id FROM problems LIMIT 13')]
        data={'format':FORMAT,'version':1,'records':[{'problem_id':pid} for pid in ids[:count]]}
        if count==12:assert len(parse(json.dumps(data),get_db())['records'])==12
        else:
            with pytest.raises(ValueError,match='12'):parse(json.dumps(data),get_db())


@pytest.mark.parametrize('as_bytes',[False,True])
def test_exact_utf8_payload_byte_limit_remains_256_kib(app,client,as_bytes):
    prepare(app,client)
    raw=json.dumps({'format':FORMAT,'version':1,'records':[{'problem_id':'two-sum','mistakes':'Unicode 🧠 漢字\n'}]},ensure_ascii=False)
    raw+=' '*(256*1024-len(raw.encode('utf-8')))
    assert len(raw.encode('utf-8'))==256*1024
    with app.app_context():
        assert parse(raw.encode('utf-8') if as_bytes else raw,get_db())['records'][0]['mistakes']=='Unicode 🧠 漢字\n'
        with pytest.raises(ValueError,match='256 KiB'):
            parse((raw+' ').encode('utf-8') if as_bytes else raw+' ',get_db())
