"""LLM provider protocol and base types."""

from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    """Protocol for LLM providers.

    Implementations must support generating enrichment fields, such as translation.
    """

    name: str

    def translate_abstract(
        self,
        abstract: str,
        target_lang: str = "Simplified Chinese",
    ) -> str:
        """Translate paper abstract.

        Args:
            abstract: Paper abstract in English.
            target_lang: Target language description (for example, Simplified Chinese).

        Returns:
            Translated abstract text.

        Raises:
            Exception: If translation fails (caller should handle gracefully).
        """
        raise NotImplementedError

    def generate_summary(
        self,
        abstract: str,
        target_lang: str = "Simplified Chinese",
    ) -> dict[str, str]:
        """Generate structured summary from paper abstract.

        Args:
            abstract: Paper abstract in English.
            target_lang: Target language for summary.

        Returns:
            Dictionary with keys: tldr, motivation, method, result, conclusion.
            All values are strings.

        Raises:
            Exception: If generation fails (caller should handle gracefully).
        """
        raise NotImplementedError

    def evaluate_theme_contribution(
        self,
        *,
        title: str,
        abstract: str,
        theme_name: str,
        theme_description: str,
        target_lang: str = "Simplified Chinese",
    ) -> dict[str, str | int]:
        """Evaluate how much a paper contributes to the active research theme."""
        raise NotImplementedError

    def suggest_theme_queries(
        self,
        *,
        theme_name: str,
        theme_description: str,
        target_lang: str = "Simplified Chinese",
    ) -> list[str]:
        """Suggest search queries for one user-defined research theme."""
        raise NotImplementedError
