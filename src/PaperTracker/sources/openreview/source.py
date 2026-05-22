"""OpenReview source using the openreview-py library.

Replaces fragile HTML scraping with the official OpenReview v2 API client.
Notes returned by the API already carry full abstracts, eliminating the
per-paper forum fetch round-trip that the old approach required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PaperTracker.ccf import CCFVenueStore
from PaperTracker.core.models import Paper, PaperLinks
from PaperTracker.core.query import SearchQuery
from PaperTracker.sources.openalex.query import apply_positive_filter
from PaperTracker.utils.log import log

if TYPE_CHECKING:
    from PaperTracker.ccf.store import CCFVenue

OPENREVIEW_V2_URL = "https://api2.openreview.net"
OPENREVIEW_FORUM_URL = "https://openreview.net/forum?id={}"
OPENREVIEW_PDF_URL = "https://openreview.net/pdf?id={}"

# Invitation suffixes tried in order until results are found.
_SUBMISSION_SUFFIXES = [
    "/-/Submission",
    "/-/Blind_Submission",
]


@dataclass(slots=True)
class OpenReviewSource:
    """OpenReview-backed source using the openreview-py v2 API."""

    venue_store: CCFVenueStore
    search_config: object
    scope: SearchQuery | None = None
    name: str = "openreview"

    def search(self, query: SearchQuery, *, max_results: int) -> list[Paper]:
        """Search curated OpenReview venues and return matched submissions."""
        if not getattr(self.search_config, "ccf_enabled", False):
            return []
        venues = [
            v
            for v in self.venue_store.list_venues(
                ranks=getattr(self.search_config, "ccf_ranks", ("A", "B"))
            )
            if v.openreview_venues
        ]
        if not venues:
            return []

        import openreview.api as or_api

        client = or_api.OpenReviewClient(baseurl=OPENREVIEW_V2_URL)

        current_year = datetime.now(timezone.utc).year
        min_year = (
            current_year
            - max(getattr(self.search_config, "openreview_recent_years", 2), 1)
            + 1
        )
        per_venue_limit = max(
            getattr(self.search_config, "openreview_max_pages", 3) * 25, 25
        )

        matched: list[Paper] = []
        for venue in venues:
            for venue_id in venue.openreview_venues:
                year = _extract_year(venue_id)
                if year is not None and year < min_year:
                    continue
                try:
                    papers = _fetch_venue(
                        client=client,
                        venue_id=venue_id,
                        venue=venue,
                        limit=per_venue_limit,
                    )
                except Exception as error:
                    log.debug(
                        "OpenReview fetch failed: venue=%s id=%s error=%s",
                        venue.short_name,
                        venue_id,
                        error,
                    )
                    continue

                filtered = apply_positive_filter(papers, query=query, scope=self.scope)
                matched.extend(filtered)
                if len(matched) >= max_results:
                    return matched[:max_results]

        return matched[:max_results]

    def close(self) -> None:
        pass


def _fetch_venue(
    client: object,
    venue_id: str,
    venue: CCFVenue,
    limit: int,
) -> list[Paper]:
    """Fetch submissions for one OpenReview venue via the v2 API."""
    year = _extract_year(venue_id) or datetime.now(timezone.utc).year

    notes = None
    for suffix in _SUBMISSION_SUFFIXES:
        invitation = venue_id + suffix
        try:
            batch = client.get_notes(invitation=invitation, limit=limit)  # type: ignore[union-attr]
            if batch:
                notes = batch
                break
        except Exception:
            continue

    if not notes:
        return []

    papers: list[Paper] = []
    for note in notes:
        if getattr(note, "ddate", None) is not None:
            continue
        paper = _note_to_paper(note, venue=venue, year=year)
        if paper is not None:
            papers.append(paper)
    return papers


def _note_to_paper(note: object, *, venue: CCFVenue, year: int) -> Paper | None:
    """Convert an openreview-py v2 Note to the internal Paper model."""
    content = getattr(note, "content", None) or {}

    title = _content_value(content, "title")
    if not title:
        return None

    abstract = _content_value(content, "abstract")

    raw_authors = (content.get("authors") or {}).get("value") or []
    authors = tuple(str(a) for a in raw_authors if a)

    forum_id = getattr(note, "forum", None) or getattr(note, "id", "")
    note_id = getattr(note, "id", "") or forum_id

    published = datetime(year, 1, 1, tzinfo=timezone.utc)

    return Paper(
        source="openreview",
        id=note_id,
        title=title,
        authors=authors,
        abstract=abstract,
        published=published,
        updated=published,
        primary_category=venue.short_name,
        categories=(venue.short_name,),
        links=PaperLinks(
            abstract=OPENREVIEW_FORUM_URL.format(forum_id),
            pdf=OPENREVIEW_PDF_URL.format(forum_id),
        ),
        doi=None,
        extra={
            "work_type": "article",
            "venue": venue.short_name,
            "venue_name": venue.full_name,
            "venue_type": "conference",
            "ccf_rank": f"CCF-{venue.rank}",
            "ccf_venue": venue.short_name,
            "ccf_venue_name": venue.full_name,
        },
    )


def _content_value(content: dict, key: str) -> str:
    """Extract a string value from a v2 OpenReview note content field."""
    field = content.get(key)
    if isinstance(field, dict):
        return str(field.get("value") or "")
    return str(field or "")


def _extract_year(venue_id: str) -> int | None:
    """Extract year from an OpenReview venue id like NeurIPS.cc/2024/Conference."""
    for segment in venue_id.split("/"):
        if segment.isdigit() and len(segment) == 4:
            return int(segment)
    return None
