"""LLM analysis abstractions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from research_digest.models import AnalysisResult, Article, InterestProfile


class AnalyzerError(RuntimeError):
    """Raised when an analyzer provider fails to produce usable analysis."""


class AnalyzerUnavailable(AnalyzerError):
    """Raised when an analyzer cannot run in the current environment."""


class LLMAnalyzer(Protocol):
    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        """Analyze one article against one interest profile."""

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        """Analyze a batch of articles keyed by stable source/article id."""


def article_analysis_key(article: Article) -> str:
    return f"{article.source}:{article.source_article_id}"
