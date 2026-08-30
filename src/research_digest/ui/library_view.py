"""Pure presentation helpers for the attention-first Library UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from research_digest.library import LibraryItem
from research_digest.models import LibrarySummarySource, ReadingState, ResolvedLibrarySummary
from research_digest.ui.article_header import format_authors

MAX_DENSE_COLLECTIONS = 2
MAX_DENSE_TAGS = 3
MAX_NOTE_PREVIEW_CHARS = 120


@dataclass(frozen=True)
class DenseLibraryRow:
    title: str
    authors_and_year: str
    interest: str
    reading: str
    collections: str
    tags: str
    note_preview: str | None


def build_dense_library_row(item: LibraryItem) -> DenseLibraryRow:
    """Build bounded display text entirely from canonical normalized owners."""

    article = item.article
    collection_names = [collection.name for collection in item.collections]
    tag_names = [assignment.tag.display_name for assignment in item.user_tags]
    tag_names.extend(f"{assignment.tag.display_name} (AI)" for assignment in item.ai_tags)
    note_preview = (
        build_note_preview(item.note.note_text) if item.note is not None else None
    )
    return DenseLibraryRow(
        title=article.title,
        authors_and_year=(
            f"{format_authors(article.authors).compact} · {article.published_at.year}"
        ),
        interest=format_interest_rating(item.entry.interest_rating),
        reading=format_reading_state(item.entry.reading_state),
        collections=format_bounded_names(
            collection_names,
            limit=MAX_DENSE_COLLECTIONS,
            empty="None",
        ),
        tags=format_bounded_names(tag_names, limit=MAX_DENSE_TAGS, empty="None"),
        note_preview=note_preview,
    )


def format_interest_rating(rating: int | None) -> str:
    if rating is None:
        return "Unrated"
    return f"{'★' * rating}{'☆' * (5 - rating)} ({rating}/5)"


def format_reading_state(reading_state: ReadingState | None) -> str:
    if reading_state is None:
        return "Not set"
    return reading_state.value.capitalize()


def format_bounded_names(values: list[str], *, limit: int, empty: str) -> str:
    if limit <= 0:
        raise ValueError("display limit must be positive")
    normalized = [value.strip() for value in values if value.strip()]
    if not normalized:
        return empty
    visible = normalized[:limit]
    hidden = len(normalized) - len(visible)
    text = " · ".join(visible)
    return f"{text} · +{hidden} more" if hidden else text


def build_note_preview(note_text: str, *, max_chars: int = MAX_NOTE_PREVIEW_CHARS) -> str | None:
    if max_chars < 2:
        raise ValueError("note preview limit must be at least two characters")
    compact = " ".join(note_text.split())
    if not compact:
        return None
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1].rstrip()}…"


def summary_source_label(summary: ResolvedLibrarySummary) -> str:
    if summary.source == LibrarySummarySource.LIBRARY_ARTIFACT:
        kind = "Library summary"
    else:
        kind = "Digest summary"
    return f"{kind} · {format_compact_date(summary.created_at)}"


def format_compact_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")
