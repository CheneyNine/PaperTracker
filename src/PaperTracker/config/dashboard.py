"""Dashboard configuration domain.

Parses and validates settings for the local dynamic dashboard server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from PaperTracker.config.common import expect_int, expect_str, get_section


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    """Store validated settings for the local dashboard server."""

    host: str
    port: int
    auto_refresh_seconds: int


def load_dashboard(raw: Mapping[str, Any]) -> DashboardConfig:
    """Load dashboard config from root mapping.

    Args:
        raw: Root configuration mapping.

    Returns:
        Parsed dashboard configuration.
    """
    section = get_section(raw, "dashboard", required=False)
    return DashboardConfig(
        host=expect_str(section.get("host", "127.0.0.1"), "dashboard.host"),
        port=expect_int(section.get("port", 8765), "dashboard.port"),
        auto_refresh_seconds=expect_int(
            section.get("auto_refresh_seconds", 30),
            "dashboard.auto_refresh_seconds",
        ),
    )


def check_dashboard(config: DashboardConfig) -> None:
    """Validate dashboard domain constraints.

    Args:
        config: Parsed dashboard configuration.

    Raises:
        ValueError: If values violate dashboard constraints.
    """
    if not config.host.strip():
        raise ValueError("dashboard.host must not be empty")
    if config.port <= 0 or config.port > 65535:
        raise ValueError("dashboard.port must be between 1 and 65535")
    if config.auto_refresh_seconds <= 0:
        raise ValueError("dashboard.auto_refresh_seconds must be positive")
