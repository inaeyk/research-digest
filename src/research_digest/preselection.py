"""Abstract preselection for analysis cache misses."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from research_digest.analysis.base import article_analysis_key
from research_digest.config import DEFAULT_PRESELECTION_FRACTION, preselection_threshold
from research_digest.models import Article, InterestProfile

_TERM_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,}")
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "based",
    "been",
    "being",
    "between",
    "but",
    "can",
    "from",
    "has",
    "have",
    "into",
    "its",
    "may",
    "not",
    "our",
    "paper",
    "papers",
    "research",
    "show",
    "study",
    "that",
    "the",
    "their",
    "this",
    "through",
    "using",
    "with",
}

TERM_OVERLAP_PRESELECTOR_VERSION = "term_overlap_v1"
UNAVAILABLE_FAIL_OPEN_PRESELECTOR_VERSION = "model_abstract_unavailable_v1"
PRESELECTION_ORIGIN_SCREENED = "SCREENED"
PRESELECTION_ORIGIN_REUSED_ANALYSIS = "REUSED_ANALYSIS_BYPASS"
PRESELECTION_ORIGIN_UNAVAILABLE_FAIL_OPEN = "UNAVAILABLE_FAIL_OPEN"


@dataclass(frozen=True)
class AbstractPreselectionDecision:
    article_id: str
    selected: bool
    stage: str
    matched_terms: tuple[str, ...]
    reason: str
    preselection_score: float | None = 0.0
    preselection_threshold: float | None = None
    preselector_version: str = TERM_OVERLAP_PRESELECTOR_VERSION
    decision_origin: str = PRESELECTION_ORIGIN_SCREENED


@dataclass(frozen=True)
class AbstractPreselectionResult:
    decisions: tuple[AbstractPreselectionDecision, ...]

    @property
    def selected_ids(self) -> set[str]:
        return {decision.article_id for decision in self.decisions if decision.selected}

    @property
    def selected_count(self) -> int:
        return sum(decision.selected for decision in self.decisions)

    @property
    def skipped_count(self) -> int:
        return sum(not decision.selected for decision in self.decisions)


class AbstractPreselector(Protocol):
    preselection_fraction: float
    preselector_version: str

    def preselect(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> AbstractPreselectionResult:
        """Choose cache-miss articles that should receive full analysis."""


class TermOverlapPreselector:
    """Two-stage title/category then abstract preselector.

    The preselector is intentionally conservative: if it cannot extract useful profile
    terms, every article is selected for full analysis.
    """

    def __init__(
        self,
        *,
        preselection_fraction: float = DEFAULT_PRESELECTION_FRACTION,
    ) -> None:
        if preselection_fraction < 0 or preselection_fraction > 1:
            raise ValueError("preselection_fraction must be between 0 and 1")
        self.preselection_fraction = preselection_fraction
        self.preselector_version = TERM_OVERLAP_PRESELECTOR_VERSION

    def preselect(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> AbstractPreselectionResult:
        profile_terms = _profile_terms(profile)
        threshold = preselection_threshold(
            relevance_threshold=profile.relevance_threshold,
            preselection_fraction=self.preselection_fraction,
        )
        if not profile_terms:
            return AbstractPreselectionResult(
                tuple(
                    AbstractPreselectionDecision(
                        article_id=article_analysis_key(article),
                        selected=True,
                        stage="fallback",
                        matched_terms=(),
                        reason="profile did not yield preselection terms",
                        preselection_score=1.0,
                        preselection_threshold=threshold,
                        preselector_version=self.preselector_version,
                    )
                    for article in articles
                )
            )

        decisions = tuple(
            _preselect_article(
                profile_terms,
                article,
                relevance_threshold=profile.relevance_threshold,
                threshold=threshold,
                preselector_version=self.preselector_version,
            )
            for article in articles
        )
        return AbstractPreselectionResult(decisions)


class UnavailableFailOpenPreselector:
    """Allow full analysis when model-based Stage 1 cannot be constructed."""

    def __init__(
        self,
        *,
        preselection_fraction: float = DEFAULT_PRESELECTION_FRACTION,
        reason: str = "Model preselection unavailable; allowed full analysis.",
    ) -> None:
        if preselection_fraction < 0 or preselection_fraction > 1:
            raise ValueError("preselection_fraction must be between 0 and 1")
        self.preselection_fraction = preselection_fraction
        self.preselector_version = UNAVAILABLE_FAIL_OPEN_PRESELECTOR_VERSION
        self._reason = reason

    def preselect(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> AbstractPreselectionResult:
        threshold = preselection_threshold(
            relevance_threshold=profile.relevance_threshold,
            preselection_fraction=self.preselection_fraction,
        )
        return fail_open_preselection_result(
            profile=profile,
            articles=articles,
            preselection_fraction=self.preselection_fraction,
            preselector_version=self.preselector_version,
            reason=self._reason,
            threshold=threshold,
        )


def fail_open_preselection_result(
    *,
    profile: InterestProfile,
    articles: Sequence[Article],
    preselection_fraction: float,
    preselector_version: str,
    reason: str,
    threshold: float | None = None,
) -> AbstractPreselectionResult:
    active_threshold = (
        threshold
        if threshold is not None
        else preselection_threshold(
            relevance_threshold=profile.relevance_threshold,
            preselection_fraction=preselection_fraction,
        )
    )
    return AbstractPreselectionResult(
        tuple(
            AbstractPreselectionDecision(
                article_id=article_analysis_key(article),
                selected=True,
                stage="unavailable",
                matched_terms=(),
                reason=reason,
                preselection_score=None,
                preselection_threshold=active_threshold,
                preselector_version=preselector_version,
                decision_origin=PRESELECTION_ORIGIN_UNAVAILABLE_FAIL_OPEN,
            )
            for article in articles
        )
    )


def reused_analysis_preselection_decision(
    *,
    article: Article,
    profile: InterestProfile,
    preselection_fraction: float,
    preselector_version: str,
) -> AbstractPreselectionDecision:
    threshold = preselection_threshold(
        relevance_threshold=profile.relevance_threshold,
        preselection_fraction=preselection_fraction,
    )
    return AbstractPreselectionDecision(
        article_id=article_analysis_key(article),
        selected=True,
        stage="cache",
        matched_terms=(),
        reason="valid full analysis already existed for this profile semantics",
        preselection_score=None,
        preselection_threshold=threshold,
        preselector_version=preselector_version,
        decision_origin=PRESELECTION_ORIGIN_REUSED_ANALYSIS,
    )


def _preselect_article(
    profile_terms: set[str],
    article: Article,
    *,
    relevance_threshold: float,
    threshold: float,
    preselector_version: str,
) -> AbstractPreselectionDecision:
    key = article_analysis_key(article)
    title_category_terms = _terms(" ".join([article.title, " ".join(article.categories)]))
    title_category_matches = _matches(profile_terms, title_category_terms)
    if title_category_matches:
        score = 1.0
        return AbstractPreselectionDecision(
            article_id=key,
            selected=score >= threshold,
            stage="title_category",
            matched_terms=title_category_matches,
            reason="profile terms matched title or category metadata",
            preselection_score=score,
            preselection_threshold=threshold,
            preselector_version=preselector_version,
        )

    abstract_matches = _matches(profile_terms, _terms(article.abstract))
    if abstract_matches:
        score = relevance_threshold
        return AbstractPreselectionDecision(
            article_id=key,
            selected=score >= threshold,
            stage="abstract",
            matched_terms=abstract_matches,
            reason="profile terms matched the abstract",
            preselection_score=score,
            preselection_threshold=threshold,
            preselector_version=preselector_version,
        )

    score = 0.0
    return AbstractPreselectionDecision(
        article_id=key,
        selected=score >= threshold,
        stage="abstract",
        matched_terms=(),
        reason="no profile terms matched title, categories, or abstract",
        preselection_score=score,
        preselection_threshold=threshold,
        preselector_version=preselector_version,
    )


def _profile_terms(profile: InterestProfile) -> set[str]:
    return _terms(f"{profile.name} {profile.description}")


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for raw in _TERM_RE.findall(text.lower()):
        if raw in _STOPWORDS:
            continue
        terms.add(raw)
        if raw.endswith("s") and len(raw) > 4:
            terms.add(raw[:-1])
    return terms


def _matches(profile_terms: set[str], article_terms: set[str]) -> tuple[str, ...]:
    return tuple(sorted(profile_terms & article_terms))
