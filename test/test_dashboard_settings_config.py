"""Tests for dashboard settings configuration helpers."""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.dashboard.settings_config import DashboardSettingsConfig


class TestDashboardSettingsConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.config_path = Path(self._tmpdir.name) / "custom.yml"
        self.env_path = Path(self._tmpdir.name) / ".env"
        self.config_path.write_text(
            textwrap.dedent(
                """
                storage:
                  enabled: true
                  content_storage_enabled: true
                search:
                  sources: [arxiv, openalex]
                  ccf_enabled: true
                  ccf_ranks: [A, B]
                queries:
                - NAME: traffic
                  OR: [traffic]
                llm:
                  enabled: true
                  provider: openai-compat
                  base_url: https://api.example.com
                  model: gpt-4o-mini
                  api_key_env: LLM_API_KEY
                  target_lang: Simplified Chinese
                  enable_translation: true
                  enable_summary: true
                """
            ).strip() + "\n",
            encoding="utf-8",
        )
        self.env_path.write_text("LLM_API_KEY=old-key\nNCBI_API_KEY=old-ncbi\n", encoding="utf-8")
        self._old_llm_key = os.getenv("LLM_API_KEY")
        self._old_ncbi_key = os.getenv("NCBI_API_KEY")
        os.environ["LLM_API_KEY"] = "old-key"
        os.environ["NCBI_API_KEY"] = "old-ncbi"

    def tearDown(self) -> None:
        if self._old_llm_key is None:
            os.environ.pop("LLM_API_KEY", None)
        else:
            os.environ["LLM_API_KEY"] = self._old_llm_key
        if self._old_ncbi_key is None:
            os.environ.pop("NCBI_API_KEY", None)
        else:
            os.environ["NCBI_API_KEY"] = self._old_ncbi_key
        self._tmpdir.cleanup()

    def test_save_settings_updates_yaml_and_env(self) -> None:
        helper = DashboardSettingsConfig(self.config_path, self.env_path)

        settings = helper.save_settings(
            {
                "llm": {
                    "enabled": True,
                    "provider": "openai-compat",
                    "base_url": "https://api.changed.example.com",
                    "model": "gpt-4.1-mini",
                    "target_lang": "Simplified Chinese",
                    "api_key": "new-key",
                    "enable_translation": True,
                    "enable_summary": False,
                },
                "search": {
                    "sources": ["dblp", "openreview", "openalex"],
                    "ccf_enabled": True,
                    "ccf_ranks": ["A", "B"],
                    "arxiv_min_interval_seconds": 9.5,
                    "ncbi_api_key": "new-ncbi",
                },
            }
        )

        self.assertEqual(settings["llm"]["model"], "gpt-4.1-mini")
        self.assertEqual(settings["search"]["sources"], ["dblp", "openreview", "openalex"])
        self.assertEqual(os.environ["LLM_API_KEY"], "new-key")
        self.assertEqual(os.environ["NCBI_API_KEY"], "new-ncbi")
        yaml_text = self.config_path.read_text(encoding="utf-8")
        env_text = self.env_path.read_text(encoding="utf-8")
        self.assertIn("model: gpt-4.1-mini", yaml_text)
        self.assertIn("sources:", yaml_text)
        self.assertIn("- dblp", yaml_text)
        self.assertIn("LLM_API_KEY=new-key", env_text)
        self.assertIn("NCBI_API_KEY=new-ncbi", env_text)


if __name__ == "__main__":
    unittest.main()
