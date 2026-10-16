"""Small psycopg adapter for the existing parameterized repository SQL.

Connections are request-scoped; Neon supplies the external connection pool.
All app write transactions take the same advisory lock for single-user consistency.
"""
from contextlib import AbstractContextManager
from urllib.parse import urlsplit
import psycopg
from psycopg.conninfo import conninfo_to_dict

WRITE_LOCK = 75752026


class Record(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def _row(self, row):
        if row is None:
            return None
        return Record(zip([c.name for c in self.cursor.description], row))

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (self._row(row) for row in self.cursor)


class PostgresDB(AbstractContextManager):
    backend = 'postgresql'

    def __init__(self, url):
        options = conninfo_to_dict(url)
        host = options.get('host', '')
        if host not in ('127.0.0.1', 'localhost', '::1'):
            if options.get('sslmode', 'require') not in ('require', 'verify-ca', 'verify-full'):
                raise ValueError('Remote PostgreSQL requires TLS (sslmode=require or stronger).')
            options.setdefault('sslmode', 'require')
        self.connection = psycopg.connect(**options, autocommit=True, connect_timeout=10)
        self._transactions = []

    def execute(self, query, parameters=()):
        query = query.replace('?', '%s')
        if 'INSERT OR IGNORE INTO' in query:
            query = query.replace('INSERT OR IGNORE INTO', 'INSERT INTO').rstrip(';') + ' ON CONFLICT DO NOTHING'
        return Cursor(self.connection.execute(query, parameters))

    def __enter__(self):
        transaction = self.connection.transaction()
        transaction.__enter__()
        self._transactions.append(transaction)
        self.execute('SELECT pg_advisory_xact_lock(?)', (WRITE_LOCK,))
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self._transactions.pop().__exit__(exc_type, exc, traceback)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()
