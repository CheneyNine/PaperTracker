"""arXiv data source adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import TYPE_CHECKING

import arxiv

from PaperTracker.core.models import Paper
from PaperTracker.core.query import SearchQuery
from PaperTracker.sources.arxiv.fetch import collect_papers_with_time_filter
from PaperTracker.utils.log import log

if TYPE_CHECKING:
    from PaperTracker.config import SearchConfig
    from PaperTracker.storage.deduplicate import SqliteDeduplicateStore


_ASCII_SEARCH_RE = re.compile(r"[A-Za-z0-9]")


@dataclass(slots=True)
class ArxivSource:
    """arXiv-backed source implementation.

    Translates `SearchQuery` into arXiv query syntax and delegates fetching,
    pagination, rate limiting, and XML parsing to the arxiv library.
    """

    client: arxiv.Client
    name: str = "arxiv"
    scope: SearchQuery | None = None
    keep_version: bool = False
    search_config: SearchConfig | None = None
    dedup_store: SqliteDeduplicateStore | None = None

    def search(
        self,
        query: SearchQuery,
        *,
        max_results: int,
    ) -> list[Paper]:
        """Search papers from arXiv.

        Args:
            query: Structured query (field -> AND/OR/NOT terms).
            max_results: Target number of returned papers for this query.

        Returns:
            A list of Paper.
        """
        if self.search_config is None:
            raise ValueError("ArxivSource.search_config is required")
        if not _supports_arxiv_query(query, self.scope):
            log.info(
                "Skip arXiv search for query %r: no usable English search terms",
                query.name or "unnamed",
            )
            return []
        policy = (
            self.search_config
            if self.search_config.max_results == max_results
            else replace(self.search_config, max_results=max_results)
        )
        return collect_papers_with_time_filter(
            query=query,
            scope=self.scope,
            policy=policy,
            arxiv_client=self.client,
            keep_version=self.keep_version,
            dedup_store=self.dedup_store,
        )

    def close(self) -> None:
        pass


def _supports_arxiv_query(query: SearchQuery, scope: SearchQuery | None) -> bool:
    """Return whether the query contains usable English search terms for arXiv."""
    for candidate in (scope, query):
        if candidate is None:
            continue
        for field_query in candidate.fields.values():
            for term in [*field_query.AND, *field_query.OR]:
                if _ASCII_SEARCH_RE.search(str(term)):
                    return True
    return False
