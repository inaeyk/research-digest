"""Deterministic analyzer used by tests and local smoke checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from research_digest.analysis.base import LLMAnalyzer, article_analysis_key
from research_digest.models import AnalysisResult, Article, InterestProfile, ReadingPriority


class FakeAnalyzer(LLMAnalyzer):
    """Return deterministic analysis data without network access."""

    def __init__(
        self,
        analyses: Mapping[str, Mapping[str, Any] | AnalysisResult] | None = None,
    ) -> None:
        self._analyses = dict(analyses or {})
        self.calls: list[str] = []

    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        self.calls.append(article.source_article_id)
        configured = self._analyses.get(article.source_article_id)
        if isinstance(configured, AnalysisResult):
            return configured
        if configured is not None:
            return AnalysisResult.from_mapping(configured)

        text = f"{article.title} {article.abstract}".lower()
        profile_text = profile.description.lower()
        terms = [
            term
            for term in ("gravity", "black", "brane", "compactification", "spin-2", "relativity")
            if term in text and term in profile_text
        ]
        score = min(1.0, 0.2 + 0.2 * len(terms))
        priority = "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.5 else "LOW"
        return AnalysisResult(
            relevance_score=score,
            relevance_reason=(
                "Deterministic fake score based on configured fixture or term overlap."
            ),
            matched_topics=terms,
            summary=f"{article.title}: {article.abstract[:140]}",
            why_it_matters=(
                "This deterministic result is intended for tests, not scientific judgment."
            ),
            reading_priority=cast(ReadingPriority, priority),
        )

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        return {
            article_analysis_key(article): self.analyze(profile=profile, article=article)
            for article in articles
        }
