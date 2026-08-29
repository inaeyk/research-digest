"""Saved article Library services."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from research_digest.db import Database
from research_digest.models import (
    Article,
    InterestProfile,
    LibraryEntry,
    LibraryRelevanceContext,
    ReadingState,
)

LibrarySort = Literal["saved_newest", "saved_oldest", "published_newest", "title"]


@dataclass(frozen=True)
class LibraryItem:
    entry: LibraryEntry
    relevance_context: LibraryRelevanceContext | None = None

    @property
    def article(self) -> Article:
        return self.entry.article


def save_article(db: Database, article_id: int) -> LibraryEntry:
    """Persist explicit user intent to keep an article in the Library."""

    return db.save_library_article(article_id)


def save_article_with_personal_interest(
    db: Database,
    *,
    article_id: int,
    profile: InterestProfile | None,
    profile_fingerprint_value: str | None,
) -> LibraryEntry:
    """Save an article and, when profile context exists, record personal interest."""

    entry = save_article(db, article_id)
    if profile is not None and profile.id is not None and profile_fingerprint_value is not None:
        db.upsert_article_feedback(
            article_id=article_id,
            profile_id=profile.id,
            profile_fingerprint=profile_fingerprint_value,
            personal_interest="YES",
        )
    return entry


def unsave_article(db: Database, article_id: int) -> None:
    """Remove an article from the Library without deleting scientific history."""

    db.unsave_library_article(article_id)


def set_reading_state(
    db: Database,
    *,
    article_id: int,
    reading_state: ReadingState | None,
) -> LibraryEntry:
    """Set explicit durable reading state without inferring it from saving."""

    return db.set_library_reading_state(article_id, reading_state)


def set_interest_rating(
    db: Database,
    *,
    article_id: int,
    interest_rating: int | None,
) -> LibraryEntry:
    """Set an explicit ordinal judgment independently of digest feedback."""

    return db.set_library_interest_rating(article_id, interest_rating)


def save_article_by_source_identity(
    db: Database,
    *,
    source: str,
    source_article_id: str,
) -> LibraryEntry | None:
    article = db.get_article_by_source_id(source, source_article_id)
    if article is None or article.id is None:
        return None
    return save_article(db, article.id)


def save_article_by_source_identity_with_personal_interest(
    db: Database,
    *,
    source: str,
    source_article_id: str,
    profile: InterestProfile | None,
    profile_fingerprint_value: str | None,
) -> LibraryEntry | None:
    article = db.get_article_by_source_id(source, source_article_id)
    if article is None or article.id is None:
        return None
    return save_article_with_personal_interest(
        db,
        article_id=article.id,
        profile=profile,
        profile_fingerprint_value=profile_fingerprint_value,
    )


def unsave_article_by_source_identity(
    db: Database,
    *,
    source: str,
    source_article_id: str,
) -> bool:
    article = db.get_article_by_source_id(source, source_article_id)
    if article is None or article.id is None:
        return False
    unsave_article(db, article.id)
    return True


def is_article_saved(db: Database, article_id: int | None) -> bool:
    if article_id is None:
        return False
    return db.get_library_entry(article_id) is not None


def is_source_article_saved(
    db: Database,
    *,
    source: str,
    source_article_id: str,
) -> bool:
    article = db.get_article_by_source_id(source, source_article_id)
    return is_article_saved(db, article.id if article is not None else None)


def saved_article_ids(db: Database, articles: Sequence[Article]) -> set[int]:
    ids = [article.id for article in articles if article.id is not None]
    return db.list_saved_library_article_ids(ids)


def list_library_items(
    db: Database,
    *,
    query: str = "",
    sort_by: LibrarySort = "saved_newest",
    collection_id: int | None = None,
    normalized_tag_name: str | None = None,
) -> list[LibraryItem]:
    matching_article_ids: set[int] | None = None
    if query.strip():
        from research_digest.library_search import search_saved_library_article_ids

        matching_article_ids = set(search_saved_library_article_ids(db, query=query))
    items = [
        LibraryItem(
            entry=entry,
            relevance_context=(
                db.get_latest_relevance_context(entry.article.id)
                if entry.article.id is not None
                else None
            ),
        )
        for entry in db.list_saved_library_entries()
    ]
    if matching_article_ids is not None:
        items = [
            item
            for item in items
            if item.article.id is not None and item.article.id in matching_article_ids
        ]
    if collection_id is not None:
        memberships = db.list_library_collection_memberships(collection_id)
        article_ids = {membership.article_id for membership in memberships}
        items = [item for item in items if item.article.id in article_ids]
    if normalized_tag_name is not None:
        items = [
            item
            for item in items
            if item.article.id is not None
            and any(
                assignment.tag.normalized_name == normalized_tag_name
                for assignment in db.list_library_tag_assignments(item.article.id)
            )
        ]
    return sort_library_items(items, sort_by=sort_by)


def filter_library_items(items: Sequence[LibraryItem], *, query: str) -> list[LibraryItem]:
    needle = query.strip().casefold()
    if not needle:
        return list(items)
    return [item for item in items if needle in _search_text(item).casefold()]


def sort_library_items(
    items: Sequence[LibraryItem],
    *,
    sort_by: LibrarySort,
) -> list[LibraryItem]:
    if sort_by == "saved_newest":
        return sorted(items, key=lambda item: item.entry.saved_at, reverse=True)
    if sort_by == "saved_oldest":
        return sorted(items, key=lambda item: item.entry.saved_at)
    if sort_by == "published_newest":
        return sorted(items, key=lambda item: item.article.published_at, reverse=True)
    if sort_by == "title":
        return sorted(
            items,
            key=lambda item: (
                item.article.title.casefold(),
                item.article.source,
                item.article.source_article_id,
            ),
        )
    raise ValueError(f"unknown library sort: {sort_by}")


def _search_text(item: LibraryItem) -> str:
    article = item.article
    fields = [
        article.title,
        " ".join(article.authors),
        " ".join(article.categories),
        article.abstract,
        article.source,
        article.source_article_id,
    ]
    context = item.relevance_context
    if context is not None:
        fields.extend(
            [
                context.profile_name,
                context.reading_priority,
                f"{context.relevance_score:.3f}",
            ]
        )
    return "\n".join(fields)
