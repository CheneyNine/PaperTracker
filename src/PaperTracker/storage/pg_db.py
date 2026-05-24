"""PostgreSQL connection pool manager.

Provides PostgresManager and PgConnection, which mirror the interface of
DatabaseManager and sqlite3.Connection so existing store code can use
'with db_manager.connection() as conn:' without backend-specific branches.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator


class PgConnection:
    """Wraps a psycopg2 connection, translating ? → %s parameter placeholders."""

    db_type: str = "postgres"

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Any = ()) -> Any:
        cursor = self._conn.cursor()
        cursor.execute(self._sql(sql), params)
        return cursor

    def executemany(self, sql: str, params_seq: Any) -> None:
        cursor = self._conn.cursor()
        cursor.executemany(self._sql(sql), params_seq)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class PostgresManager:
    """PostgreSQL connection pool manager.

    Uses psycopg2 ThreadedConnectionPool. Connections are borrowed per
    operation via the connection() context manager and returned on exit.
    """

    db_type: str = "postgres"

    def __init__(self, database_url: str) -> None:
        from psycopg2 import pool as _pg_pool  # type: ignore[import]

        self._pool = _pg_pool.ThreadedConnectionPool(2, 10, dsn=database_url)

    def get_connection(self) -> PgConnection:
        """Borrow a connection from the pool without automatic return.

        Prefer connection() context manager for normal use. Only call
        get_connection() when you must hold the connection across multiple
        call frames (and ensure putconn() is called manually).
        """
        return PgConnection(self._pool.getconn())

    @contextmanager
    def connection(self) -> Generator[PgConnection, None, None]:
        """Borrow a connection from the pool, returning it on block exit."""
        raw = self._pool.getconn()
        pg_conn = PgConnection(raw)
        try:
            yield pg_conn
        except Exception:
            raw.rollback()
            raise
        finally:
            self._pool.putconn(raw)

    def close(self) -> None:
        self._pool.closeall()

    def __enter__(self) -> PostgresManager:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
