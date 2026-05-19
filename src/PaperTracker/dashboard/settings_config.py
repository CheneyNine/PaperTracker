"""Dashboard settings configuration helpers.

Loads and updates dashboard-editable YAML and .env settings for search sources
and LLM runtime configuration.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from PaperTracker.config import load_config_with_defaults
from PaperTracker.sources.registry import supported_source_names


class DashboardSettingsConfig:
    """Read and update dashboard-managed settings."""

    def __init__(self, config_path: Path, env_path: Path) -> None:
        """Initialize with YAML config and env file paths."""
        self.config_path = config_path
        self.env_path = env_path

    def get_settings(self) -> dict[str, Any]:
        """Return dashboard-editable settings from current config and env."""
        config = load_config_with_defaults(self.config_path)
        return {
            "llm": {
                "enabled": config.llm.enabled,
                "provider": config.llm.provider,
                "base_url": config.llm.base_url,
                "model": config.llm.model,
                "api_key_env": config.llm.api_key_env,
                "api_key": os.getenv(config.llm.api_key_env, ""),
                "target_lang": config.llm.target_lang,
                "enable_translation": config.llm.enable_translation,
                "enable_summary": config.llm.enable_summary,
            },
            "search": {
                "sources": list(config.search.sources),
                "supported_sources": list(supported_source_names()),
                "ccf_enabled": config.search.ccf_enabled,
                "ccf_ranks": list(config.search.ccf_ranks),
                "arxiv_min_interval_seconds": config.search.arxiv_min_interval_seconds,
                "ncbi_api_key_env": config.search.ncbi_api_key_env,
                "ncbi_api_key": os.getenv(config.search.ncbi_api_key_env, ""),
            },
        }

    def list_configured_sources(self) -> tuple[str, ...]:
        """Return currently configured search sources."""
        config = load_config_with_defaults(self.config_path)
        return config.search.sources

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist dashboard-editable settings into YAML and env files."""
        current = self.get_settings()
        updated_yaml = self._load_yaml()

        llm_payload = payload.get("llm")
        search_payload = payload.get("search")
        if not isinstance(llm_payload, dict) or not isinstance(search_payload, dict):
            raise ValueError("settings payload must include llm and search sections")

        llm_section = updated_yaml.setdefault("llm", {})
        search_section = updated_yaml.setdefault("search", {})
        if not isinstance(llm_section, dict) or not isinstance(search_section, dict):
            raise ValueError("llm and search sections must be mappings")

        llm_section["enabled"] = bool(llm_payload.get("enabled", current["llm"]["enabled"]))
        llm_section["provider"] = str(llm_payload.get("provider", current["llm"]["provider"])).strip()
        llm_section["base_url"] = str(llm_payload.get("base_url", current["llm"]["base_url"])).strip()
        llm_section["model"] = str(llm_payload.get("model", current["llm"]["model"])).strip()
        llm_section["target_lang"] = str(llm_payload.get("target_lang", current["llm"]["target_lang"])).strip()
        llm_section["enable_translation"] = bool(
            llm_payload.get("enable_translation", current["llm"]["enable_translation"])
        )
        llm_section["enable_summary"] = bool(llm_payload.get("enable_summary", current["llm"]["enable_summary"]))

        selected_sources = _normalize_source_names(
            search_payload.get("sources", current["search"]["sources"]),
            allowed=supported_source_names(),
        )
        search_section["sources"] = list(selected_sources)
        search_section["ccf_enabled"] = bool(search_payload.get("ccf_enabled", current["search"]["ccf_enabled"]))
        search_section["ccf_ranks"] = _normalize_ccf_ranks(
            search_payload.get("ccf_ranks", current["search"]["ccf_ranks"])
        )
        search_section["arxiv_min_interval_seconds"] = float(
            search_payload.get("arxiv_min_interval_seconds", current["search"]["arxiv_min_interval_seconds"])
        )

        llm_api_key_env = str(current["llm"]["api_key_env"]).strip()
        ncbi_api_key_env = str(current["search"]["ncbi_api_key_env"]).strip()
        env_updates = {
            llm_api_key_env: str(llm_payload.get("api_key", current["llm"]["api_key"])).strip(),
            ncbi_api_key_env: str(search_payload.get("ncbi_api_key", current["search"]["ncbi_api_key"])).strip(),
        }

        original_yaml_exists = self.config_path.exists()
        original_yaml_text = self.config_path.read_text(encoding="utf-8") if original_yaml_exists else ""
        original_env_exists = self.env_path.exists()
        original_env_text = self.env_path.read_text(encoding="utf-8") if original_env_exists else ""
        original_env_values = {
            key: os.getenv(key)
            for key in env_updates
        }

        try:
            self._write_yaml(updated_yaml)
            self._write_env_updates(env_updates)
            for key, value in env_updates.items():
                os.environ[key] = value
            load_config_with_defaults(self.config_path)
        except Exception:
            if original_yaml_exists:
                self.config_path.write_text(original_yaml_text, encoding="utf-8")
            elif self.config_path.exists():
                self.config_path.unlink()
            if original_env_exists:
                self.env_path.write_text(original_env_text, encoding="utf-8")
            elif self.env_path.exists():
                self.env_path.unlink()
            for key, value in original_env_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            raise

        return self.get_settings()

    def _load_yaml(self) -> dict[str, Any]:
        """Load the override YAML file as a mutable mapping."""
        if not self.config_path.exists():
            return {}
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return dict(data) if isinstance(data, dict) else {}

    def _write_yaml(self, data: dict[str, Any]) -> None:
        """Write the override YAML file."""
        self.config_path.write_text(
            yaml.safe_dump(
                data,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _write_env_updates(self, updates: dict[str, str]) -> None:
        """Upsert selected env vars while preserving unrelated lines."""
        lines = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        for key, value in updates.items():
            lines = _upsert_env_key(lines, key, value)
        text = "\n".join(lines).rstrip() + "\n" if lines else ""
        self.env_path.write_text(text, encoding="utf-8")


def _normalize_source_names(value: object, *, allowed: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize selected source names with configured registry order."""
    if not isinstance(value, list):
        raise ValueError("search.sources must be a list")
    allowed_set = {item.strip().lower() for item in allowed if item.strip()}
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        source_name = item.strip().lower()
        if not source_name or source_name not in allowed_set or source_name in seen:
            continue
        seen.add(source_name)
        normalized.append(source_name)
    if not normalized:
        raise ValueError("At least one search source must be selected")
    return tuple(normalized)


def _normalize_ccf_ranks(value: object) -> list[str]:
    """Normalize configured CCF rank list."""
    if not isinstance(value, list):
        raise ValueError("search.ccf_ranks must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        rank = str(item).strip().upper()
        if rank not in {"A", "B", "C"} or rank in seen:
            continue
        seen.add(rank)
        normalized.append(rank)
    if not normalized:
        raise ValueError("At least one CCF rank must be selected")
    return normalized


def _upsert_env_key(lines: list[str], key: str, value: str) -> list[str]:
    """Replace or append one KEY=VALUE line in .env content."""
    prefix = f"{key}="
    updated = False
    next_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            next_lines.append(line)
            continue
        if line.startswith(prefix):
            next_lines.append(f"{prefix}{value}")
            updated = True
            continue
        next_lines.append(line)
    if not updated:
        next_lines.append(f"{prefix}{value}")
    return next_lines
