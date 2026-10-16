import pytest
from app import create_app

@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING':True,'DATABASE_URL':None,'ADMIN_PASSWORD_HASH':None,'AUTH_REQUIRED':False,'SECRET_KEY':'isolated-test-session-key-long-enough','DATABASE':str(tmp_path/'test.sqlite3'),'NOW':'2026-10-15T17:00:00+00:00'})

@pytest.fixture
def client(app):return app.test_client()


@pytest.fixture
def pg_url():
    import os, uuid
    from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
    import psycopg
    from psycopg import sql
    base=os.environ.get('TEST_DATABASE_URL')
    if not base:pytest.skip('TEST_DATABASE_URL not set; optional isolated PostgreSQL tests')
    if urlsplit(base).hostname not in ('127.0.0.1','localhost','::1'):
        pytest.fail('PostgreSQL integration tests require a disposable local PostgreSQL URL.')
    schema='test_'+uuid.uuid4().hex
    admin=psycopg.connect(base,autocommit=True)
    admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    parts=urlsplit(base);query=dict(parse_qsl(parts.query));query['options']='-csearch_path='+schema
    url=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment))
    try:yield url
    finally:
        admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)));admin.close()


@pytest.fixture(params=['sqlite','postgresql'])
def secured(request,tmp_path):
    from werkzeug.security import generate_password_hash
    from app.db import connect,initialize
    config=dict(TESTING=True,DATABASE=str(tmp_path/'secure.sqlite3'),DATABASE_URL=None,AUTH_REQUIRED=True,
        SECRET_KEY='isolated-secure-test-key-long-enough',ADMIN_USERNAME='admin',
        ADMIN_PASSWORD_HASH=generate_password_hash('unit-test-only-password',method='scrypt'),
        NOW='2026-10-15T17:00:00+00:00',SESSION_COOKIE_SECURE=True)
    if request.param=='postgresql':
        from scripts.migrate_to_postgres import migrate
        url=request.getfixturevalue('pg_url');source=tmp_path/'source.sqlite3';db=connect(source)
        initialize(db);db.close();migrate(source,url,mark_authority=False);config['DATABASE_URL']=url
    return create_app(config)
