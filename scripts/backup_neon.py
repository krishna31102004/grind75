#!/usr/bin/env python3
"""Create and inspect a private custom-format PostgreSQL backup.

The direct Neon URL is loaded from DATABASE_URL_UNPOOLED, parsed into libpq's
PG* child-environment variables, and never passed as a process argument.
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from migrate_learning_records import PreflightFailure, direct_database_url, inspect_postgres

LIBPQ_ENV = {
    'host': 'PGHOST', 'hostaddr': 'PGHOSTADDR', 'port': 'PGPORT', 'dbname': 'PGDATABASE',
    'user': 'PGUSER', 'password': 'PGPASSWORD', 'sslmode': 'PGSSLMODE',
    'sslrootcert': 'PGSSLROOTCERT', 'sslcert': 'PGSSLCERT', 'sslkey': 'PGSSLKEY',
    'sslpassword': 'PGSSLPASSWORD', 'options': 'PGOPTIONS', 'application_name': 'PGAPPNAME',
    'connect_timeout': 'PGCONNECT_TIMEOUT', 'target_session_attrs': 'PGTARGETSESSIONATTRS',
    'channel_binding': 'PGCHANNELBINDING',
}


def pg_client_environment(url):
    """Map parsed URL fields to libpq environment variables, never argv."""
    environment = os.environ.copy()
    for name in set(LIBPQ_ENV.values()) | {'PGSERVICE', 'PGSERVICEFILE'}:
        environment.pop(name, None)
    environment.pop('DATABASE_URL', None)
    environment.pop('DATABASE_URL_UNPOOLED', None)
    for key, value in conninfo_to_dict(url).items():
        env_name = LIBPQ_ENV.get(key)
        if env_name and value:
            environment[env_name] = value
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', help='Optional private dotenv file; values are never printed.')
    parser.add_argument('--directory', default=str(Path.home() / 'private-db-backups'), help='Private backup directory (default: ~/private-db-backups).')
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    try:
        url, options = direct_database_url()
        inspect_postgres(url, options)
    except PreflightFailure as exc:
        raise SystemExit(f'Preflight failed [{exc.category}]: {exc}') from None
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Could not read direct database configuration; details omitted.'
        raise SystemExit(message) from None

    dump = shutil.which('pg_dump')
    restore = shutil.which('pg_restore')
    if not dump or not restore:
        raise SystemExit('Install PostgreSQL client tools (pg_dump and pg_restore) before creating the backup.')
    directory = Path(args.directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    output = directory / ('grind75-neon-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.dump')
    if output.exists():
        raise SystemExit('Refusing to overwrite an existing backup file.')

    environment = pg_client_environment(url)
    try:
        subprocess.run([dump, '--format=custom', f'--file={output}'], env=environment, check=True)
        output.chmod(0o600)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError('pg_dump created an empty backup.')
        listing = subprocess.run([restore, '--list', str(output)], env=environment, capture_output=True, text=True, check=True)
        entries = [line for line in listing.stdout.splitlines() if line and not line.startswith(';')]
        if not entries:
            raise RuntimeError('The backup archive contains no restorable entries.')
    except Exception as exc:
        output.unlink(missing_ok=True)
        if isinstance(exc, subprocess.CalledProcessError):
            raise SystemExit('Backup or archive-list verification failed; connection details omitted and partial file removed.') from None
        raise SystemExit(str(exc)) from None
    print(f'Backup created and archive listing verified: {output}')
    print(f'Bytes: {output.stat().st_size}; TOC entries: {len(entries)}; file mode: {output.stat().st_mode & 0o777:04o}')
    print('This verifies archive readability; a full restore test into an isolated PostgreSQL database is the stronger recovery check.')


if __name__ == '__main__':
    main()
