import io
import json
import re
from app.db import get_db,ROOT
from app import services as s


def form(client,path='/problem/two-sum'):
    page=client.get(path).get_data(as_text=True)
    return dict(csrf=re.search('name="csrf" value="([^"]+)"',page)[1],token=re.search('name="token" value="([^"]+)"',page)[1])


def test_spoiler_gating(client,app):
    guide=json.loads((ROOT/'data/problem_guides.json').read_text())['two-sum']
    page=client.get('/problem/two-sum').get_data(as_text=True)
    for value in guide.values():assert value not in page
    assert 'Reveal guide' in page
    data=form(client);client.post('/problem/two-sum/reveal',data=data)
    page=client.get('/problem/two-sum').get_data(as_text=True)
    assert 'value-to-index map' in page
    with app.app_context():assert s.counts(s.rows())['attempted']==0 and s.counts(s.rows())['mastered']==0


def test_attempt_unlock_and_escape_notes(client,app):
    data=form(client);data['status']='attempted';client.post('/problem/two-sum/status',data=data)
    assert 'value-to-index map' in client.get('/problem/two-sum').get_data(as_text=True)
    data=form(client);data.update(takeaway='<script>alert(1)</script>',approach='try pairs',confidence='2',effort='10')
    result=client.post('/problem/two-sum/notes',data=data,follow_redirects=True).get_data(as_text=True)
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in result and '<script>alert(1)</script>' not in result
    assert 'Saved.' in result
    assert '1<small>/75' in client.get('/progress').get_data(as_text=True)
    assert 'Low confidence' in client.get('/review').get_data(as_text=True)


def test_concept_note(client):
    data=form(client,'/concepts/arrays');data['note']='frequency counts'
    result=client.post('/concepts/arrays/notes',data=data,follow_redirects=True)
    assert b'frequency counts' in result.data and b'Concept note saved' in result.data


def test_import_confirmation(client,app):
    with app.app_context():payload=json.dumps(__import__('app.backup',fromlist=['export_data']).export_data())
    data=form(client,'/backup');data['backup']=(io.BytesIO(payload.encode()),'backup.json')
    response=client.post('/backup',data=data)
    assert b'Type REPLACE' in response.data
    data=form(client,'/backup');data.update(confirm='REPLACE',backup=(io.BytesIO(payload.encode()),'backup.json'))
    assert b'Restored successfully' in client.post('/backup',data=data,follow_redirects=True).data


def test_import_duplicate_json_key(client):
    data=form(client,'/backup');data.update(confirm='REPLACE',backup=(io.BytesIO(b'{"a":1,"a":2}'),'bad.json'))
    result=client.post('/backup',data=data)
    assert b'Duplicate JSON keys' in result.data


def test_import_size_limit(client):
    data=form(client,'/backup');data.update(confirm='REPLACE',backup=(io.BytesIO(b'x'*(16*1024*1024)),'large.json'))
    assert client.post('/backup',data=data).status_code==413


def test_csrf_and_origin(client):
    assert client.post('/problem/two-sum/status',data={'status':'understood'}).status_code==400
    data=form(client);data['status']='understood'
    assert client.post('/problem/two-sum/status',data=data,headers={'Origin':'https://evil.example'}).status_code==403


def test_filters_search_and_links(client):
    assert b'Two Sum' in client.get('/cheatsheets?q=two+sum').data
    assert b'Valid Anagram' not in client.get('/cheatsheets?q=two+sum').data
    assert b'Two Sum' not in client.get('/concepts/arrays?difficulty=Hard').data
    for path in ['/','/concepts','/cheatsheets','/review','/calendar','/progress']:
        response=client.get(path);assert response.status_code==200
        for href in re.findall(r'href="(/[^"#]*)"',response.get_data(as_text=True)):
            assert client.get(href).status_code==200,(path,href)


def test_invalid_route_and_input(client,app):
    assert client.get('/problem/does-not-exist').status_code==404
    data=form(client);data.update(date='not-a-date')
    assert b'valid date' in client.post('/problem/two-sum/move',data=data,follow_redirects=True).data
    data=form(client);data.update(confidence='9')
    assert b'Confidence must' in client.post('/problem/two-sum/notes',data=data,follow_redirects=True).data
    with app.app_context():assert s.counts(s.rows())['attempted']==0


def test_all_problem_and_concept_pages(client,app):
    with app.app_context():items=s.rows();cids={p['concept_id'] for p in items}
    for p in items:assert client.get('/problem/'+p['id']).status_code==200
    for cid in cids:assert client.get('/concepts/'+cid).status_code==200


def test_all_guides_locked_and_unlocked(client,app):
    from html import unescape
    guides=json.loads((ROOT/'data/problem_guides.json').read_text())
    for pid,guide in guides.items():
        locked=client.get('/problem/'+pid).get_data(as_text=True)
        for key in ['clue','baseline','optimal','takeaway']:assert guide[key] not in unescape(locked)
        with app.app_context():s.set_status(pid,'attempted',False,'unlock-test-token-'+pid)
        unlocked=client.get('/problem/'+pid).get_data(as_text=True)
        for value in guide.values():assert value in unescape(unlocked)


def test_reject_untrusted_host(client):
    assert client.get('/export',headers={'Host':'attacker.example'}).status_code==400


def test_history_uses_study_labels(client,app):
    with app.app_context():
        s.set_status('two-sum','attempted',False,'history-test-token1')
        s.set_status('two-sum','understood',False,'history-test-token2')
        s.review('two-sum','hints','Need to revisit duplicates','history-test-token3')
    page=client.get('/problem/two-sum').get_data(as_text=True)
    assert 'Attempted → Understood' in page and 'Needed hints · Need to revisit duplicates' in page
    assert '{&#34;old&#34;' not in page
