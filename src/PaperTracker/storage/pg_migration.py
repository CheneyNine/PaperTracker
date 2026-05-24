"""PostgreSQL schema migration runner.

Applies versioned migrations from the migrations/ sub-package using
psycopg2's implicit transaction model (no explicit BEGIN/COMMIT strings).
Each migration's pg_sql field is used; sql field is the SQLite fallback
only when pg_sql is empty string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PaperTracker.storage.migration import MIGRATIONS, Migration
from PaperTracker.utils.log import log

if TYPE_CHECKING:
    from PaperTracker.storage.pg_db import PgConnection

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
)
"""


def run_pg_migrations(conn: PgConnection) -> None:
    """Apply all pending PostgreSQL migrations.

    psycopg2 operates in autocommit=False mode by default, meaning every
    statement runs inside an implicit transaction. Never send 'BEGIN',
    'COMMIT', or 'ROLLBACK' as SQL strings — use conn.commit() /
    conn.rollback() instead.

    Args:
        conn: PgConnection wrapper around a psycopg2 connection.
    """
    _ensure_version_table(conn)
    current_ver = _get_current_version(conn)
    pending = [m for m in MIGRATIONS if m.version > current_ver]

    if not pending:
        log.debug("PG schema already at version %d, no migrations to run", current_ver)
        return

    for migration in pending:
        _apply_pg_migration(conn, migration)
        log.info("applied PG migration v%d: %s", migration.version, migration.description)


def _ensure_version_table(conn: PgConnection) -> None:
    conn.execute(_SCHEMA_VERSION_DDL)
    conn.commit()


def _get_current_version(conn: PgConnection) -> int:
    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    return row[0] if row else 0


def _apply_pg_migration(conn: PgConnection, migration: Migration) -> None:
    """Execute one migration inside a psycopg2 transaction."""
    sql = migration.pg_sql if migration.pg_sql.strip() else migration.sql
    hook = migration.pg_hook if migration.pg_hook is not None else migration.hook

    try:
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            conn.execute(stmt)
        if hook is not None:
            hook(conn)
        conn.execute(
            "INSERT INTO schema_version (id, version) VALUES (1, ?) "
            "ON CONFLICT (id) DO UPDATE SET version = EXCLUDED.version",
            (migration.version,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
