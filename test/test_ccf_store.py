"""Tests for CCF venue matching helpers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.ccf import CCFVenueStore


class TestCCFVenueStore(unittest.TestCase):
    def test_match_venue_name_accepts_proceedings_style_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CCFVenueStore(Path(tmp) / "ccf_venues.json")
            matched = store.match_venue_name(
                "Proceedings of the AAAI Conference on Artificial Intelligence",
                venue_type="conference",
            )
        self.assertIsNotNone(matched)
        self.assertEqual(matched.short_name, "AAAI")
        self.assertEqual(matched.rank, "A")


if __name__ == "__main__":
    unittest.main()
