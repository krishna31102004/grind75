import json
from pathlib import Path

import pytest

from app import plans
from app.curriculum_migration import apply, prepare
from app.db import get_db
from app.learning_records import migrate as migrate_records
from app.reference_solutions import migrate as migrate_solutions


EXPECTED_DAYS = [
    ['two-sum','valid-anagram','contains-duplicate','ransom-note','group-anagrams'],
    ['longest-palindrome','majority-element','add-binary','string-to-integer-atoi','product-of-array-except-self'],
    ['maximum-subarray','sort-colors','subarray-sum-equals-k','valid-palindrome','best-time-to-buy-and-sell-stock'],
    ['3sum','longest-substring-without-repeating-characters','longest-repeating-character-replacement','container-with-most-water','find-all-anagrams-in-a-string'],
    ['minimum-window-substring','trapping-rain-water','valid-parentheses','implement-queue-using-stacks','min-stack'],
    [], [],
    ['evaluate-reverse-polish-notation','daily-temperatures','binary-search','first-bad-version','search-a-2d-matrix'],
    ['search-in-rotated-sorted-array','time-based-key-value-store','merge-two-sorted-lists','reverse-linked-list','middle-of-the-linked-list'],
    ['linked-list-cycle','remove-nth-node-from-end-of-list','merge-k-sorted-lists','lru-cache','merge-intervals'],
    ['insert-interval','task-scheduler','maximum-depth-of-binary-tree','invert-binary-tree','diameter-of-binary-tree'],
    ['balanced-binary-tree','lowest-common-ancestor-of-a-binary-search-tree','validate-binary-search-tree','binary-tree-level-order-traversal','lowest-common-ancestor-of-a-binary-tree'],
    [], [],
    ['kth-smallest-element-in-a-bst','binary-tree-right-side-view','construct-binary-tree-from-preorder-and-inorder-traversal','serialize-and-deserialize-binary-tree','flood-fill'],
    ['number-of-islands','rotting-oranges','clone-graph','course-schedule','accounts-merge'],
    ['word-ladder','k-closest-points-to-origin','find-median-from-data-stream','subsets','permutations'],
    ['combination-sum','word-search','climbing-stairs','house-robber','coin-change'],
    ['unique-paths','word-break','partition-equal-subset-sum','longest-palindromic-substring','implement-trie-prefix-tree'],
    [], [],
]
ARCHIVED = {
    '01-matrix', 'letter-combinations-of-a-phone-number', 'largest-rectangle-in-histogram',
    'spiral-matrix', 'basic-calculator', 'minimum-height-trees', 'maximum-profit-in-job-scheduling',
}


@pytest.fixture
def migrated_app(app):
    with app.app_context():
        db = get_db()
        migrate_records(db)
        migrate_solutions(db)
        yield app


def digest_rows(db, query):
    return [dict(row) for row in db.execute(query)]


def test_exact_75_question_15_active_day_schedule_and_replacements():
    curriculum = plans.load()
    assert len(curriculum['days']) == 21
    assert [day['problems'] and [item['problem_id'] for item in day['problems']] or [] for day in curriculum['days']] == EXPECTED_DAYS
    assert [day['day'] for day in curriculum['days'] if day['kind'] == 'flexible'] == [6,7,13,14,20,21]
    active = [item for day in curriculum['days'] for item in day['problems']]
    assert len(active) == len({item['problem_id'] for item in active}) == 75
    assert {item['tracker_number'] for item in active} == set(range(1,76))
    assert len(curriculum['archived_ids']) == 7 and curriculum['archived_ids'] == ARCHIVED
    assert len(curriculum['catalog']) == 82
    additions = json.loads((Path(__file__).parents[1] / 'data/curriculum_v2_additions.json').read_text())
    assert len(additions) == 7
    assert all(row['learning_order'] is None and row['grind_rank'] is None for row in additions)
    assert not any(row['id'] == 'network-delay-time' for row in curriculum['catalog'].values())


def test_added_problem_metadata_and_original_inventory_are_preserved():
    root = Path(__file__).parents[1]
    old = json.loads((root / 'data/grind75.json').read_text())
    additions = json.loads((root / 'data/curriculum_v2_additions.json').read_text())
    assert len(old) == 75
    assert [p['id'] for p in old] == [p['id'] for p in json.loads((root / 'data/grind75.json').read_text())]
    expected = {
        'group-anagrams': ('Group Anagrams','Medium','arrays'),
        'subarray-sum-equals-k': ('Subarray Sum Equals K','Medium','arrays'),
        'longest-repeating-character-replacement': ('Longest Repeating Character Replacement','Medium','sliding-window'),
        'daily-temperatures': ('Daily Temperatures','Medium','stack'),
        'search-a-2d-matrix': ('Search a 2D Matrix','Medium','binary-search'),
        'remove-nth-node-from-end-of-list': ('Remove Nth Node From End of List','Medium','linked-list'),
        'house-robber': ('House Robber','Medium','dp'),
    }
    assert {p['id']:(p['title'],p['difficulty'],p['primary_concept_id']) for p in additions} == expected
    guides = json.loads((root / 'data/problem_guides_v2_additions.json').read_text())
    assert set(guides) == set(expected)
    for guide in guides.values():
        assert all(guide[k].strip() for k in ('clue','baseline','bottleneck','optimal','complexity','edge','takeaway'))


def test_migration_is_additive_and_preserves_all_existing_user_rows(migrated_app):
    with migrated_app.app_context():
        db = get_db()
        # Seed representative historical state, exact text, mastery, review, events and a solution.
        db.execute("UPDATE progress SET status='understood',first_attempt_at='2026-01-02T03:04:05+00:00',first_understood_at='2026-01-03T03:04:05+00:00',mastered=1 WHERE problem_id='two-sum'")
        db.execute("UPDATE assignments SET scheduled_date='2026-02-03',manual_override=1 WHERE problem_id='two-sum'")
        db.execute("UPDATE problem_notes SET takeaway=?,approach='kept',confidence=4,effort=17 WHERE problem_id='two-sum'", ('old note 🧠\r\nwith exact text  ',))
        db.execute("INSERT INTO learning_records(problem_id,brute_force,optimized_reasoning,solution_code,updated_at) VALUES(?,?,?,?,?)", ('two-sum','brute 🧠\r\n  exact','optimized','def solve():\n    return 1\n','2026-02-03T04:05:06+00:00'))
        db.execute("INSERT INTO review_state VALUES('two-sum',2,'2026-02-10','independent')")
        db.execute("INSERT INTO review_events VALUES('rev1','two-sum','2026-02-03T04:05:06+00:00','independent','review note')")
        db.execute("INSERT INTO activity_events VALUES('evt1','two-sum','status','2026-01-02T03:04:05+00:00',?)", ('{"old":"not_started","status":"understood","independent":true}',))
        db.commit()
        before = {table:digest_rows(db, f'SELECT * FROM {table} ORDER BY 1') for table in ('problems','assignments','progress','problem_notes','activity_events','review_state','review_events','learning_records','concept_notes','submissions')}
        plan = prepare(db, '2026-11-12')
        assert plan['prior_problem_ids'] == sorted(row['id'] for row in json.loads((Path(__file__).parents[1]/'data/grind75.json').read_text()))
        assert not plan['already_applied']
        result = apply(db, plan)
        assert 'Existing rows unchanged' in result['verification']
        after = {table:digest_rows(db, f'SELECT * FROM {table} ORDER BY 1') for table in before}
        for table in before:
            if table == 'problems':
                assert before[table] == [r for r in after[table] if r['id'] not in {p['id'] for p in json.loads((Path(__file__).parents[1]/'data/curriculum_v2_additions.json').read_text())}]
            elif table == 'assignments':
                assert before[table] == [r for r in after[table] if r['problem_id'] not in {p['id'] for p in json.loads((Path(__file__).parents[1]/'data/curriculum_v2_additions.json').read_text())}]
            elif table in ('progress','problem_notes'):
                assert before[table] == [r for r in after[table] if r['problem_id'] not in {p['id'] for p in json.loads((Path(__file__).parents[1]/'data/curriculum_v2_additions.json').read_text())}]
            else:
                assert before[table] == after[table]
        assert db.execute("SELECT value FROM settings WHERE key='daily_target'").fetchone()[0] == '5'
        assert db.execute("SELECT value FROM settings WHERE key='active_study_day'").fetchone()[0] == '1'
        assert db.execute("SELECT value FROM settings WHERE key='active_plan_version'").fetchone()[0] == plans.VERSION
        assert db.execute("SELECT count(*) FROM assessment_events").fetchone()[0] == 0
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('SELECT count(*) FROM curriculum_entries').fetchone()[0] == 75
        assert db.execute('SELECT count(*) FROM curriculum_archive').fetchone()[0] == 7
        assert db.execute('SELECT count(*) FROM curriculum_days').fetchone()[0] == 21
        record = db.execute("SELECT brute_force,optimized_reasoning,solution_code,updated_at FROM learning_records WHERE problem_id='two-sum'").fetchone()
        assert tuple(record) == ('brute 🧠\r\n  exact','optimized','def solve():\n    return 1\n','2026-02-03T04:05:06+00:00')
        assert db.execute("SELECT first_attempt_at,first_understood_at,mastered FROM progress WHERE problem_id='two-sum'").fetchone()[:] == ('2026-01-02T03:04:05+00:00','2026-01-03T03:04:05+00:00',1)
        assert tuple(db.execute("SELECT baseline_date,scheduled_date,manual_override FROM assignments WHERE problem_id='two-sum'").fetchone()) == ('2026-10-15','2026-02-03',1)
        assert db.execute("SELECT next_due_date,stage FROM review_state WHERE problem_id='two-sum'").fetchone()[:] == ('2026-02-10',2)
        # This old timestamp is real lifetime history, but migration does not
        # fabricate a v2 first-pass assessment or complete a new plan day.
        day_one=plans.entries_for_day(1,db)
        two_sum=next(row for row in day_one if row['problem_id']=='two-sum')
        assert two_sum['first_attempt_at']=='2026-01-02T03:04:05+00:00'
        assert not two_sum['curriculum_attempted'] and not plans.day_complete(1,db)


def test_migration_dry_run_is_read_only_stale_plan_rejected_and_repeat_is_idempotent(migrated_app):
    with migrated_app.app_context():
        db = get_db()
        migrate_plan = prepare(db,'2026-11-12')
        assert db.execute("SELECT count(*) FROM problems").fetchone()[0] == 75
        db.execute("UPDATE problem_notes SET takeaway='changed after plan' WHERE problem_id='two-sum'")
        db.commit()
        with pytest.raises(ValueError, match='stale or changed'):
            apply(db, migrate_plan)
        refreshed = prepare(db,'2026-11-12')
        apply(db, refreshed)
        assert apply(db, refreshed)['verification'].startswith('Migration5 was already applied')
        assert db.execute("SELECT count(*) FROM problems").fetchone()[0] == 82


@pytest.fixture
def applied_app(migrated_app):
    with migrated_app.app_context():
        db=get_db();plan=prepare(db,'2026-11-12');apply(db,plan)
    return migrated_app


def test_today_plan_and_restart_use_explicit_active_day(applied_app):
    from app import create_app
    from app.db import get_db
    client=applied_app.test_client()
    page=client.get('/').get_data(as_text=True)
    assert 'Basic hashing' in page and '/ 5 attempted' in page
    assert '#1' in page and 'Two Sum' in page and 'Group Anagrams' in page
    assert client.get('/plan').status_code==200
    assert 'Flexible day 6' in client.get('/plan').get_data(as_text=True)
    # Advance the clock by a week: active position remains explicitly Day 1.
    applied_app.config['NOW']='2026-11-20T18:00:00+00:00'
    assert 'Basic hashing' in client.get('/').get_data(as_text=True)
    with applied_app.app_context(): assert get_db().execute("SELECT value FROM settings WHERE key='active_study_day'").fetchone()[0]=='1'
    restarted=create_app({'TESTING':True,'DATABASE_URL':None,'AUTH_REQUIRED':False,'SECRET_KEY':'isolated-test-session-key-long-enough',
        'DATABASE':applied_app.config['DATABASE'],'NOW':'2026-11-20T18:00:00+00:00'})
    assert 'Basic hashing' in restarted.test_client().get('/').get_data(as_text=True)


def test_assessments_require_green_attestation_and_do_not_rewrite_legacy_mastery(applied_app):
    from app import services as service
    from app.db import get_db
    with applied_app.app_context():
        db=get_db();db.execute("UPDATE progress SET status='understood',mastered=1,first_attempt_at='2026-01-01T00:00:00+00:00',first_understood_at='2026-01-02T00:00:00+00:00' WHERE problem_id='two-sum'");db.commit()
        with pytest.raises(ValueError,match='Green requires confirmation'):
            service.assessment('two-sum','green',False,'','assessment-token-0001')
        service.assessment('two-sum','yellow',False,'needed hint','assessment-token-0002')
        row=db.execute("SELECT status,mastered,first_attempt_at,first_understood_at FROM progress WHERE problem_id='two-sum'").fetchone()
        assert tuple(row)==('understood',1,'2026-01-01T00:00:00+00:00','2026-01-02T00:00:00+00:00')
        assert tuple(db.execute("SELECT assessment,green_attested,takeaway FROM assessment_events WHERE problem_id='two-sum'").fetchone())==('yellow',0,'needed hint')
        assert db.execute("SELECT next_due_date FROM review_state WHERE problem_id='two-sum'").fetchone()[0]=='2026-10-16'


def test_browser_assessment_requires_attestation_and_explicit_day_advance(applied_app):
    from app import services as service
    from app.db import get_db
    client=applied_app.test_client();page=client.get('/problem/two-sum').get_data(as_text=True)
    assert 'name="green_attested"' in page
    with client.session_transaction() as session:csrf=session['csrf']
    response=client.post('/problem/two-sum/assessment',data={'csrf':csrf,'token':'assessment-form-token-0001','assessment':'green','takeaway':'','context':'first_pass'})
    assert response.status_code==302
    with applied_app.app_context():assert get_db().execute("SELECT first_attempt_at FROM progress WHERE problem_id='two-sum'").fetchone()[0] is None
    client.post('/problem/two-sum/assessment',data={'csrf':csrf,'token':'assessment-form-token-0002','assessment':'green','green_attested':'yes','takeaway':'','context':'first_pass'})
    with applied_app.app_context():assert get_db().execute("SELECT assessment FROM assessment_events WHERE problem_id='two-sum'").fetchone()[0]=='green'
    # Red assessments count as truthful first attempts, never as mastery.
    with applied_app.app_context():
        ids=[r['problem_id'] for r in plans.entries_for_day(1)]
        for i,pid in enumerate(ids[1:],3):service.assessment(pid,'red',False,'','attempt-token-%04d'%i)
    with applied_app.app_context():
        assert service.counts(service.rows())['attempted']==5
        assert service.counts(service.rows())['mastered']==1
    before=None
    with applied_app.app_context():before=tuple(get_db().execute("SELECT first_attempt_at,mastered FROM progress WHERE problem_id='two-sum'").fetchone())
    client.post('/plan/advance',data={'csrf':csrf,'token':'advance-active-day-token-01'})
    assert 'Strings and arrays' in client.get('/').get_data(as_text=True)
    with applied_app.app_context():
        assert get_db().execute("SELECT value FROM settings WHERE key='active_study_day'").fetchone()[0]=='2'
        assert tuple(get_db().execute("SELECT first_attempt_at,mastered FROM progress WHERE problem_id='two-sum'").fetchone())==before


def test_today_library_progress_calendar_and_problem_reflect_new_curriculum(applied_app):
    client=applied_app.test_client()
    assert client.get('/library').status_code==200
    assert client.get('/progress').status_code==200
    assert client.get('/calendar').status_code==200
    for number,title in [(14,'Diameter of Binary Tree'),(15,'Balanced Binary Tree'),(16,'Lowest Common Ancestor of a Binary Search Tree'),(57,'Implement Trie'),(60,'LRU Cache')]:
        pid=next(e['problem_id'] for e in plans.load()['entries'] if e['tracker_number']==number)
        page=client.get('/problem/'+pid).get_data(as_text=True)
        assert f'#{number}' in page and title in page
    archived=client.get('/problem/01-matrix')
    assert archived.status_code==200 and 'Archived' in archived.text


def test_v2_study_context_shares_only_public_curriculum_facts(applied_app):
    from app.db import get_db
    with applied_app.app_context():
        db=get_db();db.execute("INSERT INTO learning_records(problem_id,brute_force,solution_code,updated_at) VALUES(?,?,?,?)",('two-sum','PRIVATE_RECORD_SENTINEL','PRIVATE_SOLUTION_SENTINEL','2026-11-12T00:00:00+00:00'));db.commit()
    data=applied_app.test_client().get('/study-context?format=json').get_json();encoded=json.dumps(data)
    assert data['daily_target']==5 and data['curriculum_focus']['current_active_day']==1
    assert 'PRIVATE_RECORD_SENTINEL' not in encoded and 'PRIVATE_SOLUTION_SENTINEL' not in encoded
    page=applied_app.test_client().get('/study-context').get_data(as_text=True)
    assert 'Active Day 1' in page and 'PRIVATE_SOLUTION_SENTINEL' not in page


def test_version4_backup_roundtrip_and_legacy_restore_preserve_new_problem_rows(applied_app):
    import copy
    from app.backup import export_data,restore,validate
    from app.db import get_db
    with applied_app.app_context():
        db=get_db();db.execute("INSERT INTO learning_records(problem_id,brute_force,solution_code,updated_at) VALUES(?,?,?,?)",('group-anagrams','exact note','def f():\r\n    return 3\n','2026-11-12T00:00:00+00:00'));db.commit()
        v4=export_data()
        assert v4['version']==4 and 'curriculum_entries' in v4['tables'] and 'assessment_events' in v4['tables']
        validate(v4)
        original=tuple(db.execute("SELECT brute_force,solution_code FROM learning_records WHERE problem_id='group-anagrams'").fetchone())
        db.execute("UPDATE learning_records SET solution_code='changed' WHERE problem_id='group-anagrams'");db.commit()
        restore(v4)
        assert tuple(db.execute("SELECT brute_force,solution_code FROM learning_records WHERE problem_id='group-anagrams'").fetchone())==original
        assert db.execute('SELECT count(*) FROM curriculum_entries').fetchone()[0]==75
        assert db.execute("SELECT value FROM settings WHERE key='active_study_day'").fetchone()[0]=='1'

        legacy=copy.deepcopy(v4);legacy['version']=3;legacy['tables']={k:legacy['tables'][k] for k in ('assignments','progress','problem_notes','concept_notes','activity_events','review_state','review_events','submissions','learning_records')}
        added={p['id'] for p in json.loads((Path(__file__).parents[1]/'data/curriculum_v2_additions.json').read_text())}
        for table in ('assignments','progress','problem_notes','review_state','learning_records'):
            legacy['tables'][table]=[r for r in legacy['tables'][table] if r['problem_id'] not in added]
        for table in ('activity_events','review_events'):
            legacy['tables'][table]=[r for r in legacy['tables'][table] if r['problem_id'] is None or r['problem_id'] not in added]
        validate(legacy)
        restore(legacy,acknowledge_legacy_solution_loss=True)
        assert db.execute('SELECT count(*) FROM assignments').fetchone()[0]==82
        assert db.execute('SELECT count(*) FROM progress').fetchone()[0]==82
        assert db.execute("SELECT value FROM settings WHERE key='active_study_day'").fetchone()[0]=='1'


def test_legacy_backup_refuses_to_detach_current_assessment_history(applied_app):
    import copy
    from app import services
    from app.backup import export_data,restore
    from app.db import get_db
    with applied_app.app_context():
        db=get_db();legacy=copy.deepcopy(export_data())
        legacy['version']=3
        legacy['tables']={k:legacy['tables'][k] for k in ('assignments','progress','problem_notes','concept_notes','activity_events','review_state','review_events','submissions','learning_records')}
        ids={r[0] for r in db.execute('SELECT problem_id FROM assignments')}
        added={p['id'] for p in json.loads((Path(__file__).parents[1]/'data/curriculum_v2_additions.json').read_text())}
        for table in ('assignments','progress','problem_notes','review_state','learning_records'):
            legacy['tables'][table]=[r for r in legacy['tables'][table] if r['problem_id'] not in added]
        for table in ('activity_events','review_events'):
            legacy['tables'][table]=[r for r in legacy['tables'][table] if r['problem_id'] is None or r['problem_id'] not in added]
        services.assessment('two-sum','green',True,'still current','backup-guard-green-0001')
        before=(db.execute("SELECT first_attempt_at FROM progress WHERE problem_id='two-sum'").fetchone()[0],db.execute("SELECT count(*) FROM assessment_events").fetchone()[0])
        with pytest.raises(ValueError,match='predates curriculum assessments'):
            restore(legacy,acknowledge_legacy_solution_loss=True)
        after=(db.execute("SELECT first_attempt_at FROM progress WHERE problem_id='two-sum'").fetchone()[0],db.execute("SELECT count(*) FROM assessment_events").fetchone()[0])
        assert before==after and ids=={r[0] for r in db.execute('SELECT problem_id FROM assignments')}



def test_v4_backup_validates_assessments_plan_advance_order_and_active_day(applied_app):
    from app import services
    from app.backup import export_data,validate
    from app.db import get_db
    with applied_app.app_context():
        day=plans.entries_for_day(1)
        for index,row in enumerate(day):services.assessment(row['problem_id'],'green' if index==0 else 'red',index==0,'',f'backup-test-attempt-{index:04d}')
        services.advance_active_day('backup-test-advance-0001')
        payload=export_data();validate(payload)
        corrupted=json.loads(json.dumps(payload))
        corrupted['tables']['curriculum_entries'][0]['problem_id'],corrupted['tables']['curriculum_entries'][1]['problem_id']=corrupted['tables']['curriculum_entries'][1]['problem_id'],corrupted['tables']['curriculum_entries'][0]['problem_id']
        with pytest.raises(ValueError,match='curriculum order'):validate(corrupted)
        corrupted=json.loads(json.dumps(payload));event=dict(corrupted['tables']['assessment_events'][0]);event.update(id='bad-green',assessment='green',green_attested=0);corrupted['tables']['assessment_events'].append(event)
        with pytest.raises(ValueError,match='attestation'):validate(corrupted)
        corrupted=json.loads(json.dumps(payload));event=dict(corrupted['tables']['assessment_events'][0]);event.update(id='bad-yellow-attestation',assessment='red',green_attested=1);corrupted['tables']['assessment_events'].append(event)
        with pytest.raises(ValueError,match='Only Green'):validate(corrupted)
        with pytest.raises(Exception):
            get_db().execute("INSERT INTO assessment_events(id,problem_id,assessment,green_attested,takeaway,at,context) VALUES('bad-db-attestation','two-sum','red',1,'','2026-11-12T00:00:00+00:00','first_pass')")
        get_db().rollback()
        corrupted=json.loads(json.dumps(payload));setting=next(r for r in corrupted['tables']['settings'] if r['key']=='active_study_day');setting['value']='6'
        with pytest.raises(ValueError,match='active day'):validate(corrupted)
        assert get_db().execute("SELECT value FROM settings WHERE key='active_study_day'").fetchone()[0]=='2'


def test_migration_rejects_dates_outside_backup_supported_range(migrated_app):
    from app.curriculum_migration import prepare
    with migrated_app.app_context(),pytest.raises(ValueError,match='2020 and 2100'):
        prepare(get_db(),'0001-01-01')
