"""LLM enrichment storage layer.

Stores and retrieves LLM-generated enrichment fields bound to paper content
entries with latest-result lookup.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence, TYPE_CHECKING

from PaperTracker.core.models import LLMGeneratedInfo

if TYPE_CHECKING:
    from PaperTracker.storage.db import DatabaseManager

log = logging.getLogger(__name__)


class LLMGeneratedStore:
    """Store for LLM-generated enrichment data."""

    def __init__(self, db_manager: DatabaseManager, provider: str, model: str) -> None:
        self.db_manager = db_manager
        self.provider = provider
        self.model = model

    def save(self, infos: Sequence[LLMGeneratedInfo]) -> None:
        """Save LLM-generated data to llm_generated table."""
        if not infos:
            return

        with self.db_manager.connection() as conn:
            for info in infos:
                cursor = conn.execute(
                    "SELECT id FROM paper_content WHERE source = ? AND source_id = ?",
                    (info.source, info.source_id),
                )
                row = cursor.fetchone()
                if not row:
                    log.warning(
                        "Paper not found in paper_content: %s/%s",
                        info.source,
                        info.source_id,
                    )
                    continue

                paper_content_id = row[0]
                conn.execute(
                    """
                    INSERT INTO llm_generated (
                        paper_content_id,
                        provider,
                        model,
                        language,
                        abstract_translation,
                        summary_tldr,
                        summary_motivation,
                        summary_problem,
                        summary_method,
                        summary_result,
                        summary_conclusion
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_content_id,
                        self.provider,
                        self.model,
                        info.language,
                        info.abstract_translation,
                        info.tldr,
                        info.motivation,
                        info.problem,
                        info.method,
                        info.result,
                        info.conclusion,
                    ),
                )

            conn.commit()
        log.debug("Saved LLM enrichment for %d papers", len(infos))

    def get_latest(self, source: str, source_id: str) -> LLMGeneratedInfo | None:
        """Get latest LLM-generated data for a paper."""
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    l.language,
                    l.abstract_translation,
                    l.summary_tldr,
                    l.summary_motivation,
                    l.summary_problem,
                    l.summary_method,
                    l.summary_result,
                    l.summary_conclusion
                FROM llm_generated l
                JOIN paper_content c ON l.paper_content_id = c.id
                WHERE c.source = ? AND c.source_id = ?
                ORDER BY l.generated_at DESC
                LIMIT 1
                """,
                (source, source_id),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return LLMGeneratedInfo(
            source=source,
            source_id=source_id,
            language=row[0],
            abstract_translation=row[1],
            tldr=row[2],
            motivation=row[3],
            problem=row[4],
            method=row[5],
            result=row[6],
            conclusion=row[7],
        )

    def get_batch_with_llm(
        self,
        sources_and_ids: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], LLMGeneratedInfo]:
        """Batch get LLM data for multiple papers."""
        if not sources_and_ids:
            return {}

        placeholders = ",".join(["(?, ?)"] * len(sources_and_ids))
        params: list[Any] = [item for pair in sources_and_ids for item in pair]

        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT
                    c.source,
                    c.source_id,
                    l.language,
                    l.abstract_translation,
                    l.summary_tldr,
                    l.summary_motivation,
                    l.summary_problem,
                    l.summary_method,
                    l.summary_result,
                    l.summary_conclusion
                FROM paper_content c
                LEFT JOIN (
                    SELECT
                        paper_content_id,
                        language,
                        abstract_translation,
                        summary_tldr,
                        summary_motivation,
                        summary_problem,
                        summary_method,
                        summary_result,
                        summary_conclusion,
                        ROW_NUMBER() OVER (PARTITION BY paper_content_id ORDER BY generated_at DESC) as rn
                    FROM llm_generated
                ) l ON l.paper_content_id = c.id AND l.rn = 1
                WHERE (c.source, c.source_id) IN ({placeholders})
                """,
                params,
            )
            rows = cursor.fetchall()

        results = {}
        for row in rows:
            if row[2]:
                key = (row[0], row[1])
                results[key] = LLMGeneratedInfo(
                    source=row[0],
                    source_id=row[1],
                    language=row[2],
                    abstract_translation=row[3],
                    tldr=row[4],
                    motivation=row[5],
                    problem=row[6],
                    method=row[7],
                    result=row[8],
                    conclusion=row[9],
                )

        return results
