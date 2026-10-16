import hashlib
import os
import secrets
from datetime import timedelta
from pathlib import Path
from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix
from .db import initialize, connect, close_db


def create_app(config=None):
    root = Path(__file__).resolve().parents[1]
    deployed = os.environ.get('VERCEL') == '1' or os.environ.get('APP_ENV') == 'production'
    if not deployed and not (config or {}).get('TESTING'):
        from dotenv import load_dotenv
        load_dotenv(root / '.env.local', override=False)
    deployed = os.environ.get('VERCEL') == '1' or os.environ.get('APP_ENV') == 'production'
    app = Flask(__name__, instance_path=str(root/'instance'), static_folder=str(root/'public/static'))
    app.config.update(
        DATABASE=os.environ.get('TRACKER_DATABASE', str(root/'instance/tracker.sqlite3')),
        DATABASE_URL=os.environ.get('DATABASE_URL'),
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        ADMIN_USERNAME=os.environ.get('ADMIN_USERNAME', 'admin'),
        ADMIN_PASSWORD_HASH=os.environ.get('ADMIN_PASSWORD_HASH'),
        PRODUCTION=deployed,
        MAX_CONTENT_LENGTH=4*1024*1024,
        SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=deployed, PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        TRUSTED_HOSTS=['127.0.0.1','localhost'], DEBUG=False,
    )
    if config:
        app.config.update(config)
        if config.get('TESTING') and 'DATABASE' in config and 'DATABASE_URL' not in config:
            app.config['DATABASE_URL']=None
    app.config['PRODUCTION'] = deployed or app.config['PRODUCTION']
    cloud = bool(app.config['DATABASE_URL'])
    if app.config['PRODUCTION'] and not cloud:
        raise RuntimeError('DATABASE_URL is required on Vercel/production; SQLite fallback is disabled.')
    if cloud and not app.config['DATABASE_URL'].startswith(('postgresql://','postgres://')):
        raise RuntimeError('DATABASE_URL must use PostgreSQL.')
    auth_required = app.config['PRODUCTION'] or cloud or bool(app.config['ADMIN_PASSWORD_HASH'])
    if app.testing and config and 'AUTH_REQUIRED' in config:
        auth_required = config['AUTH_REQUIRED']
    app.config['AUTH_REQUIRED'] = auth_required
    if auth_required:
        if not app.secret_key or len(app.secret_key)<32:
            raise RuntimeError('SECRET_KEY must contain at least32 characters; generate it with setup_admin.py.')
        password_hash=app.config['ADMIN_PASSWORD_HASH'] or ''
        if not password_hash.startswith(('scrypt:','pbkdf2:sha256:')) or len(password_hash.split('$'))!=3:
            raise RuntimeError('ADMIN_PASSWORD_HASH must be a Werkzeug scrypt/PBKDF2 hash; run setup_admin.py.')
    if app.config['PRODUCTION']:
        hosts = os.environ.get('TRUSTED_HOSTS','').split(',')
        hosts += [os.environ.get(k,'') for k in ('VERCEL_URL','VERCEL_PROJECT_PRODUCTION_URL','VERCEL_BRANCH_URL')]
        app.config['TRUSTED_HOSTS'] = sorted({h.strip() for h in hosts if h.strip()}) or app.config['TRUSTED_HOSTS']
        app.config['SESSION_COOKIE_SECURE'] = True
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
    if not cloud:
        path=Path(app.config['DATABASE'])
        marker=path.parent/'cloud-authority.json'
        if marker.exists() and not app.testing:
            import json
            if json.loads(marker.read_text()).get('source_name')==path.name:
                raise RuntimeError('Cloud progress is authoritative. Set DATABASE_URL in .env.local; use a different TRACKER_DATABASE for isolated offline development.')
        path.parent.mkdir(parents=True,exist_ok=True)
        if not app.secret_key:
            keypath=path.parent/'.session-key'
            if not keypath.exists():
                try:
                    with keypath.open('x') as f: f.write(secrets.token_hex(32))
                    keypath.chmod(0o600)
                except FileExistsError:
                    pass
            app.secret_key=keypath.read_text()
        db=connect(path)
        try: initialize(db)
        finally: db.close()
        path.chmod(0o600)
    # PostgreSQL startup deliberately performs no DDL, seeding, or filesystem writes.
    app.teardown_appcontext(close_db)
    from .routes import bp
    from .security import auth, install_security
    from .study_context import context_bp
    app.register_blueprint(bp)
    app.register_blueprint(auth)
    app.register_blueprint(context_bp)
    install_security(app)
    import psycopg
    @app.errorhandler(psycopg.Error)
    @app.errorhandler(RuntimeError)
    def unavailable(error):
        app.logger.error('Database unavailable (%s)', type(error).__name__)
        return render_template('unavailable.html'),503
    return app
