"""Storage Domain Configuration.

Defines loading and validation for persistence settings, including database path, content flags, and arXiv identifier behavior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from PaperTracker.config.common import (
    expect_bool,
    expect_str,
    get_optional_value,
    get_required_value,
    get_section,
)


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Store validated persistence and arXiv ID handling settings."""

    enabled: bool
    db_path: str
    content_storage_enabled: bool
    keep_arxiv_version: bool
    backend: str = "sqlite"
    database_url: str | None = None


def load_storage(raw: Mapping[str, Any]) -> StorageConfig:
    """Load storage domain config from raw mapping.

    Args:
        raw: Root configuration mapping.

    Returns:
        Parsed storage configuration.

    Raises:
        TypeError: If config types are invalid.
        ValueError: If required keys are missing.
    """
    storage_section = get_section(raw, "storage", required=True)
    backend_raw = get_optional_value(storage_section, "backend", None) or os.environ.get("STORAGE_BACKEND") or "sqlite"
    database_url_raw = get_optional_value(storage_section, "database_url", None)
    if database_url_raw is None:
        database_url_raw = os.environ.get("DATABASE_URL") or None
    return StorageConfig(
        enabled=expect_bool(
            get_required_value(storage_section, "enabled", "storage.enabled"),
            "storage.enabled",
        ),
        db_path=expect_str(
            get_required_value(storage_section, "db_path", "storage.db_path"),
            "storage.db_path",
        ),
        content_storage_enabled=expect_bool(
            get_required_value(
                storage_section, "content_storage_enabled", "storage.content_storage_enabled"
            ),
            "storage.content_storage_enabled",
        ),
        keep_arxiv_version=expect_bool(
            get_required_value(
                storage_section, "keep_arxiv_version", "storage.keep_arxiv_version"
            ),
            "storage.keep_arxiv_version",
        ),
        backend=expect_str(backend_raw, "storage.backend") if backend_raw is not None else "sqlite",
        database_url=expect_str(database_url_raw, "storage.database_url") if database_url_raw is not None else None,
    )


def check_storage(config: StorageConfig) -> None:
    """Validate storage domain constraints.

    Args:
        config: Parsed storage configuration.

    Raises:
        ValueError: If values violate storage constraints.
    """
    if not config.db_path.strip():
        raise ValueError("storage.db_path must not be empty")
