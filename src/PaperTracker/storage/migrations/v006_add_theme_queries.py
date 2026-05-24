"""Migration v006: add per-theme query assignments."""

from __future__ import annotations

from PaperTracker.storage.migration import Migration

MIGRATION = Migration(
    version=6,
    description="Add per-theme query assignments",
    sql="""
        CREATE TABLE IF NOT EXISTS theme_queries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          research_theme_id INTEGER NOT NULL,
          label TEXT NOT NULL,
          position INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
          UNIQUE(research_theme_id, label),
          FOREIGN KEY (research_theme_id) REFERENCES research_themes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_theme_queries_theme_position
          ON theme_queries(research_theme_id, position, id);
    """,
    pg_sql="""
        CREATE TABLE IF NOT EXISTS theme_queries (
          id BIGSERIAL PRIMARY KEY,
          research_theme_id BIGINT NOT NULL,
          label TEXT NOT NULL,
          position INTEGER NOT NULL DEFAULT 0,
          created_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT,
          UNIQUE(research_theme_id, label),
          FOREIGN KEY (research_theme_id) REFERENCES research_themes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_theme_queries_theme_position
          ON theme_queries(research_theme_id, position, id);
    """,
)
