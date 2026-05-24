"""Migration v005: add summary_problem to LLM enrichment."""

from __future__ import annotations

from PaperTracker.storage.migration import Migration

MIGRATION = Migration(
    version=5,
    description="Add summary_problem field for structured LLM summary",
    sql="""
        ALTER TABLE llm_generated
        ADD COLUMN summary_problem TEXT;
    """,
    pg_sql="""
        ALTER TABLE llm_generated
        ADD COLUMN IF NOT EXISTS summary_problem TEXT;
    """,
)
