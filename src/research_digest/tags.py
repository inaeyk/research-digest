"""Library tag services and AI tag generation contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from research_digest.db import Database
from research_digest.models import (
    Article,
    LibraryRelevanceContext,
    LibraryTagAssignment,
    TagOrigin,
    datetime_to_db,
    normalize_whitespace,
    utc_now,
)

AI_TAG_PROMPT_VERSION = "library_ai_tags_v1"
MAX_TAG_DISPLAY_LENGTH = 80
DEFAULT_MAX_AI_TAGS = 6


class TagValidationError(ValueError):
    """Raised when a Library tag cannot be normalized safely."""


@dataclass(frozen=True)
class NormalizedTagName:
    normalized_name: str
    display_name: str


@dataclass(frozen=True)
class ArticleTags:
    user_tags: tuple[LibraryTagAssignment, ...]
    ai_tags: tuple[LibraryTagAssignment, ...]


@dataclass(frozen=True)
class AITagSuggestion:
    tag: str


@dataclass(frozen=True)
class AITagGeneration:
    suggestions: tuple[AITagSuggestion, ...]
    provenance: dict[str, object]


class AITagGenerator(Protocol):
    def suggest_tags(
        self,
        *,
        article: Article,
        relevance_context: LibraryRelevanceContext | None,
        max_tags: int = DEFAULT_MAX_AI_TAGS,
    ) -> AITagGeneration:
        """Suggest concise scientific tags for one saved article."""


def normalize_tag_name(value: str) -> NormalizedTagName:
    display = normalize_whitespace(value)
    if display.startswith("#"):
        display = normalize_whitespace(display[1:])
    if not display:
        raise TagValidationError("tag is required")
    if len(display) > MAX_TAG_DISPLAY_LENGTH:
        raise TagValidationError(f"tag must be at most {MAX_TAG_DISPLAY_LENGTH} characters")
    normalized = display.casefold()
    if not normalized:
        raise TagValidationError("tag is required")
    return NormalizedTagName(normalized_name=normalized, display_name=display)


def add_user_tag(db: Database, *, article_id: int, tag: str) -> LibraryTagAssignment:
    normalized = normalize_tag_name(tag)
    return db.upsert_library_tag_assignment(
        article_id=article_id,
        normalized_name=normalized.normalized_name,
        display_name=normalized.display_name,
        origin=TagOrigin.USER,
    )


def remove_user_tag(db: Database, *, article_id: int, tag: str) -> None:
    normalized = normalize_tag_name(tag)
    db.remove_library_tag_assignment(
        article_id=article_id,
        normalized_name=normalized.normalized_name,
        origin=TagOrigin.USER,
    )


def assign_ai_tags(
    db: Database,
    *,
    article_id: int,
    tags: Sequence[str],
    provenance: dict[str, object],
    respect_suppressions: bool = True,
) -> list[LibraryTagAssignment]:
    suppressed = {
        suppression.tag.normalized_name
        for suppression in db.list_ai_library_tag_suppressions(article_id)
    } if respect_suppressions else set()
    assignments: list[LibraryTagAssignment] = []
    seen: set[str] = set()
    for tag in tags:
        try:
            normalized = normalize_tag_name(tag)
        except TagValidationError:
            continue
        if normalized.normalized_name in seen:
            continue
        seen.add(normalized.normalized_name)
        if normalized.normalized_name in suppressed:
            continue
        assignments.append(
            db.upsert_library_tag_assignment(
                article_id=article_id,
                normalized_name=normalized.normalized_name,
                display_name=normalized.display_name,
                origin=TagOrigin.AI,
                ai_provenance=dict(provenance),
            )
        )
    return assignments


def remove_ai_tag(
    db: Database,
    *,
    article_id: int,
    tag: str,
    reason: str = "user_removed_ai_tag",
) -> None:
    normalized = normalize_tag_name(tag)
    db.remove_library_tag_assignment(
        article_id=article_id,
        normalized_name=normalized.normalized_name,
        origin=TagOrigin.AI,
    )
    db.suppress_ai_library_tag(
        article_id=article_id,
        normalized_name=normalized.normalized_name,
        display_name=normalized.display_name,
        reason=reason,
    )


def list_article_tags(db: Database, *, article_id: int) -> ArticleTags:
    assignments = db.list_library_tag_assignments(article_id)
    user_tags = tuple(item for item in assignments if item.origin == TagOrigin.USER)
    ai_tags = tuple(item for item in assignments if item.origin == TagOrigin.AI)
    return ArticleTags(user_tags=user_tags, ai_tags=ai_tags)


def generate_ai_tags_for_saved_article(
    db: Database,
    *,
    article_id: int,
    generator: AITagGenerator,
    max_tags: int = DEFAULT_MAX_AI_TAGS,
    regenerate: bool = False,
    clear_suppressions: bool = False,
) -> list[LibraryTagAssignment]:
    if max_tags <= 0:
        raise ValueError("max AI tags must be positive")
    entry = db.get_library_entry(article_id)
    if entry is None:
        raise ValueError("AI tags can only be generated for saved Library articles")
    relevance_context = db.get_latest_relevance_context(article_id)
    generation = generator.suggest_tags(
        article=entry.article,
        relevance_context=relevance_context,
        max_tags=max_tags,
    )
    provenance = _complete_ai_provenance(
        generation.provenance,
        article=entry.article,
        relevance_context=relevance_context,
    )
    if clear_suppressions:
        db.delete_ai_library_tag_suppressions(article_id)
    if regenerate:
        db.remove_library_tag_assignments_for_origin(
            article_id=article_id,
            origin=TagOrigin.AI,
        )
    return assign_ai_tags(
        db,
        article_id=article_id,
        tags=[suggestion.tag for suggestion in generation.suggestions],
        provenance=provenance,
        respect_suppressions=not clear_suppressions,
    )


def _complete_ai_provenance(
    provenance: dict[str, object],
    *,
    article: Article,
    relevance_context: LibraryRelevanceContext | None,
) -> dict[str, object]:
    completed = dict(provenance)
    completed.setdefault("prompt_version", AI_TAG_PROMPT_VERSION)
    completed.setdefault("generated_at", datetime_to_db(utc_now()))
    completed.setdefault("source", article.source)
    completed.setdefault("source_article_id", article.source_article_id)
    completed.setdefault("article_updated_at", datetime_to_db(article.updated_at))
    completed.setdefault("relevance_context_included", relevance_context is not None)
    return completed
