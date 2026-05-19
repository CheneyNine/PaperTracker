"""Tests for arXiv source query gating."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.core.query import FieldQuery, SearchQuery
from PaperTracker.sources.arxiv.source import _supports_arxiv_query, ArxivSource


class _DummyClient:
    def __init__(self, cooldown_seconds: float = 0.0) -> None:
        self._cooldown_seconds = cooldown_seconds

    def current_cooldown_seconds(self) -> float:
        return self._cooldown_seconds

    def close(self) -> None:
        return None


class _DummySearchConfig:
    max_results = 5


class TestArxivSource(unittest.TestCase):
    def test_supports_arxiv_query_rejects_non_ascii_only_terms(self) -> None:
        query = SearchQuery(
            name="城市交通时空问答数据集",
            fields={"TEXT": FieldQuery(OR=("城市交通时空问答数据集",))},
        )
        self.assertFalse(_supports_arxiv_query(query, None))

    def test_supports_arxiv_query_accepts_english_terms(self) -> None:
        query = SearchQuery(
            name="spatio temporal qa dataset",
            fields={"TEXT": FieldQuery(OR=("spatio-temporal question answering",))},
        )
        self.assertTrue(_supports_arxiv_query(query, None))

    def test_search_skips_arxiv_for_non_ascii_only_query(self) -> None:
        source = ArxivSource(
            client=_DummyClient(),
            search_config=_DummySearchConfig(),
        )
        query = SearchQuery(
            name="城市交通时空问答数据集",
            fields={"TEXT": FieldQuery(OR=("城市交通时空问答数据集",))},
        )
        with patch("PaperTracker.sources.arxiv.source.collect_papers_with_time_filter") as collect_mock:
            result = source.search(query, max_results=5)
        self.assertEqual(result, [])
        collect_mock.assert_not_called()

    def test_search_skips_arxiv_when_client_cooldown_is_active(self) -> None:
        source = ArxivSource(
            client=_DummyClient(cooldown_seconds=30.0),
            search_config=_DummySearchConfig(),
        )
        query = SearchQuery(
            name="spatio temporal qa dataset",
            fields={"TEXT": FieldQuery(OR=("spatio-temporal question answering",))},
        )
        with patch("PaperTracker.sources.arxiv.source.collect_papers_with_time_filter") as collect_mock:
            result = source.search(query, max_results=5)
        self.assertEqual(result, [])
        collect_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
