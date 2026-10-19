import pytest

from scripts.migrate_learning_records import (
    PreflightFailure, client_major, client_tls_active, direct_database_url,
    inspect_postgres, preflight_error_message,
)
from scripts.backup_neon import pg_client_environment
from types import SimpleNamespace


def test_operations_choose_direct_url_not_runtime_pooler(monkeypatch):
    pooled = 'postgresql://app:pooled-secret@ep-demo-pooler.neon.tech/grind75?sslmode=require'
    direct = 'postgresql://ops:direct-secret@ep-demo.neon.tech/grind75?sslmode=verify-full'
    monkeypatch.setenv('DATABASE_URL', pooled)
    monkeypatch.setenv('DATABASE_URL_UNPOOLED', direct)

    actual, options = direct_database_url()

    assert actual == direct
    assert options['host'] == 'ep-demo.neon.tech'
    assert 'pooled-secret' not in repr(options)


def test_operations_refuse_pooler_even_when_set_as_unpooled(monkeypatch):
    monkeypatch.setenv('DATABASE_URL_UNPOOLED', 'postgresql://ops:secret@ep-demo-pooler.neon.tech/grind75?sslmode=require')
    with pytest.raises(ValueError, match='direct Neon endpoint'):
        direct_database_url()


def test_operations_require_tls_for_remote_neon(monkeypatch):
    monkeypatch.setenv('DATABASE_URL_UNPOOLED', 'postgresql://ops:secret@ep-demo.neon.tech/grind75?sslmode=disable')
    with pytest.raises(ValueError, match='require TLS'):
        direct_database_url()


def test_operations_require_explicit_tls_mode_for_remote_neon(monkeypatch):
    monkeypatch.setenv('DATABASE_URL_UNPOOLED', 'postgresql://ops:secret@ep-demo.neon.tech/grind75')
    with pytest.raises(ValueError, match='require TLS'):
        direct_database_url()


def test_operations_fail_without_direct_variable_even_if_runtime_url_exists(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://app:secret@ep-demo-pooler.neon.tech/grind75?sslmode=require')
    monkeypatch.delenv('DATABASE_URL_UNPOOLED', raising=False)
    with pytest.raises(ValueError, match='DATABASE_URL_UNPOOLED'):
        direct_database_url()


@pytest.mark.parametrize('version', [
    'pg_dump (PostgreSQL) 14.19 (Homebrew)',
    'pg_restore (PostgreSQL) 17.4',
])
def test_postgres_tool_version_parser_accepts_platform_suffixes(version):
    assert client_major(version) == int(version.split('(PostgreSQL) ')[1].split('.')[0].split()[0])


def test_postgres_tool_version_parser_rejects_unrecognized_output():
    assert client_major('unexpected pg_dump output') is None


def test_backup_maps_connection_fields_to_libpq_environment_without_url(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://pooled:pool-secret@pool.neon.tech/other?sslmode=require')
    monkeypatch.setenv('DATABASE_URL_UNPOOLED', 'postgresql://ops:direct-secret@ep.neon.tech/grind75?sslmode=verify-full&channel_binding=require')
    url = 'postgresql://ops:direct-secret@ep.neon.tech/grind75?sslmode=verify-full&channel_binding=require'

    environment = pg_client_environment(url)

    assert environment['PGHOST'] == 'ep.neon.tech'
    assert environment['PGDATABASE'] == 'grind75'
    assert environment['PGUSER'] == 'ops'
    assert environment['PGPASSWORD'] == 'direct-secret'
    assert environment['PGSSLMODE'] == 'verify-full'
    assert environment['PGCHANNELBINDING'] == 'require'
    assert 'DATABASE_URL' not in environment
    assert 'DATABASE_URL_UNPOOLED' not in environment


@pytest.mark.parametrize('client_tls', [True, False])
def test_tls_check_uses_client_libpq_status_not_server_view(client_tls):
    db = SimpleNamespace(connection=SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=client_tls)))
    assert client_tls_active(db) is client_tls


def test_preflight_accepts_client_tls_when_neon_backend_view_could_report_false(monkeypatch, capsys):
    class FakeDB:
        connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True))
        closed = False

        def execute(self, query):
            assert 'pg_stat_ssl' not in query
            return SimpleNamespace(fetchone=lambda: {'database': 'grind75', 'server_version': '18.6'})

        def close(self):
            self.closed = True

    db = FakeDB()
    monkeypatch.setattr('scripts.migrate_learning_records.connect', lambda _url: db)
    monkeypatch.setattr('scripts.migrate_learning_records.shutil.which', lambda tool: f'/usr/bin/{tool}')
    versions = iter(['pg_dump (PostgreSQL) 18.6', 'pg_restore (PostgreSQL) 18.6'])
    monkeypatch.setattr('scripts.migrate_learning_records.subprocess.run', lambda *_a, **_k: SimpleNamespace(stdout=next(versions)))

    inspect_postgres('postgresql://redacted', {'host': 'ep-demo.neon.tech', 'sslmode': 'require'})

    assert 'tls=on sslmode=require' in capsys.readouterr().out
    assert db.closed


def test_preflight_tls_failure_has_safe_category_and_redacts_exception(monkeypatch):
    secret = 'synthetic-password-never-print'
    class FakeDB:
        connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=False))
        def execute(self, _query):
            return SimpleNamespace(fetchone=lambda: {'database': 'grind75', 'server_version': '18.6'})
        def close(self):
            pass
    monkeypatch.setattr('scripts.migrate_learning_records.connect', lambda _url: FakeDB())
    with pytest.raises(PreflightFailure) as error:
        inspect_postgres(f'postgresql://user:{secret}@host', {'host': 'ep-demo.neon.tech', 'sslmode': 'require'})
    message = preflight_error_message(error.value)
    assert message.startswith('Preflight failed [tls]:')
    assert secret not in message
