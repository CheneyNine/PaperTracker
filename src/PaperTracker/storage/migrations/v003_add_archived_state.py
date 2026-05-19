"""Migration v003: archive state for dashboard-managed papers."""

from __future__ import annotations

from PaperTracker.storage.migration import Migration

MIGRATION = Migration(
    version=3,
    description="Add archive state to seen_papers",
    sql="""
        ALTER TABLE seen_papers
          ADD COLUMN archived_at INTEGER;

        CREATE INDEX IF NOT EXISTS idx_seen_archived_at
          ON seen_papers(archived_at);
    """,
)
