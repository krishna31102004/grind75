import json
import re
import pytest
from app import create_app
from app.db import get_db
from app import services as s

BASE='https://localhost'


def login(client):
    page=client.get('/login',base_url=BASE)
    csrf=re.search(r'name="csrf" value="([^"]+)"',page.get_data(as_text=True))[1]
    return client.post('/login',base_url=BASE,data=dict(csrf=csrf,username='admin',password='unit-test-only-password'))


def form(client,path='/study-context'):
    page=client.get(path,base_url=BASE).get_data(as_text=True)
    return dict(csrf=re.search(r'name="csrf" value="([^"]+)"',page)[1],token=re.search(r'name="token" value="([^"]+)"',page)[1])


def test_private_access(secured):
    client=secured.test_client()
    for path in ['/','/concepts','/problem/two-sum','/review','/calendar','/progress','/backup','/export','/study-context','/study-context?format=json','/backup/safety/fake']:
        result=client.get(path,base_url=BASE)
        assert result.status_code==302 and result.location.endswith('/login'),path
    for path in ['/problem/two-sum/status','/problem/two-sum/notes','/backup','/reschedule','/study-context/sharing']:
        assert client.post(path,base_url=BASE,data={'status':'understood'}).status_code==401
    with secured.app_context():assert s.counts(s.rows())['attempted']==0


def test_login_session_csrf_logout(secured):
    client=secured.test_client()
    assert client.post('/login',base_url=BASE,data={'password':'unit-test-only-password'}).status_code==400
    result=login(client);assert result.status_code==302
    cookie=result.headers['Set-Cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
    assert client.get('/',base_url=BASE).status_code==200
    assert client.post('/logout',base_url=BASE).status_code==400
    data=form(client);data['status']='attempted'
    assert client.post('/problem/two-sum/status',base_url=BASE,data=data,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/problem/two-sum/status',base_url=BASE,data=data).status_code==302
    assert client.post('/logout',base_url=BASE,data={'csrf':data['csrf']}).status_code==302
    assert client.get('/export',base_url=BASE).status_code==302


def test_unicode_username_and_rate_limit(secured):
    client=secured.test_client()
    page=client.get('/login',base_url=BASE).get_data(as_text=True)
    csrf=re.search(r'name="csrf" value="([^"]+)"',page)[1]
    for _ in range(8):
        result=client.post('/login',base_url=BASE,data=dict(csrf=csrf,username='你好',password='unit-test-only-password'))
        assert result.status_code==401
    assert client.post('/login',base_url=BASE,data=dict(csrf=csrf,username='admin',password='unit-test-only-password')).status_code==429


def test_share_whitelist_live_revocable(secured):
    owner=secured.test_client();public=secured.test_client();login(owner)
    assert public.get('/share/'+'a'*43,base_url=BASE).status_code==404
    with secured.app_context():
        s.set_status('two-sum','hints',False,'secure-test-action1')
        s.save_notes('two-sum',dict(takeaway='PRIVATE_TAKEAWAY_SENTINEL',approach='PRIVATE_APPROACH_SENTINEL',confidence='2',effort='20'),'secure-test-action2')
        get_db().execute("INSERT INTO concept_notes VALUES('arrays','PRIVATE_CONCEPT_SENTINEL')");get_db().commit()
    data=form(owner);data['action']='enable'
    result=owner.post('/study-context/sharing',base_url=BASE,data=data)
    url=re.search(r'value="(https://localhost/share/[A-Za-z0-9_-]+)"',result.get_data(as_text=True))[1]
    shared=public.get(url)
    assert shared.status_code==200 and b'Two Sum' in shared.data and b'<script' not in shared.data and b'<form' not in shared.data
    facts=public.get(url+'?format=json').get_json()
    assert facts['counts']['attempted']==1 and len(facts['hinted_questions'])==1 and facts['weak_concepts']
    for content in (shared.get_data(as_text=True),json.dumps(facts)):
        for forbidden in ['PRIVATE_','password','DATABASE_URL','SECRET_KEY','ADMIN_PASSWORD_HASH','takeaway','approach','effort','security_state']:
            assert forbidden not in content
    assert public.post(url,data={'status':'understood'}).status_code==405
    assert public.post('/problem/two-sum/status',base_url=BASE,data={'status':'understood','token':url.rsplit('/',1)[1]}).status_code==401
    for header,part in [('Cache-Control','no-store'),('X-Robots-Tag','noindex'),('Referrer-Policy','no-referrer')]:
        assert part in shared.headers[header]
        assert part in public.get(url+'?format=json').headers[header]
    with secured.app_context():s.set_status('two-sum','understood',False,'secure-test-action3')
    assert public.get(url+'?format=json').get_json()['counts']['understood']==1
    data=form(owner);data['action']='regenerate';result=owner.post('/study-context/sharing',base_url=BASE,data=data)
    new=re.search(r'value="(https://localhost/share/[A-Za-z0-9_-]+)"',result.get_data(as_text=True))[1]
    assert new!=url and public.get(url).status_code==404 and public.get(new).status_code==200
    with secured.app_context():
        saved=get_db().execute("SELECT value FROM security_state WHERE key='study_share_hash'").fetchone()[0]
        assert url.rsplit('/',1)[1] not in saved and len(saved)==64
    data=form(owner);data['action']='revoke';owner.post('/study-context/sharing',base_url=BASE,data=data)
    assert public.get(new).status_code==404


def test_headers_all_blueprints(secured):
    client=secured.test_client()
    for path in ['/login','/share/'+'a'*43]:
        response=client.get(path,base_url=BASE)
        assert response.headers['Cache-Control']=='no-store'
        assert 'noindex' in response.headers['X-Robots-Tag']
        assert response.headers['Referrer-Policy']==('no-referrer' if path.startswith('/share/') else 'same-origin')
    login(client)
    for path in ['/study-context','/study-context?format=json','/backup']:
        response=client.get(path,base_url=BASE)
        assert response.headers['Cache-Control']=='no-store' and 'noindex' in response.headers['X-Robots-Tag']


def test_separate_authenticated_sessions_persist(secured):
    one=secured.test_client();two=secured.test_client();login(one);login(two)
    data=form(one);data['status']='understood'
    one.post('/problem/two-sum/status',base_url=BASE,data=data)
    assert two.get('/study-context?format=json',base_url=BASE).get_json()['counts']['understood']==1
    refreshed=create_app(secured.config).test_client();login(refreshed)
    assert refreshed.get('/study-context?format=json',base_url=BASE).get_json()['counts']['understood']==1


def test_password_rotation_invalidates_session(secured):
    from werkzeug.security import generate_password_hash
    client=secured.test_client();login(client)
    secured.config['ADMIN_PASSWORD_HASH']=generate_password_hash('new-test-only-password')
    assert client.get('/',base_url=BASE).status_code==302


def test_invalid_unicode_csrf_is_400(secured):
    client=secured.test_client();client.get('/login',base_url=BASE)
    assert client.post('/login',base_url=BASE,data={'csrf':'é'}).status_code==400


def test_upcoming_respects_manual_dates(secured):
    owner=secured.test_client();login(owner)
    with secured.app_context():
        s.move('two-sum','2099-01-01','context-future-111')
        s.move('word-ladder','2026-10-16','context-future-222')
    data=owner.get('/study-context?format=json',base_url=BASE).get_json()
    upcoming=data['upcoming_questions']
    assert upcoming[0]['id']=='word-ladder' and all(p['id']!='two-sum' for p in upcoming)


def test_json_link_after_sharing_post(secured):
    owner=secured.test_client();login(owner)
    data=form(owner);data['action']='enable'
    response=owner.post('/study-context/sharing',base_url=BASE,data=data)
    html=response.get_data(as_text=True)
    assert 'href="/study-context?format=json"' in html
    assert owner.get('/study-context?format=json',base_url=BASE).is_json
