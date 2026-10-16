import copy
import hashlib
import json
import pytest
from app import create_app,services as s
from app.db import connect,initialize,get_db
from app.backup import export_data,restore
from scripts.migrate_to_postgres import migrate,verify,records


@pytest.fixture
def populated_source(tmp_path):
    source=tmp_path/'original.sqlite3'
    app=create_app(dict(TESTING=True,DATABASE=str(source),DATABASE_URL=None,AUTH_REQUIRED=False,SECRET_KEY='test-key-with-enough-characters',NOW='2026-10-15T17:00:00+00:00'))
    with app.app_context():
        s.set_status('two-sum','understood',True,'pg-initial-status1')
        s.save_notes('two-sum',dict(takeaway='Check-before-insert → ✓',approach='map',confidence='4',effort='27'),'pg-initial-notes11')
        s.review('two-sum','independent','Independent review note','pg-initial-review1')
        s.move('valid-anagram','2026-10-20','pg-manual-move1111')
        db=get_db();db.execute("INSERT INTO concept_notes VALUES('arrays','Patterns, not guesses')");db.execute("INSERT INTO settings VALUES('personal_preference','preserve-me')");db.commit()
    return source,app


def test_migrate_verify_retry_and_source_unchanged(pg_url,populated_source):
    source,app=populated_source;before=hashlib.sha256(source.read_bytes()).hexdigest()
    result=migrate(source,pg_url)
    assert result['matched'] and result['status']=='migrated_and_verified'
    assert all(result['source_counts'][t]==result['destination_counts'][t] for t in result['source_counts'])
    assert verify(source,pg_url)['matched']
    assert migrate(source,pg_url)['status']=='already_migrated'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    assert (source.parent/'cloud-authority.json').exists()
    assert list((source.parent/'backups').glob('migration-source-*.sqlite3'))


def test_pg_progress_reviews_backup_restart_and_catchup(pg_url,populated_source):
    source,original=populated_source;migrate(source,pg_url,mark_authority=False)
    config=dict(original.config,DATABASE_URL=pg_url)
    app=create_app(config)
    with app.app_context():
        items=s.rows();p=next(p for p in items if p['id']=='two-sum')
        assert p['takeaway']=='Check-before-insert → ✓' and p['mastered']==1 and p['next_due_date']=='2026-10-18'
        s.review('two-sum','independent','retained', 'pg-next-review111')
        assert next(p for p in s.rows() if p['id']=='two-sum')['next_due_date']=='2026-10-22'
        payload=export_data();s.set_status('two-sum','needs_review',False,'pg-downgrade11111')
        name=restore(payload);assert export_data()['tables']==payload['tables']
        assert get_db().execute('SELECT payload FROM safety_backups WHERE id=?',(name,)).fetchone()
        app.config['NOW']='2026-10-20T17:00:00+00:00';s.catch_up('pg-catch-up111111');first=[p['scheduled_date'] for p in s.rows()]
        s.catch_up('pg-catch-up222222');assert first==[p['scheduled_date'] for p in s.rows()]
        assert next(p for p in s.rows() if p['id']=='valid-anagram')['scheduled_date']=='2026-10-20'
        assert s.counts(s.rows())['attempted']==1
    client=create_app(config).test_client()
    for path in ['/','/concepts','/review','/calendar','/progress','/backup','/study-context','/problem/two-sum','/static/style.css','/static/app.js']:
        assert client.get(path).status_code==200,path


def test_refuse_existing_destination_and_transaction_rollback(pg_url,populated_source):
    source,_=populated_source;db=connect(pg_url);initialize(db)
    with db:db.execute("INSERT INTO settings VALUES('existing','do-not-overwrite')")
    with pytest.raises(ValueError,match='contains data'):migrate(source,pg_url,mark_authority=False)
    assert db.execute('SELECT count(*) FROM problems').fetchone()[0]==0
    assert db.execute("SELECT value FROM settings WHERE key='existing'").fetchone()[0]=='do-not-overwrite'
    db.close()


def test_retry_after_cloud_progress_does_not_reset(pg_url,populated_source):
    source,local=populated_source;migrate(source,pg_url,mark_authority=False)
    app=create_app(dict(local.config,DATABASE_URL=pg_url))
    with app.app_context():s.set_status('valid-anagram','attempted',False,'cloud-only-action11')
    result=migrate(source,pg_url,mark_authority=False)
    assert result['status']=='already_migrated' and not result['matched']
    with app.app_context():assert s.counts(s.rows())['attempted']==2


def test_migration_failure_is_atomic(pg_url,populated_source,monkeypatch):
    import scripts.migrate_to_postgres as module
    source,_=populated_source
    original=module.comparison
    def fail_after_copy(a,b):
        result=original(a,b);result['matched']=False;return result
    monkeypatch.setattr(module,'comparison',fail_after_copy)
    with pytest.raises(ValueError,match='rolled back'):migrate(source,pg_url,mark_authority=False)
    db=connect(pg_url)
    assert db.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()").fetchone()[0]==0
    db.close()


def test_baseline_constraint_pg(pg_url,populated_source):
    import psycopg
    source,_=populated_source;migrate(source,pg_url,mark_authority=False)
    db=connect(pg_url)
    with pytest.raises(psycopg.Error):
        with db:db.execute("UPDATE assignments SET baseline_date='2026-10-30' WHERE problem_id='two-sum'")
    assert db.execute("SELECT baseline_date FROM assignments WHERE problem_id='two-sum'").fetchone()[0]=='2026-10-15'
    db.close()
