"""Tests for dashboard storage queries and archive state."""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.core.models import ThemeContributionInfo
from PaperTracker.storage.dashboard import DashboardStore
from PaperTracker.storage.migration import run_migrations


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(path))


class _FakeDbManager:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_connection(self) -> sqlite3.Connection:
        return self._conn


class TestDashboardStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmpdir.name) / "dashboard.db"
        self._conn = _connect(self._db_path)
        run_migrations(self._conn)

        self._conn.execute(
            """
            INSERT INTO seen_papers (
                source, source_id, doi, title, title_author_year_fingerprint
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("arxiv", "2501.00001", "10.1000/example", "Test Paper", "fp-1"),
        )
        seen_id = self._conn.execute(
            "SELECT id FROM seen_papers WHERE source = ? AND source_id = ?",
            ("arxiv", "2501.00001"),
        ).fetchone()[0]

        self._conn.execute(
            """
            INSERT INTO paper_content (
                seen_paper_id, source, source_id, title, authors, abstract,
                published_at, updated_at, fetched_at, primary_category, categories,
                abstract_url, pdf_url, doi, extra
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seen_id,
                "arxiv",
                "2501.00001",
                "Test Paper",
                json.dumps(["Ada Lovelace"]),
                "A test abstract.",
                1704067200,
                1704153600,
                1704240000,
                "cs.AI",
                json.dumps(["cs.AI", "cs.LG"]),
                "https://arxiv.org/abs/2501.00001",
                "https://arxiv.org/pdf/2501.00001",
                "10.1000/example",
                json.dumps({"matched_query": "q1"}),
            ),
        )
        paper_content_id = self._conn.execute(
            "SELECT id FROM paper_content WHERE source = ? AND source_id = ?",
            ("arxiv", "2501.00001"),
        ).fetchone()[0]
        self._conn.execute(
            """
            INSERT INTO llm_generated (
                paper_content_id, provider, model, language, abstract_translation, summary_tldr
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                paper_content_id,
                "openai-compat",
                "gpt-4o-mini",
                "Simplified Chinese",
                "测试翻译",
                "测试 TLDR",
            ),
        )
        self._conn.commit()
        self.store = DashboardStore(_FakeDbManager(self._conn))

    def tearDown(self) -> None:
        self._conn.close()
        self._tmpdir.cleanup()

    def test_list_active_papers_returns_latest_row(self) -> None:
        papers = self.store.list_active_papers()
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.title, "Test Paper")
        self.assertEqual(paper.matched_query, "q1")
        self.assertEqual(paper.abstract_translation, "测试翻译")
        self.assertEqual(paper.tldr, "测试 TLDR")

    def test_archive_moves_paper_out_of_active_list(self) -> None:
        self.store.archive_paper("arxiv", "2501.00001")
        self.assertEqual(self.store.list_active_papers(), [])
        archived = self.store.list_archived_papers()
        self.assertEqual(len(archived), 1)
        self.assertIsNotNone(archived[0].archived_at)

    def test_restore_returns_paper_to_active_list(self) -> None:
        self.store.archive_paper("arxiv", "2501.00001")
        self.store.restore_paper("arxiv", "2501.00001")
        self.assertEqual(len(self.store.list_active_papers()), 1)
        self.assertEqual(self.store.list_archived_papers(), [])

    def test_archive_active_papers_for_query_only_archives_matching_active_rows(self) -> None:
        self._conn.execute(
            """
            INSERT INTO seen_papers (
                source, source_id, doi, title, title_author_year_fingerprint
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("openalex", "W1", "10.1000/example-2", "Second Paper", "fp-2"),
        )
        seen_id = self._conn.execute(
            "SELECT id FROM seen_papers WHERE source = ? AND source_id = ?",
            ("openalex", "W1"),
        ).fetchone()[0]
        self._conn.execute(
            """
            INSERT INTO paper_content (
                seen_paper_id, source, source_id, title, authors, abstract,
                published_at, updated_at, fetched_at, primary_category, categories,
                abstract_url, pdf_url, doi, extra
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seen_id,
                "openalex",
                "W1",
                "Second Paper",
                json.dumps(["Grace Hopper"]),
                "Another abstract.",
                1704067200,
                1704153600,
                1704240000,
                "cs.CL",
                json.dumps(["cs.CL"]),
                "https://example.com/abs",
                "https://example.com/pdf",
                "10.1000/example-2",
                json.dumps({"matched_query": "q2"}),
            ),
        )
        self._conn.commit()

        archived_count = self.store.archive_active_papers_for_query("q1")

        self.assertEqual(archived_count, 1)
        self.assertEqual([paper.matched_query for paper in self.store.list_active_papers()], ["q2"])
        self.assertEqual(len(self.store.list_archived_papers()), 1)

    def test_list_active_papers_missing_enrichment_detects_missing_summary(self) -> None:
        self._conn.execute("DELETE FROM llm_generated")
        paper_content_id = self._conn.execute(
            "SELECT id FROM paper_content WHERE source = ? AND source_id = ?",
            ("arxiv", "2501.00001"),
        ).fetchone()[0]
        self._conn.execute(
            """
            INSERT INTO llm_generated (
                paper_content_id, provider, model, language, abstract_translation
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                paper_content_id,
                "openai-compat",
                "gpt-4o-mini",
                "Simplified Chinese",
                "只有翻译",
            ),
        )
        self._conn.commit()

        papers = self.store.list_active_papers_missing_enrichment(
            require_translation=True,
            require_summary=True,
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].id, "2501.00001")

    def test_research_theme_contribution_roundtrip(self) -> None:
        theme = self.store.create_research_theme(
            "时空问答",
            "关注时空问答数据集、基准和知识图谱推理能力。",
        )
        self.assertEqual(self.store.list_theme_query_labels(theme.id), [])

        missing = self.store.list_active_papers_missing_theme_contribution(theme.id)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].id, "2501.00001")

        self.store.save_theme_contributions(
            theme_id=theme.id,
            provider="openai-compat",
            model="gpt-4o-mini",
            infos=[
                ThemeContributionInfo(
                    source="arxiv",
                    source_id="2501.00001",
                    contribution_score=82,
                    rationale="直接覆盖时空问答任务定义。",
                )
            ],
        )

        snapshot = self.store.get_snapshot()
        self.assertEqual(snapshot["research_themes"][0]["name"], "时空问答")
        self.assertEqual(len(snapshot["theme_boards"]), 1)
        self.assertEqual(snapshot["theme_boards"][0]["theme"]["name"], "时空问答")
        self.assertEqual(snapshot["theme_boards"][0]["papers"][0]["theme_contribution_score"], 82)
        self.assertEqual(
            snapshot["theme_boards"][0]["papers"][0]["theme_contribution_rationale"],
            "直接覆盖时空问答任务定义。",
        )
        self.assertEqual(self.store.list_active_papers_missing_theme_contribution(theme.id), [])

    def test_multiple_research_themes_keep_independent_boards(self) -> None:
        theme_one = self.store.create_research_theme("主题一", "描述一")
        theme_two = self.store.create_research_theme("主题二", "描述二")

        self.store.save_theme_contributions(
            theme_id=theme_one.id,
            provider="openai-compat",
            model="gpt-4o-mini",
            infos=[
                ThemeContributionInfo(
                    source="arxiv",
                    source_id="2501.00001",
                    contribution_score=60,
                    rationale="主题一匹配。",
                )
            ],
        )
        self.store.save_theme_contributions(
            theme_id=theme_two.id,
            provider="openai-compat",
            model="gpt-4o-mini",
            infos=[
                ThemeContributionInfo(
                    source="arxiv",
                    source_id="2501.00001",
                    contribution_score=91,
                    rationale="主题二更匹配。",
                )
            ],
        )

        snapshot = self.store.get_snapshot()
        self.assertEqual(len(snapshot["theme_boards"]), 2)
        scores = {
            board["theme"]["name"]: board["papers"][0]["theme_contribution_score"]
            for board in snapshot["theme_boards"]
        }
        self.assertEqual(scores["主题一"], 60)
        self.assertEqual(scores["主题二"], 91)

    def test_theme_query_labels_remain_scoped_per_theme_board(self) -> None:
        theme_one = self.store.create_research_theme("主题一", "描述一")
        theme_two = self.store.create_research_theme("主题二", "描述二")

        self.store.add_theme_query(theme_one.id, "q1")
        self.store.add_theme_query(theme_one.id, "q2")
        self.store.add_theme_query(theme_two.id, "q2")

        self.assertEqual(self.store.list_theme_query_labels(theme_one.id), ["q1", "q2"])
        self.assertEqual(self.store.list_theme_query_labels(theme_two.id), ["q2"])

        boards = {
            board["theme"]["name"]: board["query_labels"]
            for board in self.store.get_snapshot()["theme_boards"]
        }
        self.assertEqual(boards["主题一"], ["q1", "q2"])
        self.assertEqual(boards["主题二"], ["q2"])

    def test_archive_theme_papers_for_query_only_archives_selected_theme_rows(self) -> None:
        self._conn.execute(
            """
            INSERT INTO seen_papers (
                source, source_id, doi, title, title_author_year_fingerprint
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("openalex", "W1", "10.1000/example-2", "Second Paper", "fp-2"),
        )
        second_seen_id = self._conn.execute(
            "SELECT id FROM seen_papers WHERE source = ? AND source_id = ?",
            ("openalex", "W1"),
        ).fetchone()[0]
        self._conn.execute(
            """
            INSERT INTO paper_content (
                seen_paper_id, source, source_id, title, authors, abstract,
                published_at, updated_at, fetched_at, primary_category, categories,
                abstract_url, pdf_url, doi, extra
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                second_seen_id,
                "openalex",
                "W1",
                "Second Paper",
                json.dumps(["Grace Hopper"]),
                "Another abstract.",
                1704067200,
                1704153600,
                1704240000,
                "cs.CL",
                json.dumps(["cs.CL"]),
                "https://example.com/abs",
                "https://example.com/pdf",
                "10.1000/example-2",
                json.dumps({"matched_query": "q1"}),
            ),
        )
        self._conn.commit()

        theme_one = self.store.create_research_theme("主题一", "描述一")
        theme_two = self.store.create_research_theme("主题二", "描述二")
        self.store.add_theme_query(theme_one.id, "q1")
        self.store.add_theme_query(theme_two.id, "q1")

        self.store.save_theme_contributions(
            theme_id=theme_one.id,
            provider="openai-compat",
            model="gpt-4o-mini",
            infos=[
                ThemeContributionInfo(
                    source="arxiv",
                    source_id="2501.00001",
                    contribution_score=80,
                    rationale="主题一命中第一篇。",
                )
            ],
        )
        self.store.save_theme_contributions(
            theme_id=theme_two.id,
            provider="openai-compat",
            model="gpt-4o-mini",
            infos=[
                ThemeContributionInfo(
                    source="openalex",
                    source_id="W1",
                    contribution_score=88,
                    rationale="主题二命中第二篇。",
                )
            ],
        )

        archived_count = self.store.archive_theme_papers_for_query(theme_one.id, "q1")

        self.assertEqual(archived_count, 1)
        active_ids = {(paper.source, paper.source_id) for paper in self.store.list_active_papers()}
        self.assertEqual(active_ids, {("openalex", "W1")})

    def test_theme_query_table_is_created_lazily_for_legacy_database(self) -> None:
        self._conn.execute("DROP TABLE theme_queries")
        self._conn.commit()

        theme = self.store.create_research_theme("主题一", "描述一")
        self.store.add_theme_query(theme.id, "q1")

        self.assertEqual(self.store.list_theme_query_labels(theme.id), ["q1"])

    def test_delete_all_theme_queries_keeps_theme_empty(self) -> None:
        theme = self.store.create_research_theme("主题一", "描述一")
        self.store.add_theme_query(theme.id, "q1")
        self.store.delete_theme_query(theme.id, "q1")

        self.assertTrue(self.store.theme_queries_table_exists())
        self.assertEqual(self.store.list_theme_query_labels(theme.id), [])
