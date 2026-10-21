"""Focused browser checks; only a new disposable SQLite app is accepted."""
import json
import re
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app, learning_records as lr, reference_solutions as ref
from app.db import get_db
from app.curriculum import state
from werkzeug.serving import make_server, WSGIRequestHandler
from werkzeug.security import generate_password_hash
from playwright.sync_api import sync_playwright, expect

class Quiet(WSGIRequestHandler):
    def log(self,*args,**kwargs):pass


def main():
    with tempfile.TemporaryDirectory(prefix='grind75-reference-browser-') as directory:
        root=Path(directory)
        app=create_app(dict(TESTING=True,DATABASE_URL=None,DATABASE=str(root/'test.sqlite3'),
            AUTH_REQUIRED=True,SECRET_KEY='synthetic-only-browser-secret-at-least32characters',
            ADMIN_USERNAME='test',ADMIN_PASSWORD_HASH=generate_password_hash('isolated-only-password')))
        code='\nclass Solution:\r\n    # 🧠 <script>window.SOURCE_RAN=1</script>\r\n    def solve(self):\r\n        return 42  \r\n'
        with app.app_context():
            db=get_db();lr.migrate(db);ref.migrate(db)
            with db:db.execute('INSERT INTO learning_records(problem_id,solution_code,updated_at) VALUES(?,?,?)',('two-sum',code,'2026-10-20T12:00:00+00:00'))
            before={t:rows for t,rows in state(db).items() if t in ('progress','assignments','review_events','review_state','problem_notes')}
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}';errors=[]
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch()
                context=browser.new_context(permissions=['clipboard-read','clipboard-write'])
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/login');page.get_by_label('Username',exact=True).fill('test');page.get_by_label('Password',exact=True).fill('isolated-only-password');page.get_by_role('button',name='Sign in',exact=True).click();page.wait_for_url(base+'/')
                for width in (1440,390,320):
                    page.set_viewport_size(dict(width=width,height=900));page.goto(base+'/problem/two-sum')
                    details=page.locator('.solution-disclosure');assert not details.evaluate('(e)=>e.open')
                    details.locator('summary').click();expect(page.locator('#solution-code')).to_be_visible()
                    assert page.locator('#solution-code').input_value()==code.replace('\r\n','\n')
                    assert page.evaluate('window.SOURCE_RAN') is None
                    page.get_by_role('button',name='Copy Code',exact=True).click()
                    assert page.evaluate('navigator.clipboard.readText()')==code
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                    with page.expect_navigation():page.get_by_role('button',name='Save Python solution',exact=True).click()
                    with app.app_context():assert lr.get_record(get_db(),'two-sum')['solution_code']==code
                    details=page.locator('.solution-disclosure');details.locator('summary').click();details.locator('summary').click();assert not details.evaluate('(e)=>e.open')
                # Browser upload and actual download, not simulated HTTP calls.
                records=[dict(problem_id='reverse-linked-list',solution_code=code)]
                batch=dict(format=lr.FORMAT,version=2,records=records)
                path=root/'batch.json';path.write_text(json.dumps(batch,ensure_ascii=False))
                page.goto(base+'/learning-records/import');page.get_by_label('JSON file',exact=True).set_input_files(str(path));page.get_by_role('button',name='Validate and preview',exact=True).click()
                page.get_by_role('button',name='Confirm approved changes',exact=True).click();page.wait_for_url(base+'/learning-records')
                with page.expect_download() as download:page.get_by_role('link',name=re.compile(r'^Export all \d+ saved records$')).click()
                output=root/'download.json';download.value.save_as(str(output))
                exported=json.loads(output.read_text());assert exported['version']==2
                assert next(r for r in exported['records'] if r['problem_id']=='reverse-linked-list')['solution_code']==code
                page.goto(base+'/problem/reverse-linked-list');details=page.locator('.solution-disclosure');details.locator('summary').click()
                page.locator('#solution-code').fill('def solve():\n    return "edited"\n')
                with page.expect_navigation():page.get_by_role('button',name='Save Python solution',exact=True).click()
                with app.app_context():assert lr.get_record(get_db(),'reverse-linked-list')['solution_code']=='def solve():\n    return "edited"\n'
                for route in ('/study-context','/study-context?format=json'):
                    page.goto(base+route);assert 'solution_code' not in page.content() and 'SOURCE_RAN' not in page.content()
                with app.app_context():assert {t:rows for t,rows in state(get_db()).items() if t in before}==before
                assert not errors,errors
                browser.close()
            print('PASS: reference solutions at1440/390/320px; hidden/reveal/hide, exact CRLF copy/save, escaped inert source, manual edit, JSON v2 file upload/download, context privacy, unchanged study state; no JS errors.')
        finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
