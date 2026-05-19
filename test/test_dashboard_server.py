"""Tests for dashboard server helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.dashboard.server import _normalize_selected_sources


class TestDashboardServer(unittest.TestCase):
    def test_normalize_selected_sources_preserves_config_order_and_uniqueness(self) -> None:
        selected = _normalize_selected_sources(
            ["OpenAlex", "arxiv", "openalex", "invalid"],
            ("dblp", "openreview", "arxiv", "openalex"),
        )
        self.assertEqual(selected, ("openalex", "arxiv"))

    def test_normalize_selected_sources_rejects_non_list_payload(self) -> None:
        self.assertEqual(
            _normalize_selected_sources("arxiv", ("dblp", "arxiv")),
            (),
        )


if __name__ == "__main__":
    unittest.main()
