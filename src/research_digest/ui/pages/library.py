"""Saved article Library page."""

from __future__ import annotations

from typing import Any

from research_digest.errors import sanitize_error
from research_digest.library import LibraryItem, LibrarySort, list_library_items
from research_digest.models import Article, LibraryRelevanceContext, TagOrigin
from research_digest.tags import (
    TagValidationError,
    add_user_tag,
    generate_ai_tags_for_saved_article,
    list_article_tags,
    remove_ai_tag,
    remove_user_tag,
)
from research_digest.ui.abstracts import render_abstract_control
from research_digest.ui.common import get_ai_tag_generator, get_database
from research_digest.ui.library_controls import render_library_control
from research_digest.ui.tag_controls import ai_tag_generation_label, tag_action_key

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
        _render_tags(item)
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


def _render_tags(item: LibraryItem) -> None:
    import streamlit as st

    article = item.article
    if article.id is None:
        return
    db = get_database()
    tags = list_article_tags(db, article_id=article.id)
    st.markdown("**Tags**")
    user_col, ai_col = st.columns(2)
    with user_col:
        st.caption("User tags")
        if tags.user_tags:
            for assignment in tags.user_tags:
                with st.container(horizontal=True):
                    st.badge(assignment.tag.display_name, color="blue")
                    if st.button(
                        "Remove",
                        key=tag_action_key(
                            article_id=article.id,
                            action="remove",
                            origin=TagOrigin.USER,
                            normalized_name=assignment.tag.normalized_name,
                        ),
                        icon=":material/close:",
                    ):
                        remove_user_tag(
                            db,
                            article_id=article.id,
                            tag=assignment.tag.display_name,
                        )
                        st.rerun()
        else:
            st.caption("No user tags")
        with st.form(f"add_user_tag_{article.id}", border=False):
            tag_text = st.text_input("Add user tag", placeholder="e.g. black branes")
            submitted = st.form_submit_button("Add tag", icon=":material/add:")
        if submitted:
            try:
                add_user_tag(db, article_id=article.id, tag=tag_text)
            except TagValidationError as exc:
                st.warning(str(exc), icon=":material/warning:")
            else:
                st.rerun()
    with ai_col:
        st.caption("AI tags")
        if tags.ai_tags:
            for assignment in tags.ai_tags:
                with st.container(horizontal=True):
                    st.badge(assignment.tag.display_name, color="green")
                    st.caption("AI")
                    if st.button(
                        "Remove",
                        key=tag_action_key(
                            article_id=article.id,
                            action="remove",
                            origin=TagOrigin.AI,
                            normalized_name=assignment.tag.normalized_name,
                        ),
                        icon=":material/close:",
                    ):
                        remove_ai_tag(
                            db,
                            article_id=article.id,
                            tag=assignment.tag.display_name,
                        )
                        st.rerun()
        else:
            st.caption("No AI tags")
        _render_ai_tag_generation(article_id=article.id, has_ai_tags=bool(tags.ai_tags))


def _render_ai_tag_generation(*, article_id: int, has_ai_tags: bool) -> None:
    import streamlit as st

    generator, message = get_ai_tag_generator()
    label = ai_tag_generation_label(has_ai_tags=has_ai_tags)
    if st.button(
        label,
        key=tag_action_key(
            article_id=article_id,
            action="generate",
            origin=TagOrigin.AI,
        ),
        icon=":material/auto_awesome:",
        disabled=generator is None,
    ):
        if generator is None:
            st.warning(message or "AI tag generation is unavailable.", icon=":material/warning:")
            return
        with st.spinner("Generating AI tags..."):
            try:
                assignments = generate_ai_tags_for_saved_article(
                    get_database(),
                    article_id=article_id,
                    generator=generator,
                    regenerate=has_ai_tags,
                )
            except Exception as exc:
                st.error(
                    f"AI tag generation failed: {sanitize_error(exc)}",
                    icon=":material/error:",
                )
                return
        if assignments:
            st.success(f"Added {len(assignments)} AI tag(s).", icon=":material/check_circle:")
        else:
            st.info("No new AI tags were added.")
        st.rerun()
    if generator is None and message:
        st.caption(f"AI tag generation unavailable: {sanitize_error(message)}")


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
