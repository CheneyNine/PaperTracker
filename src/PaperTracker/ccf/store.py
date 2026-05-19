"""CCF whitelist cache store.

Loads a bundled CCF A/B venue snapshot, persists a local cache file, and
returns filtered venue definitions for search sources and dashboard actions.
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class CCFVenue:
    """One cached CCF venue definition."""

    short_name: str
    full_name: str
    rank: str
    venue_type: str
    dblp_stream: str
    openreview_venues: tuple[str, ...] = ()


class CCFVenueStore:
    """Local cache manager for bundled CCF venue snapshot data."""

    def __init__(self, cache_path: Path) -> None:
        """Initialize the store with a writable cache file path."""
        self.cache_path = cache_path

    def list_venues(
        self,
        *,
        ranks: tuple[str, ...] = ("A", "B"),
    ) -> list[CCFVenue]:
        """Load cached venues filtered by rank."""
        data = self._load_cached_payload()
        allowed = {rank.strip().upper() for rank in ranks if rank.strip()}
        venues: list[CCFVenue] = []
        for item in data.get("venues", []):
            if not isinstance(item, dict):
                continue
            rank = str(item.get("rank", "")).strip().upper()
            if rank not in allowed:
                continue
            venues.append(
                CCFVenue(
                    short_name=str(item.get("short_name", "")).strip(),
                    full_name=str(item.get("full_name", "")).strip(),
                    rank=rank,
                    venue_type=str(item.get("venue_type", "conference")).strip().lower(),
                    dblp_stream=str(item.get("dblp_stream", "")).strip(),
                    openreview_venues=tuple(
                        str(value).strip()
                        for value in item.get("openreview_venues", [])
                        if str(value).strip()
                    ),
                )
            )
        return [venue for venue in venues if venue.short_name and venue.dblp_stream]

    def refresh_cache(self) -> dict[str, Any]:
        """Rewrite the local cache file from the bundled snapshot."""
        self._write_bundled_payload()
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        """Return lightweight cache metadata for the dashboard."""
        data = self._load_cached_payload()
        return {
            "ccf_venue_count": len(data.get("venues", [])),
            "ccf_last_updated_at": data.get("refreshed_at"),
        }

    def _write_bundled_payload(self) -> dict[str, Any]:
        """Write bundled snapshot to disk and return the in-memory payload."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(_load_bundled_snapshot_text())
        payload["refreshed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def match_venue_name(
        self,
        venue_name: str,
        *,
        venue_type: str | None = None,
        ranks: tuple[str, ...] = ("A", "B"),
    ) -> CCFVenue | None:
        """Match one external venue name against the cached CCF whitelist."""
        normalized_name = _normalize_venue_name(venue_name)
        if not normalized_name:
            return None
        normalized_type = (venue_type or "").strip().casefold() or None
        venues = self.list_venues(ranks=ranks)
        exact_index: dict[str, CCFVenue] = {}
        for venue in venues:
            if normalized_type and venue.venue_type != normalized_type:
                continue
            for alias in _venue_aliases(venue):
                exact_index.setdefault(alias, venue)
        exact_match = exact_index.get(normalized_name)
        if exact_match is not None:
            return exact_match

        best_match: CCFVenue | None = None
        best_score = 0
        padded_name = f" {normalized_name} "
        for venue in venues:
            if normalized_type and venue.venue_type != normalized_type:
                continue
            for alias in _venue_aliases(venue):
                if alias == normalized_name:
                    return venue
                padded_alias = f" {alias} "
                if padded_alias in padded_name or padded_name in padded_alias:
                    score = len(alias)
                    if score > best_score:
                        best_match = venue
                        best_score = score
        return best_match

    def build_venue_extra(
        self,
        venue: CCFVenue,
        *,
        venue_name: str | None = None,
        venue_type: str | None = None,
    ) -> dict[str, str]:
        """Build canonical venue metadata for one matched CCF venue."""
        resolved_name = (venue_name or venue.full_name or venue.short_name).strip()
        resolved_type = (venue_type or venue.venue_type).strip()
        return {
            "venue": venue.short_name,
            "venue_name": resolved_name,
            "venue_type": resolved_type,
            "ccf_rank": f"CCF-{venue.rank}",
            "ccf_venue": venue.short_name,
            "ccf_venue_name": venue.full_name,
        }

    def _load_cached_payload(self) -> dict[str, Any]:
        """Load the current cache payload, seeding it if needed."""
        if not self.cache_path.exists():
            return self._seed_cache()
        raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        return dict(raw) if isinstance(raw, dict) else self._seed_cache()

    def _seed_cache(self) -> dict[str, Any]:
        """Create cache file from bundled snapshot when missing."""
        return self._write_bundled_payload()


def _load_bundled_snapshot_text() -> str:
    """Read bundled venue snapshot JSON from package resources."""
    package = importlib.resources.files("PaperTracker.ccf.assets")
    return (package / "venues_ab.json").read_text(encoding="utf-8")


_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")


def _normalize_venue_name(value: str) -> str:
    """Normalize venue names for cross-source matching."""
    lowered = value.casefold().strip()
    if not lowered:
        return ""
    collapsed = _NON_ALNUM_RE.sub(" ", lowered)
    return " ".join(collapsed.split())


def _venue_aliases(venue: CCFVenue) -> tuple[str, ...]:
    """Build normalized aliases for one CCF venue."""
    aliases: list[str] = []
    raw_values = [venue.short_name, venue.full_name]
    raw_values.extend(value for value in venue.short_name.split("/") if value.strip())
    raw_values.extend(value for value in venue.full_name.split("/") if value.strip())
    raw_values.extend(
        _openreview_venue_label(venue_id)
        for venue_id in venue.openreview_venues
        if venue_id.strip()
    )
    if venue.full_name:
        raw_values.append(f"Proceedings of the {venue.full_name}")
    seen: set[str] = set()
    for value in raw_values:
        normalized = _normalize_venue_name(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(normalized)
    return tuple(aliases)


def _openreview_venue_label(venue_id: str) -> str:
    """Convert one OpenReview venue id into a matchable label."""
    parts = [part for part in venue_id.split("/") if part and not part.isdigit()]
    return " ".join(parts)
