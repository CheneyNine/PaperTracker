"""Command implementations for PaperTracker CLI.

Encapsulates business logic for commands like search, separated from
CLI parameter handling and output formatting.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PaperTracker.config import AppConfig
from PaperTracker.core.models import Paper
from PaperTracker.llm import LLMService
from PaperTracker.renderers import OutputWriter
from PaperTracker.renderers.mapper import map_papers_to_views
from PaperTracker.services.search import PaperSearchService
from PaperTracker.storage.content import PaperContentStore
from PaperTracker.storage.deduplicate import SqliteDeduplicateStore
from PaperTracker.storage.llm import LLMGeneratedStore
from PaperTracker.utils.log import log


@dataclass(slots=True)
class SearchCommand:
    """Encapsulates search command business logic.

    Responsible for orchestrating search across multiple queries,
    managing deduplication, and delegating output to OutputWriter.
    """

    config: AppConfig
    search_service: PaperSearchService
    dedup_store: SqliteDeduplicateStore | None
    content_store: PaperContentStore | None
    llm_service: LLMService | None
    llm_store: LLMGeneratedStore | None
    output_writer: OutputWriter
    progress_callback: Callable[[str, dict[str, object]], None] | None = None

    def execute(self) -> None:
        """Execute search for all configured queries.

        Iterates through queries, applies filtering, and delegates
        output to the configured OutputWriter. Search behavior uses `config.search`.
        Source-specific fetch strategies are encapsulated by each source adapter.
        """
        multiple = len(self.config.search.queries) > 1

        for idx, query in enumerate(self.config.search.queries, start=1):
            if self.progress_callback is not None:
                self.progress_callback(
                    "query_started",
                    {
                        "query_index": idx,
                        "query_total": len(self.config.search.queries),
                        "query_name": query.name or "",
                    },
                )
            log.debug(
                "Running query %d/%d name=%s fields=%s",
                idx,
                len(self.config.search.queries),
                query.name,
                query.fields,
            )
            if multiple:
                log.info("=== Query %d/%d ===", idx, len(self.config.search.queries))
            if self.config.search.scope:
                log.info("scope=%s", self.config.search.scope.fields)
            if query.name:
                log.info("name=%s", query.name)
            log.info("fields=%s", dict(query.fields))

            # Search papers; source adapters decide their own fetch strategy.
            papers = self.search_service.search(
                query,
                max_results=self.config.search.max_results,
            )
            papers = self._attach_query_metadata(papers, query_name=query.name)
            log.info("Collected %d papers", len(papers))
            infos = None

            # Generate LLM enrichment.
            if self.llm_service and papers:
                if self.progress_callback is not None:
                    self.progress_callback(
                        "llm_started",
                        {
                            "query_index": idx,
                            "query_total": len(self.config.search.queries),
                            "query_name": query.name or "",
                        },
                    )
                log.info("Generating LLM enrichment for %d papers", len(papers))
                infos = self.llm_service.generate_batch(papers)

                # Inject enrichment data into paper.extra
                papers = self.llm_service.enrich_papers(papers, infos)

            # Output process
            paper_views = map_papers_to_views(papers)
            self.output_writer.write_query_result(paper_views, query, self.config.search.scope)

            # Persist only after output is successfully rendered.
            if self.dedup_store and papers:
                self.dedup_store.mark_seen(papers)
            if self.content_store and papers:
                self.content_store.save_papers(papers)
            if infos and self.llm_store:
                self.llm_store.save(infos)

    def _attach_query_metadata(
        self,
        papers: list[Paper],
        *,
        query_name: str | None,
    ) -> list[Paper]:
        """Attach matched query metadata to each paper before persistence."""
        if not papers or not query_name:
            return papers

        enriched: list[Paper] = []
        for paper in papers:
            extra_data = dict(paper.extra)
            extra_data["matched_query"] = query_name
            enriched.append(
                Paper(
                    source=paper.source,
                    id=paper.id,
                    title=paper.title,
                    authors=paper.authors,
                    abstract=paper.abstract,
                    published=paper.published,
                    updated=paper.updated,
                    primary_category=paper.primary_category,
                    categories=paper.categories,
                    links=paper.links,
                    doi=paper.doi,
                    extra=extra_data,
                )
            )
        return enriched
