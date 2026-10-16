import importlib
import json
import pytest
from app import create_app
from app.db import ROOT,get_db
from app import services as s


def test_production_requires_database(monkeypatch):
    monkeypatch.setenv('VERCEL','1');monkeypatch.delenv('DATABASE_URL',raising=False)
    with pytest.raises(RuntimeError,match='DATABASE_URL'):create_app({'TESTING':True})


@pytest.mark.parametrize('missing',['SECRET_KEY','ADMIN_PASSWORD_HASH'])
def test_production_requires_secrets(monkeypatch,missing):
    monkeypatch.setenv('VERCEL','1');monkeypatch.setenv('DATABASE_URL','postgresql://unused.invalid/db')
    monkeypatch.setenv('SECRET_KEY','test-secret-long-enough-for-production')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH','scrypt:32768:8:1$test$test')
    monkeypatch.delenv(missing,raising=False)
    with pytest.raises(RuntimeError,match=missing):create_app({'TESTING':True})


def test_wsgi_import_no_network_or_filesystem_writes(monkeypatch,tmp_path):
    import psycopg
    monkeypatch.setenv('VERCEL','1');monkeypatch.setenv('DATABASE_URL','postgresql://unused.invalid/db')
    monkeypatch.setenv('SECRET_KEY','test-secret-long-enough-for-production')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH','scrypt:32768:8:1$test$test')
    monkeypatch.setenv('VERCEL_URL','grind75-test.vercel.app')
    monkeypatch.setattr(psycopg,'connect',lambda *a,**k:pytest.fail('WSGI import must not connect/migrate'))
    from pathlib import Path
    monkeypatch.setattr(Path,'mkdir',lambda *a,**k:pytest.fail('Production startup must not write filesystem'))
    import wsgi;importlib.reload(wsgi)
    assert wsgi.app.debug is False
    assert wsgi.app.config['AUTH_REQUIRED'] and wsgi.app.config['SESSION_COOKIE_SECURE']
    assert 'grind75-test.vercel.app' in wsgi.app.config['TRUSTED_HOSTS']


def test_native_config_and_public_assets(client):
    config=json.loads((ROOT/'vercel.json').read_text())
    assert config=={'$schema':'https://openapi.vercel.sh/vercel.json'}
    for filename in ['style.css','app.js']:
        assert (ROOT/'public/static'/filename).is_file()
        assert client.get('/static/'+filename).status_code==200


def test_catchup_reads_inside_write_transaction(app,monkeypatch):
    original=s.rows
    with app.app_context():
        def locked_rows():
            assert get_db().in_transaction,'Schedule snapshot must be read after acquiring write transaction'
            return original()
        monkeypatch.setattr(s,'rows',locked_rows)
        s.catch_up('catchup-race-regression1')


def test_temporary_sqlite_ignores_cloud_environment(monkeypatch,tmp_path):
    monkeypatch.setenv('DATABASE_URL','postgresql://must-never-connect.invalid/private')
    app=create_app({'TESTING':True,'DATABASE':str(tmp_path/'isolated.sqlite3')})
    assert app.config['DATABASE_URL'] is None
    with app.app_context():assert len(s.rows())==75


def test_wsgi_fails_closed_without_platform_detection(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv',lambda *args,**kwargs:False)
    monkeypatch.delenv('VERCEL',raising=False)
    monkeypatch.delenv('APP_ENV',raising=False)
    monkeypatch.delenv('DATABASE_URL',raising=False)
    with pytest.raises(RuntimeError,match='DATABASE_URL'):
        import wsgi
        importlib.reload(wsgi)
