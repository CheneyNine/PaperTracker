"""OpenAI-Compatible Provider Implementation.

Builds prompts and parses structured JSON outputs for translation and summary generation with an OpenAI-compatible provider.
"""

from __future__ import annotations

from dataclasses import dataclass

from PaperTracker.llm.client import LLMApiClient, extract_json
from PaperTracker.utils.log import log


@dataclass(slots=True)
class OpenAICompatProvider:
    """LLM provider using OpenAI-compatible chat completions API.

    Supports any API following OpenAI's chat completion spec:
    - OpenAI GPT models
    - DeepSeek
    - SiliconFlow
    - Local models via OpenAI-compatible servers
    """

    name: str
    client: LLMApiClient
    model: str
    temperature: float = 0.0
    max_tokens: int = 800

    def translate_abstract(
        self,
        abstract: str,
        target_lang: str = "Simplified Chinese",
    ) -> str:
        """Translate paper abstract.

        Args:
            abstract: Paper abstract in English.
            target_lang: Target language.

        Returns:
            Translated abstract text.

        Raises:
            requests.HTTPError: If API request fails.
        """
        system_prompt = (
            "You are a precise academic translator. "
            "Translate faithfully without adding commentary or changing meaning. "
            "Preserve technical terms and proper nouns."
        )

        user_prompt = f"""Translate the following paper abstract to {target_lang}.
Return ONLY a JSON object with this exact key:
{{"summary_translated": "..."}}

Do not include any other text outside the JSON.

Abstract: {abstract}
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        log.debug("Translating abstract to %s", target_lang)

        response_text = self.client.chat_completion(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        log.debug(response_text)

        # Parse JSON response
        data = extract_json(response_text)

        result = str(data.get("summary_translated", "") or "").strip()
        if not result:
            log.warning("Translation incomplete")
        return result

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
            Dictionary with keys aligned to internal storage fields.

        Raises:
            requests.HTTPError: If API request fails.
        """
        system_prompt = (
            "You are a professional paper analyst. "
            "You should provide concise, detailed, and precise analysis using correct terminology. "
            "Avoid unnecessarily long replies."
        )

        user_prompt = f"""Please analyze the following abstract of a research paper.

Content:
{abstract}

Your output should be in {target_lang}.
Return ONLY a JSON object with these exact keys:
{{
  "motivation": "research motivation",
  "problem": "the concrete problem this paper solves",
  "state_of_art": "what the current situation or prior limitations are",
  "method_and_data": "main method, model, and data used",
  "experiments": "experimental setting and main empirical findings",
  "contribution": "main contribution and value of the paper"
}}

Do not include any other text outside the JSON."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        log.debug("Generating summary for abstract (lang=%s)", target_lang)

        response_text = self.client.chat_completion(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        # Parse JSON response
        data = extract_json(response_text)

        # Return dictionary with default values for missing fields
        return {
            "tldr": str(data.get("state_of_art", "") or "现状分析暂缺"),
            "motivation": str(data.get("motivation", "") or "研究动机暂缺"),
            "problem": str(data.get("problem", "") or "解决问题暂缺"),
            "method": str(data.get("method_and_data", "") or "主要方法和数据暂缺"),
            "result": str(data.get("experiments", "") or "数据实验暂缺"),
            "conclusion": str(data.get("contribution", "") or "主要贡献暂缺"),
        }

    def evaluate_theme_contribution(
        self,
        *,
        title: str,
        abstract: str,
        theme_name: str,
        theme_description: str,
        target_lang: str = "Simplified Chinese",
    ) -> dict[str, str | int]:
        """Score one paper's contribution to a user-defined research theme."""
        system_prompt = (
            "You are an academic research assistant. "
            "Judge how much a paper contributes to a target research theme. "
            "Be strict, evidence-based, and avoid inflating scores."
        )

        user_prompt = f"""Please evaluate the contribution of the following paper to a research theme.

Research theme name:
{theme_name}

Research theme description:
{theme_description}

Paper title:
{title}

Paper abstract:
{abstract}

Return ONLY a JSON object in {target_lang} with these exact keys:
{{
  "contribution_score": 0,
  "rationale": "brief reason"
}}

Rules:
- contribution_score must be an integer between 0 and 100.
- Higher score means the paper is more directly useful to the research theme.
- rationale should be concise and evidence-based.
- Do not output any text outside the JSON."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_text = self.client.chat_completion(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        data = extract_json(response_text)
        raw_score = data.get("contribution_score", 0)
        try:
            score = int(raw_score)
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
        rationale = str(data.get("rationale", "") or "").strip()
        return {
            "contribution_score": score,
            "rationale": rationale,
        }

    def suggest_theme_queries(
        self,
        *,
        theme_name: str,
        theme_description: str,
        existing_queries: list[str] | None = None,
        target_lang: str = "Simplified Chinese",
    ) -> dict[str, list]:
        """Suggest and optimize search queries for one research theme."""
        system_prompt = (
            "You are an academic literature search assistant. "
            "Design concise search queries that are likely to retrieve relevant papers. "
            "Use English search phrases only."
        )

        existing_section = ""
        if existing_queries:
            lines = "\n".join(f"- {q}" for q in existing_queries)
            existing_section = f"""
Existing search keywords:
{lines}

Your task:
1. Review the existing keywords. If any are overly long or specific (unlikely to match real paper titles/abstracts), provide a shorter and more effective replacement.
2. Generate 4 to 6 NEW search phrases not already covered by the existing keywords.
"""
        else:
            existing_section = """
Your task:
1. Generate 6 to 8 new search phrases for this research theme.
"""

        user_prompt = f"""You are helping a researcher track papers for the following research theme.

Research theme name:
{theme_name}

Research theme description:
{theme_description}
{existing_section}
Return ONLY a JSON object with this exact structure:
{{
  "new_queries": ["new query 1", "new query 2"],
  "optimized_queries": [
    {{"from": "old overly-specific phrase", "to": "shorter better phrase"}}
  ]
}}

Rules:
- Use English only. No Chinese keywords.
- Each query should be short (1-5 words) and suitable for academic search.
- Only include entries in "optimized_queries" if an existing keyword genuinely needs improvement.
- "optimized_queries" may be an empty list if all existing keywords are already good.
- Do not include any text outside the JSON."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_text = self.client.chat_completion(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        data = extract_json(response_text)

        def _clean_list(raw: object) -> list[str]:
            if not isinstance(raw, list):
                return []
            result: list[str] = []
            seen: set[str] = set()
            for item in raw:
                if not isinstance(item, str):
                    continue
                normalized = " ".join(item.split())
                if not normalized:
                    continue
                key = normalized.casefold()
                if key in seen:
                    continue
                seen.add(key)
                result.append(normalized)
            return result

        new_queries = _clean_list(data.get("new_queries", []))

        raw_optimized = data.get("optimized_queries", [])
        optimized_queries: list[dict[str, str]] = []
        if isinstance(raw_optimized, list):
            for entry in raw_optimized:
                if not isinstance(entry, dict):
                    continue
                from_val = " ".join(str(entry.get("from", "")).split())
                to_val = " ".join(str(entry.get("to", "")).split())
                if from_val and to_val and from_val.casefold() != to_val.casefold():
                    optimized_queries.append({"from": from_val, "to": to_val})

        return {"new_queries": new_queries, "optimized_queries": optimized_queries}
