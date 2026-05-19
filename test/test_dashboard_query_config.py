"""Tests for dashboard query config editing."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.dashboard.query_config import DashboardQueryConfig


class TestDashboardQueryConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.config_path = Path(self._tmpdir.name) / "custom.yml"
        self.config_path.write_text(
            yaml.safe_dump(
                {
                    "queries": [
                        {"NAME": "existing_query", "OR": ["existing query"]},
                    ]
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_add_query_appends_new_item(self) -> None:
        config = DashboardQueryConfig(self.config_path)

        config.add_query("new query phrase")

        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            data["queries"][-1],
            {"NAME": "new query phrase", "OR": ["new query phrase"]},
        )

    def test_delete_query_removes_matching_label(self) -> None:
        config = DashboardQueryConfig(self.config_path)

        config.delete_query("existing query")

        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(data["queries"], [])


if __name__ == "__main__":
    unittest.main()
