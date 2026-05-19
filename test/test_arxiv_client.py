"""Tests for arXiv rate limiting behavior."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.sources.arxiv.client import ArxivApiClient, ArxivRateLimitedError, _parse_retry_after_seconds


class TestArxivApiClient(unittest.TestCase):
    def test_wait_for_request_slot_persists_shared_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "arxiv-rate-limit.json"
            first = ArxivApiClient(
                min_interval_seconds=5.0,
                rate_limit_state_path=state_path,
            )

            with patch("PaperTracker.sources.arxiv.client.time.time", side_effect=[100.0]):
                with patch("PaperTracker.sources.arxiv.client.time.sleep") as sleep:
                    first._wait_for_request_slot()
                sleep.assert_not_called()

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["next_allowed_at"], 105.0)

            second = ArxivApiClient(
                min_interval_seconds=5.0,
                rate_limit_state_path=state_path,
            )
            with patch("PaperTracker.sources.arxiv.client.time.time", side_effect=[102.0, 105.0]):
                with patch("PaperTracker.sources.arxiv.client.time.sleep") as sleep:
                    second._wait_for_request_slot()
                sleep.assert_called_once_with(3.0)

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["next_allowed_at"], 110.0)

    def test_parse_retry_after_seconds_supports_numeric_header(self) -> None:
        response = Mock()
        response.headers = {"Retry-After": "17"}
        self.assertEqual(_parse_retry_after_seconds(response), 17.0)

    def test_parse_retry_after_seconds_invalid_header_returns_none(self) -> None:
        response = Mock()
        response.headers = {"Retry-After": "not-a-delay"}
        self.assertIsNone(_parse_retry_after_seconds(response))

    def test_http_429_aborts_early_and_persists_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "arxiv-rate-limit.json"
            client = ArxivApiClient(
                min_interval_seconds=5.0,
                rate_limit_state_path=state_path,
            )
            response = Mock()
            response.status_code = 429
            response.headers = {"Retry-After": "17"}
            client._session.get = Mock(return_value=response)

            with patch.object(client, "_wait_for_request_slot") as wait_slot:
                with self.assertRaises(ArxivRateLimitedError):
                    client._get_with_retry("https://example.com", params={}, timeout=5.0)

            wait_slot.assert_called_once()
            self.assertGreaterEqual(client.current_cooldown_seconds(), 0.0)


if __name__ == "__main__":
    unittest.main()
