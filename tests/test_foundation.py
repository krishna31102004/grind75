import json
from collections import Counter
from datetime import date
from app import create_app
from app.db import get_db,ROOT,initialize
from app import services as s


def test_dataset():
    seed=json.loads((ROOT/'data/grind75.json').read_text());official=json.loads((ROOT/'data/sources/published75.json').read_text())
    concepts=json.loads((ROOT/'data/concepts.json').read_text());cids={c['id'] for c in concepts}
    assert len(seed)==len({p['id'] for p in seed})==75
    assert sorted(p['learning_order'] for p in seed)==list(range(1,76))
    assert sorted(p['grind_rank'] for p in seed)==list(range(1,76))
    for p,o in zip(seed,official):
        assert all(p[k]==o[k] for k in ('title','difficulty','url'))
        assert p['url']==f"https://leetcode.com/problems/{p['leetcode_slug']}/"
        assert p['id']==p['leetcode_slug'] and p['source_version']
        assert p['primary_concept_id'] in cids
        assert set(p['secondary_patterns'])<=cids
        assert p['premium_status']=='free'
    assert Counter(p['difficulty'] for p in seed)=={'Easy':23,'Medium':43,'Hard':9}
    for c in concepts:assert len(c['body'])>100 and c['template'] and c['prerequisites']


def test_baseline(app):
    with app.app_context():
        items=s.rows();assert len(items)==75
        counts=Counter(p['baseline_date'] for p in items)
        for day in range(15,27):assert counts[f'2026-10-{day}']==6
        assert counts['2026-10-27']==3
        assert len(s.queue(items))==6


def test_persistence(app):
    with app.app_context():
        s.set_status('two-sum','understood',False,'a'*20)
        s.save_notes('two-sum',dict(takeaway='complement',approach='map',confidence='4',effort='20'),'b'*20)
        initialize(get_db())
        before=s.rows()[0]
    restarted=create_app(app.config)
    with restarted.app_context():
        after=s.rows()[0];assert after==before
        assert after['status']=='understood' and after['takeaway']=='complement'
        assert after['next_due_date']=='2026-10-16'


def test_pages(client):
    for path in ['/','/concepts','/concepts/arrays','/problem/two-sum','/cheatsheets','/review','/calendar','/progress','/backup','/export']:
        assert client.get(path).status_code==200,path


def test_frozen_source_evidence():
    import hashlib
    source=ROOT/'data/sources'
    manifest=json.loads((source/'manifest.json').read_text())
    for filename,digest in manifest.items():assert hashlib.sha256((source/filename).read_bytes()).hexdigest()==digest
    official=json.loads((source/'QuestionGroups.json').read_text())
    flattened=[p for week in official.values() for p in week]
    seed=json.loads((ROOT/'data/grind75.json').read_text())
    assert len(flattened)==75
    for p,o in zip(seed,flattened):
        assert p['leetcode_slug']==o['slug']
        assert all(p[k]==o[k] for k in ('title','url','difficulty'))
    urls='\n'.join(p['url'] for p in seed)+'\n'
    summary=json.loads((source/'remote-verification.json').read_text())
    assert hashlib.sha256(urls.encode()).hexdigest()==summary['ordered_urls_sha256']
    assert summary['verified_target_count']==75 and not summary['failed_targets']
