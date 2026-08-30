"""Saved article Library services."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from research_digest.db import Database
from research_digest.models import (
    Article,
    InterestProfile,
    LibraryCollection,
    LibraryEntry,
    LibraryNote,
    LibraryRelevanceContext,
    LibraryTagAssignment,
    ReadingState,
    TagOrigin,
)

LibrarySort = Literal[
    "saved_newest",
    "saved_oldest",
    "interest_desc",
    "published_newest",
    "published_oldest",
    "title",
]
LibraryInterestFilter = Literal[
    "any",
    "unrated",
    "rated",
    "at_least_1",
    "at_least_2",
    "at_least_3",
    "at_least_4",
    "at_least_5",
]
LibraryReadingFilter = Literal[
    "any",
    "unset",
    "unread",
    "skimmed",
    "read",
    "reference",
]


@dataclass(frozen=True)
class LibraryItem:
    entry: LibraryEntry
    relevance_context: LibraryRelevanceContext | None = None
    note: LibraryNote | None = None
    collections: tuple[LibraryCollection, ...] = ()
    tags: tuple[LibraryTagAssignment, ...] = ()

    @property
    def article(self) -> Article:
        return self.entry.article

    @property
    def user_tags(self) -> tuple[LibraryTagAssignment, ...]:
        return tuple(tag for tag in self.tags if tag.origin == TagOrigin.USER)

    @property
    def ai_tags(self) -> tuple[LibraryTagAssignment, ...]:
        return tuple(tag for tag in self.tags if tag.origin == TagOrigin.AI)


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
    interest_filter: LibraryInterestFilter = "any",
    reading_filter: LibraryReadingFilter = "any",
    collection_id: int | None = None,
    normalized_tag_name: str | None = None,
) -> list[LibraryItem]:
    matching_article_ids: set[int] | None = None
    if query.strip():
        from research_digest.library_search import search_saved_library_article_ids

        matching_article_ids = set(search_saved_library_article_ids(db, query=query))
    entries = db.list_saved_library_entries()
    if not entries:
        return []
    relevance_contexts = db.list_latest_saved_library_relevance_contexts()
    notes = db.list_saved_library_notes()
    collections_by_article = db.list_saved_library_collections_by_article()
    tags_by_article = db.list_saved_library_tag_assignments()
    items: list[LibraryItem] = []
    for entry in entries:
        article_id = entry.article.id
        if article_id is None:
            continue
        items.append(
            LibraryItem(
                entry=entry,
                relevance_context=relevance_contexts.get(article_id),
                note=notes.get(article_id),
                collections=tuple(collections_by_article.get(article_id, ())),
                tags=tuple(tags_by_article.get(article_id, ())),
            )
        )
    if matching_article_ids is not None:
        items = [
            item
            for item in items
            if item.article.id is not None and item.article.id in matching_article_ids
        ]
    if collection_id is not None:
        items = [
            item
            for item in items
            if any(collection.id == collection_id for collection in item.collections)
        ]
    if normalized_tag_name is not None:
        items = [
            item
            for item in items
            if any(
                assignment.tag.normalized_name == normalized_tag_name
                for assignment in item.tags
            )
        ]
    items = [
        item
        for item in items
        if _matches_interest_filter(item, interest_filter=interest_filter)
        and _matches_reading_filter(item, reading_filter=reading_filter)
    ]
    return sort_library_items(items, sort_by=sort_by)


def get_library_item(db: Database, article_id: int) -> LibraryItem | None:
    """Load one detail view from normalized L1-A owners without copied state."""

    entry = db.get_library_entry(article_id)
    if entry is None:
        return None
    return LibraryItem(
        entry=entry,
        relevance_context=db.get_latest_relevance_context(article_id),
        note=db.get_library_note(article_id),
        collections=tuple(db.list_library_collections_for_article(article_id)),
        tags=tuple(db.list_library_tag_assignments(article_id)),
    )


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
    if sort_by == "interest_desc":
        return sorted(
            items,
            key=lambda item: (
                item.entry.interest_rating is None,
                -(item.entry.interest_rating or 0),
                -item.entry.saved_at.timestamp(),
                item.article.title.casefold(),
            ),
        )
    if sort_by == "published_newest":
        return sorted(items, key=lambda item: item.article.published_at, reverse=True)
    if sort_by == "published_oldest":
        return sorted(items, key=lambda item: item.article.published_at)
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
    if item.note is not None:
        fields.append(item.note.note_text)
    fields.extend(collection.name for collection in item.collections)
    fields.extend(assignment.tag.display_name for assignment in item.tags)
    return "\n".join(fields)


def _matches_interest_filter(
    item: LibraryItem,
    *,
    interest_filter: LibraryInterestFilter,
) -> bool:
    rating = item.entry.interest_rating
    if interest_filter == "any":
        return True
    if interest_filter == "unrated":
        return rating is None
    if interest_filter == "rated":
        return rating is not None
    if interest_filter.startswith("at_least_"):
        minimum = int(interest_filter.removeprefix("at_least_"))
        return rating is not None and rating >= minimum
    raise ValueError(f"unknown Library interest filter: {interest_filter}")


def _matches_reading_filter(
    item: LibraryItem,
    *,
    reading_filter: LibraryReadingFilter,
) -> bool:
    reading_state = item.entry.reading_state
    if reading_filter == "any":
        return True
    if reading_filter == "unset":
        return reading_state is None
    return reading_state == ReadingState(reading_filter)
