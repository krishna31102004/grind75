import json
import subprocess
import sys
import pytest
from app import create_app, curriculum, services as s
from app.db import ROOT, get_db, initialize, connect
from app import learning_records as lr
from app.backup import export_data, validate

# Independent human-readable acceptance sequence, not derived from the implementation.
TITLES = '''Two Sum|Valid Anagram|Contains Duplicate|Ransom Note|Valid Palindrome|Binary Search|Valid Parentheses|Merge Two Sorted Lists|Reverse Linked List|Linked List Cycle|Middle of the Linked List|Invert Binary Tree|Maximum Depth of Binary Tree|Diameter of Binary Tree|Balanced Binary Tree|Lowest Common Ancestor of a Binary Search Tree|Flood Fill|Best Time to Buy and Sell Stock|Majority Element|First Bad Version|Implement Queue using Stacks|Climbing Stairs|Longest Palindrome|Add Binary|String to Integer (atoi)|Product of Array Except Self|Maximum Subarray|Spiral Matrix|3Sum|Container With Most Water|Sort Colors|Trapping Rain Water|Merge Intervals|Insert Interval|Longest Substring Without Repeating Characters|Find All Anagrams in a String|Longest Palindromic Substring|Minimum Window Substring|Search in Rotated Sorted Array|Time Based Key-Value Store|Validate Binary Search Tree|Kth Smallest Element in a BST|Binary Tree Level Order Traversal|Binary Tree Right Side View|Lowest Common Ancestor of a Binary Tree|Construct Binary Tree from Preorder and Inorder Traversal|Serialize and Deserialize Binary Tree|Number of Islands|Clone Graph|Rotting Oranges|01 Matrix|Course Schedule|Accounts Merge|Minimum Height Trees|Word Ladder|Min Stack|Evaluate Reverse Polish Notation|Largest Rectangle in Histogram|Basic Calculator|K Closest Points to Origin|Task Scheduler|Find Median from Data Stream|Merge k Sorted Lists|Subsets|Permutations|Combination Sum|Letter Combinations of a Phone Number|Word Search|Unique Paths|Coin Change|Word Break|Partition Equal Subset Sum|Maximum Profit in Job Scheduling|Implement Trie (Prefix Tree)|LRU Cache'''.split('|')


def legacy(db):
    ids=json.loads((ROOT/'data/baseline_order.json').read_text())
    with db:
        db.execute('UPDATE problems SET learning_order=-learning_order')
        for i,pid in enumerate(ids,1):
            row=db.execute('SELECT metadata FROM problems WHERE id=?',(pid,)).fetchone()
            metadata=json.loads(row[0]);metadata['learning_order']=i
            db.execute('UPDATE problems SET learning_order=?,metadata=? WHERE id=?',(i,json.dumps(metadata),pid))
        db.execute('UPDATE assignments SET scheduled_date=baseline_date')


@pytest.fixture(params=['sqlite','postgresql'])
def prepared(request,app,tmp_path):
    if request.param=='postgresql':
        from scripts.migrate_to_postgres import migrate
        url=request.getfixturevalue('pg_url')
        migrate(app.config['DATABASE'],url,mark_authority=False)
        app=create_app(dict(app.config,DATABASE_URL=url))
    app.config['NOW']='2026-10-19T17:00:00+00:00'
    with app.app_context():
        db=get_db();lr.migrate(db);legacy(db)
        for i,pid in enumerate(curriculum.order()[:13]):
            s.set_status(pid,'understood',i==0,('initial-status-'+str(i)).ljust(20,'x'))
        s.save_notes('two-sum',dict(takeaway='  私の notes\n',approach='exact 🧠\n',confidence='4',effort='31'),'save-notes-token1')
        s.review('two-sum','independent','retain my history','independent-review1')
        with db:
            db.execute("INSERT INTO concept_notes VALUES('trees','  recursive notes\n')")
            db.execute("INSERT INTO security_state VALUES('study_share_hash','retain-sharing-value')")
            db.execute("INSERT INTO settings VALUES('personal-setting','retain')")
            db.execute("UPDATE assignments SET manual_override=1,scheduled_date='2026-10-25' WHERE problem_id='basic-calculator'")
            db.execute("UPDATE assignments SET scheduled_date='2026-10-14' WHERE problem_id='two-sum'")
            values={f:'\n'+f+'\r\nUnicode 🧠 漢字  \n```code```  ' for f in lr.FIELDS}
            columns=['problem_id',*lr.FIELDS,'updated_at']
            db.execute(f"INSERT INTO learning_records ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",['two-sum',*values.values(),'2026-10-19T12:00:00+00:00'])
    app.config['NOW']='2026-10-20T17:00:00+00:00'
    return app


def test_exact_inventory(app):
    seed=json.loads((ROOT/'data/grind75.json').read_text())
    ranked=sorted(seed,key=lambda p:p['learning_order'])
    assert [p['title'].casefold() for p in ranked]==[t.casefold() for t in TITLES]
    assert [p['id'] for p in ranked]==curriculum.order()
    assert [p['learning_order'] for p in ranked]==list(range(1,76))
    old=json.loads((ROOT/'data/baseline_order.json').read_text())
    assert set(old)==set(curriculum.order()) and old[:2]==curriculum.order()[:2]
    assert old[4:13]==curriculum.order()[4:13]
    assert set(old[2:4])==set(curriculum.order()[2:4]) # Owner approved #3/#4 swap.


def test_preservation_and_idempotence(prepared):
    with prepared.app_context():
        db=get_db();before=curriculum.state(db);backup=export_data();validate(backup)
        proposed=curriculum.plan(db)
        assert proposed['schedules']
        receipt=curriculum.apply(db,proposed)
        after=curriculum.state(db)
        assert [p['id'] for p in s.rows()]==curriculum.order()
        for table in before:
            if table not in ('problems','assignments'):assert after[table]==before[table],table
        old={p['problem_id']:p for p in before['assignments']}
        for row in after['assignments']:
            assert row['baseline_date']==old[row['problem_id']]['baseline_date']
            if row['manual_override'] or row['problem_id'] in curriculum.order()[:13]: assert row==old[row['problem_id']]
        for pid in curriculum.order():
            a=next(p for p in before['problems'] if p['id']==pid);b=next(p for p in after['problems'] if p['id']==pid)
            assert {k:v for k,v in a.items() if k not in ('learning_order','metadata')}=={k:v for k,v in b.items() if k not in ('learning_order','metadata')}
            ma=json.loads(a['metadata']);mb=json.loads(b['metadata']);ma.pop('learning_order');mb.pop('learning_order');assert ma==mb
        assert receipt['verification']
        second=curriculum.plan(db);assert not second['schedules']
        curriculum.apply(db,second);assert curriculum.state(db)==after
        assert validate(export_data()) and validate(backup)


def test_stale_plan_rolls_back(prepared):
    with prepared.app_context():
        db=get_db();p=curriculum.plan(db)
        s.move('diameter-of-binary-tree','2026-10-26','manual-new-date111')
        before=curriculum.state(db)
        with pytest.raises(ValueError,match='stale'):curriculum.apply(db,p)
        assert curriculum.state(db)==before


def test_ordering_across_pages_and_due_priority(prepared):
    with prepared.app_context():
        db=get_db();curriculum.apply(db,curriculum.plan(db))
        assert s.queue(s.rows())[0]['id']=='diameter-of-binary-tree'
        with db:
            db.execute("UPDATE review_state SET next_due_date='2026-10-19' WHERE problem_id='two-sum'")
            db.execute("UPDATE review_state SET next_due_date='2026-10-18' WHERE problem_id='valid-anagram'")
    c=prepared.test_client()
    today=c.get('/').text
    assert 'Next up' in today and 'Diameter of Binary Tree' in today
    assert c.get('/problem/diameter-of-binary-tree').text.find('Problem 14 of 75')>=0
    assert c.get('/problem/balanced-binary-tree').text.find('Problem 15 of 75')>=0
    assert c.get('/problem/lowest-common-ancestor-of-a-binary-search-tree').text.find('Problem 16 of 75')>=0
    for path in ['/learning-records','/cheatsheets','/calendar','/concepts/trees','/?ahead=1','/progress']:
        assert c.get(path).status_code==200
    snap=c.get('/study-context?format=json').json
    assert snap['next_questions'][0]['id']=='diameter-of-binary-tree'
    assert snap['next_questions'][0]['learning_order']==14
    assert snap['reviews_due'][0]['id']=='valid-anagram'
    assert c.get('/review').text.index('Valid Anagram')<c.get('/review').text.index('Two Sum')
    assert 'brute_force' not in json.dumps(snap)


def test_mismatch_rolls_back(prepared):
    with prepared.app_context():
        db=get_db()
        with db:db.execute("UPDATE problems SET title='Wrong identity' WHERE id='two-sum'")
        before=curriculum.state(db)
        with pytest.raises(ValueError,match='metadata'):curriculum.apply(db,{})
        assert curriculum.state(db)==before


def test_restart_does_not_auto_apply_or_revert(app):
    with app.app_context():
        db=get_db();legacy(db);before=curriculum.plan(db)
        initialize(db)
        assert curriculum.plan(db)==before
        curriculum.apply(db,before);after=curriculum.state(db);initialize(db)
        assert curriculum.state(db)==after


def test_cli_dry_run_apply_and_repeat(app,tmp_path):
    path=app.config['DATABASE']
    with app.app_context():legacy(get_db())
    import hashlib
    original=hashlib.sha256(open(path,'rb').read()).hexdigest()
    plan=tmp_path/'plan.json';receipt=tmp_path/'receipt.json'
    args=[sys.executable,str(ROOT/'scripts/reorder_curriculum.py'),'--sqlite',path,'--plan',str(plan)]
    result=subprocess.run(args+['--dry-run'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert hashlib.sha256(open(path,'rb').read()).hexdigest()==original
    assert plan.stat().st_mode&0o777==0o600
    result=subprocess.run(args+['--apply','--receipt',str(receipt)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert receipt.stat().st_mode&0o777==0o600
    db=connect(path)
    try:assert [r[0] for r in db.execute('SELECT id FROM problems ORDER BY learning_order')]==curriculum.order()
    finally:db.close()


def test_old_backup_restores_without_reverting_order(prepared):
    from app.backup import restore
    with prepared.app_context():
        db=get_db();old=export_data();curriculum.apply(db,curriculum.plan(db))
        restore(old)
        assert [p['id'] for p in s.rows()]==curriculum.order()
        assert export_data()['tables']==old['tables']
        # Reconciliation after an intentional older restore remains explicit.
        assert curriculum.plan(db)['schedules']


def test_forward_anchor_and_stale_metadata(prepared):
    with prepared.app_context():
        db=get_db();before=curriculum.state(db)
        curriculum.apply(db,curriculum.plan(db));after=curriculum.state(db)
        from collections import Counter
        changed=[a for a in after['assignments'] if a not in before['assignments']]
        assert changed and all(a['scheduled_date']>='2026-10-20' for a in changed)
        slots=[p['scheduled_date'] for p in s.rows() if not p['first_attempt_at'] and not p['manual_override']]
        assert slots==sorted(slots)
        assert next(p for p in s.rows() if p['id']=='basic-calculator')['manual_override']==1


def test_private_backup_validation(tmp_path,monkeypatch):
    import os,time
    from types import SimpleNamespace
    from scripts.reorder_curriculum import verify_backup
    path=tmp_path/'synthetic.dump';path.write_bytes(b'synthetic archive');path.chmod(0o600)
    listing='; dbname: expected\n1; 0 1 TABLE DATA public problems owner\n2; 0 2 TABLE DATA public progress owner\n'
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=listing))
    assert len(verify_backup(path,'expected',['problems','progress']))==64
    with pytest.raises(ValueError,match='database name'):verify_backup(path,'wrong',['problems'])
    with pytest.raises(ValueError,match='table-data'):verify_backup(path,'expected',['learning_records'])
    os.utime(path,(time.time()-90000,time.time()-90000))
    with pytest.raises(ValueError,match='freshly'):verify_backup(path,'expected',['problems'])


def test_postgres_operator_backup_plan_apply(pg_url,app,tmp_path):
    import os,shutil
    from scripts.migrate_to_postgres import migrate
    from scripts.backup_neon import pg_client_environment
    from scripts.reorder_curriculum import verify_backup
    with app.app_context():legacy(get_db())
    migrate(app.config['DATABASE'],pg_url,mark_authority=False)
    db=connect(pg_url)
    try:lr.migrate(db);tables=curriculum.tables(db)
    finally:db.close()
    archive=tmp_path/'fresh.dump'
    dump=shutil.which('pg_dump') or '/opt/homebrew/opt/postgresql@14/bin/pg_dump'
    env=os.environ.copy();env['PATH']=str(__import__('pathlib').Path(dump).parent)+os.pathsep+env['PATH']
    subprocess.run([dump,'--format=custom','--file',str(archive)],env=pg_client_environment(pg_url),check=True,capture_output=True)
    archive.chmod(0o600)
    env['DATABASE_URL_UNPOOLED']=pg_url
    from urllib.parse import urlsplit
    database=urlsplit(pg_url).path.lstrip('/')
    base=[sys.executable,str(ROOT/'scripts/reorder_curriculum.py'),'--postgres','--expected-host','127.0.0.1','--expected-database',database,'--plan',str(tmp_path/'plan.json')]
    dry=subprocess.run(base+['--dry-run','--backup',str(archive)],env=env,capture_output=True,text=True)
    assert dry.returncode==0,dry.stderr
    assert 'Backup verified:' in dry.stdout
    # No approval flag: must fail before any mutation.
    blocked=subprocess.run(base+['--apply','--receipt',str(tmp_path/'blocked.json'),'--backup',str(archive)],env=env,capture_output=True,text=True)
    assert blocked.returncode!=0 and 'approval' in blocked.stderr
    result=subprocess.run(base+['--apply','--receipt',str(tmp_path/'receipt.json'),'--backup',str(archive),'--acknowledge-production-update'],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert pg_url not in result.stdout+result.stderr
    db=connect(pg_url)
    try:assert [r[0] for r in db.execute('SELECT id FROM problems ORDER BY learning_order')]==curriculum.order()
    finally:db.close()


@pytest.fixture(params=['sqlite','postgresql'])
def unfinished(request,app):
    if request.param=='postgresql':
        from scripts.migrate_to_postgres import migrate
        url=request.getfixturevalue('pg_url');migrate(app.config['DATABASE'],url,mark_authority=False)
        app=create_app(dict(app.config,DATABASE_URL=url))
    app.config['NOW']='2026-10-20T17:00:00+00:00'
    with app.app_context():
        db=get_db();lr.migrate(db);legacy(db)
    return app


def test_fixed_anchor_with_honest_prior_entries(unfinished):
    with unfinished.app_context():
        db=get_db();before=curriculum.state(db);p=curriculum.plan(db)
        assert p['anchor']=='2026-10-20' and p['focus']['eligible_for_anchor'] and p['applicable']
        assert len(p['earlier_unfinished'])==13 and p['eligible_count']==62
        assert [r['id'] for r in p['next_questions'][:6]]==curriculum.order()[13:19]
        assert {r['scheduled_date'] for r in p['next_questions'][:6]}=={'2026-10-20'}
        assert p['next_questions'][6]['scheduled_date']=='2026-10-21'
        curriculum.apply(db,p)
        after=curriculum.state(db)
        for t in before:
            if t not in ('problems','assignments'):assert before[t]==after[t],t
        for row in before['assignments']:
            if row['problem_id'] in curriculum.order()[:13]:assert row in after['assignments']
        assert s.counts(s.rows())['attempted']==0 and s.new_today(s.rows())==0
        assert s.queue(s.rows())[0]['id']=='diameter-of-binary-tree'
        same=curriculum.plan(db);assert same['rows_to_update']==dict(problems=0,assignments=0)
        unfinished.config['NOW']='2026-11-02T17:00:00+00:00'
        assert curriculum.plan(db)==same  # Fixed anchor, never a rolling today.
        curriculum.apply(db,same);assert curriculum.state(db)==after
        initialize(db) if not hasattr(db,'backend') else None
        assert curriculum.plan(db)==same
    config=dict(unfinished.config)
    restarted=create_app(config)
    with restarted.app_context():assert s.queue(s.rows())[0]['id']=='diameter-of-binary-tree'


def test_prior_entries_today_calendar_context_and_catchup(unfinished):
    with unfinished.app_context():
        db=get_db();curriculum.apply(db,curriculum.plan(db))
        prior=[dict(r) for r in db.execute('SELECT * FROM assignments') if r['problem_id'] in curriculum.order()[:13]]
        baseline={r['problem_id']:r['baseline_date'] for r in db.execute('SELECT * FROM assignments')}
    c=unfinished.test_client();html=c.get('/').text
    assert 'id="next-heading">Diameter of Binary Tree' in html and 'Earlier unfinished tracker entries' in html
    context=c.get('/study-context?format=json').json
    assert context['counts']['attempted']==0 and context['new_attempts_today']==0
    assert len(context['earlier_unfinished'])==13 and context['curriculum_focus']['anchor']=='2026-10-20'
    assert [p['learning_order'] for p in context['next_questions']]==list(range(14,20))
    assert context['next_questions'][0]['scheduled_date']=='2026-10-20'
    calendar=c.get('/calendar').text
    assert 'id="day-2026-10-20"' in calendar and 'Original assignments' in calendar
    assert c.get('/problem/diameter-of-binary-tree').status_code==200
    with unfinished.app_context():
        db=get_db();s.catch_up('post-anchor-catchup1',reset=True)
        assert all(dict(db.execute('SELECT * FROM assignments WHERE problem_id=?',(r['problem_id'],)).fetchone())==r for r in prior)
        assert {r['problem_id']:r['baseline_date'] for r in db.execute('SELECT * FROM assignments')}==baseline


def test_preserved_capacity_and_actual_attempt_day(unfinished):
    with unfinished.app_context():
        db=get_db()
        # One actual Chicago Oct20 attempt, two protected future assignments.
        s.set_status('two-sum','attempted',False,'actual-attempt-reserve')
        s.move('balanced-binary-tree','2026-10-20','preserve-manual-reserve')
        with db:db.execute("UPDATE assignments SET scheduled_date='2026-10-20' WHERE problem_id='valid-anagram'")
        plan=curriculum.plan(db)
        assert plan['reserved_capacity']['2026-10-20']==3
        assert plan['focus']['scheduled_date']=='2026-10-20'
        assert [p['id'] for p in plan['resulting_schedule'][:3]]==['diameter-of-binary-tree','lowest-common-ancestor-of-a-binary-search-tree','flood-fill']
        assert plan['resulting_schedule'][3]['scheduled_date']=='2026-10-21'
        before=curriculum.state(db);curriculum.apply(db,plan)
        for a in before['assignments']:
            if a['problem_id'] in ('two-sum','valid-anagram','balanced-binary-tree'):assert a in curriculum.state(db)['assignments']
        assert s.new_today(s.rows())==1


def test_full_anchor_capacity_conflicts(unfinished):
    with unfinished.app_context():
        db=get_db()
        for i,pid in enumerate(curriculum.order()[:6]):s.move(pid,'2026-10-20',f'capacity-protected-{i}')
        p=curriculum.plan(db);assert not p['applicable'] and not p['focus']['eligible_for_anchor']
        assert p['conflicts'] and p['reserved_capacity']['2026-10-20']==6
        before=curriculum.state(db)
        with pytest.raises(ValueError,match='focus conflict'):curriculum.apply(db,p)
        assert curriculum.state(db)==before


@pytest.mark.parametrize('evidence',['attempt','manual','status_history','review_event','review_state','move_history'])
def test_focus_protection_conflicts_and_history_stales(unfinished,evidence):
    with unfinished.app_context():
        db=get_db();prior=curriculum.plan(db);pid='diameter-of-binary-tree'
        with db:
            if evidence=='attempt':db.execute("UPDATE progress SET first_attempt_at='2026-10-19T12:00:00+00:00',status='attempted' WHERE problem_id=?",(pid,))
            elif evidence=='manual':db.execute('UPDATE assignments SET manual_override=1 WHERE problem_id=?',(pid,))
            elif evidence=='status_history':db.execute('INSERT INTO activity_events VALUES(?,?,?,?,?)',('old-status',pid,'status','2026-10-19T12:00:00+00:00',json.dumps(dict(status='attempted'))))
            elif evidence=='move_history':db.execute('INSERT INTO activity_events VALUES(?,?,?,?,?)',('old-move',pid,'move','2026-10-19T12:00:00+00:00','{}'))
            elif evidence=='review_event':db.execute('INSERT INTO review_events VALUES(?,?,?,?,?)',('old-review',pid,'2026-10-19T12:00:00+00:00','independent','private review note'))
            else:db.execute('INSERT INTO review_state VALUES(?,0,?,NULL)',(pid,'2026-10-21'))
        before=curriculum.state(db);current=curriculum.plan(db)
        assert not current['applicable'] and not current['focus']['eligible_for_anchor']
        with pytest.raises(ValueError,match='stale'):curriculum.apply(db,prior)
        with pytest.raises(ValueError,match='focus conflict'):curriculum.apply(db,current)
        assert curriculum.state(db)==before


def test_old_recycling_plan_cannot_apply(unfinished):
    with unfinished.app_context():
        db=get_db();old=dict(curriculum.plan(db),version='personal-curriculum-2026-10-20')
        before=curriculum.state(db)
        with pytest.raises(ValueError,match='stale'):curriculum.apply(db,old)
        assert curriculum.state(db)==before


def test_malformed_status_protected_and_history_capacity(unfinished):
    with unfinished.app_context():
        db=get_db()
        with db:
            db.execute('INSERT INTO activity_events VALUES(?,?,?,?,?)',('missing-status','diameter-of-binary-tree','status','2026-10-20T04:00:00+00:00','{}'))
        assert not curriculum.plan(db)['applicable']
        with db:
            db.execute("DELETE FROM activity_events WHERE id='missing-status'")
            db.execute('INSERT INTO activity_events VALUES(?,?,?,?,?)',('evidenced-attempt','valid-anagram','status','2026-10-21T03:00:00+00:00',json.dumps(dict(old='not_started',status='attempted',independent=False))))
        p=curriculum.plan(db)
        assert p['reserved_capacity']['2026-10-20']==1 #03:00UTC is Chicago Oct20.
        assert 'valid-anagram' in {x['id'] for x in p['exclusions']}
        assert p['focus']['eligible_for_anchor']
        assert len([x for x in p['resulting_schedule'] if x['scheduled_date']=='2026-10-20'])==5


def test_reset_status_history_reserves_without_faking_attempt(unfinished):
    with unfinished.app_context():
        db=get_db()
        with db:db.execute('INSERT INTO activity_events VALUES(?,?,?,?,?)',('historical-reset','valid-anagram','status','2026-10-21T03:00:00+00:00',json.dumps(dict(old='attempted',status='not_started',independent=False))))
        before=curriculum.state(db);p=curriculum.plan(db)
        assert p['reserved_capacity']['2026-10-20']==1
        curriculum.apply(db,p)
        assert curriculum.state(db)['progress']==before['progress']
        assert s.new_today(s.rows())==0 and s.counts(s.rows())['attempted']==0
