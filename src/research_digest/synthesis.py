"""Deterministic cross-paper synthesis for a digest run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from research_digest.models import DigestItem, normalize_whitespace


@dataclass(frozen=True)
class TopicSynthesis:
    topic: str
    paper_count: int
    paper_titles: tuple[str, ...]


@dataclass(frozen=True)
class CrossPaperSynthesis:
    analyzed_count: int
    relevant_count: int
    recurring_topics: tuple[TopicSynthesis, ...]
    high_priority_titles: tuple[str, ...]
    category_counts: tuple[tuple[str, int], ...]

    @property
    def has_signal(self) -> bool:
        return bool(self.recurring_topics or self.high_priority_titles or self.category_counts)


class CrossPaperSynthesizer(Protocol):
    def build(
        self,
        *,
        items: Sequence[DigestItem],
        threshold: float,
    ) -> CrossPaperSynthesis:
        """Build a cross-paper synthesis for a completed digest run."""


class DeterministicCrossPaperSynthesizer:
    def build(
        self,
        *,
        items: Sequence[DigestItem],
        threshold: float,
    ) -> CrossPaperSynthesis:
        return build_cross_paper_synthesis(items=items, threshold=threshold)


def build_cross_paper_synthesis(
    *,
    items: Sequence[DigestItem],
    threshold: float,
) -> CrossPaperSynthesis:
    relevant_items = [
        item for item in items if item.analysis.relevance_score >= threshold
    ]
    topic_titles: dict[str, list[str]] = {}
    category_counter: Counter[str] = Counter()
    high_priority_titles: list[str] = []

    for item in relevant_items:
        if item.analysis.reading_priority == "HIGH":
            high_priority_titles.append(item.article.title)
        for category in item.article.categories:
            category_counter[category] += 1
        item_topics = {
            normalized
            for topic in item.analysis.matched_topics
            if (normalized := _topic_key(topic))
        }
        for normalized in item_topics:
            topic_titles.setdefault(normalized, []).append(item.article.title)

    recurring_topics = tuple(
        TopicSynthesis(topic=topic, paper_count=len(titles), paper_titles=tuple(titles))
        for topic, titles in sorted(
            topic_titles.items(),
            key=lambda pair: (-len(pair[1]), pair[0]),
        )
        if len(titles) >= 2
    )
    category_counts = tuple(
        sorted(category_counter.items(), key=lambda pair: (-pair[1], pair[0]))
    )
    return CrossPaperSynthesis(
        analyzed_count=len(items),
        relevant_count=len(relevant_items),
        recurring_topics=recurring_topics,
        high_priority_titles=tuple(sorted(high_priority_titles)),
        category_counts=category_counts,
    )


def _topic_key(topic: str) -> str:
    return normalize_whitespace(topic).lower()
