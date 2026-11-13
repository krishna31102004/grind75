"""Playwright walkthrough for the v2 curriculum using disposable synthetic data only."""
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.db import get_db
from app.learning_records import migrate as migrate_records
from app.reference_solutions import migrate as migrate_solutions
from app.curriculum_migration import apply, prepare
from werkzeug.serving import WSGIRequestHandler, make_server
from playwright.sync_api import sync_playwright, expect


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def main():
    out=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/grind75-curriculum-after')
    out.mkdir(parents=True,exist_ok=True)
    errors=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='grind75-curriculum-ui-') as tmp:
        app=create_app({'TESTING':True,'DATABASE':str(Path(tmp)/'ui.sqlite3'),'DATABASE_URL':None,'AUTH_REQUIRED':False,
            'SECRET_KEY':'curriculum-browser-test-key-32chars-minimum','NOW':'2026-11-12T17:00:00+00:00'})
        with app.app_context():
            db=get_db();migrate_records(db);migrate_solutions(db);plan=prepare(db,'2026-11-12');apply(db,plan)
            db.execute("INSERT INTO learning_records(problem_id,solution_code,updated_at) VALUES(?,?,?)",('valid-anagram','class Solution:\r\n    def isAnagram(self, s, t):\r\n        return sorted(s) == sorted(t)\r\n','2026-11-12T00:00:00+00:00'));db.commit()
            db.execute("INSERT INTO learning_records(problem_id,recognition_clue,brute_force,updated_at) VALUES(?,?,?,?)",('two-sum','Store the needed complement.','A\r\n  exact indentation\r\n','2026-11-12T00:00:00+00:00'));db.commit()
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                context.grant_permissions(['clipboard-read','clipboard-write'])
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/');expect(page.get_by_role('heading',name='Basic hashing')).to_be_visible()
                expect(page.get_by_text('0 / 5 attempted')).to_be_visible()
                expect(page.get_by_role('link',name='Continue studying')).to_be_visible()
                page.screenshot(path=str(out/'today-day1-desktop.png'),full_page=True)
                checks.append('Today: active topic, 0/5 count, next question, short day list')
                page.goto(base+'/plan');expect(page.get_by_role('heading',name='Your study plan')).to_be_visible()
                assert page.locator('.plan-flex').count()==6
                assert page.locator('.plan-day').count()==15
                checks.append('Plan: exactly 15 active days and six flexible days')
                # An actual Yellow attempt counts once and does not become mastery.
                page.goto(base+'/problem/two-sum');expect(page.get_by_role('heading',name='Two Sum')).to_be_visible()
                assert 'value-to-index map' not in page.content()
                # Editing one field must preserve untouched source text byte-for-byte.
                record=page.locator('details.problem-disclosure').filter(has_text='Detailed learning record')
                record.locator('summary').click()
                record.locator('textarea[name=optimized_reasoning]').fill('Use a complement map.')
                record.get_by_role('button',name='Save detailed record').click();page.wait_for_load_state('networkidle')
                with app.app_context():
                    saved=get_db().execute("SELECT brute_force,optimized_reasoning FROM learning_records WHERE problem_id='two-sum'").fetchone()
                    assert tuple(saved)==('A\r\n  exact indentation\r\n','Use a complement map.')
                form=page.locator('form[action$="/assessment"]').first
                form.locator('select[name=assessment]').select_option('yellow')
                form.locator('textarea[name=takeaway]').fill('Keep the needed complement in a map.')
                form.get_by_role('button',name='Save assessment').click();page.wait_for_load_state('networkidle')
                assert 'value-to-index map' in page.content()
                with app.app_context():
                    db=get_db();assert db.execute("SELECT status,mastered FROM progress WHERE problem_id='two-sum'").fetchone()[:]==('not_started',0)
                    assert db.execute("SELECT count(*) FROM assessment_events WHERE problem_id='two-sum' AND assessment='yellow'").fetchone()[0]==1
                checks.append('Problem: spoiler hidden then unlocked after attempt; untouched CRLF learning text survives edits; Yellow leaves legacy mastery unchanged')
                # Fill the remaining four attempts; no auto replacement or auto-advance.
                with app.app_context():
                    db=get_db();ids=[r['problem_id'] for r in __import__('app.plans',fromlist=['entries_for_day']).entries_for_day(1,db)]
                for i,pid in enumerate(ids[1:]):
                    page.goto(base+'/problem/'+pid);f=page.locator('form[action$="/assessment"]').first;f.locator('select[name=assessment]').select_option('red');f.get_by_role('button',name='Save assessment').click();page.wait_for_load_state('networkidle')
                page.goto(base+'/');expect(page.get_by_text('5 / 5 attempted')).to_be_visible();expect(page.get_by_role('button',name='Advance to Day 2')).to_be_visible()
                page.screenshot(path=str(out/'today-complete-desktop.png'),full_page=True)
                page.get_by_role('button',name='Advance to Day 2').click();page.wait_for_load_state('networkidle');expect(page.get_by_role('heading',name='Strings and arrays')).to_be_visible()
                checks.append('First-pass workflow: five honest attempts, explicit next-day advance')
                # Private reference disclosure stays collapsed and code is copied literally.
                page.goto(base+'/problem/valid-anagram');details=page.locator('#reference-solution');assert not details.evaluate('(e)=>e.open')
                details.locator('summary').click();expect(page.locator('#python-reference-code')).to_be_visible()
                page.get_by_role('button',name='Copy Code').click();assert page.evaluate('navigator.clipboard.readText()')=='class Solution:\r\n    def isAnagram(self, s, t):\r\n        return sorted(s) == sorted(t)\r\n'
                checks.append('Python solution: private, collapsed by default, copy preserves source')
                # Routes and static learning workflows.
                for path in ['/review','/library','/concepts','/cheatsheets','/learning-records','/learning-records/import','/calendar','/progress','/study-context','/backup','/study-context?format=json']:
                    response=context.request.get(base+path);assert response.status==200,(path,response.status)
                page.goto(base+'/concepts/arrays');expect(page.get_by_role('heading',name='Arrays & Hashing')).to_be_visible()
                page.goto(base+'/review/two-sum');expect(page.get_by_role('heading',name='Two Sum')).to_be_visible();expect(page.get_by_role('heading',name='How did recall go?')).to_be_visible()
                page.goto(base+'/review');assert page.locator('a[href="/review/two-sum"]').count()==1
                page.goto(base+'/learning-records/import');page.locator('textarea[name=json]').fill(json.dumps({'format':'grind75-learning-records','version':2,'records':[{'problem_id':'two-sum','solution_code':'def solve():\n    return 1'}]}));page.get_by_role('button',name='Validate and preview').click();page.wait_for_load_state('networkidle');expect(page.get_by_role('heading',name='Review import preview')).to_be_visible();page.screenshot(path=str(out/'learning-import-preview.png'),full_page=True)
                checks.append('Concept detail, personalized review, and import preview render with synthetic data')
                page.goto(base+'/');page.locator('.more-menu > summary').click();assert page.locator('.more-menu').evaluate('(e)=>e.open')
                data=context.request.get(base+'/study-context?format=json').json();assert data['daily_target']==5 and data['curriculum_focus']['current_active_day']==2
                assert 'return sorted(s) == sorted(t)' not in json.dumps(data)
                checks.append('Review/library/concepts/cheatsheets/records/import/calendar/progress/context/backup routes')
                # Responsive widths and both themes, with no horizontal overflow.
                for width in (1440,768,390,320):
                    page.set_viewport_size({'width':width,'height':900})
                    for theme in ('dark','light'):
                        page.goto(base+'/');page.locator('#theme').click() if page.locator('html').get_attribute('data-theme')!=theme else None
                        assert page.locator('html').get_attribute('data-theme')==theme
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),(width,theme)
                        if width==320:
                            for path in ('/library','/concepts','/learning-records'):
                                page.goto(base+path)
                                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),(path,width,theme,page.evaluate('document.documentElement.scrollWidth'))
                        if width in (1440,390) and theme=='dark':page.screenshot(path=str(out/f'today-day2-{width}.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':900});page.goto(base+'/plan?day=8')
                expect(page.get_by_text('Day 8 · Active session 6/15 · Week 2')).to_be_visible()
                checks.append('Review: weak Yellow opens recall context; Plan labels calendar day separately from active-session index; Library tabs fit at 320px in both themes')
                assert not errors,errors
                checks.append('1440/768/390/320 widths × light/dark: no overflow or JS page errors')
                browser.close()
        finally:server.shutdown();thread.join(timeout=3);server.server_close()
    print(json.dumps({'checks':checks,'screenshots':str(out),'page_errors':errors},indent=2))


if __name__=='__main__':main()
