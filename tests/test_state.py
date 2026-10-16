import json
import sqlite3
from datetime import date
import pytest
from app.db import get_db,ROOT
from app import services as s

PID='two-sum'
def tok(n):return f'test-action-token-{n}'
def item():return next(p for p in s.rows() if p['id']==PID)


def test_guides_complete():
    guides=json.loads((ROOT/'data/problem_guides.json').read_text());seed=json.loads((ROOT/'data/grind75.json').read_text())
    assert set(guides)=={p['id'] for p in seed}
    for key in ['clue','baseline','bottleneck','optimal','complexity','edge','takeaway']:
        if key != 'complexity': assert len({g[key] for g in guides.values()})==75
        for g in guides.values():assert len(g[key])>(15 if key=='complexity' else 25) and 'TODO' not in g[key]


def test_separate_progress_and_lapse(app):
    with app.app_context():
        s.set_status(PID,'hints',False,tok(1));p=item();assert p['first_attempt_at'] and not p['mastered'] and not p['first_understood_at']
        first=p['first_attempt_at']
        s.set_status(PID,'understood',True,tok(2));understood=item()['first_understood_at']
        assert s.counts(s.rows())['understood']==1 and s.counts(s.rows())['mastered']==1
        s.set_status(PID,'needs_review',False,tok(3));p=item()
        assert p['first_attempt_at']==first and p['first_understood_at']==understood
        assert s.counts(s.rows())==dict(attempted=1,understood=0,mastered=0,needs_review=1,ever_understood=1)
        s.set_status(PID,'not_started',False,tok(4))
        assert s.counts(s.rows())['attempted']==1 and s.new_today(s.rows())==1


def test_concept_counts(app):
    with app.app_context():
        s.set_status(PID,'understood',False,tok(1))
        arrays=[p for p in s.rows() if p['concept_id']=='arrays']
        assert s.counts(arrays)['attempted']==s.counts(arrays)['understood']==1
        assert s.counts(arrays)['mastered']==0


@pytest.mark.parametrize('status,independent',[('bad',False),('attempted',True),(None,False)])
def test_invalid_status_rollback(app,status,independent):
    with app.app_context():
        with pytest.raises(ValueError):s.set_status(PID,status,independent,tok(1))
        assert not item()['first_attempt_at']
        assert get_db().execute('SELECT count(*) FROM submissions').fetchone()[0]==0


def test_review_intervals_idempotency(app):
    with app.app_context():
        s.set_status(PID,'understood',False,tok(1))
        assert item()['next_due_date']=='2026-10-16'
        s.set_status(PID,'understood',False,tok(2))
        assert get_db().execute('SELECT count(*) FROM review_state').fetchone()[0]==1
        app.config['NOW']='2026-10-18T17:00:00+00:00'
        s.review(PID,'independent','transfer',tok(3));s.review(PID,'independent','transfer',tok(3))
        assert item()['next_due_date']=='2026-10-21' and item()['stage']==1
        assert get_db().execute('SELECT count(*) FROM review_events').fetchone()[0]==1
        app.config['NOW']='2026-10-22T17:00:00+00:00';s.review(PID,'independent','',tok(4))
        assert item()['next_due_date']=='2026-10-29' and item()['stage']==2
        app.config['NOW']='2026-10-30T17:00:00+00:00';s.review(PID,'independent','',tok(5))
        assert item()['next_due_date'] is None and item()['stage']==3
        assert s.counts(s.rows())['attempted']==1
        assert s.new_today(s.rows())==0
        s.set_status(PID,'understood',False,tok(6));assert item()['next_due_date'] is None


@pytest.mark.parametrize('result',['hints','failed'])
def test_review_retry_no_mastery(app,result):
    with app.app_context():
        s.set_status(PID,'understood',True,tok(1));s.review(PID,result,'',tok(2))
        assert item()['next_due_date']=='2026-10-16' and item()['mastered']==0 and item()['stage']==0
        assert item()['status']=='needs_review'
        assert s.counts(s.rows())['attempted']==1


def test_review_cannot_create_attempt(app):
    with app.app_context():
        with pytest.raises(ValueError):s.review(PID,'independent','',tok(1))
        assert not item()['first_attempt_at']
        assert not get_db().execute('SELECT * FROM review_events').fetchall()
        assert not get_db().execute('SELECT * FROM submissions').fetchall()


def test_review_success_not_auto_understood(app):
    with app.app_context():
        s.set_status(PID,'attempted',False,tok(1));s.review(PID,'independent','',tok(2))
        assert item()['mastered']==1 and item()['status']=='attempted' and not item()['first_understood_at']


def test_status_double_post(app):
    with app.app_context():
        s.set_status(PID,'attempted',False,tok(1));s.set_status(PID,'attempted',False,tok(1))
        assert get_db().execute('SELECT count(*) FROM activity_events').fetchone()[0]==1


def test_schedule_catchup_deterministic_manual_history(app):
    with app.app_context():
        baseline={p['id']:p['baseline_date'] for p in s.rows()}
        s.set_status(PID,'attempted',False,tok(1));attempt=item()['first_attempt_at']
        s.move('valid-anagram','2026-10-25',tok(2))
        app.config['NOW']='2026-10-20T17:00:00+00:00'
        assert len(s.queue(s.rows()))>6
        s.catch_up(tok(3));first=[(p['id'],p['scheduled_date']) for p in s.rows()]
        s.catch_up(tok(4));assert first==[(p['id'],p['scheduled_date']) for p in s.rows()]
        assert {p['id']:p['baseline_date'] for p in s.rows()}==baseline
        assert item()['first_attempt_at']==attempt and item()['scheduled_date']=='2026-10-15'
        p=next(p for p in s.rows() if p['id']=='valid-anagram');assert p['scheduled_date']=='2026-10-25' and p['manual_override']==1
        auto=[p for p in s.rows() if not p['first_attempt_at'] and not p['manual_override']]
        assert [p['scheduled_date'] for p in auto]==sorted(p['scheduled_date'] for p in auto)
        assert len(s.rows())==75 and get_db().execute('SELECT count(*) FROM activity_events').fetchone()[0]==4
        with pytest.raises(sqlite3.IntegrityError):get_db().execute("UPDATE assignments SET baseline_date='2026-10-30' WHERE problem_id=?",(PID,))


def test_catchup_reset_manual_explicit(app):
    with app.app_context():
        s.move(PID,'2026-11-08',tok(1));s.catch_up(tok(2),reset=True)
        assert item()['manual_override']==0 and item()['scheduled_date']=='2026-10-15'


def test_work_ahead_and_soft_target(app):
    with app.app_context():
        ahead=next(p for p in s.rows() if p['learning_order']==75)
        s.set_status(ahead['id'],'attempted',False,tok(1))
        assert s.new_today(s.rows())==1
        assert next(p for p in s.rows() if p['id']==ahead['id'])['baseline_date']=='2026-10-27'
        for i,p in enumerate(s.rows()[:7]):s.set_status(p['id'],'attempted',False,tok(i+2))
        assert s.new_today(s.rows())==8 and s.counts(s.rows())['attempted']==8
        assert len(s.rows())==75
        s.catch_up(tok(20));assert not [p for p in s.rows() if not p['first_attempt_at'] and p['scheduled_date']=='2026-10-15']


@pytest.mark.parametrize('now,day,new',[('2026-10-16T04:59:00+00:00','2026-10-15',1),('2026-10-16T05:00:00+00:00','2026-10-16',0)])
def test_chicago_boundary(app,now,day,new):
    with app.app_context():
        s.set_status(PID,'attempted',False,tok(1));app.config['NOW']=now
        assert s.today().isoformat()==day and s.new_today(s.rows())==new


@pytest.mark.parametrize('now,days,average,shortfall',[('2026-10-15T17:00:00+00:00',13,5.77,0),('2026-10-20T17:00:00+00:00',8,9.38,27),('2026-10-28T17:00:00+00:00',0,None,75)])
def test_pace(app,now,days,average,shortfall):
    with app.app_context():
        app.config['NOW']=now;p=s.pace(s.rows(),date(2026,10,27))
        assert (p['days'],p['average'],p['shortfall'])==(days,average,shortfall)
        fallback=s.pace(s.rows(),date(2026,11,1));assert fallback['days']>=p['days']


def test_early_start_preserves_baseline(app):
    with app.app_context():
        app.config['NOW']='2026-10-13T17:00:00+00:00'
        assert not s.queue(s.rows())
        s.set_status(PID,'attempted',False,tok(1))
        assert item()['baseline_date']=='2026-10-15' and s.local_day(item()['first_attempt_at'])=='2026-10-13'
