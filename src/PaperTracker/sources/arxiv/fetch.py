"""arXiv fetching strategy using the arxiv library.

Provides time-window filtering and optional deduplication backed by the
official arxiv Python library, which handles HTTP, pagination, and rate
limiting internally.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from time import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import arxiv

from PaperTracker.core.models import Paper, PaperLinks

if TYPE_CHECKING:
    from PaperTracker.config import SearchConfig
    from PaperTracker.core.query import SearchQuery
    from PaperTracker.storage.deduplicate import SqliteDeduplicateStore

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120
_RE_VERSION = re.compile(r"v\d+$")


def collect_papers_with_time_filter(
    query: SearchQuery,
    scope: SearchQuery | None,
    policy: SearchConfig,
    arxiv_client: arxiv.Client,
    keep_version: bool,
    dedup_store: SqliteDeduplicateStore | None,
) -> list[Paper]:
    """Collect papers with time filtering and optional deduplication.

    Iterates the arxiv result generator (sorted by lastUpdatedDate descending)
    and stops early once the target count is reached or the oldest seen paper
    falls outside the active collection window.

    Args:
        query: Query for this fetch task.
        scope: Optional global scope merged into query compilation.
        policy: Fetch policy: limits, time window, fill mode.
        arxiv_client: Configured arxiv.Client instance.
        keep_version: Whether to keep the arXiv version suffix in paper IDs.
        dedup_store: Optional persistent deduplication store.

    Returns:
        Filtered papers sorted by timestamp descending, capped at policy.max_results.
    """
    from PaperTracker.sources.arxiv.query import compile_search_query

    search_query_str = compile_search_query(query=query, scope=scope)
    max_fetch = policy.max_fetch_items if policy.max_fetch_items != -1 else None

    search = arxiv.Search(
        query=search_query_str,
        max_results=max_fetch,
        sort_by=arxiv.SortCriterion.LastUpdatedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    new_items: list[Paper] = []
    candidate_count = 0
    fetched_items = 0
    now = datetime.now(timezone.utc)
    start_time = time()

    logger.info(
        "Start collecting papers - query: '%s', target: %d",
        query.name or "unnamed",
        policy.max_results,
    )

    for result in arxiv_client.results(search):
        elapsed = time() - start_time
        if elapsed > TIMEOUT_SECONDS:
            logger.warning(
                "Fetch timeout (%.1fs > %ds) - fetched %d, candidates %d; stop",
                elapsed,
                TIMEOUT_SECONDS,
                fetched_items,
                candidate_count,
            )
            break

        fetched_items += 1
        paper = _result_to_paper(result, keep_version=keep_version)

        if _can_include(
            paper,
            pull_every_days=policy.pull_every,
            fill_enabled=policy.fill_enabled,
            max_lookback_days=policy.max_lookback_days,
            now=now,
        ):
            candidate_count += 1
            if dedup_store:
                new_items.extend(dedup_store.filter_new_in_source("arxiv", [paper]))
            else:
                new_items.append(paper)

            if len(new_items) >= policy.max_results:
                logger.info(
                    "Reached target - new papers: %d (target %d); stop",
                    len(new_items),
                    policy.max_results,
                )
                break

        elif _is_outside_collection_window(
            paper,
            pull_every_days=policy.pull_every,
            fill_enabled=policy.fill_enabled,
            max_lookback_days=policy.max_lookback_days,
            now=now,
        ):
            ts = paper.updated or paper.published
            logger.info(
                "Early stop - paper outside collection window (%s); stop",
                ts.isoformat() if ts else "unknown",
            )
            break

    new_items.sort(
        key=lambda p: p.updated or p.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    result_list = new_items[: policy.max_results]

    if len(result_list) < policy.max_results:
        logger.warning(
            "Target not reached - target: %d, actual: %d (candidates %d, after dedup %d)",
            policy.max_results,
            len(result_list),
            candidate_count,
            len(new_items),
        )
    else:
        logger.info("Collection done - returning %d papers", len(result_list))

    return result_list


def _result_to_paper(result: arxiv.Result, *, keep_version: bool) -> Paper:
    """Convert an arxiv.Result to the internal Paper model."""
    paper_id = _normalize_arxiv_id(result.entry_id, keep_version=keep_version)
    return Paper(
        source="arxiv",
        id=paper_id,
        title=result.title.replace("\n", " ").strip(),
        authors=[author.name for author in result.authors],
        abstract=result.summary or "",
        published=result.published,
        updated=result.updated,
        primary_category=result.primary_category or None,
        categories=list(result.categories),
        links=PaperLinks(abstract=result.entry_id, pdf=result.pdf_url),
        doi=result.doi or None,
        extra={"work_type": "preprint"},
    )


def _normalize_arxiv_id(raw_id: str, *, keep_version: bool) -> str:
    """Normalize an arXiv entry_id URL to a bare paper ID."""
    if not raw_id:
        return ""
    value = raw_id.strip()
    if "arxiv.org" in value:
        parsed = urlparse(value)
        path = parsed.path or ""
        if "/abs/" in path:
            value = path.split("/abs/", 1)[1]
        elif "/pdf/" in path:
            value = path.split("/pdf/", 1)[1]
        else:
            value = path.lstrip("/")
        if value.endswith(".pdf"):
            value = value[:-4]
    value = value.strip("/")
    if not value:
        return raw_id
    if not keep_version:
        value = _RE_VERSION.sub("", value)
    return value


def _can_include(
    paper: Paper,
    *,
    pull_every_days: int,
    fill_enabled: bool,
    max_lookback_days: int,
    now: datetime,
) -> bool:
    if _is_in_strict_window(paper, pull_every_days, now):
        return True
    if fill_enabled and _is_in_fill_window(paper, max_lookback_days, now):
        return True
    return False


def _is_outside_collection_window(
    paper: Paper,
    *,
    pull_every_days: int,
    fill_enabled: bool,
    max_lookback_days: int,
    now: datetime,
) -> bool:
    timestamp = paper.updated or paper.published
    if timestamp is None:
        return False
    if fill_enabled:
        if max_lookback_days == -1:
            return False
        return timestamp < now - timedelta(days=max_lookback_days)
    return timestamp < now - timedelta(days=pull_every_days)


def _is_in_strict_window(paper: Paper, pull_every_days: int, now: datetime) -> bool:
    timestamp = paper.updated or paper.published
    if timestamp is None:
        return False
    return timestamp >= now - timedelta(days=pull_every_days)


def _is_in_fill_window(paper: Paper, max_lookback_days: int, now: datetime) -> bool:
    timestamp = paper.updated or paper.published
    if timestamp is None:
        return False
    if max_lookback_days == -1:
        return True
    return timestamp >= now - timedelta(days=max_lookback_days)
