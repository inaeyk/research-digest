"""Library notes and collection services."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research_digest.db import Database
from research_digest.library import LibraryItem
from research_digest.models import LibraryCollection, LibraryNote, normalize_whitespace
from research_digest.tags import list_article_tags

MAX_COLLECTION_NAME_LENGTH = 120


class CollectionValidationError(ValueError):
    """Raised when a collection name cannot be normalized safely."""


@dataclass(frozen=True)
class NormalizedCollectionName:
    normalized_name: str
    display_name: str


def normalize_collection_name(value: str) -> NormalizedCollectionName:
    display = normalize_whitespace(value)
    if not display:
        raise CollectionValidationError("collection name is required")
    if len(display) > MAX_COLLECTION_NAME_LENGTH:
        raise CollectionValidationError(
            f"collection name must be at most {MAX_COLLECTION_NAME_LENGTH} characters"
        )
    return NormalizedCollectionName(
        normalized_name=display.casefold(),
        display_name=display,
    )


def save_note(db: Database, *, article_id: int, note_text: str) -> LibraryNote | None:
    return db.save_library_note(article_id=article_id, note_text=note_text)


def get_note(db: Database, *, article_id: int) -> LibraryNote | None:
    return db.get_library_note(article_id)


def delete_note(db: Database, *, article_id: int) -> None:
    db.delete_library_note(article_id=article_id)


def create_collection(
    db: Database,
    *,
    name: str,
    description: str = "",
) -> LibraryCollection:
    normalized = normalize_collection_name(name)
    return db.create_library_collection(
        name=normalized.display_name,
        normalized_name=normalized.normalized_name,
        description=description,
    )


def rename_collection(
    db: Database,
    *,
    collection_id: int,
    name: str,
    description: str,
) -> LibraryCollection:
    normalized = normalize_collection_name(name)
    return db.update_library_collection(
        collection_id=collection_id,
        name=normalized.display_name,
        normalized_name=normalized.normalized_name,
        description=description,
    )


def delete_collection(db: Database, *, collection_id: int) -> None:
    db.delete_library_collection(collection_id)


def list_collections(db: Database) -> list[LibraryCollection]:
    return db.list_library_collections()


def add_article_to_collection(
    db: Database,
    *,
    collection_id: int,
    article_id: int,
) -> None:
    db.add_library_collection_membership(
        collection_id=collection_id,
        article_id=article_id,
    )


def remove_article_from_collection(
    db: Database,
    *,
    collection_id: int,
    article_id: int,
) -> None:
    db.remove_library_collection_membership(
        collection_id=collection_id,
        article_id=article_id,
    )


def list_article_collections(
    db: Database,
    *,
    article_id: int,
) -> list[LibraryCollection]:
    return db.list_library_collections_for_article(article_id)


def filter_library_items_by_collection(
    db: Database,
    items: Sequence[LibraryItem],
    *,
    collection_id: int | None,
) -> list[LibraryItem]:
    if collection_id is None:
        return list(items)
    memberships = db.list_library_collection_memberships(collection_id)
    article_ids = {membership.article_id for membership in memberships}
    return [item for item in items if item.article.id in article_ids]


def filter_library_items_by_tag(
    db: Database,
    items: Sequence[LibraryItem],
    *,
    normalized_tag_name: str | None,
) -> list[LibraryItem]:
    if normalized_tag_name is None:
        return list(items)
    filtered: list[LibraryItem] = []
    for item in items:
        article_id = item.article.id
        if article_id is None:
            continue
        tags = list_article_tags(db, article_id=article_id)
        if any(
            assignment.tag.normalized_name == normalized_tag_name
            for assignment in (*tags.user_tags, *tags.ai_tags)
        ):
            filtered.append(item)
    return filtered
