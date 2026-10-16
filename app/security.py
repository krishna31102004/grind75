"""Single-user sessions, CSRF, and persistent per-client login throttling."""
import hashlib
import hmac
import secrets
import time
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from urllib.parse import urlsplit
from .db import get_db, is_postgres


auth=Blueprint('auth',__name__)


def fingerprint():
    credentials=current_app.config['ADMIN_USERNAME']+'\0'+(current_app.config['ADMIN_PASSWORD_HASH'] or '')
    return hmac.new(current_app.secret_key.encode(),credentials.encode(),hashlib.sha256).hexdigest()


def signed_in():
    if not current_app.config['AUTH_REQUIRED']:
        return True
    return hmac.compare_digest(session.get('identity',''),fingerprint())


def csrf_value():
    if 'csrf' not in session:
        session['csrf']=secrets.token_hex(24)
    return session['csrf']


def install_security(app):
    @app.before_request
    def enforce_access():
        if request.path.startswith('/share/') and request.method not in ('GET','HEAD','OPTIONS'):
            abort(405)
        public=request.endpoint in ('auth.login','static','context.shared')
        if not public and not signed_in():
            if request.method!='GET': abort(401)
            return redirect(url_for('auth.login'))
        if request.method in ('POST','PUT','PATCH','DELETE'):
            origin=request.headers.get('Origin')
            if origin:
                parsed=urlsplit(origin)
                if parsed.netloc!=request.host or parsed.scheme!=request.scheme: abort(403)
            if not secrets.compare_digest(request.form.get('csrf','').encode(),session.get('csrf','invalid').encode()):
                abort(400,description='Invalid form token; refresh the page and try again.')

    @app.context_processor
    def auth_context():
        return dict(auth_required=app.config['AUTH_REQUIRED'],signed_in=signed_in(),csrf=csrf_value)


@auth.route('/login',methods=['GET','POST'])
def login():
    if not current_app.config['AUTH_REQUIRED'] or signed_in():
        return redirect(url_for('main.today'))
    if request.method=='POST':
        username=request.form.get('username','')
        password=request.form.get('password','')
        # No raw address or password is retained. A DB-backed bucket works across workers.
        key=hmac.new(current_app.secret_key.encode(),(request.remote_addr or 'unknown').encode(),hashlib.sha256).hexdigest()
        db=get_db();epoch=int(time.time())
        with db:
            if not is_postgres(db): db.execute('BEGIN IMMEDIATE')
            bucket=db.execute('SELECT * FROM login_throttle WHERE key=?',(key,)).fetchone()
            failures=bucket['failures'] if bucket and bucket['expires_at']>epoch else 0
            expires=bucket['expires_at'] if bucket and bucket['expires_at']>epoch else epoch+900
            if failures>=8:
                return render_template('login.html',error='Too many attempts. Try again in15 minutes.'),429
            valid_password=False
            if len(password)<=1024:
                try: valid_password=check_password_hash(current_app.config['ADMIN_PASSWORD_HASH'],password)
                except ValueError: pass
            if valid_password and secrets.compare_digest(username.encode(),current_app.config['ADMIN_USERNAME'].encode()):
                db.execute('DELETE FROM login_throttle WHERE key=?',(key,))
                session.clear()
                session.permanent=True
                session['identity']=fingerprint()
                session['csrf']=secrets.token_hex(24)
                return redirect(url_for('main.today'))
            db.execute('INSERT INTO login_throttle VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET failures=excluded.failures,expires_at=excluded.expires_at',(key,failures+1,expires))
            db.execute('DELETE FROM login_throttle WHERE expires_at<?',(epoch,))
        return render_template('login.html',error='Sign-in failed. Check your credentials.'),401
    return render_template('login.html',error=None)


@auth.route('/logout',methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
