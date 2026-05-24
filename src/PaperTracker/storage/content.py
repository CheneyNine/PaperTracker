"""Paper content storage layer.

Persists full paper metadata and source content into database tables while
keeping enrichment storage separate.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Sequence

from PaperTracker.core.models import Paper
from PaperTracker.utils.log import log

if TYPE_CHECKING:
    from PaperTracker.storage.db import DatabaseManager


class PaperContentStore:
    """Database-backed content store for full paper data."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        log.debug("Initializing PaperContentStore")
        self.db_manager = db_manager

    def save_papers(self, papers: Sequence[Paper]) -> None:
        """Save full paper content to database."""
        if not papers:
            return

        with self.db_manager.connection() as conn:
            for paper in papers:
                cursor = conn.execute(
                    "SELECT id FROM seen_papers WHERE source = ? AND source_id = ?",
                    (paper.source, paper.id),
                )
                row = cursor.fetchone()
                if not row:
                    log.warning("Paper %s not in seen_papers, skipping content save", paper.id)
                    continue

                seen_paper_id = row[0]
                code_urls = paper.extra.get("code_urls", [])
                project_urls = paper.extra.get("project_urls", [])

                conn.execute(
                    """
                    INSERT INTO paper_content (
                        seen_paper_id, source, source_id, title, authors, abstract,
                        published_at, updated_at, primary_category, categories,
                        abstract_url, pdf_url, code_urls, project_urls, doi, extra
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seen_paper_id,
                        paper.source,
                        paper.id,
                        paper.title,
                        json.dumps(list(paper.authors), ensure_ascii=False),
                        paper.abstract,
                        int(paper.published.timestamp()) if paper.published else None,
                        int(paper.updated.timestamp()) if paper.updated else None,
                        paper.primary_category,
                        json.dumps(list(paper.categories), ensure_ascii=False),
                        paper.links.abstract,
                        paper.links.pdf,
                        json.dumps(code_urls, ensure_ascii=False),
                        json.dumps(project_urls, ensure_ascii=False),
                        paper.doi,
                        json.dumps(dict(paper.extra), ensure_ascii=False),
                    ),
                )

            conn.commit()
        log.debug("Saved %d papers to content store", len(papers))

    def get_statistics(self) -> dict[str, Any]:
        """Get content store statistics."""
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(DISTINCT source_id) as unique_papers,
                    COUNT(DISTINCT primary_category) as categories,
                    MIN(fetched_at) as first_fetch,
                    MAX(fetched_at) as last_fetch
                FROM paper_content
                """
            )
            row = cursor.fetchone()

        return {
            "total_records": row[0],
            "unique_papers": row[1],
            "categories": row[2],
            "first_fetch": row[3],
            "last_fetch": row[4],
        }
