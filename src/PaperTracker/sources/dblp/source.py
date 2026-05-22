"""DBLP venue-constrained source using dblp-crawler.

Replaces custom HTML scraping with XML-based fetching via the dblp-crawler
library. Downloads DBLP venue index and proceedings XML, then maps
Publication objects to the internal Paper model.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from dblp_crawler import (
    Journal,
    JournalList,
    Publication,
    download_journal,
    download_journal_list,
)

from PaperTracker.ccf import CCFVenueStore
from PaperTracker.core.models import Paper, PaperLinks
from PaperTracker.core.query import SearchQuery
from PaperTracker.sources.openalex.query import apply_positive_filter
from PaperTracker.utils.log import log

# dblp-crawler logs every failed HTTP request at ERROR level which creates
# noise when dblp.org is slow or unreliable. We handle failures ourselves
# via return_exceptions=True, so suppress the library's error-level output.
logging.getLogger("dblp_crawler").setLevel(logging.CRITICAL)

if TYPE_CHECKING:
    from PaperTracker.ccf.store import CCFVenue

_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})")


@dataclass(slots=True)
class DBLPSource:
    """DBLP-backed source using dblp-crawler for XML-based paper collection."""

    venue_store: CCFVenueStore
    search_config: object
    scope: SearchQuery | None = None
    name: str = "dblp"

    def search(self, query: SearchQuery, *, max_results: int) -> list[Paper]:
        """Search recent DBLP venue publications constrained by the CCF whitelist."""
        if not getattr(self.search_config, "ccf_enabled", False):
            return []
        venues = self.venue_store.list_venues(
            ranks=getattr(self.search_config, "ccf_ranks", ("A", "B"))
        )
        if not venues:
            return []

        current_year = datetime.now(timezone.utc).year
        min_year = current_year - max(getattr(self.search_config, "dblp_recent_years", 2), 1) + 1

        try:
            per_venue_papers = asyncio.run(
                asyncio.wait_for(
                    _fetch_all_venues(venues=venues, min_year=min_year, max_editions=2),
                    timeout=90.0,
                )
            )
        except asyncio.TimeoutError:
            log.warning("DBLP fetch timed out after 90s; skipping DBLP results")
            return []
        except Exception as error:
            log.warning("DBLP fetch failed: %s", error)
            return []

        matched: list[Paper] = []
        for venue_papers in per_venue_papers:
            filtered = apply_positive_filter(venue_papers, query=query, scope=self.scope)
            matched.extend(filtered)
            if len(matched) >= max_results:
                return matched[:max_results]
        return matched[:max_results]

    def close(self) -> None:
        pass


async def _fetch_all_venues(
    venues: list[CCFVenue],
    min_year: int,
    max_editions: int,
) -> list[list[Paper]]:
    """Fetch papers from all venues concurrently via asyncio.gather."""
    active = [v for v in venues if v.dblp_stream]
    tasks = [_fetch_venue_papers(v, min_year=min_year, max_editions=max_editions) for v in active]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: list[list[Paper]] = []
    failed = 0
    for venue, result in zip(active, results):
        if isinstance(result, Exception):
            failed += 1
            log.debug("DBLP venue fetch failed: venue=%s error=%s", venue.short_name, result)
            output.append([])
        else:
            output.append(result)  # type: ignore[arg-type]
    if failed:
        log.warning("DBLP: %d/%d venue(s) failed to fetch (network issue?)", failed, len(active))
    return output


async def _fetch_venue_papers(
    venue: CCFVenue,
    *,
    min_year: int,
    max_editions: int,
) -> list[Paper]:
    """Download and parse papers for one DBLP venue stream."""
    index_data = await download_journal_list(venue.dblp_stream)
    if index_data is None:
        return []

    try:
        journal_list = JournalList(index_data)
    except AssertionError:
        log.debug("DBLP unexpected index XML for stream: %s", venue.dblp_stream)
        return []

    keys = journal_list.journal_keys()
    recent_keys = [
        k for k in keys if _year_from_key(k) is None or _year_from_key(k) >= min_year
    ][:max_editions]

    edition_data_list = await asyncio.gather(
        *[download_journal(key) for key in recent_keys],
        return_exceptions=True,
    )

    papers: list[Paper] = []
    for key, edition_data in zip(recent_keys, edition_data_list):
        if isinstance(edition_data, Exception) or edition_data is None:
            log.debug("DBLP journal download failed: key=%s", key)
            continue
        try:
            journal = Journal(edition_data)
        except AssertionError:
            log.debug("DBLP unexpected journal XML: key=%s", key)
            continue

        for pub in journal.publications():
            year = pub.year()
            if year is not None and year < min_year:
                continue
            paper = _pub_to_paper(pub, venue=venue)
            if paper is not None:
                papers.append(paper)

    return papers


def _pub_to_paper(pub: Publication, *, venue: CCFVenue) -> Paper | None:
    """Convert a dblp_crawler Publication to the internal Paper model."""
    title = pub.title()
    if not title:
        return None

    year = pub.year() or datetime.now(timezone.utc).year
    published = datetime(year, 1, 1, tzinfo=timezone.utc)
    authors = tuple(author.name() for author in pub.authors())

    ee_urls = list(pub.ee())
    doi = pub.doi()
    detail_url = next(iter(ee_urls), None) or f"https://dblp.org/{pub.key()}"
    paper_id = pub.key().replace("/", "_")

    return Paper(
        source="dblp",
        id=paper_id,
        title=title,
        authors=authors,
        abstract="",
        published=published,
        updated=published,
        primary_category=venue.short_name,
        categories=(venue.short_name,),
        links=PaperLinks(abstract=detail_url, pdf=None),
        doi=doi,
        extra={
            "work_type": "article",
            "venue": venue.short_name,
            "venue_name": venue.full_name,
            "venue_type": venue.venue_type,
            "ccf_rank": f"CCF-{venue.rank}",
            "ccf_venue": venue.short_name,
            "ccf_venue_name": venue.full_name,
        },
    )


def _year_from_key(key: str) -> int | None:
    """Extract year from a DBLP key like db/conf/aaai/aaai2024."""
    match = _YEAR_RE.search(key)
    return int(match.group(1)) if match else None
