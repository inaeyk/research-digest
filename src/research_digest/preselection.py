"""Deterministic abstract preselection for analysis cache misses."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from research_digest.analysis.base import article_analysis_key
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


@dataclass(frozen=True)
class AbstractPreselectionDecision:
    article_id: str
    selected: bool
    stage: str
    matched_terms: tuple[str, ...]
    reason: str


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

    def preselect(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> AbstractPreselectionResult:
        profile_terms = _profile_terms(profile)
        if not profile_terms:
            return AbstractPreselectionResult(
                tuple(
                    AbstractPreselectionDecision(
                        article_id=article_analysis_key(article),
                        selected=True,
                        stage="fallback",
                        matched_terms=(),
                        reason="profile did not yield preselection terms",
                    )
                    for article in articles
                )
            )

        decisions = tuple(_preselect_article(profile_terms, article) for article in articles)
        return AbstractPreselectionResult(decisions)


def _preselect_article(
    profile_terms: set[str],
    article: Article,
) -> AbstractPreselectionDecision:
    key = article_analysis_key(article)
    title_category_terms = _terms(" ".join([article.title, " ".join(article.categories)]))
    title_category_matches = _matches(profile_terms, title_category_terms)
    if title_category_matches:
        return AbstractPreselectionDecision(
            article_id=key,
            selected=True,
            stage="title_category",
            matched_terms=title_category_matches,
            reason="profile terms matched title or category metadata",
        )

    abstract_matches = _matches(profile_terms, _terms(article.abstract))
    if abstract_matches:
        return AbstractPreselectionDecision(
            article_id=key,
            selected=True,
            stage="abstract",
            matched_terms=abstract_matches,
            reason="profile terms matched the abstract",
        )

    return AbstractPreselectionDecision(
        article_id=key,
        selected=False,
        stage="abstract",
        matched_terms=(),
        reason="no profile terms matched title, categories, or abstract",
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
