"""Derived local search documents for the saved Library."""

from __future__ import annotations

import re
from collections.abc import Iterable

from research_digest.db import Database
from research_digest.library import LibraryItem
from research_digest.models import Article, LibraryRelevanceContext

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{2,}")
_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "into",
    "paper",
    "papers",
    "that",
    "the",
    "their",
    "this",
    "through",
    "using",
    "with",
}


def rebuild_library_search_index(db: Database) -> None:
    """Rebuild derived Library search documents from normalized tables."""

    saved_entries = db.list_saved_library_entries()
    saved_ids = [entry.article.id for entry in saved_entries if entry.article.id is not None]
    for entry in saved_entries:
        article_id = entry.article.id
        if article_id is None:
            continue
        db.upsert_library_search_document(
            article_id=article_id,
            document_text=build_library_search_document(db, article=entry.article),
        )
    db.prune_library_search_documents(saved_ids)


def refresh_library_search_document(db: Database, *, article_id: int) -> None:
    entry = db.get_library_entry(article_id)
    if entry is None:
        db.delete_library_search_document(article_id)
        return
    db.upsert_library_search_document(
        article_id=article_id,
        document_text=build_library_search_document(db, article=entry.article),
    )


def search_saved_library_article_ids(db: Database, *, query: str) -> list[int]:
    if not query.strip():
        return []
    rebuild_library_search_index(db)
    return db.search_library_document_article_ids(query)


def build_library_search_document(db: Database, *, article: Article) -> str:
    article_id = article.id
    fields: list[str] = [
        article.title,
        " ".join(article.authors),
        " ".join(article.categories),
        article.abstract,
        article.source,
        article.source_article_id,
    ]
    if article_id is not None:
        note = db.get_library_note(article_id)
        if note is not None:
            fields.append(note.note_text)
        fields.extend(_tag_fields(db, article_id))
        fields.extend(_collection_fields(db, article_id))
        context = db.get_latest_relevance_context(article_id)
        if context is not None:
            fields.extend(_relevance_fields(context))
    return "\n".join(field for field in fields if field).casefold()


def search_tokens(values: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for match in _TOKEN_RE.finditer(value.casefold()):
            token = match.group(0)
            if token not in _STOPWORDS:
                tokens.add(token)
    return tokens


def filter_items_by_search_ids(
    items: list[LibraryItem],
    *,
    matching_article_ids: set[int],
) -> list[LibraryItem]:
    return [
        item
        for item in items
        if item.article.id is not None and item.article.id in matching_article_ids
    ]


def _tag_fields(db: Database, article_id: int) -> list[str]:
    return [
        f"{assignment.tag.display_name} {assignment.tag.normalized_name}"
        for assignment in db.list_library_tag_assignments(article_id)
    ]


def _collection_fields(db: Database, article_id: int) -> list[str]:
    fields: list[str] = []
    for collection in db.list_library_collections_for_article(article_id):
        fields.append(collection.name)
        if collection.description:
            fields.append(collection.description)
    return fields


def _relevance_fields(context: LibraryRelevanceContext) -> list[str]:
    return [
        context.profile_name,
        context.reading_priority,
        f"{context.relevance_score:.3f}",
    ]
