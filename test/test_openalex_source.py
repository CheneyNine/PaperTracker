"""Tests for OpenAlex venue to CCF matching."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.ccf import CCFVenueStore
from PaperTracker.core.models import Paper
from PaperTracker.core.query import FieldQuery, SearchQuery
from PaperTracker.sources.openalex.source import OpenAlexSource


class _DummyClient:
    def close(self) -> None:
        return None


class _DummySearchConfig:
    max_results = 5
    ccf_enabled = True
    ccf_ranks = ("A", "B")


class TestOpenAlexSource(unittest.TestCase):
    def test_search_attaches_ccf_metadata_from_venue_name(self) -> None:
        paper = Paper(
            source="openalex",
            id="W1",
            title="Test AAAI Paper",
            authors=("Ada Lovelace",),
            abstract="Benchmark paper.",
            published=None,
            updated=None,
            extra={
                "work_type": "article",
                "venue_name": "Proceedings of the AAAI Conference on Artificial Intelligence",
                "venue_type": "conference",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = OpenAlexSource(
                client=_DummyClient(),
                search_config=_DummySearchConfig(),
                venue_store=CCFVenueStore(Path(tmp) / "ccf_venues.json"),
            )
            query = SearchQuery(name="traffic", fields={"TEXT": FieldQuery(OR=("traffic",))})
            with patch(
                "PaperTracker.sources.openalex.source.collect_papers_with_time_filter_openalex",
                return_value=[paper],
            ):
                papers = source.search(query, max_results=5)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].extra.get("venue"), "AAAI")
        self.assertEqual(
            papers[0].extra.get("venue_name"),
            "Proceedings of the AAAI Conference on Artificial Intelligence",
        )
        self.assertEqual(papers[0].extra.get("venue_type"), "conference")
        self.assertEqual(papers[0].extra.get("ccf_rank"), "CCF-A")
        self.assertEqual(papers[0].extra.get("ccf_venue"), "AAAI")


if __name__ == "__main__":
    unittest.main()
