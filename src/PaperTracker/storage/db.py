"""SQLite database management.

Manages SQLite connection lifecycle and initialization, ensures database files exist, and applies migrations on startup.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from PaperTracker.storage.migration import run_migrations


class DatabaseManager:
    """Shared database connection manager.

    Uses singleton pattern to ensure only one connection is created per database path.
    This avoids connection resource waste, transaction isolation issues, and concurrent
    write conflicts.

    Supports context manager protocol for automatic connection cleanup.
    """

    _instances: dict[tuple[str, int], DatabaseManager] = {}

    def __new__(cls, db_path: Path):
        """Create or return existing DatabaseManager instance.

        The manager is shared per `(database path, thread)` pair. This keeps
        one reusable connection per thread while avoiding SQLite's
        `check_same_thread` violations in background refresh workers.

        Args:
            db_path: Absolute path or project-relative path to database file.

        Returns:
            DatabaseManager instance scoped to the current thread.
        """
        resolved_path = str(db_path.resolve())
        thread_id = threading.get_ident()
        instance_key = (resolved_path, thread_id)

        if instance_key not in cls._instances:
            instance = super().__new__(cls)
            instance.conn = ensure_db(db_path)
            instance._instance_key = instance_key
            instance._db_path = db_path
            run_migrations(instance.conn)
            cls._instances[instance_key] = instance
        return cls._instances[instance_key]

    db_type: str = "sqlite"

    def get_connection(self) -> sqlite3.Connection:
        """Get the shared database connection.

        Returns:
            SQLite connection.
        """
        return self.conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield the per-thread SQLite connection.

        FastAPI runs sync routes in a threadpool. Calling this from a worker
        thread transparently creates (or reuses) a per-thread connection so
        SQLite's thread-safety check is never violated.
        """
        thread_manager: DatabaseManager = type(self)(self._db_path)
        yield thread_manager.conn

    def close(self) -> None:
        """Close the database connection and reset singleton instance.

        This ensures the connection is properly closed and allows creating
        a new instance with a different database path if needed.
        """
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
            type(self)._instances.pop(getattr(self, "_instance_key", None), None)

    def __enter__(self) -> DatabaseManager:
        """Enter context manager.

        Returns:
            Self for use in with statement.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager and close connection.

        Args:
            exc_type: Exception type if an exception occurred.
            exc_val: Exception value if an exception occurred.
            exc_tb: Exception traceback if an exception occurred.
        """
        self.close()


def ensure_db(db_path: Path) -> sqlite3.Connection:
    """Ensure database file exists and return connection.
    
    Args:
        db_path: Absolute path or project-relative path to database file.
        
    Returns:
        SQLite connection.
        
    Raises:
        OSError: If directory creation fails.
        sqlite3.Error: If database connection fails.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    return conn
