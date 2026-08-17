"""Saved article Library services."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from research_digest.db import Database
from research_digest.models import Article, LibraryEntry, LibraryRelevanceContext

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


def unsave_article(db: Database, article_id: int) -> None:
    """Remove an article from the Library without deleting scientific history."""

    db.unsave_library_article(article_id)


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
    return sort_library_items(filter_library_items(items, query=query), sort_by=sort_by)


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
