"""Attention-first saved-paper Library list and detail views."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from research_digest.ai_artifacts import resolve_preferred_library_summary
from research_digest.collections import (
    CollectionValidationError,
    add_article_to_collection,
    create_collection,
    delete_collection,
    remove_article_from_collection,
    rename_collection,
    save_note,
)
from research_digest.connections import dismiss_connection, list_related_connections
from research_digest.conversations import (
    AIConversationOverview,
    list_conversation_overviews,
    list_messages,
)
from research_digest.errors import sanitize_error
from research_digest.library import (
    LibraryInterestFilter,
    LibraryItem,
    LibraryReadingFilter,
    LibrarySort,
    get_library_item,
    list_library_items,
    set_interest_rating,
    set_reading_state,
    unsave_article,
)
from research_digest.library_context import build_collection_intelligence_snapshot
from research_digest.models import LibraryCollection, LibraryTag, ReadingState
from research_digest.tags import (
    TagValidationError,
    add_user_tag,
    normalize_tag_name,
    remove_ai_tag,
    remove_user_tag,
)
from research_digest.ui.article_header import render_article_header
from research_digest.ui.common import get_database
from research_digest.ui.library_view import (
    build_dense_library_row,
    format_compact_date,
    summary_source_label,
)
from research_digest.ui.tag_controls import (
    collection_action_key,
    collection_intelligence_action_key,
    connection_action_key,
)

_DETAIL_QUERY_PARAM = "paper"
_FILTER_SESSION_KEY = "library_filter_selection"
_SORT_OPTIONS: tuple[LibrarySort, ...] = (
    "saved_newest",
    "interest_desc",
    "published_newest",
    "published_oldest",
    "title",
)
_SORT_LABELS: dict[LibrarySort, str] = {
    "saved_newest": "Recently saved",
    "saved_oldest": "Saved oldest",
    "interest_desc": "Interest high → low",
    "published_newest": "Publication newest",
    "published_oldest": "Publication oldest",
    "title": "Title",
}
_INTEREST_FILTER_OPTIONS: tuple[LibraryInterestFilter, ...] = (
    "any",
    "unrated",
    "rated",
    "at_least_3",
    "at_least_4",
    "at_least_5",
)
_INTEREST_FILTER_LABELS: dict[LibraryInterestFilter, str] = {
    "any": "Any",
    "unrated": "Unrated",
    "rated": "Any rated",
    "at_least_1": "1+",
    "at_least_2": "2+",
    "at_least_3": "3+",
    "at_least_4": "4+",
    "at_least_5": "5",
}
_READING_FILTER_OPTIONS: tuple[LibraryReadingFilter, ...] = (
    "any",
    "unset",
    "unread",
    "skimmed",
    "read",
    "reference",
)
_READING_FILTER_LABELS: dict[LibraryReadingFilter, str] = {
    "any": "Any",
    "unset": "Not set",
    "unread": "Unread",
    "skimmed": "Skimmed",
    "read": "Read",
    "reference": "Reference",
}
_RATING_OPTIONS: tuple[int | None, ...] = (None, 1, 2, 3, 4, 5)
_READING_OPTIONS: tuple[ReadingState | None, ...] = (None, *tuple(ReadingState))


@dataclass(frozen=True)
class _LibraryFilterSelection:
    query: str
    sort_by: LibrarySort
    interest: LibraryInterestFilter
    reading: LibraryReadingFilter
    collection_id: int | None
    normalized_tag_name: str | None


def render() -> None:
    import streamlit as st

    detail_article_id = parse_detail_article_id(st.query_params.get(_DETAIL_QUERY_PARAM))
    if detail_article_id is not None:
        _render_paper_detail(detail_article_id)
        return
    _render_library_list()


def parse_detail_article_id(value: object) -> int | None:
    if isinstance(value, list):
        value = value[-1] if value else None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        article_id = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    return article_id if article_id > 0 else None


def _render_library_list() -> None:
    import streamlit as st

    st.title("Library")
    db = get_database()
    collections = db.list_library_collections()
    known_tags = db.list_library_tags()
    filters = _render_filter_controls(collections, known_tags)
    _render_collection_management(collections)
    items = list_library_items(
        db,
        query=filters.query,
        sort_by=filters.sort_by,
        interest_filter=filters.interest,
        reading_filter=filters.reading,
        collection_id=filters.collection_id,
        normalized_tag_name=filters.normalized_tag_name,
    )
    if not items:
        if _filters_are_active(filters):
            st.info("No saved papers match the current filters.")
        else:
            st.info("No papers have been saved to the Library yet.")
        return

    st.caption(f"{len(items)} saved paper(s) · select a title to open details")
    with st.container(gap=None):
        for item in items:
            _render_dense_library_row(item)


def _render_filter_controls(
    collections: list[LibraryCollection],
    known_tags: Sequence[LibraryTag],
) -> _LibraryFilterSelection:
    import streamlit as st

    defaults = _persisted_filter_selection(
        st.session_state.get(_FILTER_SESSION_KEY),
        collections=collections,
        known_tags=known_tags,
    )
    collection_options = [None, *collections]
    selected_collection = next(
        (
            collection
            for collection in collections
            if collection.id == defaults.collection_id
        ),
        None,
    )
    tag_options = [None, *known_tags]
    selected_tag = next(
        (
            tag
            for tag in known_tags
            if tag.normalized_name == defaults.normalized_tag_name
        ),
        None,
    )
    with st.form("library_filters", border=False):
        query = st.text_input(
            "Search",
            value=defaults.query,
            placeholder="Title, author, tag, collection, abstract, note…",
            key="library_search",
        )
        interest_col, reading_col, collection_col, tag_col = st.columns(4)
        with interest_col:
            interest = st.selectbox(
                "Interest",
                options=_INTEREST_FILTER_OPTIONS,
                index=_INTEREST_FILTER_OPTIONS.index(defaults.interest),
                format_func=lambda value: _INTEREST_FILTER_LABELS[value],
                key="library_interest_filter",
            )
        with reading_col:
            reading = st.selectbox(
                "Reading",
                options=_READING_FILTER_OPTIONS,
                index=_READING_FILTER_OPTIONS.index(defaults.reading),
                format_func=lambda value: _READING_FILTER_LABELS[value],
                key="library_reading_filter",
            )
        with collection_col:
            collection = st.selectbox(
                "Collection",
                options=collection_options,
                index=collection_options.index(selected_collection),
                format_func=lambda value: "Any" if value is None else value.name,
                key="library_collection_filter",
            )
        with tag_col:
            tag = st.selectbox(
                "Tag",
                options=tag_options,
                index=tag_options.index(selected_tag),
                format_func=lambda value: "Any" if value is None else value.display_name,
                key="library_tag_filter",
            )
        with st.container(horizontal=True, vertical_alignment="bottom"):
            sort_by = st.selectbox(
                "Sort",
                options=_SORT_OPTIONS,
                index=_SORT_OPTIONS.index(defaults.sort_by),
                format_func=lambda value: _SORT_LABELS[value],
                key="library_sort",
                width=260,
            )
            st.form_submit_button("Apply", icon=":material/filter_list:")
    selection = _LibraryFilterSelection(
        query=query,
        sort_by=cast(LibrarySort, sort_by),
        interest=cast(LibraryInterestFilter, interest),
        reading=cast(LibraryReadingFilter, reading),
        collection_id=collection.id if collection is not None else None,
        normalized_tag_name=tag.normalized_name if tag is not None else None,
    )
    st.session_state[_FILTER_SESSION_KEY] = selection
    return selection


def _persisted_filter_selection(
    value: object,
    *,
    collections: Sequence[LibraryCollection],
    known_tags: Sequence[LibraryTag],
) -> _LibraryFilterSelection:
    if not isinstance(value, _LibraryFilterSelection):
        return _LibraryFilterSelection(
            query="",
            sort_by="saved_newest",
            interest="any",
            reading="any",
            collection_id=None,
            normalized_tag_name=None,
        )
    collection_ids = {collection.id for collection in collections}
    normalized_tag_names = {tag.normalized_name for tag in known_tags}
    return _LibraryFilterSelection(
        query=value.query,
        sort_by=value.sort_by if value.sort_by in _SORT_OPTIONS else "saved_newest",
        interest=value.interest if value.interest in _INTEREST_FILTER_OPTIONS else "any",
        reading=value.reading if value.reading in _READING_FILTER_OPTIONS else "any",
        collection_id=(
            value.collection_id if value.collection_id in collection_ids else None
        ),
        normalized_tag_name=(
            value.normalized_tag_name
            if value.normalized_tag_name in normalized_tag_names
            else None
        ),
    )


def _filters_are_active(filters: _LibraryFilterSelection) -> bool:
    return any(
        (
            filters.query.strip(),
            filters.interest != "any",
            filters.reading != "any",
            filters.collection_id is not None,
            filters.normalized_tag_name is not None,
        )
    )


def _render_dense_library_row(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    row = build_dense_library_row(item)
    with st.container(gap=None):
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            st.caption(f"Interest: {row.interest}")
            st.caption(f"Reading: {row.reading}")
        if st.button(
            row.title,
            key=f"library_open_{article_id}",
            type="tertiary",
            width="stretch",
            help=f"Open details for {row.title}",
        ):
            st.query_params[_DETAIL_QUERY_PARAM] = str(article_id)
            st.rerun()
        st.caption(row.authors_and_year)
        organization: list[str] = []
        if row.collections != "None":
            organization.append(f"Collections: {row.collections}")
        if row.tags != "None":
            organization.append(f"Tags: {row.tags}")
        if organization:
            st.caption(" · ".join(organization))
        if row.note_preview is not None:
            st.caption(f"My note: {row.note_preview}")


def _render_paper_detail(article_id: int) -> None:
    import streamlit as st

    db = get_database()
    item = get_library_item(db, article_id)
    if st.button(
        "Back to Library",
        icon=":material/arrow_back:",
        type="tertiary",
        key="library_detail_back",
    ):
        del st.query_params[_DETAIL_QUERY_PARAM]
        st.rerun()
    if item is None:
        st.title("Library paper unavailable")
        st.caption("This paper is no longer saved in the Library.")
        return

    article = item.article
    render_article_header(
        article,
        context=f"library-detail:{article.source}:{article.source_article_id}",
        title_style="title",
    )
    _render_detail_user_state(item)
    _render_notes(item)
    _render_abstract(item)
    _render_ai_summary(item)
    _render_ai_discussions(item)
    _render_related_saved_papers(item)
    _render_bibliography(item)
    st.subheader("Research Atlas")
    st.caption("Not connected yet.")


def _render_detail_user_state(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    db = get_database()
    st.subheader("My Library state")
    interest_col, reading_col = st.columns(2)
    with interest_col:
        rating = st.selectbox(
            "Interest",
            options=_RATING_OPTIONS,
            index=_RATING_OPTIONS.index(item.entry.interest_rating),
            format_func=_rating_control_label,
            key=f"library_detail_interest_{article_id}",
        )
    with reading_col:
        reading_state = st.selectbox(
            "Reading state",
            options=_READING_OPTIONS,
            index=_READING_OPTIONS.index(item.entry.reading_state),
            format_func=_reading_control_label,
            key=f"library_detail_reading_{article_id}",
        )
    if rating != item.entry.interest_rating:
        set_interest_rating(db, article_id=article_id, interest_rating=rating)
        st.toast("Interest updated.", icon=":material/check_circle:")
        st.rerun()
    if reading_state != item.entry.reading_state:
        set_reading_state(db, article_id=article_id, reading_state=reading_state)
        st.toast("Reading state updated.", icon=":material/check_circle:")
        st.rerun()

    _render_detail_collections(item)
    _render_detail_tags(item)
    if st.button(
        "Remove from Library",
        key=f"library_detail_unsave_{article_id}",
        type="tertiary",
        icon=":material/bookmark_remove:",
    ):
        unsave_article(db, article_id)
        del st.query_params[_DETAIL_QUERY_PARAM]
        st.rerun()


def _rating_control_label(value: int | None) -> str:
    if value is None:
        return "Unrated"
    labels = {
        1: "1 — Peripheral",
        2: "2 — Mildly interesting",
        3: "3 — Useful",
        4: "4 — Highly interesting",
        5: "5 — Central",
    }
    return labels[value]


def _reading_control_label(value: ReadingState | None) -> str:
    return "Not set" if value is None else value.value.capitalize()


def _render_detail_collections(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    db = get_database()
    all_collections = db.list_library_collections()
    current_ids = {collection.id for collection in item.collections if collection.id is not None}
    selected = st.multiselect(
        "Collections",
        options=all_collections,
        default=list(item.collections),
        format_func=lambda collection: collection.name,
        key=f"library_detail_collections_{article_id}",
        placeholder="No collections",
    )
    selected_ids = {collection.id for collection in selected if collection.id is not None}
    if selected_ids == current_ids:
        return
    for collection_id in sorted(selected_ids - current_ids):
        add_article_to_collection(db, collection_id=collection_id, article_id=article_id)
    for collection_id in sorted(current_ids - selected_ids):
        remove_article_from_collection(db, collection_id=collection_id, article_id=article_id)
    st.toast("Collections updated.", icon=":material/check_circle:")
    st.rerun()


def _render_detail_tags(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    db = get_database()
    known_names = [tag.display_name for tag in db.list_library_tags()]
    current_user_names = [assignment.tag.display_name for assignment in item.user_tags]
    user_options = list(dict.fromkeys([*known_names, *current_user_names]))
    selected_user_names = st.multiselect(
        "User tags",
        options=user_options,
        default=current_user_names,
        accept_new_options=True,
        key=f"library_detail_user_tags_{article_id}",
        placeholder="Choose or add tags",
    )
    try:
        current_by_normalized = {
            assignment.tag.normalized_name: assignment.tag.display_name
            for assignment in item.user_tags
        }
        selected_by_normalized = {
            normalize_tag_name(name).normalized_name: name for name in selected_user_names
        }
    except TagValidationError as exc:
        st.warning(str(exc), icon=":material/warning:")
        return
    if selected_by_normalized != current_by_normalized:
        for normalized_name in current_by_normalized.keys() - selected_by_normalized.keys():
            remove_user_tag(
                db,
                article_id=article_id,
                tag=current_by_normalized[normalized_name],
            )
        for normalized_name in selected_by_normalized.keys() - current_by_normalized.keys():
            add_user_tag(
                db,
                article_id=article_id,
                tag=selected_by_normalized[normalized_name],
            )
        st.toast("User tags updated.", icon=":material/check_circle:")
        st.rerun()

    current_ai_names = [assignment.tag.display_name for assignment in item.ai_tags]
    if not current_ai_names:
        st.caption("AI tags: None")
        return
    selected_ai_names = st.multiselect(
        "AI tags (remove only)",
        options=current_ai_names,
        default=current_ai_names,
        key=f"library_detail_ai_tags_{article_id}",
        help="AI tag generation is intentionally unavailable in Library L1-B.",
    )
    removed_ai_names = set(current_ai_names) - set(selected_ai_names)
    if removed_ai_names:
        for tag_name in sorted(removed_ai_names):
            remove_ai_tag(db, article_id=article_id, tag=tag_name)
        st.toast("AI tags removed.", icon=":material/check_circle:")
        st.rerun()


def _render_notes(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    st.subheader("My Notes")
    note_text = item.note.note_text if item.note is not None else ""
    if note_text:
        st.markdown(note_text)
    else:
        st.caption("No note yet.")
    with st.expander(
        "Edit note" if note_text else "Add a note",
        icon=":material/edit_note:",
    ):
        with st.form(f"library_detail_note_{article_id}", border=False):
            updated_note = st.text_area("Note", value=note_text, height=160)
            submitted = st.form_submit_button("Save note", icon=":material/save:")
        if submitted:
            saved = save_note(get_database(), article_id=article_id, note_text=updated_note)
            message = "Note saved." if saved is not None else "Note cleared."
            st.toast(message, icon=":material/check_circle:")
            st.rerun()


def _render_abstract(item: LibraryItem) -> None:
    import streamlit as st

    st.subheader("Abstract")
    abstract = item.article.abstract.strip()
    if abstract:
        st.write(abstract)
    else:
        st.caption("Abstract unavailable.")


def _render_ai_summary(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    st.subheader("AI Summary")
    summary = resolve_preferred_library_summary(get_database(), article_id=article_id)
    if summary is None:
        st.caption("No AI summary generated.")
        st.caption("Summary generation will be added in a later Library stage.")
        return
    st.caption(summary_source_label(summary))
    st.markdown(summary.content)


def _render_ai_discussions(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    st.subheader("AI Discussions")
    overviews = list_conversation_overviews(get_database(), article_id=article_id)
    if not overviews:
        st.caption("No discussions yet.")
        return
    for overview in overviews:
        st.markdown(f"**{overview.conversation.title}**")
        st.caption(_conversation_caption(overview))
    selected = st.selectbox(
        "Inspect stored transcript",
        options=[None, *overviews],
        index=0,
        format_func=lambda value: (
            "Choose a discussion" if value is None else value.conversation.title
        ),
        key=f"library_detail_discussion_{article_id}",
    )
    if selected is None or selected.conversation.id is None:
        return
    messages = list_messages(get_database(), conversation_id=selected.conversation.id)
    if not messages:
        st.caption("This discussion has no messages.")
        return
    for message in messages:
        role = "You" if message.role.value == "user" else "Assistant"
        st.markdown(f"**{role} · message {message.sequence_number}**")
        st.markdown(message.content)


def _conversation_caption(overview: AIConversationOverview) -> str:
    noun = "message" if overview.message_count == 1 else "messages"
    return (
        f"{overview.message_count} {noun} · updated "
        f"{format_compact_date(overview.conversation.updated_at)}"
    )


def _render_related_saved_papers(item: LibraryItem) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    related = list_related_connections(get_database(), article_id=article_id)
    if not related:
        return
    with st.expander("Stored related-paper suggestions", icon=":material/hub:"):
        for relation in related:
            related_article = relation.related_article
            st.markdown(f"**{related_article.title}**")
            confidence = (
                f" · confidence {relation.connection.confidence:.2f}"
                if relation.connection.confidence is not None
                else ""
            )
            st.caption(f"{relation.connection.relation_label}{confidence}")
            st.write(relation.connection.rationale)
            if related_article.id is not None and st.button(
                "Dismiss relationship",
                key=connection_action_key(
                    action="dismiss",
                    article_id=article_id,
                    related_article_id=related_article.id,
                ),
                type="tertiary",
                icon=":material/close:",
            ):
                dismiss_connection(
                    get_database(),
                    article_id=article_id,
                    related_article_id=related_article.id,
                )
                st.rerun()


def _render_bibliography(item: LibraryItem) -> None:
    import streamlit as st

    article = item.article
    st.subheader("Bibliography and links")
    with st.container(horizontal=True):
        st.link_button("Source page", article.abstract_url, icon=":material/open_in_new:")
        if article.pdf_url:
            st.link_button("PDF", article.pdf_url, icon=":material/picture_as_pdf:")
    source_name = "arXiv" if article.source.casefold() == "arxiv" else article.source
    st.caption(f"{source_name}: {article.source_article_id}")


def _render_collection_management(collections: list[LibraryCollection]) -> None:
    import streamlit as st

    if not st.toggle(
        "Manage collections",
        key="library_collection_manager_open",
    ):
        return
    with st.container(border=True):
        with st.form("create_collection", border=False):
            name = st.text_input("New collection")
            description = st.text_input("Description")
            submitted = st.form_submit_button(
                "Create collection",
                icon=":material/create_new_folder:",
            )
        if submitted:
            try:
                create_collection(get_database(), name=name, description=description)
            except CollectionValidationError as exc:
                st.warning(str(exc), icon=":material/warning:")
            except Exception as exc:
                st.error(sanitize_error(exc), icon=":material/error:")
            else:
                st.rerun()
        if not collections:
            st.caption("No collections yet.")
            return
        selected = st.selectbox(
            "Edit collection",
            options=collections,
            format_func=lambda collection: collection.name,
            key="library_collection_manager_selection",
        )
        if selected.id is None:
            return
        with st.form(f"edit_collection_{selected.id}", border=False):
            updated_name = st.text_input("Collection name", value=selected.name)
            updated_description = st.text_input("Description", value=selected.description)
            saved = st.form_submit_button("Save", icon=":material/save:")
        if saved:
            try:
                rename_collection(
                    get_database(),
                    collection_id=selected.id,
                    name=updated_name,
                    description=updated_description,
                )
            except CollectionValidationError as exc:
                st.warning(str(exc), icon=":material/warning:")
            except Exception as exc:
                st.error(sanitize_error(exc), icon=":material/error:")
            else:
                st.rerun()
        _render_collection_intelligence(selected)
        st.caption("Deleting a collection does not delete papers.")
        if st.button(
            "Delete collection",
            key=collection_action_key(
                action="delete_collection",
                collection_id=selected.id,
            ),
            type="tertiary",
            icon=":material/delete:",
        ):
            delete_collection(get_database(), collection_id=selected.id)
            st.rerun()


def _render_collection_intelligence(collection: LibraryCollection) -> None:
    import streamlit as st

    if collection.id is None:
        return
    db = get_database()
    snapshots = db.list_collection_intelligence_snapshots(collection.id)
    if snapshots:
        st.caption("Stored collection intelligence")
        for snapshot in snapshots[:2]:
            st.markdown(f"**{snapshot.title}**")
            st.write(snapshot.summary)
            st.caption(f"{snapshot.origin.value} · {snapshot.generated_at:%Y-%m-%d}")
            if snapshot.id is not None and st.button(
                "Dismiss snapshot",
                key=collection_intelligence_action_key(
                    action="dismiss",
                    collection_id=collection.id,
                    snapshot_id=snapshot.id,
                ),
                type="tertiary",
                icon=":material/close:",
            ):
                db.dismiss_collection_intelligence_snapshot(snapshot.id)
                st.rerun()
    if st.button(
        "Update intelligence snapshot",
        key=collection_intelligence_action_key(
            action="generate",
            collection_id=collection.id,
        ),
        type="tertiary",
        icon=":material/insights:",
    ):
        try:
            build_collection_intelligence_snapshot(db, collection_id=collection.id)
        except Exception as exc:
            st.error(sanitize_error(exc), icon=":material/error:")
        else:
            st.rerun()
