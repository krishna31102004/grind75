"""Executable browser acceptance tests. Always creates its own disposable app/data.

Run with a Python environment containing Flask, project dependencies and Playwright.
No production URL or database option is accepted. Screenshots contain synthetic data.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, services as s
from app.db import get_db
from app.learning_records import FIELDS, FORMAT, migrate
from werkzeug.security import generate_password_hash
from werkzeug.serving import WSGIRequestHandler, make_server
from playwright.sync_api import sync_playwright, expect


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def content(prefix, field):
    value=f'\n{prefix} / {field}\n\nUnicode 🧠 café 漢字 & <tags>.  \n```python\nfor i in range(n):\n    print(i)\n```\n'
    return value*12+'\nTrailing spaces stay.  '


def save_personal(page):
    with page.expect_navigation(wait_until='networkidle'):
        page.get_by_role('button',name='Save personal record',exact=True).click()
    expect(page.get_by_text('Personal learning record saved.',exact=True)).to_be_visible()
    expect(page.get_by_role('button',name='Save personal record',exact=True)).to_be_enabled()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots',default='docs/screenshots/redesign')
    args=parser.parse_args();out=Path(args.screenshots);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='grind75-ui-') as temporary:
        scratch=Path(temporary)
        app=create_app(dict(TESTING=True,DATABASE=str(scratch/'ui.sqlite3'),DATABASE_URL=None,AUTH_REQUIRED=True,ADMIN_USERNAME='browser-test',ADMIN_PASSWORD_HASH=generate_password_hash('isolated-browser-password'),SECRET_KEY='synthetic-browser-test-key-at-least32characters',NOW='2026-10-19T17:00:00+00:00'))
        with app.app_context():migrate(get_db())
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        checks=[];errors=[]
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/login');page.wait_for_load_state('networkidle')
                page.keyboard.press('Tab');assert page.locator('.skip').evaluate('(e)=>e===document.activeElement')
                page.get_by_label('Username',exact=True).fill('browser-test');page.get_by_label('Password',exact=True).fill('isolated-browser-password');page.get_by_role('button',name='Sign in',exact=True).click();page.wait_for_url(base+'/')
                expect(page.get_by_role('link',name='Start studying')).to_be_visible()
                assert page.locator('.focus-problem').inner_text().count('Two Sum')==1
                page.get_by_role('link',name='Start studying').click()
                assert 'value-to-index map' not in page.content()
                assert page.get_by_role('link',name='Open LeetCode',exact=False).get_attribute('href')=='https://leetcode.com/problems/two-sum/'
                page.locator('form[action$="/status"] select').select_option('attempted');page.get_by_role('button',name='Save status',exact=True).click();page.wait_for_load_state('networkidle')
                assert 'value-to-index map' in page.content()
                page.locator('textarea[name=approach]').fill('Synthetic attempt notes 🧠');page.locator('textarea[name=takeaway]').fill('Check duplicates.');page.get_by_role('button',name='Save notes',exact=True).click();page.wait_for_load_state('networkidle')
                page.locator('form[action$="/status"] select').select_option('understood');page.get_by_role('button',name='Save status',exact=True).click();page.wait_for_load_state('networkidle')
                with app.app_context():assert s.counts(s.rows())['mastered']==0
                page.locator('form[action$="/review"] select').select_option('independent');page.get_by_role('button',name='Record review',exact=True).click();page.wait_for_load_state('networkidle')
                with app.app_context():assert s.counts(s.rows())['mastered']==1
                checks.append('login/keyboard/Today/LeetCode/spoiler/notes/status/mastery/review')
                ids=['two-sum','valid-anagram','ransom-note','contains-duplicate','valid-palindrome','binary-search']
                original={'format':FORMAT,'version':1,'records':[{'problem_id':pid,**{key:content(pid,key) for key in FIELDS}} for pid in ids]}
                # Include literal CRLF to verify unchanged manual saves keep their
                # original representation instead of browser form normalization.
                original['records'][0]['brute_force']='\r\nCRLF original\r\n  spaces stay  \r\n'+original['records'][0]['brute_force']
                batchfile=scratch/'synthetic-batch.json';batchfile.write_text(json.dumps(original,ensure_ascii=False))
                page.goto(base+'/learning-records/import');page.get_by_label('JSON file',exact=True).set_input_files(str(batchfile));page.get_by_role('button',name='Validate and preview',exact=True).click();page.wait_for_load_state('networkidle')
                assert '54' in page.locator('.change-stats').inner_text()
                page.get_by_role('button',name='Expand full comparisons',exact=True).click()
                incoming=page.locator('[data-incoming]').all_text_contents()
                expected=[r[f].replace('\r\n','\n') for r in original['records'] for f in FIELDS]
                assert incoming==expected
                with app.app_context():assert get_db().execute('SELECT COUNT(*) FROM learning_records').fetchone()[0]==0
                page.get_by_role('button',name='Confirm approved changes',exact=True).click();page.wait_for_url(base+'/learning-records')
                exported=context.request.get(base+'/learning-records/export').json()
                assert sorted(exported['records'],key=lambda r:r['problem_id'])==sorted(original['records'],key=lambda r:r['problem_id'])
                page.goto(base+'/problem/two-sum')
                record_form=page.locator('form[data-exact-record]')
                for key in FIELDS:
                    expected_value=original['records'][0][key].replace('\r\n','\n')
                    assert record_form.locator(f'textarea[name={key}]').input_value()==expected_value
                save_personal(page)
                assert context.request.get(base+'/learning-records/export?problem_id=two-sum').json()['records']==[original['records'][0]]
                for detail in record_form.locator('details').all():
                    if not detail.evaluate('(e)=>e.open'):detail.locator('summary').click()
                edited={f:content('manual',f) for f in FIELDS}
                for key,value in edited.items():page.locator(f'textarea[name={key}]').fill(value)
                held=[];dialogs=[]
                page.route('**/problem/two-sum/learning-record',lambda route:held.append(route))
                page.get_by_role('button',name='Save personal record',exact=True).click()
                expect(page.get_by_role('button',name='Saving…',exact=True)).to_be_disabled()
                def dismiss_pending(dialog):
                    dialogs.append(dialog.type);dialog.dismiss()
                page.once('dialog',dismiss_pending)
                page.get_by_role('link',name='Today',exact=True).click(no_wait_after=True)
                page.wait_for_timeout(100)
                assert dialogs==['beforeunload'] and '/problem/two-sum' in page.url
                assert held
                held[0].abort()
                expect(page.locator('[data-save-state]')).to_contain_text('Could not save')
                page.unroute('**/problem/two-sum/learning-record')
                page.route('**/problem/two-sum/learning-record',lambda route:route.abort())
                page.get_by_role('button',name='Save personal record',exact=True).click()
                expect(page.locator('[data-save-state]')).to_contain_text('Could not save')
                assert page.locator('textarea[name=mistakes]').input_value()==edited['mistakes']
                expect(page.get_by_role('button',name='Save personal record',exact=True)).to_be_enabled()
                page.unroute('**/problem/two-sum/learning-record')
                save_personal(page)
                original['records'][0]={'problem_id':'two-sum',**edited}
                assert context.request.get(base+'/learning-records/export?problem_id=two-sum').json()['records']==[original['records'][0]]
                # The server counts Python characters; emoji must not be clipped by
                # HTML maxlength's UTF-16-unit interpretation.
                for detail in page.locator('form[data-exact-record] details').all():
                    if not detail.evaluate('(e)=>e.open'):detail.locator('summary').click()
                page.locator('textarea[name=mistakes]').fill('🧠'*8000)
                assert page.locator('textarea[name=mistakes]').evaluate('(e)=>e.checkValidity()')
                save_personal(page)
                original['records'][0]['mistakes']='🧠'*8000
                assert context.request.get(base+'/learning-records/export?problem_id=two-sum').json()['records'][0]['mistakes']=='🧠'*8000
                checks.append('six-record file upload;54 full fields;preview/confirm/export;manual exact strings/CRLF/8000Unicode/pending-navigation guard/failed-save retention')
                replacement={'format':FORMAT,'version':1,'records':[{'problem_id':pid,**{key:content('incoming '+pid,key) for key in FIELDS}} for pid in ids]}
                page.goto(base+'/learning-records/import');page.locator('textarea[name=json]').fill(json.dumps(replacement,ensure_ascii=False));page.get_by_role('button',name='Validate and preview',exact=True).click();page.wait_for_load_state('networkidle')
                assert page.locator('input[name^="replace_"]:checked').count()==0
                assert page.locator('.conflict-field').count()==54
                page.screenshot(path=str(out/'after-preview-desktop.png'),full_page=True)
                page.get_by_role('button',name='Expand full comparisons',exact=True).click()
                existing=page.locator('[data-existing]').all_text_contents();incoming=page.locator('[data-incoming]').all_text_contents()
                assert existing==[r[f].replace('\r\n','\n') for r in original['records'] for f in FIELDS]
                assert incoming==[r[f] for r in replacement['records'] for f in FIELDS]
                for el in page.locator('.record-text').all():
                    assert el.evaluate('(e)=>e.scrollHeight<=e.clientHeight+2')
                page.set_viewport_size({'width':390,'height':844});page.locator('.conflict-field').first.scroll_into_view_if_needed();page.screenshot(path=str(out/'after-full-conflict-mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth')
                page.get_by_label('Skip Binary Search',exact=True).check()
                for field in ['mistakes','corrections']:page.locator(f'input[name=replace_two-sum][value={field}]').check()
                expect(page.locator('#decision-summary')).to_contain_text('5 problems included')
                expect(page.locator('#decision-summary')).to_contain_text('2 replacements approved')
                page.get_by_role('button',name='Confirm approved changes',exact=True).click();page.wait_for_url(base+'/learning-records')
                for field in ['mistakes','corrections']:original['records'][0][field]=replacement['records'][0][field]
                assert context.request.get(base+'/learning-records/export').json()['records']==sorted(original['records'],key=lambda r:r['problem_id'])
                checks.append('six-record paste/54full conflicts/defaultkeep/explicitreplace/skip/live decision summary')
                page.get_by_role('button',name='Select visible records',exact=True).click();expect(page.locator('#selection-count')).to_have_text('6 saved records selected')
                page.get_by_role('button',name='Clear selection',exact=True).click();expect(page.locator('#selection-count')).to_have_text('0 saved records selected')
                for pid in ['two-sum','valid-anagram']:page.locator(f'input[name=problem_id][value="{pid}"]').check()
                with page.expect_download() as download:page.get_by_role('button',name='Export selected records',exact=True).click()
                selected=json.loads(Path(download.value.path()).read_text());assert {r['problem_id'] for r in selected['records']}=={'two-sum','valid-anagram'}
                with page.expect_download() as download:page.get_by_role('link',name='Export all 6 saved records',exact=True).click()
                assert json.loads(Path(download.value.path()).read_text())['records']==sorted(original['records'],key=lambda r:r['problem_id'])
                page.goto(base+'/learning-records/import');page.locator('textarea[name=json]').fill('invalid JSON');page.get_by_role('button',name='Validate and preview',exact=True).click();expect(page.locator('textarea[name=json]')).to_have_value('invalid JSON')
                page.goto(base+'/review/two-sum');assert not page.get_by_text(original['records'][0]['corrections'],exact=True).is_visible();page.get_by_text('Reveal my previous mistakes and corrections',exact=True).click();expect(page.get_by_text(original['records'][0]['corrections'],exact=True)).to_be_visible()
                page.goto(base+'/problem/valid-anagram');page.locator('#history>summary').click();page.locator('form[action$="/move"] input[type=date]').fill('2026-10-22');page.get_by_role('button',name='Move assignment',exact=True).click();page.wait_for_load_state('networkidle')
                page.goto(base+'/calendar');page.locator('#catch-up>summary').click();page.get_by_role('button',name='Reschedule unfinished questions',exact=True).click();page.wait_for_load_state('networkidle')
                with app.app_context():
                    row=get_db().execute("SELECT scheduled_date,baseline_date FROM assignments WHERE problem_id='valid-anagram'").fetchone();assert row[0]=='2026-10-22' and row[1]=='2026-10-15'
                checks.append('selected/all JSON downloads;invalid paste retention;recall reveal;manual move/catch-up preserve baseline')
                page.goto(base+'/study-context');page.get_by_role('button',name='Enable sharing & generate link',exact=True).click();page.wait_for_load_state('networkidle');share=page.get_by_label('Read-only sharing URL',exact=True).input_value()
                anon=browser.new_context(java_script_enabled=False);anonpage=anon.new_page();anonpage.goto(share)
                assert anonpage.locator('form').count()==0 and original['records'][0]['mistakes'] not in anonpage.content()
                sharedata=anon.request.get(share+'?format=json').json();assert 'learning_records' not in sharedata
                page.get_by_role('button',name='Revoke sharing',exact=True).click();page.wait_for_load_state('networkidle');assert anon.request.get(share).status==404
                assert anon.request.get(base+'/learning-records').url.endswith('/login?next=/learning-records') or '/login' in anon.request.get(base+'/learning-records').url
                anon.close()
                page.goto(base+'/backup');backup=context.request.get(base+'/export').json();backupfile=scratch/'backup.json';backupfile.write_text(json.dumps(backup))
                page.locator('input[name=backup]').set_input_files(str(backupfile));page.locator('input[name=confirm]').fill('WRONG');page.get_by_role('button',name='Validate & restore',exact=True).click();expect(page.get_by_text('Import rejected: Type REPLACE to confirm replacement of current progress.',exact=True)).to_be_visible()
                page.locator('input[name=backup]').set_input_files(str(backupfile));page.locator('input[name=confirm]').fill('REPLACE');page.get_by_role('button',name='Validate & restore',exact=True).click();page.wait_for_load_state('networkidle');expect(page.get_by_text('Restored successfully.',exact=False)).to_be_visible()
                assert context.request.get(base+'/export').json()['tables']==backup['tables']
                checks.append('no-JS shared privacy/read-only;revocation;anonymous auth;actual backup upload/REPLACE/restore')
                paths={'today':'/','problem':'/problem/two-sum','library':'/learning-records','import':'/learning-records/import','recall':'/review/two-sum','concepts':'/concepts','concept':'/concepts/arrays','cheatsheets':'/cheatsheets','review':'/review','calendar':'/calendar','progress':'/progress','context':'/study-context','backup':'/backup'}
                overflow=[];contrast=[]
                for theme in ['light','dark']:
                    page.goto(base+'/');current=page.locator('html').get_attribute('data-theme')
                    if current!=theme:page.get_by_role('button',name='Toggle light and dark mode',exact=True).click()
                    page.reload();assert page.locator('html').get_attribute('data-theme')==theme
                    colors=page.evaluate("Object.fromEntries(['--text','--muted','--accent','--good','--error','--warm','--bg','--surface','--control-line'].map(k=>[k,getComputedStyle(document.documentElement).getPropertyValue(k).trim()]))")
                    def luminance(hex_value):
                        h=hex_value.lstrip('#');h=''.join(c*2 for c in h) if len(h)==3 else h
                        values=[int(h[i:i+2],16)/255 for i in (0,2,4)]
                        values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
                        return sum(a*b for a,b in zip(values,[.2126,.7152,.0722]))
                    for foreground in ['--text','--muted','--accent','--good','--error','--warm','--control-line']:
                        for background in ['--bg','--surface']:
                            a,b=sorted([luminance(colors[foreground]),luminance(colors[background])])
                            ratio=(b+.05)/(a+.05);minimum=3 if foreground=='--control-line' else 4.5
                            assert ratio>=minimum,(theme,foreground,background,ratio)
                            contrast.append(round(ratio,2))

                    for width in [1440,1024,768,390,320]:
                        page.set_viewport_size({'width':width,'height':1000 if width>650 else 844})
                        for name,path in paths.items():
                            page.goto(base+path);page.wait_for_load_state('networkidle')
                            dimensions=page.evaluate('({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})')
                            if dimensions['scroll']>dimensions['client']:overflow.append([theme,width,path,dimensions])
                            if width<=1000:
                                assert not page.locator('.nav-disclosure').evaluate('(e)=>e.open')
                            if width in [1440,390] and name in ['today','problem','library','concepts','progress','calendar','import','recall']:
                                page.screenshot(path=str(out/f'after-{name}-{theme}-{width}.png'),full_page=True)

                assert not overflow,overflow
                page.set_viewport_size({'width':320,'height':844});page.goto(base+'/');page.locator('.nav-disclosure>summary').click();expect(page.get_by_role('navigation',name='Main navigation')).to_be_visible();page.get_by_role('link',name='My Learning Records',exact=True).click();expect(page.get_by_role('heading',name='My Learning Records',exact=True)).to_be_visible()
                page.get_by_role('button',name='Sign out',exact=True).click();page.wait_for_url('**/login');page.screenshot(path=str(out/'after-login-mobile.png'),full_page=True)
                assert not errors,errors
                checks.append('130 route/theme/viewport combinations;zero document overflow;mobile menu;theme persistence;reduced-motion;28 contrast checks;logout;zero JS errors')
                browser.close()
                print(json.dumps({'checks':checks,'viewport_widths':[1440,1024,768,390,320],'themes':['light','dark'],'route_layout_checks':130,'js_errors':errors,'overflow':overflow,'minimum_text_and_control_contrast':min(contrast),'screenshots':str(out),'isolation':'fresh TemporaryDirectory SQLite, explicit DATABASE_URL=None, own loopback server'},indent=2))
        finally:
            server.shutdown();thread.join(timeout=5)


if __name__=='__main__':main()
