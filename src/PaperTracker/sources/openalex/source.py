"""OpenAlex data source adapter.

Builds OpenAlex source behavior by delegating paged fetching and filtering to
the OpenAlex-specific multi-round strategy module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from PaperTracker.ccf import CCFVenueStore
from PaperTracker.core.models import Paper
from PaperTracker.core.query import SearchQuery
from PaperTracker.sources.openalex.client import OpenAlexApiClient
from PaperTracker.sources.openalex.fetch import collect_papers_with_time_filter_openalex

if TYPE_CHECKING:
    from PaperTracker.config import SearchConfig
    from PaperTracker.storage.deduplicate import SqliteDeduplicateStore


@dataclass(slots=True)
class OpenAlexSource:
    """OpenAlex-backed source adapter that returns normalized papers."""

    client: OpenAlexApiClient
    scope: SearchQuery | None = None
    search_config: SearchConfig | None = None
    dedup_store: SqliteDeduplicateStore | None = None
    venue_store: CCFVenueStore | None = None
    name: str = "openalex"

    def search(self, query: SearchQuery, *, max_results: int) -> list[Paper]:
        """Search papers from OpenAlex and normalize the result set.

        Args:
            query: Structured user query to compile for OpenAlex.
            max_results: Maximum number of requested items.

        Returns:
            A list of normalized ``Paper`` objects.
        """
        if self.search_config is None:
            raise ValueError("OpenAlexSource.search_config is required for multi-round fetching")

        policy = (
            self.search_config
            if self.search_config.max_results == max_results
            else replace(self.search_config, max_results=max_results)
        )

        papers = collect_papers_with_time_filter_openalex(
            query=query,
            scope=self.scope,
            policy=policy,
            fetch_page_func=self._fetch_page,
            dedup_store=self.dedup_store,
        )
        return [self._attach_ccf_metadata(paper) for paper in papers]

    def _fetch_page(
        self,
        params: dict[str, str],
        page: int,
        page_size: int,
    ) -> list[dict[str, object]]:
        """Fetch one OpenAlex works page for strategy callbacks."""
        return self.client.fetch_works_page(
            params=params,
            page=page,
            page_size=page_size,
        )

    def close(self) -> None:
        """Close resources held by the OpenAlex source adapter."""
        self.client.close()

    def _attach_ccf_metadata(self, paper: Paper) -> Paper:
        """Attach canonical venue and optional CCF metadata to one paper."""
        venue_name = str(paper.extra.get("venue_name") or "").strip()
        venue_type = str(paper.extra.get("venue_type") or "").strip().lower() or None
        extra = dict(paper.extra)
        if venue_name:
            extra.setdefault("venue", venue_name)
            extra["venue_name"] = venue_name
        if venue_type:
            extra["venue_type"] = venue_type
        if (
            self.venue_store is None
            or self.search_config is None
            or not getattr(self.search_config, "ccf_enabled", False)
            or not venue_name
        ):
            return replace(paper, extra=extra)
        matched = self.venue_store.match_venue_name(
            venue_name,
            venue_type=venue_type,
            ranks=getattr(self.search_config, "ccf_ranks", ("A", "B")),
        )
        if matched is None:
            return replace(paper, extra=extra)
        extra.update(
            self.venue_store.build_venue_extra(
                matched,
                venue_name=venue_name,
                venue_type=venue_type,
            )
        )
        return replace(paper, extra=extra)
