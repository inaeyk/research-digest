"""Deterministic source-metadata headers for paper presentations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from research_digest.models import Article

MAX_VISIBLE_AUTHORS = 5
_MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

ArticleTitleStyle = Literal["title", "subheader", "markdown"]


@dataclass(frozen=True)
class AuthorPresentation:
    compact: str
    full: str
    author_count: int
    hidden_count: int


def format_authors(authors: Sequence[str]) -> AuthorPresentation:
    """Preserve source order while producing a bounded author-line presentation."""

    names = tuple(author.strip() for author in authors if author.strip())
    if not names:
        return AuthorPresentation(
            compact="Authors unavailable",
            full="Authors unavailable",
            author_count=0,
            hidden_count=0,
        )
    hidden_count = max(len(names) - MAX_VISIBLE_AUTHORS, 0)
    compact_names = names[:MAX_VISIBLE_AUTHORS]
    compact = ", ".join(compact_names)
    if hidden_count:
        compact += f", +{hidden_count} more"
    return AuthorPresentation(
        compact=compact,
        full=", ".join(names),
        author_count=len(names),
        hidden_count=hidden_count,
    )


def render_article_header(
    article: Article,
    *,
    context: str,
    title_style: ArticleTitleStyle = "subheader",
    show_all_authors: bool = True,
) -> None:
    """Render title, authors, then publication/source metadata from a stored article."""

    render_article_identity(
        title=article.title,
        authors=article.authors,
        published_at=article.published_at,
        categories=article.categories,
        source=article.source,
        source_article_id=article.source_article_id,
        context=context,
        title_style=title_style,
        show_all_authors=show_all_authors,
    )


def render_snapshot_article_header(
    payload: Mapping[str, object],
    *,
    context: str,
    fallback_source: str = "unknown",
    title_style: ArticleTitleStyle = "markdown",
) -> None:
    """Render only article metadata frozen into an immutable History snapshot."""

    title = payload.get("title")
    source = payload.get("source")
    source_article_id = payload.get("source_article_id")
    render_article_identity(
        title=title if isinstance(title, str) and title.strip() else "Untitled paper",
        authors=_snapshot_strings(payload.get("authors")),
        published_at=payload.get("published_at"),
        categories=_snapshot_strings(payload.get("categories")),
        source=source if isinstance(source, str) and source.strip() else fallback_source,
        source_article_id=(
            source_article_id
            if isinstance(source_article_id, str) and source_article_id.strip()
            else "unknown"
        ),
        context=context,
        title_style=title_style,
    )


def render_article_identity(
    *,
    title: str,
    authors: Sequence[str],
    published_at: object,
    categories: Sequence[str],
    source: str,
    source_article_id: str,
    context: str,
    title_style: ArticleTitleStyle,
    show_all_authors: bool = True,
) -> None:
    import streamlit as st

    if title_style == "title":
        st.title(title)
    elif title_style == "subheader":
        st.subheader(title)
    else:
        st.markdown(f"**{title}**")
    author_presentation = format_authors(authors)
    st.write(author_presentation.compact)
    if show_all_authors and author_presentation.hidden_count:
        with st.expander(
            "Show all authors",
            icon=":material/group:",
        ):
            st.write(author_presentation.full)
    st.caption(
        format_article_metadata(
            published_at=published_at,
            categories=categories,
            source=source,
            source_article_id=source_article_id,
        )
    )


def format_article_metadata(
    *,
    published_at: object,
    categories: Sequence[str],
    source: str,
    source_article_id: str,
) -> str:
    publication_date = _publication_date(published_at)
    publication = (
        f"Published {_format_date(publication_date)}"
        if publication_date is not None
        else "Publication date unavailable"
    )
    normalized_categories = tuple(category.strip() for category in categories if category.strip())
    category_text = " · ".join(normalized_categories) or "Uncategorized"
    source_name = "arXiv" if source.strip().casefold() == "arxiv" else source.strip()
    source_identity = ":".join(
        value for value in (source_name or "unknown", source_article_id.strip() or "unknown")
    )
    return f"{publication} · {category_text} · {source_identity}"


def _snapshot_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _publication_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def _format_date(value: date) -> str:
    return f"{_MONTH_NAMES[value.month - 1]} {value.day}, {value.year}"
