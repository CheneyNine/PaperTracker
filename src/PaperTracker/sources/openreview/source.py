"""OpenReview venue source.

Collects submissions from a small curated set of OpenReview-managed CCF venues
and enriches matched papers with forum abstracts when available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from urllib.parse import quote, urljoin

from PaperTracker.ccf import CCFVenueStore
from PaperTracker.core.models import Paper, PaperLinks
from PaperTracker.core.query import SearchQuery
from PaperTracker.sources.openalex.query import apply_positive_filter
from PaperTracker.sources.openreview.client import OPENREVIEW_BASE_URL, OpenReviewHtmlClient
from PaperTracker.utils.log import log

_CARD_RE = re.compile(
    r'<li><div class="note.*?"><h4><a href="/forum\?id=(?P<forum>[^"]+)">(?P<title>.*?)</a></h4>'
    r'.*?<div class="note-authors"><span>(?P<authors>.*?)</span></div>',
    re.S,
)
_AUTHOR_RE = re.compile(r'>(?P<name>[^<>]+)</a>')
_ABSTRACT_RE = re.compile(
    r'Abstract<!-- -->:</strong>\s*<span class="note-content-value">(?P<abstract>.*?)</span>',
    re.S,
)
_PDF_RE = re.compile(r'href="(?P<href>/(?:pdf|attachment)\?id=[^"&]+[^"]*)"')


@dataclass(slots=True)
class OpenReviewSource:
    """OpenReview-backed source for curated CCF venues."""

    client: OpenReviewHtmlClient
    venue_store: CCFVenueStore
    search_config: object
    scope: SearchQuery | None = None
    name: str = "openreview"

    def search(self, query: SearchQuery, *, max_results: int) -> list[Paper]:
        """Search curated OpenReview venues and return matched submissions."""
        if not getattr(self.search_config, "ccf_enabled", False):
            return []
        venues = [
            venue
            for venue in self.venue_store.list_venues(ranks=getattr(self.search_config, "ccf_ranks", ("A", "B")))
            if venue.openreview_venues
        ]
        if not venues:
            return []

        current_year = datetime.now(timezone.utc).year
        min_year = current_year - max(getattr(self.search_config, "openreview_recent_years", 2), 1) + 1
        max_pages = max(getattr(self.search_config, "openreview_max_pages", 3), 1)
        matched: list[Paper] = []

        for venue in venues:
            for venue_id in venue.openreview_venues:
                year = _extract_year_from_venue_id(venue_id)
                if year is not None and year < min_year:
                    continue
                try:
                    papers = self._search_one_venue(
                        query,
                        venue_id=venue_id,
                        venue_short=venue.short_name,
                        venue_full=venue.full_name,
                        rank=venue.rank,
                        max_pages=max_pages,
                    )
                except Exception as error:  # noqa: BLE001 - isolate venue failures
                    log.debug("OpenReview venue failed: venue=%s id=%s error=%s", venue.short_name, venue_id, error)
                    continue
                matched.extend(papers)
                if len(matched) >= max_results:
                    return matched[:max_results]
        return matched[:max_results]

    def close(self) -> None:
        """Close client resources."""
        self.client.close()

    def _search_one_venue(
        self,
        query: SearchQuery,
        *,
        venue_id: str,
        venue_short: str,
        venue_full: str,
        rank: str,
        max_pages: int,
    ) -> list[Paper]:
        """Search one OpenReview venue submissions listing."""
        matched: list[Paper] = []
        seen_forums: set[str] = set()
        encoded_venue = quote(venue_id, safe="")

        for page in range(1, max_pages + 1):
            suffix = f"/submissions?page={page}&venue={encoded_venue}"
            page_text = self.client.fetch_text(suffix)
            cards = list(_CARD_RE.finditer(page_text))
            if not cards:
                break

            page_hits = 0
            for card in cards:
                forum_id = card.group("forum").strip()
                if not forum_id or forum_id in seen_forums:
                    continue
                seen_forums.add(forum_id)
                title = _clean_text(_strip_tags(card.group("title")))
                authors = [_clean_text(unescape(match.group("name"))) for match in _AUTHOR_RE.finditer(card.group("authors"))]
                authors = [author for author in authors if author]
                year = _extract_year_from_venue_id(venue_id) or datetime.now(timezone.utc).year
                published = datetime(year, 1, 1, tzinfo=timezone.utc)
                forum_url = urljoin(OPENREVIEW_BASE_URL, f"/forum?id={forum_id}")

                candidate = Paper(
                    source=self.name,
                    id=forum_id,
                    title=title,
                    authors=tuple(authors),
                    abstract="",
                    published=published,
                    updated=published,
                    primary_category=venue_short,
                    categories=(venue_short,),
                    links=PaperLinks(abstract=forum_url, pdf=None),
                    doi=None,
                    extra={
                        "work_type": "article",
                        "venue": venue_short,
                        "venue_name": venue_full,
                        "venue_type": "conference",
                        "ccf_rank": f"CCF-{rank}",
                        "ccf_venue": venue_short,
                        "ccf_venue_name": venue_full,
                    },
                )
                if not apply_positive_filter([candidate], query=query, scope=self.scope):
                    continue

                abstract, pdf_url = self._fetch_forum_details(forum_url)
                matched.append(
                    Paper(
                        source=candidate.source,
                        id=candidate.id,
                        title=candidate.title,
                        authors=candidate.authors,
                        abstract=abstract,
                        published=candidate.published,
                        updated=candidate.updated,
                        primary_category=candidate.primary_category,
                        categories=candidate.categories,
                        links=PaperLinks(abstract=forum_url, pdf=pdf_url),
                        doi=None,
                        extra=dict(candidate.extra),
                    )
                )
                page_hits += 1

            if page_hits == 0:
                break

        return matched

    def _fetch_forum_details(self, forum_url: str) -> tuple[str, str | None]:
        """Fetch abstract and PDF link from one OpenReview forum page."""
        page_text = self.client.fetch_text(forum_url)
        abstract_match = _ABSTRACT_RE.search(page_text)
        abstract = _clean_text(_strip_tags(abstract_match.group("abstract"))) if abstract_match else ""
        pdf_match = _PDF_RE.search(page_text)
        pdf_url = urljoin(OPENREVIEW_BASE_URL, unescape(pdf_match.group("href"))) if pdf_match else None
        return abstract, pdf_url


def _clean_text(value: str) -> str:
    """Normalize whitespace for OpenReview text."""
    return " ".join(unescape(value).split())


def _strip_tags(value: str) -> str:
    """Drop HTML tags from a snippet."""
    return re.sub(r"<[^>]+>", "", value)


def _extract_year_from_venue_id(venue_id: str) -> int | None:
    """Extract year segment from OpenReview venue id."""
    for segment in venue_id.split("/"):
        if segment.isdigit() and len(segment) == 4:
            return int(segment)
    return None
