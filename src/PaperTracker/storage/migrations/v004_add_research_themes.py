"""Migration v004: research themes and contribution scores."""

from __future__ import annotations

from PaperTracker.storage.migration import Migration

MIGRATION = Migration(
    version=4,
    description="Add research themes and theme contribution scores",
    sql="""
        CREATE TABLE IF NOT EXISTS research_themes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          description TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
          updated_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER))
        );

        CREATE TABLE IF NOT EXISTS theme_contributions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          research_theme_id INTEGER NOT NULL,
          paper_content_id INTEGER NOT NULL,
          generated_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          contribution_score INTEGER NOT NULL,
          rationale TEXT,
          FOREIGN KEY (research_theme_id) REFERENCES research_themes(id) ON DELETE CASCADE,
          FOREIGN KEY (paper_content_id) REFERENCES paper_content(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_theme_active
          ON research_themes(is_active);

        CREATE INDEX IF NOT EXISTS idx_theme_contributions_theme_paper
          ON theme_contributions(research_theme_id, paper_content_id, generated_at DESC);
    """,
    pg_sql="""
        CREATE TABLE IF NOT EXISTS research_themes (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL,
          description TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 0,
          created_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT,
          updated_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
        );

        CREATE TABLE IF NOT EXISTS theme_contributions (
          id BIGSERIAL PRIMARY KEY,
          research_theme_id BIGINT NOT NULL,
          paper_content_id BIGINT NOT NULL,
          generated_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          contribution_score INTEGER NOT NULL,
          rationale TEXT,
          FOREIGN KEY (research_theme_id) REFERENCES research_themes(id) ON DELETE CASCADE,
          FOREIGN KEY (paper_content_id) REFERENCES paper_content(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_theme_active
          ON research_themes(is_active);

        CREATE INDEX IF NOT EXISTS idx_theme_contributions_theme_paper
          ON theme_contributions(research_theme_id, paper_content_id, generated_at DESC);
    """,
)
