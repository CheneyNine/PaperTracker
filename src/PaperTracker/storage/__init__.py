"""Storage layer for PaperTracker.

Provides database management, deduplication, and content storage
for paper tracking.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PaperTracker.storage.content import PaperContentStore
from PaperTracker.storage.dashboard import DashboardPaperRecord, DashboardStore
from PaperTracker.storage.db import DatabaseManager
from PaperTracker.storage.deduplicate import ReadOnlyDeduplicateStore, SqliteDeduplicateStore
from PaperTracker.storage.llm import LLMGeneratedStore
from PaperTracker.storage.migration import run_migrations
from PaperTracker.utils.log import log

if TYPE_CHECKING:
    from PaperTracker.config import AppConfig


def create_storage(
    config: AppConfig,
) -> tuple[Any, SqliteDeduplicateStore | None, PaperContentStore | None]:
    """Create database manager and storage components.

    Returns (db_manager, dedup_store, content_store). db_manager is a
    DatabaseManager (SQLite) or PostgresManager (PostgreSQL) depending on
    config.storage.backend.
    """
    db_manager = None
    dedup_store = None
    content_store = None

    if not config.storage.enabled:
        return db_manager, dedup_store, content_store

    if config.storage.backend == "postgres":
        db_manager = _create_pg_manager(config)
    else:
        db_path = Path(config.storage.db_path)
        db_manager = DatabaseManager(db_path)
        log.info("SQLite storage enabled: %s", db_path)

    dedup_store = SqliteDeduplicateStore(db_manager)

    if config.storage.content_storage_enabled:
        content_store = PaperContentStore(db_manager)
        log.info("Content storage enabled")

    return db_manager, dedup_store, content_store


def _create_pg_manager(config: AppConfig) -> Any:
    """Create and initialise a PostgresManager, running schema migrations."""
    from PaperTracker.storage.pg_db import PostgresManager
    from PaperTracker.storage.pg_migration import run_pg_migrations

    database_url = config.storage.database_url
    if not database_url:
        raise ValueError(
            "storage.database_url must be set when storage.backend = 'postgres'. "
            "Example: postgresql://user:pass@localhost:5432/papertracker"
        )

    manager = PostgresManager(database_url)
    log.info("PostgreSQL storage enabled")

    with manager.connection() as conn:
        run_pg_migrations(conn)

    return manager


def create_llm_store(
    db_manager: Any,
    config: AppConfig,
) -> LLMGeneratedStore | None:
    """Create LLM generated store from config."""
    if not config.llm.enabled or not config.storage.content_storage_enabled:
        return None

    return LLMGeneratedStore(
        db_manager=db_manager,
        provider=config.llm.provider,
        model=config.llm.model,
    )


__all__ = [
    "DatabaseManager",
    "SqliteDeduplicateStore",
    "ReadOnlyDeduplicateStore",
    "PaperContentStore",
    "DashboardPaperRecord",
    "DashboardStore",
    "LLMGeneratedStore",
    "run_migrations",
    "create_storage",
    "create_llm_store",
]
