"""Digest history page."""

from __future__ import annotations

from research_digest.history import RunHistoryEntry, get_run_snapshot, list_run_history
from research_digest.ui.common import get_database


def render() -> None:
    import streamlit as st

    st.title("History")
    db = get_database()
    limit = st.number_input("Run limit", min_value=1, max_value=100, value=25, step=5)
    entries = list_run_history(db, limit=int(limit))
    if not entries:
        st.info("No digest runs have been recorded yet.")
        return

    selected = st.selectbox(
        "Digest run",
        options=entries,
        format_func=_run_label,
    )
    _render_entry(selected)
    snapshot = get_run_snapshot(db, run_id=selected.run_id)
    if snapshot is None:
        st.info("No persisted digest snapshot is available for this run.")
        return
    _render_snapshot(snapshot)


def _run_label(entry: RunHistoryEntry) -> str:
    return (
        f"{entry.started_at} | {entry.status} | "
        f"profile {entry.profile_id or '-'} | {entry.relevant_count} relevant"
    )


def _render_entry(entry: RunHistoryEntry) -> None:
    import streamlit as st

    with st.container(border=True):
        st.markdown(f"**Run #{entry.run_id}**")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Status", entry.status)
        col2.metric("Retrieved", entry.retrieved_count)
        col3.metric("Analyzed", entry.analyzed_count)
        col4.metric("Relevant", entry.relevant_count)
        st.caption(
            f"Started: {entry.started_at}. "
            f"Completed: {entry.completed_at or '-'}. "
            f"Source: {entry.source_name}."
        )
        if entry.error_message:
            st.error(entry.error_message)


def _render_snapshot(snapshot: dict[str, object]) -> None:
    import streamlit as st

    synthesis = snapshot.get("synthesis")
    if isinstance(synthesis, dict):
        with st.container(border=True):
            st.markdown("**Persisted synthesis**")
            st.metric("Relevant papers", int(synthesis.get("relevant_count", 0)))
            topics = synthesis.get("recurring_topics")
            if isinstance(topics, list) and topics:
                st.markdown("**Recurring topics**")
                for topic in topics[:5]:
                    if isinstance(topic, dict):
                        st.write(f"{topic.get('topic')} ({topic.get('paper_count')})")

    items = snapshot.get("items")
    if not isinstance(items, list) or not items:
        st.info("No analyzed papers were persisted for this run.")
        return

    st.markdown("**Persisted digest**")
    for item in items:
        if not isinstance(item, dict):
            continue
        with st.container(border=True):
            st.markdown(f"**{item.get('title', 'Untitled paper')}**")
            st.caption(
                f"Score: {float(item.get('relevance_score', 0.0)):.2f}. "
                f"Priority: {item.get('reading_priority', '-')}. "
                f"Origin: {item.get('analysis_origin', '-')}."
            )
            summary = item.get("summary")
            if isinstance(summary, str) and summary:
                st.write(summary)
            why_it_matters = item.get("why_it_matters")
            if isinstance(why_it_matters, str) and why_it_matters:
                st.write(why_it_matters)
            url = item.get("abstract_url")
            if isinstance(url, str) and url:
                st.link_button("Open arXiv", url)
