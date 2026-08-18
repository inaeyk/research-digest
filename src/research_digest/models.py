"""Core domain models for Research Digest."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

ReadingPriority = Literal["LOW", "MEDIUM", "HIGH"]
FeedbackLabel = Literal["RELEVANT", "NOT_RELEVANT"]
FeedbackAnswer = Literal["YES", "NO"]
QuantitativeCalibrationState = Literal["PENDING", "COMPLETED", "DISMISSED", "SKIPPED"]
MAX_ARXIV_LOOKBACK_HOURS = 24 * 30
MAX_ARXIV_RESULTS = 500
SOURCE_DATE_TIMEZONE_NAME = "America/Chicago"
SOURCE_DATE_TIMEZONE = ZoneInfo(SOURCE_DATE_TIMEZONE_NAME)

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


class RunOrigin(StrEnum):
    LEGACY = "LEGACY"
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"


class TagOrigin(StrEnum):
    USER = "USER"
    AI = "AI"


class ConnectionOrigin(StrEnum):
    AI = "AI"


class LibraryContextOrigin(StrEnum):
    AI = "AI"
    DETERMINISTIC = "DETERMINISTIC"


class DateSelectionKind(StrEnum):
    LATEST_AVAILABLE = "LATEST_AVAILABLE"
    SINGLE_DATE = "SINGLE_DATE"
    DATE_RANGE = "DATE_RANGE"
    EXPLICIT_DATES = "EXPLICIT_DATES"


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


def source_date_from_datetime(value: datetime) -> date:
    """Return the Research Digest source date for a source timestamp."""

    return ensure_utc(value).astimezone(SOURCE_DATE_TIMEZONE).date()


@dataclass(frozen=True)
class DateSelection:
    """Normalized source-date selection for date-native digest runs."""

    kind: DateSelectionKind
    dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        coerced_kind = DateSelectionKind(self.kind)
        dates = tuple(_coerce_date(value) for value in self.dates)
        normalized = _normalize_date_selection_dates(coerced_kind, dates)
        object.__setattr__(self, "kind", coerced_kind)
        object.__setattr__(self, "dates", normalized)

    @classmethod
    def latest_available(cls) -> DateSelection:
        return cls(DateSelectionKind.LATEST_AVAILABLE)

    @classmethod
    def single_date(cls, value: date) -> DateSelection:
        return cls(DateSelectionKind.SINGLE_DATE, (value,))

    @classmethod
    def date_range(cls, start: date, end: date) -> DateSelection:
        return cls(DateSelectionKind.DATE_RANGE, (start, end))

    @classmethod
    def explicit_dates(cls, values: Sequence[date]) -> DateSelection:
        return cls(DateSelectionKind.EXPLICIT_DATES, tuple(values))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> DateSelection:
        raw_kind = payload.get("kind")
        if not isinstance(raw_kind, str):
            raise ModelValidationError("date selection kind is required")
        raw_dates = payload.get("dates", [])
        if not isinstance(raw_dates, list) or not all(
            isinstance(value, str) for value in raw_dates
        ):
            raise ModelValidationError("date selection dates must be a list of ISO dates")
        try:
            dates = tuple(date.fromisoformat(value) for value in raw_dates)
        except ValueError as exc:
            raise ModelValidationError("date selection dates must be ISO calendar dates") from exc
        try:
            kind = DateSelectionKind(raw_kind)
        except ValueError as exc:
            raise ModelValidationError("unsupported date selection kind") from exc
        return cls(kind, dates)

    def to_mapping(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "dates": [value.isoformat() for value in self.dates],
        }

    def selected_dates(self) -> tuple[date, ...]:
        if self.kind == DateSelectionKind.LATEST_AVAILABLE:
            return ()
        if self.kind == DateSelectionKind.DATE_RANGE:
            start, end = self.dates
            days = (end - start).days
            return tuple(start + timedelta(days=offset) for offset in range(days + 1))
        return self.dates

    def canonical_key(self) -> str:
        return json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":"))

    def display_label(self) -> str:
        if self.kind == DateSelectionKind.LATEST_AVAILABLE:
            return "Latest available source date"
        if self.kind == DateSelectionKind.SINGLE_DATE:
            return self.dates[0].isoformat()
        if self.kind == DateSelectionKind.DATE_RANGE:
            return f"{self.dates[0].isoformat()} to {self.dates[1].isoformat()}"
        return ", ".join(value.isoformat() for value in self.dates)


def _coerce_date(value: date) -> date:
    if isinstance(value, datetime):
        return source_date_from_datetime(value)
    if not isinstance(value, date):
        raise ModelValidationError("date selection values must be dates")
    return value


def _normalize_date_selection_dates(
    kind: DateSelectionKind,
    dates: tuple[date, ...],
) -> tuple[date, ...]:
    if kind == DateSelectionKind.LATEST_AVAILABLE:
        if dates:
            raise ModelValidationError("latest available date selection must not include dates")
        return ()
    if kind == DateSelectionKind.SINGLE_DATE:
        if len(dates) != 1:
            raise ModelValidationError("single date selection requires exactly one date")
        return dates
    if kind == DateSelectionKind.DATE_RANGE:
        if len(dates) != 2:
            raise ModelValidationError("date range selection requires start and end dates")
        start, end = dates
        if start > end:
            raise ModelValidationError("date range start must be on or before end")
        return (start, end)
    if kind == DateSelectionKind.EXPLICIT_DATES:
        normalized = tuple(sorted(set(dates)))
        if not normalized:
            raise ModelValidationError("explicit date selection requires at least one date")
        return normalized
    raise ModelValidationError(f"unsupported date selection kind: {kind}")


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


def profile_semantic_payload(profile: InterestProfile) -> dict[str, float | int | str | None]:
    """Return the prompt-visible profile fields that define analysis cache identity."""

    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "relevance_threshold": profile.relevance_threshold,
    }


def profile_semantic_signature(profile: InterestProfile) -> str:
    return json.dumps(
        profile_semantic_payload(profile),
        sort_keys=True,
        separators=(",", ":"),
    )


def profile_semantic_fingerprint(profile: InterestProfile) -> str:
    return hashlib.sha256(profile_semantic_signature(profile).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArxivSourceConfig:
    enabled: bool = True
    categories: list[str] | None = None
    lookback_hours: int = 48
    max_results: int = 50

    def __post_init__(self) -> None:
        categories = self.categories if self.categories is not None else ["hep-th", "gr-qc"]
        normalized = list(canonical_arxiv_categories(categories))
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


def canonical_arxiv_categories(categories: Sequence[str]) -> tuple[str, ...]:
    """Return the source-semantic arXiv category set in canonical order."""

    normalized = {
        normalize_whitespace(category)
        for category in categories
        if category.strip()
    }
    return tuple(sorted(normalized))


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
class LibraryEntry:
    article: Article
    saved_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.article.id is None:
            raise ModelValidationError("library entry article id is required")
        object.__setattr__(self, "saved_at", ensure_utc(self.saved_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


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
class LibraryRelevanceContext:
    profile_id: int
    profile_name: str
    relevance_score: float
    reading_priority: ReadingPriority
    analyzed_at: datetime

    def __post_init__(self) -> None:
        if self.profile_id <= 0:
            raise ModelValidationError("library relevance profile id must be positive")
        if not self.profile_name.strip():
            raise ModelValidationError("library relevance profile name is required")
        if not 0 <= self.relevance_score <= 1:
            raise ModelValidationError("library relevance score must be between 0 and 1")
        if self.reading_priority not in {"LOW", "MEDIUM", "HIGH"}:
            raise ModelValidationError("library relevance priority must be LOW, MEDIUM, or HIGH")
        object.__setattr__(self, "profile_name", normalize_whitespace(self.profile_name))
        object.__setattr__(self, "analyzed_at", ensure_utc(self.analyzed_at))


@dataclass(frozen=True)
class LibraryTag:
    id: int | None
    normalized_name: str
    display_name: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("library tag id must be positive")
        if not self.normalized_name.strip():
            raise ModelValidationError("library tag normalized name is required")
        if not self.display_name.strip():
            raise ModelValidationError("library tag display name is required")
        object.__setattr__(self, "normalized_name", normalize_whitespace(self.normalized_name))
        object.__setattr__(self, "display_name", normalize_whitespace(self.display_name))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


@dataclass(frozen=True)
class LibraryTagAssignment:
    id: int | None
    article_id: int
    tag: LibraryTag
    origin: TagOrigin
    created_at: datetime
    updated_at: datetime
    ai_provenance: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("library tag assignment id must be positive")
        if self.article_id <= 0:
            raise ModelValidationError("library tag assignment article id must be positive")
        origin = TagOrigin(self.origin)
        if origin == TagOrigin.AI and self.ai_provenance is None:
            raise ModelValidationError("AI tag assignments require provenance")
        if origin == TagOrigin.USER and self.ai_provenance is not None:
            raise ModelValidationError("USER tag assignments must not include AI provenance")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


@dataclass(frozen=True)
class AITagSuppression:
    article_id: int
    tag: LibraryTag
    suppressed_at: datetime
    reason: str

    def __post_init__(self) -> None:
        if self.article_id <= 0:
            raise ModelValidationError("AI tag suppression article id must be positive")
        if not self.reason.strip():
            raise ModelValidationError("AI tag suppression reason is required")
        object.__setattr__(self, "reason", normalize_whitespace(self.reason))
        object.__setattr__(self, "suppressed_at", ensure_utc(self.suppressed_at))


@dataclass(frozen=True)
class LibraryNote:
    article_id: int
    note_text: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.article_id <= 0:
            raise ModelValidationError("library note article id must be positive")
        object.__setattr__(self, "note_text", self.note_text.strip())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


@dataclass(frozen=True)
class LibraryCollection:
    id: int | None
    name: str
    normalized_name: str
    description: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("library collection id must be positive")
        if not self.name.strip():
            raise ModelValidationError("library collection name is required")
        if not self.normalized_name.strip():
            raise ModelValidationError("library collection normalized name is required")
        object.__setattr__(self, "name", normalize_whitespace(self.name))
        object.__setattr__(self, "normalized_name", normalize_whitespace(self.normalized_name))
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


@dataclass(frozen=True)
class LibraryCollectionMembership:
    collection_id: int
    article_id: int
    added_at: datetime

    def __post_init__(self) -> None:
        if self.collection_id <= 0:
            raise ModelValidationError("collection membership collection id must be positive")
        if self.article_id <= 0:
            raise ModelValidationError("collection membership article id must be positive")
        object.__setattr__(self, "added_at", ensure_utc(self.added_at))


@dataclass(frozen=True)
class LibrarySearchDocument:
    article_id: int
    document_text: str
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.article_id <= 0:
            raise ModelValidationError("library search document article id must be positive")
        object.__setattr__(self, "document_text", self.document_text.strip())
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))


@dataclass(frozen=True)
class LibraryConnection:
    id: int | None
    article_id_a: int
    article_id_b: int
    relation_label: str
    rationale: str
    origin: ConnectionOrigin
    provenance: dict[str, object]
    generated_at: datetime
    confidence: float | None = None
    dismissed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("library connection id must be positive")
        if self.article_id_a <= 0 or self.article_id_b <= 0:
            raise ModelValidationError("library connection article ids must be positive")
        if self.article_id_a == self.article_id_b:
            raise ModelValidationError("library connection cannot link an article to itself")
        if self.article_id_a > self.article_id_b:
            raise ModelValidationError("library connection article ids must be canonical")
        if not self.relation_label.strip():
            raise ModelValidationError("library connection relation label is required")
        if not self.rationale.strip():
            raise ModelValidationError("library connection rationale is required")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ModelValidationError("library connection confidence must be between 0 and 1")
        object.__setattr__(self, "relation_label", normalize_whitespace(self.relation_label))
        object.__setattr__(self, "rationale", normalize_whitespace(self.rationale))
        object.__setattr__(self, "origin", ConnectionOrigin(self.origin))
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at))
        if self.dismissed_at is not None:
            object.__setattr__(self, "dismissed_at", ensure_utc(self.dismissed_at))


@dataclass(frozen=True)
class LibraryContextSuggestion:
    id: int | None
    run_id: int | None
    article_id: int
    related_article_id: int
    collection_id: int | None
    relation_label: str
    rationale: str
    origin: LibraryContextOrigin
    provenance: dict[str, object]
    created_at: datetime
    confidence: float | None = None
    dismissed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("library context suggestion id must be positive")
        if self.run_id is not None and self.run_id <= 0:
            raise ModelValidationError("library context suggestion run id must be positive")
        if self.article_id <= 0 or self.related_article_id <= 0:
            raise ModelValidationError("library context suggestion article ids must be positive")
        if self.article_id == self.related_article_id:
            raise ModelValidationError(
                "library context suggestion cannot link an article to itself"
            )
        if self.collection_id is not None and self.collection_id <= 0:
            raise ModelValidationError("library context suggestion collection id must be positive")
        if not self.relation_label.strip():
            raise ModelValidationError("library context suggestion relation label is required")
        if not self.rationale.strip():
            raise ModelValidationError("library context suggestion rationale is required")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ModelValidationError(
                "library context suggestion confidence must be between 0 and 1"
            )
        object.__setattr__(self, "relation_label", normalize_whitespace(self.relation_label))
        object.__setattr__(self, "rationale", normalize_whitespace(self.rationale))
        object.__setattr__(self, "origin", LibraryContextOrigin(self.origin))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        if self.dismissed_at is not None:
            object.__setattr__(self, "dismissed_at", ensure_utc(self.dismissed_at))


@dataclass(frozen=True)
class CollectionIntelligenceSnapshot:
    id: int | None
    collection_id: int
    title: str
    summary: str
    evidence: dict[str, object]
    origin: LibraryContextOrigin
    provenance: dict[str, object]
    generated_at: datetime
    dismissed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("collection intelligence snapshot id must be positive")
        if self.collection_id <= 0:
            raise ModelValidationError("collection intelligence collection id must be positive")
        if not self.title.strip():
            raise ModelValidationError("collection intelligence title is required")
        if not self.summary.strip():
            raise ModelValidationError("collection intelligence summary is required")
        object.__setattr__(self, "title", normalize_whitespace(self.title))
        object.__setattr__(self, "summary", normalize_whitespace(self.summary))
        object.__setattr__(self, "origin", LibraryContextOrigin(self.origin))
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at))
        if self.dismissed_at is not None:
            object.__setattr__(self, "dismissed_at", ensure_utc(self.dismissed_at))


@dataclass(frozen=True)
class DigestItem:
    article: Article
    analysis: AnalysisResult
    analysis_origin: AnalysisOrigin


@dataclass(frozen=True)
class ArticleFeedback:
    id: int | None
    article_id: int
    profile_id: int
    profile_fingerprint: str
    feedback_label: FeedbackLabel | None
    created_at: datetime
    updated_at: datetime
    profile_match: FeedbackAnswer | None = None
    personal_interest: FeedbackAnswer | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("article feedback id must be positive")
        if self.article_id <= 0:
            raise ModelValidationError("article feedback article_id must be positive")
        if self.profile_id <= 0:
            raise ModelValidationError("article feedback profile_id must be positive")
        if not self.profile_fingerprint.strip():
            raise ModelValidationError("article feedback profile_fingerprint is required")
        if self.feedback_label is not None and self.feedback_label not in {
            "RELEVANT",
            "NOT_RELEVANT",
        }:
            raise ModelValidationError("feedback_label must be RELEVANT or NOT_RELEVANT")
        if self.profile_match not in {None, "YES", "NO"}:
            raise ModelValidationError("profile_match must be YES, NO, or unanswered")
        if self.personal_interest not in {None, "YES", "NO"}:
            raise ModelValidationError("personal_interest must be YES, NO, or unanswered")
        object.__setattr__(
            self,
            "profile_fingerprint",
            normalize_whitespace(self.profile_fingerprint),
        )
        if self.profile_match is None and self.feedback_label is not None:
            object.__setattr__(
                self,
                "profile_match",
                "YES" if self.feedback_label == "RELEVANT" else "NO",
            )
        if self.feedback_label is None and self.profile_match is not None:
            object.__setattr__(
                self,
                "feedback_label",
                "RELEVANT" if self.profile_match == "YES" else "NOT_RELEVANT",
            )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))

    @property
    def answered_profile_match(self) -> bool:
        return self.profile_match is not None

    @property
    def answered_personal_interest(self) -> bool:
        return self.personal_interest is not None


@dataclass(frozen=True)
class QuantitativeRelevanceCalibration:
    id: int | None
    run_id: int
    profile_id: int
    profile_fingerprint: str
    state: QuantitativeCalibrationState
    created_at: datetime
    article_id: int | None = None
    model_relevance_score: float | None = None
    user_relevance_score: float | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("calibration id must be positive")
        if self.run_id <= 0:
            raise ModelValidationError("calibration run_id must be positive")
        if self.profile_id <= 0:
            raise ModelValidationError("calibration profile_id must be positive")
        if not self.profile_fingerprint.strip():
            raise ModelValidationError("calibration profile_fingerprint is required")
        if self.state not in {"PENDING", "COMPLETED", "DISMISSED", "SKIPPED"}:
            raise ModelValidationError("calibration state is invalid")
        if self.state != "SKIPPED":
            if self.article_id is None or self.article_id <= 0:
                raise ModelValidationError("calibration article_id is required")
            if self.model_relevance_score is None:
                raise ModelValidationError("calibration model score is required")
        if self.model_relevance_score is not None and not 0 <= self.model_relevance_score <= 1:
            raise ModelValidationError("calibration model score must be between 0 and 1")
        if self.user_relevance_score is not None and not 0 <= self.user_relevance_score <= 1:
            raise ModelValidationError("calibration user score must be between 0 and 1")
        if self.state == "COMPLETED" and self.user_relevance_score is None:
            raise ModelValidationError("completed calibration requires a user score")
        object.__setattr__(
            self,
            "profile_fingerprint",
            normalize_whitespace(self.profile_fingerprint),
        )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        if self.completed_at is not None:
            object.__setattr__(self, "completed_at", ensure_utc(self.completed_at))


@dataclass(frozen=True)
class SuggestedInterestProfile:
    id: int | None
    profile_id: int
    profile_fingerprint: str
    suggested_name: str
    suggested_description: str
    evidence_article_ids: tuple[int, ...]
    explanation: str
    suggestion_key: str
    provenance: dict[str, object]
    created_at: datetime
    dismissed_at: datetime | None = None
    accepted_profile_id: int | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ModelValidationError("suggested interest id must be positive")
        if self.profile_id <= 0:
            raise ModelValidationError("suggested interest profile_id must be positive")
        if not self.profile_fingerprint.strip():
            raise ModelValidationError("suggested interest profile_fingerprint is required")
        if not self.suggested_name.strip():
            raise ModelValidationError("suggested interest name is required")
        if not self.suggested_description.strip():
            raise ModelValidationError("suggested interest description is required")
        if len(set(self.evidence_article_ids)) != len(self.evidence_article_ids):
            raise ModelValidationError("suggested interest evidence ids must be unique")
        if any(article_id <= 0 for article_id in self.evidence_article_ids):
            raise ModelValidationError("suggested interest evidence ids must be positive")
        if not self.explanation.strip():
            raise ModelValidationError("suggested interest explanation is required")
        if not self.suggestion_key.strip():
            raise ModelValidationError("suggested interest key is required")
        if self.accepted_profile_id is not None and self.accepted_profile_id <= 0:
            raise ModelValidationError("accepted profile id must be positive")
        object.__setattr__(
            self,
            "profile_fingerprint",
            normalize_whitespace(self.profile_fingerprint),
        )
        object.__setattr__(self, "suggested_name", normalize_whitespace(self.suggested_name))
        object.__setattr__(
            self,
            "suggested_description",
            normalize_whitespace(self.suggested_description),
        )
        object.__setattr__(self, "explanation", normalize_whitespace(self.explanation))
        object.__setattr__(self, "suggestion_key", normalize_whitespace(self.suggestion_key))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        if self.dismissed_at is not None:
            object.__setattr__(self, "dismissed_at", ensure_utc(self.dismissed_at))


@dataclass(frozen=True)
class PreselectionEvidence:
    article_id: str
    preselection_score: float | None
    preselection_threshold: float | None
    passed: bool
    stage: str
    decision_origin: str
    preselector_version: str
    reason: str | None = None


@dataclass(frozen=True)
class DigestResult:
    run_id: int
    profile: InterestProfile
    source_config: Any
    retrieved_count: int
    stored_count: int
    preselected_count: int
    skipped_analysis_count: int
    analyzed_count: int
    new_analysis_count: int
    reused_analysis_count: int
    above_threshold_count: int
    analysis_available: bool
    items: list[DigestItem]
    started_at: datetime
    completed_at: datetime | None
    analysis_complete: bool = True
    skipped_articles: list[Article] = field(default_factory=list)
    unresolved_articles: list[Article] = field(default_factory=list)
    run_status: str = "COMPLETED"
    error_message: str | None = None
    run_origin: RunOrigin = RunOrigin.LEGACY
    date_selection: DateSelection | None = None
    requested_source_dates: tuple[date, ...] = ()
    covered_source_dates: tuple[date, ...] = ()
    empty_source_dates: tuple[date, ...] = ()
    incomplete_source_dates: tuple[date, ...] = ()
    retrieval_complete: bool = True
    retrieval_safety_limit: int | None = None
    preselection_evidence: tuple[PreselectionEvidence, ...] = ()

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
