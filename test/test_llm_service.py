"""Tests for LLM service helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PaperTracker.llm.service import LLMService


class _FakeProvider:
    name = "fake"

    def translate_abstract(self, abstract: str, target_lang: str = "Simplified Chinese") -> str:
        return ""

    def generate_summary(self, abstract: str, target_lang: str = "Simplified Chinese") -> dict[str, str]:
        return {}

    def evaluate_theme_contribution(
        self,
        *,
        title: str,
        abstract: str,
        theme_name: str,
        theme_description: str,
        target_lang: str = "Simplified Chinese",
    ) -> dict[str, str | int]:
        return {"contribution_score": 0, "rationale": ""}

    def suggest_theme_queries(
        self,
        *,
        theme_name: str,
        theme_description: str,
        target_lang: str = "Simplified Chinese",
    ) -> list[str]:
        return [
            "traffic llm reasoning",
            "traffic llm reasoning",
            " urban mobility qa ",
            "",
            "交通问答 traffic question answering",
            "12345",
        ]


class TestLLMService(unittest.TestCase):
    def test_generate_theme_query_suggestions_deduplicates_and_normalizes(self) -> None:
        service = LLMService(provider=_FakeProvider(), enabled=True)

        results = service.generate_theme_query_suggestions(
            theme_name="城市交通时空问答数据集",
            theme_description="研究交通领域的时空问答数据集与基准。",
        )

        self.assertEqual(
            results,
            [
                "traffic llm reasoning",
                "urban mobility qa",
            ],
        )


if __name__ == "__main__":
    unittest.main()
