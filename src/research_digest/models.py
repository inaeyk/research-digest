"""Core domain models for Research Digest."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, cast

ReadingPriority = Literal["LOW", "MEDIUM", "HIGH"]
MAX_ARXIV_LOOKBACK_HOURS = 24 * 30
MAX_ARXIV_RESULTS = 500

_WHITESPACE_RE = re.compile(r"\s+")
_EXPECTED_ANALYSIS_KEYS = {
    "relevance_score",
    "relevance_reason",
    "matched_topics",
    "summary",
    "why_it_matters",
    "reading_priority",
}


class ModelValidationError(ValueError):
    """Raised when data cannot be converted into a valid domain model."""


class AnalysisOrigin(StrEnum):
    NEW_THIS_RUN = "NEW_THIS_RUN"
    REUSED = "REUSED"


def normalize_whitespace(value: str) -> str:
    """Collapse repeated whitespace and trim surrounding whitespace."""

    return _WHITESPACE_RE.sub(" ", value).strip()


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def datetime_to_db(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def datetime_from_db(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return ensure_utc(parsed)


@dataclass(frozen=True)
class InterestProfile:
    id: int | None
    name: str
    description: str
    relevance_threshold: float = 0.6
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("interest profile id must be positive")
        if not self.name.strip():
            raise ModelValidationError("interest profile name is required")
        if not self.description.strip():
            raise ModelValidationError("interest profile description is required")
        if not 0 <= self.relevance_threshold <= 1:
            raise ModelValidationError("relevance_threshold must be between 0 and 1")
        object.__setattr__(self, "name", normalize_whitespace(self.name))
        object.__setattr__(self, "description", self.description.strip())


@dataclass(frozen=True)
class ArxivSourceConfig:
    enabled: bool = True
    categories: list[str] | None = None
    lookback_hours: int = 48
    max_results: int = 50

    def __post_init__(self) -> None:
        categories = self.categories if self.categories is not None else ["hep-th", "gr-qc"]
        normalized = [normalize_whitespace(category) for category in categories if category.strip()]
        if self.enabled and not normalized:
            raise ModelValidationError("at least one arXiv category is required when enabled")
        if self.lookback_hours <= 0:
            raise ModelValidationError("lookback_hours must be positive")
        if self.lookback_hours > MAX_ARXIV_LOOKBACK_HOURS:
            raise ModelValidationError(
                f"lookback_hours must be at most {MAX_ARXIV_LOOKBACK_HOURS}"
            )
        if self.max_results <= 0:
            raise ModelValidationError("max_results must be positive")
        if self.max_results > MAX_ARXIV_RESULTS:
            raise ModelValidationError(f"max_results must be at most {MAX_ARXIV_RESULTS}")
        object.__setattr__(self, "categories", normalized)


@dataclass(frozen=True)
class Article:
    id: int | None
    source: str
    source_article_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published_at: datetime
    updated_at: datetime
    abstract_url: str
    pdf_url: str | None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("article id must be positive")
        if not self.source.strip():
            raise ModelValidationError("article source is required")
        if not self.source_article_id.strip():
            raise ModelValidationError("source_article_id is required")
        if not self.title.strip():
            raise ModelValidationError("article title is required")
        if not self.abstract.strip():
            raise ModelValidationError("article abstract is required")
        authors = [normalize_whitespace(author) for author in self.authors if author.strip()]
        categories = [
            normalize_whitespace(category)
            for category in self.categories
            if category.strip()
        ]
        object.__setattr__(self, "source", normalize_whitespace(self.source))
        object.__setattr__(self, "source_article_id", normalize_whitespace(self.source_article_id))
        object.__setattr__(self, "title", normalize_whitespace(self.title))
        object.__setattr__(self, "abstract", normalize_whitespace(self.abstract))
        object.__setattr__(self, "authors", authors)
        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "published_at", ensure_utc(self.published_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        object.__setattr__(self, "abstract_url", self.abstract_url.strip())
        if self.pdf_url is not None:
            object.__setattr__(self, "pdf_url", self.pdf_url.strip() or None)


@dataclass(frozen=True)
class AnalysisResult:
    relevance_score: float
    relevance_reason: str
    matched_topics: list[str]
    summary: str
    why_it_matters: str
    reading_priority: ReadingPriority

    def __post_init__(self) -> None:
        if not 0 <= self.relevance_score <= 1:
            raise ModelValidationError("relevance_score must be between 0 and 1")
        if not self.relevance_reason.strip():
            raise ModelValidationError("relevance_reason is required")
        if not self.summary.strip():
            raise ModelValidationError("summary is required")
        if not self.why_it_matters.strip():
            raise ModelValidationError("why_it_matters is required")
        if self.reading_priority not in {"LOW", "MEDIUM", "HIGH"}:
            raise ModelValidationError("reading_priority must be LOW, MEDIUM, or HIGH")
        topics = [normalize_whitespace(topic) for topic in self.matched_topics if topic.strip()]
        object.__setattr__(self, "relevance_reason", normalize_whitespace(self.relevance_reason))
        object.__setattr__(self, "matched_topics", topics)
        object.__setattr__(self, "summary", normalize_whitespace(self.summary))
        object.__setattr__(self, "why_it_matters", normalize_whitespace(self.why_it_matters))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AnalysisResult:
        keys = set(data.keys())
        if keys != _EXPECTED_ANALYSIS_KEYS:
            missing = sorted(_EXPECTED_ANALYSIS_KEYS - keys)
            extra = sorted(keys - _EXPECTED_ANALYSIS_KEYS)
            details = []
            if missing:
                details.append(f"missing keys: {', '.join(missing)}")
            if extra:
                details.append(f"extra keys: {', '.join(extra)}")
            raise ModelValidationError("invalid analysis payload (" + "; ".join(details) + ")")

        score = data["relevance_score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise ModelValidationError("relevance_score must be numeric")

        topics = data["matched_topics"]
        if not isinstance(topics, list) or not all(isinstance(topic, str) for topic in topics):
            raise ModelValidationError("matched_topics must be a list of strings")

        priority = data["reading_priority"]
        if not isinstance(priority, str):
            raise ModelValidationError("reading_priority must be a string")

        return cls(
            relevance_score=float(score),
            relevance_reason=_required_string(data, "relevance_reason"),
            matched_topics=topics,
            summary=_required_string(data, "summary"),
            why_it_matters=_required_string(data, "why_it_matters"),
            reading_priority=_priority(priority),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "relevance_score": self.relevance_score,
            "relevance_reason": self.relevance_reason,
            "matched_topics": list(self.matched_topics),
            "summary": self.summary,
            "why_it_matters": self.why_it_matters,
            "reading_priority": self.reading_priority,
        }


@dataclass(frozen=True)
class DigestItem:
    article: Article
    analysis: AnalysisResult
    analysis_origin: AnalysisOrigin


@dataclass(frozen=True)
class DigestResult:
    run_id: int
    profile: InterestProfile
    source_config: ArxivSourceConfig
    retrieved_count: int
    stored_count: int
    analyzed_count: int
    new_analysis_count: int
    reused_analysis_count: int
    above_threshold_count: int
    analysis_available: bool
    items: list[DigestItem]
    started_at: datetime
    completed_at: datetime | None

    @property
    def relevant_count(self) -> int:
        return self.above_threshold_count


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise ModelValidationError(f"{key} must be a string")
    return value


def _priority(value: str) -> ReadingPriority:
    if value not in {"LOW", "MEDIUM", "HIGH"}:
        raise ModelValidationError("reading_priority must be LOW, MEDIUM, or HIGH")
    return cast(ReadingPriority, value)


def sorted_digest_items(items: Sequence[DigestItem]) -> list[DigestItem]:
    return sorted(
        items,
        key=lambda item: (
            item.analysis.relevance_score,
            item.article.published_at,
            item.article.title,
        ),
        reverse=True,
    )


def is_above_threshold(item: DigestItem, threshold: float) -> bool:
    return item.analysis.relevance_score >= threshold


def above_threshold_digest_items(result: DigestResult) -> list[DigestItem]:
    return sorted_digest_items(
        [
            item
            for item in result.items
            if is_above_threshold(item, result.profile.relevance_threshold)
        ]
    )


def below_threshold_digest_items(result: DigestResult) -> list[DigestItem]:
    return sorted_digest_items(
        [
            item
            for item in result.items
            if not is_above_threshold(item, result.profile.relevance_threshold)
        ]
    )
