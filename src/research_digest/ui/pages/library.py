"""Saved article Library page."""

from __future__ import annotations

from typing import Any

from research_digest.library import LibraryItem, LibrarySort, list_library_items
from research_digest.models import Article, LibraryRelevanceContext
from research_digest.ui.abstracts import render_abstract_control
from research_digest.ui.common import get_database
from research_digest.ui.library_controls import render_library_control

_SORT_OPTIONS: tuple[LibrarySort, ...] = (
    "saved_newest",
    "saved_oldest",
    "published_newest",
    "title",
)
_SORT_LABELS: dict[LibrarySort, str] = {
    "saved_newest": "Saved newest",
    "saved_oldest": "Saved oldest",
    "published_newest": "Published newest",
    "title": "Title",
}


def render() -> None:
    import streamlit as st

    st.title("Library")
    db = get_database()

    with st.form("library_filters", border=False):
        query = st.text_input("Search Library", placeholder="Title, author, category, abstract...")
        sort_by = st.selectbox(
            "Sort",
            options=_SORT_OPTIONS,
            format_func=lambda value: _SORT_LABELS[value],
        )
        st.form_submit_button("Apply", icon=":material/search:")

    items = list_library_items(db, query=query, sort_by=sort_by)
    if not items:
        if query.strip():
            st.info("No saved papers match the current search.")
        else:
            st.info("No papers have been saved to the Library yet.")
        return

    st.caption(f"{len(items)} saved paper(s)")
    for item in items:
        _render_library_item(item)


def _render_library_item(item: LibraryItem) -> None:
    import streamlit as st

    article = item.article
    with st.container(border=True):
        st.subheader(article.title)
        st.caption(_article_caption(article))
        metric_cols = st.columns(3)
        metric_cols[0].metric("Saved", f"{item.entry.saved_at:%Y-%m-%d}")
        metric_cols[1].metric("Published", f"{article.published_at:%Y-%m-%d}")
        _render_relevance_metric(metric_cols[2], item.relevance_context)
        _render_relevance_context(item.relevance_context)
        with st.container(horizontal=True):
            st.link_button("arXiv", article.abstract_url)
            if article.pdf_url:
                st.link_button("PDF", article.pdf_url)
        render_abstract_control(
            source=article.source,
            source_article_id=article.source_article_id,
            abstract=article.abstract,
            context=f"library:{article.source}:{article.source_article_id}",
        )
        db = get_database()
        render_library_control(
            db=db,
            article=article,
            context=f"library:membership:{article.source}:{article.source_article_id}",
        )


def _article_caption(article: Article) -> str:
    authors = ", ".join(article.authors) if article.authors else "Unknown authors"
    categories = ", ".join(article.categories) if article.categories else "Uncategorized"
    return (
        f"{article.source}:{article.source_article_id} | {authors} | "
        f"Published {article.published_at:%Y-%m-%d %H:%M UTC} | "
        f"Categories: {categories}"
    )


def _render_relevance_metric(column: Any, context: LibraryRelevanceContext | None) -> None:
    if context is None:
        column.metric("Relevance", "-")
        return
    column.metric("Relevance", f"{context.relevance_score:.2f}")


def _render_relevance_context(context: LibraryRelevanceContext | None) -> None:
    import streamlit as st

    if context is None:
        st.caption("No relevance analysis is available for this saved paper.")
        return
    st.caption(
        f"Latest relevance context: {context.profile_name}; "
        f"priority {context.reading_priority}; analyzed {context.analyzed_at:%Y-%m-%d}."
    )
