"""LLM Enrichment Service.

Coordinates batch enrichment with concurrency, calls provider operations, and merges generated outputs into paper objects.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import re
from typing import Sequence

from PaperTracker.core.models import LLMGeneratedInfo, Paper, ThemeContributionInfo
from PaperTracker.llm.provider import LLMProvider
from PaperTracker.utils.log import log

_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


@dataclass(slots=True)
class LLMService:
    """High-level service for LLM-powered paper enhancement.

    Handles batch processing, concurrency, and error recovery.
    """

    provider: LLMProvider
    target_lang: str = "zh"
    max_workers: int = 3
    enabled: bool = True

    # Feature selection
    enable_translation: bool = True
    enable_summary: bool = True

    def generate_batch(self, papers: Sequence[Paper]) -> list[LLMGeneratedInfo]:
        """Generate LLM enrichment for a batch of papers in parallel.

        Args:
            papers: Papers to enrich.

        Returns:
            List of LLMGeneratedInfo objects for successful generations.
        """
        if not self.enabled or not papers:
            return []

        log.info(
            "Starting LLM batch: papers=%d workers=%d lang=%s translation=%s summary=%s",
            len(papers),
            self.max_workers,
            self.target_lang,
            self.enable_translation,
            self.enable_summary,
        )

        results: list[LLMGeneratedInfo] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_paper = {
                executor.submit(
                    self._generate_single,
                    paper,
                ): paper
                for paper in papers
            }

            for future in as_completed(future_to_paper):
                paper = future_to_paper[future]
                try:
                    info = future.result()
                    if info is not None:
                        results.append(info)
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        "LLM generation failed for paper %s: %s",
                        paper.id,
                        e,
                    )

        log.info(
            "LLM batch complete: success=%d/%d",
            len(results),
            len(papers),
        )

        return results

    def enrich_papers(
        self,
        papers: Sequence[Paper],
        infos: Sequence[LLMGeneratedInfo],
    ) -> list[Paper]:
        """Merge generated LLM information into paper ``extra`` payloads.

        Args:
            papers: Original papers to enrich.
            infos: Generated LLM outputs keyed by source and paper id.

        Returns:
            A new list of papers where matched items contain translation and summary data.
        """
        info_map = {(info.source, info.source_id): info for info in infos}

        enriched: list[Paper] = []
        for paper in papers:
            info = info_map.get((paper.source, paper.id))
            if not info:
                enriched.append(paper)
                continue

            extra_data = dict(paper.extra)

            if info.abstract_translation:
                extra_data["translation"] = {
                    "summary_translated": info.abstract_translation,
                    "language": info.language,
                }

            if info.tldr or info.motivation or info.problem or info.method or info.result or info.conclusion:
                extra_data["summary"] = {
                    "tldr": info.tldr,
                    "motivation": info.motivation,
                    "problem": info.problem,
                    "method": info.method,
                    "result": info.result,
                    "conclusion": info.conclusion,
                }

            enriched.append(
                Paper(
                    source=paper.source,
                    id=paper.id,
                    title=paper.title,
                    authors=paper.authors,
                    abstract=paper.abstract,
                    published=paper.published,
                    updated=paper.updated,
                    primary_category=paper.primary_category,
                    categories=paper.categories,
                    links=paper.links,
                    doi=paper.doi,
                    extra=extra_data,
                )
            )

        return enriched

    def generate_theme_contribution_batch(
        self,
        papers: Sequence[Paper],
        *,
        theme_name: str,
        theme_description: str,
    ) -> list[ThemeContributionInfo]:
        """Generate theme contribution scores for a batch of papers."""
        if not self.enabled or not papers:
            return []

        results: list[ThemeContributionInfo] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_paper = {
                executor.submit(
                    self._generate_single_theme_contribution,
                    paper,
                    theme_name,
                    theme_description,
                ): paper
                for paper in papers
            }
            for future in as_completed(future_to_paper):
                paper = future_to_paper[future]
                try:
                    info = future.result()
                    if info is not None:
                        results.append(info)
                except Exception as e:  # noqa: BLE001
                    log.warning("Theme contribution failed for paper %s: %s", paper.id, e)
        return results

    def generate_theme_query_suggestions(
        self,
        *,
        theme_name: str,
        theme_description: str,
        existing_queries: list[str] | None = None,
    ) -> dict[str, list]:
        """Generate and optimize search query suggestions for one research theme."""
        if not self.enabled:
            return {"new_queries": [], "optimized_queries": []}
        raw = self.provider.suggest_theme_queries(
            theme_name=theme_name,
            theme_description=theme_description,
            existing_queries=existing_queries,
            target_lang=self.target_lang,
        )

        def _is_valid_english(text: str) -> bool:
            return bool(_ASCII_LETTER_RE.search(text)) and not bool(_CJK_RE.search(text))

        def _clean_phrases(items: list) -> list[str]:
            results: list[str] = []
            seen: set[str] = set()
            for item in items:
                normalized = " ".join(str(item).split())
                if not normalized or not _is_valid_english(normalized):
                    continue
                key = normalized.casefold()
                if key in seen:
                    continue
                seen.add(key)
                results.append(normalized)
            return results

        new_queries = _clean_phrases(raw.get("new_queries", []))

        optimized_queries: list[dict[str, str]] = []
        for entry in raw.get("optimized_queries", []):
            if not isinstance(entry, dict):
                continue
            from_val = " ".join(str(entry.get("from", "")).split())
            to_val = " ".join(str(entry.get("to", "")).split())
            if from_val and to_val and _is_valid_english(to_val):
                optimized_queries.append({"from": from_val, "to": to_val})

        return {"new_queries": new_queries, "optimized_queries": optimized_queries}

    def _generate_single(self, paper: Paper) -> LLMGeneratedInfo | None:
        """Generate LLM enrichment for a single paper.

        Generates both translation and summary based on configuration.

        Args:
            paper: Paper to enrich.

        Returns:
            LLMGeneratedInfo on success, otherwise None.
        """
        if not paper.abstract:
            log.debug(
                "Skipping LLM enrichment for paper with missing abstract: source=%s id=%s",
                paper.source,
                paper.id,
            )
            return None

        translation = None
        summary_dict = None

        # Generate translation if enabled
        if self.enable_translation:
            try:
                translation = self.provider.translate_abstract(
                    abstract=paper.abstract,
                    target_lang=self.target_lang,
                )
                translation = translation.strip() or None
            except Exception as e:  # noqa: BLE001
                log.warning("Translation failed for %s: %s", paper.id, e)

        # Generate summary if enabled
        if self.enable_summary:
            try:
                summary_dict = self.provider.generate_summary(
                    abstract=paper.abstract,
                    target_lang=self.target_lang,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Summary generation failed for %s: %s", paper.id, e)

        # Return None if both failed
        if translation is None and summary_dict is None:
            return None

        return LLMGeneratedInfo(
            source=paper.source,
            source_id=paper.id,
            language=self.target_lang,
            abstract_translation=translation,
            tldr=summary_dict.get("tldr") if summary_dict else None,
            motivation=summary_dict.get("motivation") if summary_dict else None,
            problem=summary_dict.get("problem") if summary_dict else None,
            method=summary_dict.get("method") if summary_dict else None,
            result=summary_dict.get("result") if summary_dict else None,
            conclusion=summary_dict.get("conclusion") if summary_dict else None,
        )

    def _generate_single_theme_contribution(
        self,
        paper: Paper,
        theme_name: str,
        theme_description: str,
    ) -> ThemeContributionInfo | None:
        """Generate contribution score of one paper to one research theme."""
        if not paper.title and not paper.abstract:
            return None

        payload = self.provider.evaluate_theme_contribution(
            title=paper.title,
            abstract=paper.abstract,
            theme_name=theme_name,
            theme_description=theme_description,
            target_lang=self.target_lang,
        )
        return ThemeContributionInfo(
            source=paper.source,
            source_id=paper.id,
            contribution_score=int(payload.get("contribution_score", 0)),
            rationale=str(payload.get("rationale", "") or "").strip() or None,
        )
