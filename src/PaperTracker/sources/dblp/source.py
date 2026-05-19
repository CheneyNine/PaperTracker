"""DBLP venue-constrained source.

Collects recent papers from curated DBLP venue pages, then applies the user's
structured query locally so only papers from cached CCF venues survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

from PaperTracker.ccf import CCFVenueStore
from PaperTracker.core.models import Paper, PaperLinks
from PaperTracker.core.query import SearchQuery
from PaperTracker.sources.dblp.client import DBLPVenueClient
from PaperTracker.sources.openalex.query import apply_positive_filter
from PaperTracker.utils.log import log

_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})")
_DBLP_BASE_URL = "https://dblp.org/"
_PROCEEDINGS_RE = re.compile(
    r"<proceedings\b.*?>.*?<year>(?P<year>\d{4})</year>.*?<url>(?P<url>[^<]+)</url>.*?</proceedings>",
    re.S,
)
_REF_RE = re.compile(r'<ref href="(?P<href>[^"]+)">(?P<label>.*?)</ref>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class DBLPSource:
    """DBLP-backed source that scans curated venue pages."""

    client: DBLPVenueClient
    venue_store: CCFVenueStore
    search_config: object
    scope: SearchQuery | None = None
    name: str = "dblp"

    def search(self, query: SearchQuery, *, max_results: int) -> list[Paper]:
        """Search recent DBLP venue pages constrained by the cached CCF whitelist."""
        if not getattr(self.search_config, "ccf_enabled", False):
            return []
        venues = self.venue_store.list_venues(ranks=getattr(self.search_config, "ccf_ranks", ("A", "B")))
        if not venues:
            return []
        page_limit = 2

        current_year = datetime.now(timezone.utc).year
        min_year = current_year - max(getattr(self.search_config, "dblp_recent_years", 2), 1) + 1
        matched: list[Paper] = []

        for venue in venues:
            try:
                page_refs = self._list_recent_pages(venue.dblp_stream, min_year=min_year)
            except Exception as error:  # noqa: BLE001 - isolate venue fetch failures
                log.debug("DBLP venue listing failed: venue=%s error=%s", venue.short_name, error)
                continue

            for page_url, year in page_refs[:page_limit]:
                try:
                    parser = _DBLPEntryParser(
                        page_url=page_url,
                        venue_short=venue.short_name,
                        venue_full=venue.full_name,
                        venue_type=venue.venue_type,
                        rank=venue.rank,
                        year=year,
                    )
                    parser.feed(self.client.fetch_text(page_url))
                    candidates = parser.build_papers()
                except Exception as error:  # noqa: BLE001 - isolate page parse failures
                    log.debug("DBLP venue page failed: url=%s error=%s", page_url, error)
                    continue

                filtered = apply_positive_filter(candidates, query=query, scope=self.scope)
                matched.extend(filtered)
                if len(matched) >= max_results:
                    return matched[:max_results]

        return matched[:max_results]

    def close(self) -> None:
        """Close client resources."""
        self.client.close()

    def _list_recent_pages(self, dblp_stream: str, *, min_year: int) -> list[tuple[str, int]]:
        """Resolve recent venue page URLs from one DBLP stream index."""
        index_text = self.client.fetch_text(f"{dblp_stream.rstrip('/')}/index.xml")
        pages: list[tuple[str, int]] = []

        for match in _PROCEEDINGS_RE.finditer(index_text):
            year = int(match.group("year"))
            url_text = match.group("url").strip()
            if year >= min_year and url_text:
                pages.append((urljoin(_DBLP_BASE_URL, url_text), year))

        for match in _REF_RE.finditer(index_text):
            href = match.group("href").strip()
            label = _strip_tags(match.group("label"))
            year = _extract_year(label) or _extract_year(href)
            if not href or year is None or year < min_year:
                continue
            pages.append((urljoin(_DBLP_BASE_URL, href), year))

        deduped: list[tuple[str, int]] = []
        seen_urls: set[str] = set()
        for page_url, year in sorted(pages, key=lambda item: (-item[1], item[0])):
            if page_url in seen_urls:
                continue
            seen_urls.add(page_url)
            deduped.append((page_url, year))
        return deduped


class _DBLPEntryParser(HTMLParser):
    """Parse DBLP HTML proceedings pages into canonical paper candidates."""

    def __init__(
        self,
        *,
        page_url: str,
        venue_short: str,
        venue_full: str,
        venue_type: str,
        rank: str,
        year: int,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.venue_short = venue_short
        self.venue_full = venue_full
        self.venue_type = venue_type
        self.rank = rank
        self.year = year
        self.entries: list[dict[str, object]] = []
        self._entry_depth = 0
        self._current: dict[str, object] | None = None
        self._capture_title = False
        self._capture_author = False
        self._current_author: list[str] = []
        self._li_stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        class_name = (attr_map.get("class") or "").strip()
        if tag == "li":
            self._li_stack.append(class_name or None)
            if self._current is None and "entry" in class_name and ("inproceedings" in class_name or "article" in class_name):
                self._current = {
                    "id": (attr_map.get("id") or "").strip(),
                    "title": [],
                    "authors": [],
                    "detail_url": None,
                    "ee_url": None,
                }
                self._entry_depth = 1
                return
            if self._current is not None:
                self._entry_depth += 1
            return

        if self._current is None:
            return

        if tag == "span" and "title" in class_name:
            self._capture_title = True
            return
        if tag == "span" and attr_map.get("itemprop") == "author":
            self._capture_author = True
            self._current_author = []
            return
        if tag == "a":
            href = (attr_map.get("href") or "").strip()
            active_li = self._li_stack[-1] if self._li_stack else None
            if active_li and "details" in active_li and href and self._current.get("detail_url") is None:
                self._current["detail_url"] = urljoin(_DBLP_BASE_URL, href)
            if active_li and "ee" in active_li and href and self._current.get("ee_url") is None:
                self._current["ee_url"] = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture_title:
            self._capture_title = False
            return
        if tag == "span" and self._capture_author:
            self._capture_author = False
            author = _clean_text("".join(self._current_author))
            if author and self._current is not None:
                authors = self._current.setdefault("authors", [])
                if isinstance(authors, list):
                    authors.append(author)
            self._current_author = []
            return

        if tag == "li":
            if self._li_stack:
                self._li_stack.pop()
            if self._current is None:
                return
            self._entry_depth -= 1
            if self._entry_depth == 0:
                self.entries.append(self._current)
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._capture_title:
            title_parts = self._current.setdefault("title", [])
            if isinstance(title_parts, list):
                title_parts.append(data)
        if self._capture_author:
            self._current_author.append(data)

    def build_papers(self) -> list[Paper]:
        """Convert parsed entry payloads into canonical papers."""
        published = datetime(self.year, 1, 1, tzinfo=timezone.utc)
        papers: list[Paper] = []
        for entry in self.entries:
            title = _clean_text("".join(entry.get("title", [])))
            authors = tuple(entry.get("authors", []))
            if not title:
                continue
            detail_url = str(entry.get("detail_url") or self.page_url)
            ee_url = str(entry.get("ee_url") or detail_url)
            doi = _extract_doi(ee_url)
            paper_id = str(entry.get("id") or detail_url.rsplit("/", 1)[-1]).strip()
            papers.append(
                Paper(
                    source="dblp",
                    id=paper_id,
                    title=title,
                    authors=authors,
                    abstract="",
                    published=published,
                    updated=published,
                    primary_category=self.venue_short,
                    categories=(self.venue_short,),
                    links=PaperLinks(abstract=detail_url, pdf=None),
                    doi=doi,
                    extra=self._build_extra(),
                )
            )
        return papers

    def _build_extra(self) -> dict[str, str]:
        """Build canonical venue metadata for one DBLP venue entry."""
        return {
            "work_type": "article",
            "venue": self.venue_short,
            "venue_name": self.venue_full,
            "venue_type": self.venue_type,
            "ccf_rank": f"CCF-{self.rank}",
            "ccf_venue": self.venue_short,
            "ccf_venue_name": self.venue_full,
        }


def _clean_text(value: str) -> str:
    """Normalize whitespace in extracted text."""
    return " ".join(value.split())


def _extract_year(value: str) -> int | None:
    """Extract first four-digit year from text."""
    match = _YEAR_RE.search(value or "")
    if match is None:
        return None
    return int(match.group(1))


def _extract_doi(link: str) -> str | None:
    """Extract DOI suffix from DOI link when present."""
    normalized = link.strip()
    marker = "doi.org/"
    if marker not in normalized:
        return None
    return normalized.split(marker, 1)[1].strip() or None


def _strip_tags(value: str) -> str:
    """Drop HTML/XML tags from a short snippet."""
    return _TAG_RE.sub("", value)
