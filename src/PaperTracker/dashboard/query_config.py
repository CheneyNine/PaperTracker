"""Dashboard query configuration helpers.

Loads and updates the user config file query list for dashboard-side editing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class DashboardQueryItem:
    """One dashboard-managed query item."""

    label: str
    raw_name: str


class DashboardQueryConfig:
    """Read and update dashboard query definitions in the user YAML config."""

    def __init__(self, config_path: Path) -> None:
        """Initialize with the YAML config path."""
        self.config_path = config_path

    def list_items(self) -> list[DashboardQueryItem]:
        """List configured query labels in file order."""
        data = self._load_yaml()
        queries = data.get("queries", [])
        items: list[DashboardQueryItem] = []
        if not isinstance(queries, list):
            return items

        for index, item in enumerate(queries, start=1):
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("NAME") or f"Query {index}").strip()
            label = _normalize_label(raw_name)
            items.append(DashboardQueryItem(label=label, raw_name=raw_name))
        return items

    def list_labels(self) -> list[str]:
        """List normalized query labels."""
        return [item.label for item in self.list_items()]

    def add_query(self, label: str) -> None:
        """Append a new query item using the label as the search phrase."""
        normalized = _normalize_label(label)
        if not normalized:
            raise ValueError("Query label must not be empty")

        data = self._load_yaml()
        queries = data.get("queries")
        if not isinstance(queries, list):
            queries = []
            data["queries"] = queries

        existing = {item.label.casefold() for item in self.list_items()}
        if normalized.casefold() in existing:
            return

        queries.append(
            {
                "NAME": normalized,
                "OR": [normalized],
            }
        )
        self._write_yaml(data)

    def delete_query(self, label: str) -> None:
        """Delete a query item by normalized label."""
        normalized = _normalize_label(label)
        data = self._load_yaml()
        queries = data.get("queries", [])
        if not isinstance(queries, list):
            return

        filtered = []
        for item in queries:
            if not isinstance(item, dict):
                filtered.append(item)
                continue
            raw_name = str(item.get("NAME") or "").strip()
            if _normalize_label(raw_name).casefold() == normalized.casefold():
                continue
            filtered.append(item)
        data["queries"] = filtered
        self._write_yaml(data)

    def _load_yaml(self) -> dict[str, Any]:
        """Load the user override YAML file as a dict."""
        if not self.config_path.exists():
            return {}
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return dict(data) if isinstance(data, dict) else {}

    def _write_yaml(self, data: dict[str, Any]) -> None:
        """Write the user override YAML back to disk."""
        self.config_path.write_text(
            yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )


def _normalize_label(value: str) -> str:
    """Normalize a dashboard label for display and matching."""
    return " ".join(value.replace("_", " ").split())
