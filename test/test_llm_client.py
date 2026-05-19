"""Tests for LLM API client helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.llm.client import LLMApiClient, normalize_models_endpoint


class TestLLMClient(unittest.TestCase):
    def test_normalize_models_endpoint_accepts_base_url(self) -> None:
        self.assertEqual(
            normalize_models_endpoint("https://api.example.com"),
            "https://api.example.com/v1/models",
        )
        self.assertEqual(
            normalize_models_endpoint("https://api.example.com/v1"),
            "https://api.example.com/v1/models",
        )
        self.assertEqual(
            normalize_models_endpoint("https://api.example.com/v1/chat/completions"),
            "https://api.example.com/v1/models",
        )

    @patch("PaperTracker.llm.client.requests.get")
    def test_list_models_extracts_unique_ids(self, mock_get: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "data": [
                {"id": "gpt-4o-mini"},
                {"id": "deepseek-chat"},
                {"id": "gpt-4o-mini"},
                {"name": "missing-id"},
            ]
        }
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        client = LLMApiClient(base_url="https://api.example.com", api_key="test-key")

        self.assertEqual(client.list_models(), ["gpt-4o-mini", "deepseek-chat"])
        mock_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
