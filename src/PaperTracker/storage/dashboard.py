"""Dashboard storage queries.

Reads aggregated paper data for the local dashboard and persists archive state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from PaperTracker.core.models import Paper, PaperLinks, ThemeContributionInfo

if TYPE_CHECKING:
    from PaperTracker.storage.db import DatabaseManager


@dataclass(frozen=True, slots=True)
class DashboardPaperRecord:
    """Database-backed paper record for the local dashboard."""

    source: str
    source_id: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    published_at: int | None
    updated_at: int | None
    fetched_at: int
    primary_category: str | None
    categories: tuple[str, ...]
    abstract_url: str | None
    pdf_url: str | None
    doi: str | None
    matched_query: str | None
    ccf_rank: str | None
    ccf_venue: str | None
    abstract_translation: str | None
    tldr: str | None
    motivation: str | None
    problem: str | None
    method: str | None
    result: str | None
    conclusion: str | None
    theme_contribution_score: int | None
    theme_contribution_rationale: str | None
    archived_at: int | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable payload."""
        return {
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "authors": list(self.authors),
            "abstract": self.abstract,
            "published_at": _format_timestamp(self.published_at),
            "updated_at": _format_timestamp(self.updated_at),
            "fetched_at": _format_timestamp(self.fetched_at),
            "primary_category": self.primary_category,
            "categories": list(self.categories),
            "abstract_url": self.abstract_url,
            "pdf_url": self.pdf_url,
            "doi": self.doi,
            "matched_query": self.matched_query,
            "ccf_rank": self.ccf_rank,
            "ccf_venue": self.ccf_venue,
            "abstract_translation": self.abstract_translation,
            "tldr": self.tldr,
            "motivation": self.motivation,
            "problem": self.problem,
            "method": self.method,
            "result": self.result,
            "conclusion": self.conclusion,
            "theme_contribution_score": self.theme_contribution_score,
            "theme_contribution_rationale": self.theme_contribution_rationale,
            "archived_at": _format_timestamp(self.archived_at),
        }


@dataclass(frozen=True, slots=True)
class ResearchThemeRecord:
    """User-defined research theme stored in the database."""

    id: int
    name: str
    description: str
    is_active: bool
    created_at: int
    updated_at: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable payload."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": _format_timestamp(self.created_at, include_time=True),
            "updated_at": _format_timestamp(self.updated_at, include_time=True),
        }


class DashboardStore:
    """Database-backed store for dashboard listing and archive actions."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self._theme_queries_ready = False

    def list_active_papers(self) -> list[DashboardPaperRecord]:
        """List non-archived papers for the dashboard."""
        return self._list_papers(archived=False, theme_id=None)

    def list_archived_papers(self) -> list[DashboardPaperRecord]:
        """List archived papers for the dashboard archive area."""
        return self._list_papers(archived=True, theme_id=None)

    def archive_paper(self, source: str, source_id: str) -> None:
        """Mark a paper as archived."""
        now = int(datetime.now().timestamp())
        with self.db_manager.connection() as conn:
            conn.execute(
                "UPDATE seen_papers SET archived_at = ? WHERE source = ? AND source_id = ?",
                (now, source, source_id),
            )
            conn.commit()

    def archive_active_papers_for_query(self, query_label: str) -> int:
        """Archive currently active papers that belong to one query label."""
        count = 0
        normalized = query_label.strip().casefold()
        for paper in self.list_active_papers():
            label = (paper.matched_query or "").strip().casefold()
            if label != normalized:
                continue
            self.archive_paper(paper.source, paper.source_id)
            count += 1
        return count

    def archive_theme_papers_for_query(self, theme_id: int, query_label: str) -> int:
        """Archive currently visible theme papers that belong to one query label."""
        count = 0
        normalized = query_label.strip().casefold()
        for paper in self._list_papers(archived=False, theme_id=theme_id):
            if paper.theme_contribution_score is None:
                continue
            label = (paper.matched_query or "").strip().casefold()
            if label != normalized:
                continue
            self.archive_paper(paper.source, paper.source_id)
            count += 1
        return count

    def restore_paper(self, source: str, source_id: str) -> None:
        """Remove archive state from a paper."""
        with self.db_manager.connection() as conn:
            conn.execute(
                "UPDATE seen_papers SET archived_at = NULL WHERE source = ? AND source_id = ?",
                (source, source_id),
            )
            conn.commit()

    def get_snapshot(self) -> dict[str, Any]:
        """Build one dashboard snapshot payload."""
        active = self.list_active_papers()
        archived = self.list_archived_papers()
        themes = self.list_research_themes()
        return {
            "active_count": len(active),
            "archived_count": len(archived),
            "active_papers": [paper.to_dict() for paper in active],
            "archived_papers": [paper.to_dict() for paper in archived],
            "research_themes": [theme.to_dict() for theme in themes],
            "theme_boards": [self._build_theme_board(theme) for theme in themes],
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def list_theme_query_labels(self, theme_id: int) -> list[str]:
        """List query labels assigned to one research theme."""
        self.ensure_theme_queries_table()
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                SELECT label
                FROM theme_queries
                WHERE research_theme_id = ?
                ORDER BY position ASC, id ASC
                """,
                (theme_id,),
            )
            return [str(row[0]) for row in cursor.fetchall() if isinstance(row[0], str) and row[0].strip()]

    def add_theme_query(self, theme_id: int, label: str) -> None:
        """Attach one query label to one research theme."""
        self.ensure_theme_queries_table()
        normalized = " ".join(label.split())
        if not normalized:
            return
        with self.db_manager.connection() as conn:
            existing_rows = conn.execute(
                "SELECT label FROM theme_queries WHERE research_theme_id = ? ORDER BY position ASC, id ASC",
                (theme_id,),
            ).fetchall()
            existing = {str(row[0]).casefold() for row in existing_rows if isinstance(row[0], str) and row[0].strip()}
            if normalized.casefold() in existing:
                return
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM theme_queries WHERE research_theme_id = ?",
                (theme_id,),
            ).fetchone()
            next_position = int(row[0]) if row is not None else 0
            conn.execute(
                "INSERT INTO theme_queries (research_theme_id, label, position) VALUES (?, ?, ?)",
                (theme_id, normalized, next_position),
            )
            conn.commit()

    def delete_theme_query(self, theme_id: int, label: str) -> None:
        """Remove one query label from one research theme."""
        self.ensure_theme_queries_table()
        with self.db_manager.connection() as conn:
            conn.execute(
                "DELETE FROM theme_queries WHERE research_theme_id = ? AND lower(label) = lower(?)",
                (theme_id, label.strip()),
            )
            conn.commit()

    def update_research_theme(self, theme_id: int, name: str, description: str) -> None:
        """Update one research theme title and description."""
        timestamp = int(datetime.now().timestamp())
        with self.db_manager.connection() as conn:
            conn.execute(
                """
                UPDATE research_themes
                SET name = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (name.strip(), description.strip(), timestamp, theme_id),
            )
            conn.commit()

    def list_research_themes(self) -> list[ResearchThemeRecord]:
        """List all research themes ordered by active state then recency."""
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, description, is_active, created_at, updated_at
                FROM research_themes
                ORDER BY is_active DESC, updated_at DESC, id DESC
                """
            )
            return [
                ResearchThemeRecord(
                    id=int(row[0]),
                    name=str(row[1]),
                    description=str(row[2]),
                    is_active=bool(row[3]),
                    created_at=int(row[4]),
                    updated_at=int(row[5]),
                )
                for row in cursor.fetchall()
            ]

    def get_active_research_theme(self) -> ResearchThemeRecord | None:
        """Return the currently active research theme."""
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, description, is_active, created_at, updated_at
                FROM research_themes
                WHERE is_active = 1
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ResearchThemeRecord(
            id=int(row[0]),
            name=str(row[1]),
            description=str(row[2]),
            is_active=bool(row[3]),
            created_at=int(row[4]),
            updated_at=int(row[5]),
        )

    def get_research_theme(self, theme_id: int) -> ResearchThemeRecord | None:
        """Return one research theme by id."""
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, name, description, is_active, created_at, updated_at
                FROM research_themes
                WHERE id = ?
                LIMIT 1
                """,
                (theme_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ResearchThemeRecord(
            id=int(row[0]),
            name=str(row[1]),
            description=str(row[2]),
            is_active=bool(row[3]),
            created_at=int(row[4]),
            updated_at=int(row[5]),
        )

    def create_research_theme(self, name: str, description: str) -> ResearchThemeRecord:
        """Create a new enabled theme without affecting existing theme boards."""
        timestamp = int(datetime.now().timestamp())
        is_postgres = getattr(self.db_manager, "db_type", "sqlite") == "postgres"

        with self.db_manager.connection() as conn:
            if is_postgres:
                cursor = conn.execute(
                    """
                    INSERT INTO research_themes (name, description, is_active, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?) RETURNING id
                    """,
                    (name.strip(), description.strip(), timestamp, timestamp),
                )
                new_id = int(cursor.fetchone()[0])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO research_themes (name, description, is_active, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    """,
                    (name.strip(), description.strip(), timestamp, timestamp),
                )
                new_id = int(cursor.lastrowid)
            conn.commit()

        return ResearchThemeRecord(
            id=new_id,
            name=name.strip(),
            description=description.strip(),
            is_active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def set_active_research_theme(self, theme_id: int) -> None:
        """Enable one theme board without disabling other theme boards."""
        timestamp = int(datetime.now().timestamp())
        with self.db_manager.connection() as conn:
            conn.execute(
                "UPDATE research_themes SET is_active = 1, updated_at = ? WHERE id = ?",
                (timestamp, theme_id),
            )
            conn.commit()

    def delete_research_theme(self, theme_id: int) -> None:
        """Delete one theme and its contribution rows."""
        with self.db_manager.connection() as conn:
            conn.execute("DELETE FROM research_themes WHERE id = ?", (theme_id,))
            conn.commit()

    def list_active_papers_missing_translation(self) -> list[Paper]:
        """List active papers that still do not have an LLM translation."""
        records = [paper for paper in self.list_active_papers() if paper.abstract and not paper.abstract_translation]
        return [_record_to_paper(record) for record in records]

    def list_active_papers_missing_enrichment(
        self,
        *,
        require_translation: bool,
        require_summary: bool,
    ) -> list[Paper]:
        """List active papers missing translation or structured summary fields."""
        records: list[DashboardPaperRecord] = []
        for paper in self.list_active_papers():
            if not paper.abstract:
                continue
            translation_missing = require_translation and not paper.abstract_translation
            summary_missing = require_summary and not all(
                [
                    paper.tldr,
                    paper.motivation,
                    paper.problem,
                    paper.conclusion,
                    paper.method,
                    paper.result,
                ]
            )
            if translation_missing or summary_missing:
                records.append(paper)
        return [_record_to_paper(record) for record in records]

    def list_active_papers_missing_theme_contribution(
        self,
        theme_id: int,
        *,
        query_labels: tuple[str, ...] = (),
    ) -> list[Paper]:
        """List active papers that do not yet have a contribution score for one theme."""
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                """
                WITH latest_content AS (
                    SELECT
                        c.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY c.source, c.source_id
                            ORDER BY c.fetched_at DESC, c.id DESC
                        ) AS rn
                    FROM paper_content c
                ),
                latest_theme AS (
                    SELECT
                        c.source,
                        c.source_id,
                        tc.research_theme_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY tc.research_theme_id, c.source, c.source_id
                            ORDER BY tc.generated_at DESC, tc.id DESC
                        ) AS rn
                    FROM theme_contributions tc
                    JOIN paper_content c ON c.id = tc.paper_content_id
                    WHERE tc.research_theme_id = ?
                )
                SELECT
                    lc.source,
                    lc.source_id,
                    lc.title,
                    lc.authors,
                    lc.abstract,
                    lc.published_at,
                    lc.updated_at,
                    lc.primary_category,
                    lc.categories,
                    lc.abstract_url,
                    lc.pdf_url,
                    lc.doi,
                    lc.extra
                FROM seen_papers s
                JOIN latest_content lc
                  ON lc.source = s.source
                 AND lc.source_id = s.source_id
                 AND lc.rn = 1
                LEFT JOIN latest_theme tt
                  ON tt.source = s.source
                 AND tt.source_id = s.source_id
                 AND tt.research_theme_id = ?
                 AND tt.rn = 1
                WHERE s.archived_at IS NULL
                  AND COALESCE(lc.abstract, '') <> ''
                  AND tt.source IS NULL
                ORDER BY COALESCE(lc.updated_at, lc.published_at, lc.fetched_at) DESC, lc.id DESC
                """,
                (theme_id, theme_id),
            )
            rows = cursor.fetchall()

        papers: list[Paper] = []
        normalized_labels = {label.strip().casefold() for label in query_labels if label.strip()}
        for row in rows:
            extra = _parse_json_object(row[12])
            matched_query = str(extra.get("matched_query") or "").strip().casefold()
            if normalized_labels and matched_query not in normalized_labels:
                continue
            papers.append(
                Paper(
                    source=str(row[0]),
                    id=str(row[1]),
                    title=str(row[2]),
                    authors=tuple(_parse_json_list(row[3])),
                    abstract=str(row[4]),
                    published=_timestamp_to_datetime(_to_optional_int(row[5])),
                    updated=_timestamp_to_datetime(_to_optional_int(row[6])),
                    primary_category=_to_optional_str(row[7]),
                    categories=tuple(_parse_json_list(row[8])),
                    links=PaperLinks(
                        abstract=_to_optional_str(row[9]),
                        pdf=_to_optional_str(row[10]),
                    ),
                    doi=_to_optional_str(row[11]),
                    extra=extra,
                )
            )
        return papers

    def save_theme_contributions(
        self,
        *,
        theme_id: int,
        provider: str,
        model: str,
        infos: list[ThemeContributionInfo],
    ) -> None:
        """Persist theme contribution scores using the latest paper_content row."""
        if not infos:
            return
        timestamp = int(datetime.now().timestamp())
        rows: list[tuple[int, int, str, str, int, str | None]] = []

        with self.db_manager.connection() as conn:
            for info in infos:
                paper_row = conn.execute(
                    """
                    SELECT id
                    FROM paper_content
                    WHERE source = ? AND source_id = ?
                    ORDER BY fetched_at DESC, id DESC
                    LIMIT 1
                    """,
                    (info.source, info.source_id),
                ).fetchone()
                if paper_row is None:
                    continue
                rows.append(
                    (
                        theme_id,
                        int(paper_row[0]),
                        provider,
                        model,
                        int(info.contribution_score),
                        info.rationale,
                    )
                )
            if not rows:
                return
            conn.executemany(
                """
                INSERT INTO theme_contributions (
                    research_theme_id,
                    paper_content_id,
                    generated_at,
                    provider,
                    model,
                    contribution_score,
                    rationale
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (theme_id, paper_content_id, timestamp, provider, model, score, rationale)
                    for theme_id, paper_content_id, provider, model, score, rationale in rows
                ],
            )
            conn.commit()

    def _list_papers(self, *, archived: bool, theme_id: int | None) -> list[DashboardPaperRecord]:
        """Query latest paper rows joined with latest LLM enrichment."""
        comparison = "IS NOT NULL" if archived else "IS NULL"
        theme_select = "NULL AS contribution_score, NULL AS rationale"
        theme_join = ""
        params: tuple[Any, ...] = ()
        if theme_id is not None:
            theme_select = "theme.contribution_score, theme.rationale"
            theme_join = """
            LEFT JOIN latest_theme theme
              ON theme.research_theme_id = ?
             AND theme.source = s.source
             AND theme.source_id = s.source_id
             AND theme.rn = 1
            """
            params = (theme_id,)
        with self.db_manager.connection() as conn:
            cursor = conn.execute(
                f"""
                WITH latest_content AS (
                    SELECT
                        c.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY c.source, c.source_id
                            ORDER BY c.fetched_at DESC, c.id DESC
                        ) AS rn
                    FROM paper_content c
                ),
                latest_llm AS (
                    SELECT
                        c.source,
                        c.source_id,
                        l.abstract_translation,
                        l.summary_tldr,
                        l.summary_motivation,
                        l.summary_problem,
                        l.summary_method,
                        l.summary_result,
                        l.summary_conclusion,
                        ROW_NUMBER() OVER (
                            PARTITION BY c.source, c.source_id
                            ORDER BY l.generated_at DESC, l.id DESC
                        ) AS rn
                    FROM llm_generated l
                    JOIN paper_content c ON c.id = l.paper_content_id
                ),
                latest_theme AS (
                    SELECT
                        tc.research_theme_id,
                        c.source,
                        c.source_id,
                        tc.contribution_score,
                        tc.rationale,
                        ROW_NUMBER() OVER (
                            PARTITION BY tc.research_theme_id, c.source, c.source_id
                            ORDER BY tc.generated_at DESC, tc.id DESC
                        ) AS rn
                    FROM theme_contributions tc
                    JOIN paper_content c ON c.id = tc.paper_content_id
                )
                SELECT
                    s.source,
                    s.source_id,
                    lc.title,
                    lc.authors,
                    lc.abstract,
                    lc.published_at,
                    lc.updated_at,
                    lc.fetched_at,
                    lc.primary_category,
                    lc.categories,
                    lc.abstract_url,
                    lc.pdf_url,
                    lc.doi,
                    lc.extra,
                    llm.abstract_translation,
                    llm.summary_tldr,
                    llm.summary_motivation,
                    llm.summary_problem,
                    llm.summary_method,
                    llm.summary_result,
                    llm.summary_conclusion,
                    {theme_select},
                    s.archived_at
                FROM seen_papers s
                JOIN latest_content lc
                  ON lc.source = s.source
                 AND lc.source_id = s.source_id
                 AND lc.rn = 1
                LEFT JOIN latest_llm llm
                  ON llm.source = s.source
                 AND llm.source_id = s.source_id
                 AND llm.rn = 1
                {theme_join}
                WHERE s.archived_at {comparison}
                ORDER BY COALESCE(lc.updated_at, lc.published_at, lc.fetched_at) DESC, lc.id DESC
                """,
                params,
            )
            return [_row_to_record(row) for row in cursor.fetchall()]

    def _build_theme_board(self, theme: ResearchThemeRecord) -> dict[str, Any]:
        """Build one theme-specific board payload."""
        papers = [
            paper
            for paper in self._list_papers(archived=False, theme_id=theme.id)
            if paper.theme_contribution_score is not None
        ]
        return {
            "theme": theme.to_dict(),
            "paper_count": len(papers),
            "query_labels": self.list_theme_query_labels(theme.id),
            "papers": [paper.to_dict() for paper in papers],
        }

    def theme_queries_table_exists(self) -> bool:
        """Return whether the per-theme query table already exists."""
        is_postgres = getattr(self.db_manager, "db_type", "sqlite") == "postgres"
        with self.db_manager.connection() as conn:
            if is_postgres:
                row = conn.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'theme_queries' LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'theme_queries' LIMIT 1"
                ).fetchone()
        return row is not None

    def ensure_theme_queries_table(self) -> None:
        """Create theme query assignment table lazily for legacy SQLite databases."""
        if self._theme_queries_ready:
            return
        if getattr(self.db_manager, "db_type", "sqlite") == "postgres":
            # PostgreSQL: table is always created by migration runner on startup.
            self._theme_queries_ready = True
            return
        with self.db_manager.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS theme_queries (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  research_theme_id INTEGER NOT NULL,
                  label TEXT NOT NULL,
                  position INTEGER NOT NULL DEFAULT 0,
                  created_at INTEGER NOT NULL DEFAULT (CAST(strftime('%s','now') AS INTEGER)),
                  UNIQUE(research_theme_id, label),
                  FOREIGN KEY (research_theme_id) REFERENCES research_themes(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_theme_queries_theme_position
                  ON theme_queries(research_theme_id, position, id)
                """
            )
            conn.commit()
        self._theme_queries_ready = True


def _row_to_record(row: tuple[Any, ...]) -> DashboardPaperRecord:
    """Map one SQL row to a dashboard record."""
    extra = _parse_json_object(row[13])
    authors = _parse_json_list(row[3])
    categories = _parse_json_list(row[9])
    matched_query = extra.get("matched_query")
    ccf_rank = extra.get("ccf_rank")
    ccf_venue = extra.get("ccf_venue")
    return DashboardPaperRecord(
        source=str(row[0]),
        source_id=str(row[1]),
        title=str(row[2]),
        authors=tuple(authors),
        abstract=str(row[4]),
        published_at=_to_optional_int(row[5]),
        updated_at=_to_optional_int(row[6]),
        fetched_at=int(row[7]),
        primary_category=_to_optional_str(row[8]),
        categories=tuple(categories),
        abstract_url=_to_optional_str(row[10]),
        pdf_url=_to_optional_str(row[11]),
        doi=_to_optional_str(row[12]),
        matched_query=str(matched_query) if isinstance(matched_query, str) and matched_query.strip() else None,
        ccf_rank=str(ccf_rank) if isinstance(ccf_rank, str) and ccf_rank.strip() else None,
        ccf_venue=str(ccf_venue) if isinstance(ccf_venue, str) and ccf_venue.strip() else None,
        abstract_translation=_to_optional_str(row[14]),
        tldr=_to_optional_str(row[15]),
        motivation=_to_optional_str(row[16]),
        problem=_to_optional_str(row[17]),
        method=_to_optional_str(row[18]),
        result=_to_optional_str(row[19]),
        conclusion=_to_optional_str(row[20]),
        theme_contribution_score=_to_optional_int(row[21]),
        theme_contribution_rationale=_to_optional_str(row[22]),
        archived_at=_to_optional_int(row[23]),
    )


def _parse_json_list(raw: Any) -> list[str]:
    """Parse a JSON array of strings safely."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if isinstance(item, str)]


def _parse_json_object(raw: Any) -> dict[str, Any]:
    """Parse a JSON object safely."""
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(data) if isinstance(data, dict) else {}


def _to_optional_int(value: Any) -> int | None:
    """Convert numeric DB value to int or None."""
    if isinstance(value, int):
        return value
    return None


def _to_optional_str(value: Any) -> str | None:
    """Convert DB value to non-empty string or None."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _format_timestamp(value: int | None, *, include_time: bool = False) -> str | None:
    """Format unix timestamp into local display string."""
    if value is None:
        return None
    fmt = "%Y-%m-%d %H:%M" if include_time else "%Y-%m-%d"
    return datetime.fromtimestamp(value).strftime(fmt)


def _record_to_paper(record: DashboardPaperRecord) -> Paper:
    """Convert a dashboard record back to the core paper model."""
    extra: dict[str, Any] = {}
    if record.matched_query:
        extra["matched_query"] = record.matched_query
    if record.ccf_rank:
        extra["ccf_rank"] = record.ccf_rank
    if record.ccf_venue:
        extra["ccf_venue"] = record.ccf_venue
    return Paper(
        source=record.source,
        id=record.source_id,
        title=record.title,
        authors=record.authors,
        abstract=record.abstract,
        published=_timestamp_to_datetime(record.published_at),
        updated=_timestamp_to_datetime(record.updated_at),
        primary_category=record.primary_category,
        categories=record.categories,
        links=PaperLinks(
            abstract=record.abstract_url,
            pdf=record.pdf_url,
        ),
        doi=record.doi,
        extra=extra,
    )


def _timestamp_to_datetime(value: int | None) -> datetime | None:
    """Convert unix timestamp to local datetime object."""
    if value is None:
        return None
    return datetime.fromtimestamp(value)
