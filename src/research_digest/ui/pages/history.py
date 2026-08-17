"""Digest history page."""

from __future__ import annotations

from datetime import date

from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_PARTIAL,
    Database,
)
from research_digest.history import RunHistoryEntry, get_run_snapshot, list_run_history
from research_digest.ui.abstracts import render_abstract_control
from research_digest.ui.common import get_database
from research_digest.ui.library_controls import render_library_control_for_source_identity


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
    _render_snapshot(snapshot, db)


def _run_label(entry: RunHistoryEntry) -> str:
    return (
        f"{history_period_label(entry)} | {origin_label(entry)} | "
        f"{history_status_label(entry)} | {entry.preselected_count} preselected | "
        f"{entry.relevant_count} relevant"
    )


def _render_entry(entry: RunHistoryEntry) -> None:
    import streamlit as st

    with st.container(border=True):
        st.markdown(f"**{history_period_label(entry)}**")
        st.caption(f"{origin_label(entry)} digest - run #{entry.run_id}")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Status", history_status_label(entry))
        col2.metric("Retrieved", entry.retrieved_count)
        col3.metric("Preselected", entry.preselected_count)
        col4.metric("Analyzed", entry.analyzed_count)
        col5.metric("Relevant", entry.relevant_count)
        st.caption(
            f"Started: {entry.started_at}. "
            f"Completed: {entry.completed_at or '-'}. "
            f"Source: {entry.source_name}."
        )
        requested = ", ".join(entry.requested_source_dates) or "-"
        covered = ", ".join(entry.covered_source_dates) or "-"
        st.caption(f"Requested source dates: {requested}. Covered source dates: {covered}.")
        if entry.empty_source_dates:
            st.caption("No submissions: " + ", ".join(entry.empty_source_dates))
        if entry.incomplete_source_dates:
            st.warning(
                "Incomplete retrieval for "
                + ", ".join(entry.incomplete_source_dates),
                icon=":material/warning:",
            )
        if entry.error_message:
            st.error(entry.error_message)


def _render_snapshot(snapshot: dict[str, object], db: Database) -> None:
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
    else:
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
                source, source_article_id = _snapshot_source_identity(item, snapshot)
                render_abstract_control(
                    source=source,
                    source_article_id=source_article_id,
                    abstract=item.get("abstract"),
                    context=(
                        f"history:{snapshot.get('run_id', 'unknown')}:"
                        f"{source}:{source_article_id}"
                    ),
                )
                _render_snapshot_library_control(
                    db=db,
                    source=source,
                    source_article_id=source_article_id,
                    context=(
                        f"history:{snapshot.get('run_id', 'unknown')}:library:"
                        f"{source}:{source_article_id}"
                    ),
                )

    skipped_articles = snapshot.get("skipped_articles")
    if isinstance(skipped_articles, list) and skipped_articles:
        st.markdown("**Preselected out**")
        for article in skipped_articles:
            if not isinstance(article, dict):
                continue
            with st.container(border=True):
                st.markdown(f"**{article.get('title', 'Untitled paper')}**")
                source, source_article_id = _snapshot_source_identity(article, snapshot)
                st.caption(f"{source}:{source_article_id}")
                url = article.get("abstract_url")
                if isinstance(url, str) and url:
                    st.link_button("Open arXiv", url)
                render_abstract_control(
                    source=source,
                    source_article_id=source_article_id,
                    abstract=article.get("abstract"),
                    context=(
                        f"history:{snapshot.get('run_id', 'unknown')}:"
                        f"preselected:{source}:{source_article_id}"
                    ),
                )
                _render_snapshot_library_control(
                    db=db,
                    source=source,
                    source_article_id=source_article_id,
                    context=(
                        f"history:{snapshot.get('run_id', 'unknown')}:preselected:library:"
                        f"{source}:{source_article_id}"
                    ),
                )

    unresolved_articles = snapshot.get("unresolved_articles")
    if isinstance(unresolved_articles, list) and unresolved_articles:
        st.markdown("**Analysis unavailable**")
        for article in unresolved_articles:
            if not isinstance(article, dict):
                continue
            with st.container(border=True):
                st.markdown(f"**{article.get('title', 'Untitled paper')}**")
                source, source_article_id = _snapshot_source_identity(article, snapshot)
                st.caption(f"{source}:{source_article_id}")
                url = article.get("abstract_url")
                if isinstance(url, str) and url:
                    st.link_button("Open arXiv", url)
                render_abstract_control(
                    source=source,
                    source_article_id=source_article_id,
                    abstract=article.get("abstract"),
                    context=(
                        f"history:{snapshot.get('run_id', 'unknown')}:"
                        f"unresolved:{source}:{source_article_id}"
                    ),
                )
                _render_snapshot_library_control(
                    db=db,
                    source=source,
                    source_article_id=source_article_id,
                    context=(
                        f"history:{snapshot.get('run_id', 'unknown')}:unresolved:library:"
                        f"{source}:{source_article_id}"
                    ),
                )


def _snapshot_source_identity(
    article_payload: dict[str, object],
    snapshot: dict[str, object],
) -> tuple[str, str]:
    source = article_payload.get("source")
    if not isinstance(source, str) or not source.strip():
        source = str(snapshot.get("source", "unknown"))
    source_article_id = article_payload.get("source_article_id")
    if not isinstance(source_article_id, str) or not source_article_id.strip():
        source_article_id = "unknown"
    return source, source_article_id


def _render_snapshot_library_control(
    *,
    db: Database,
    source: str,
    source_article_id: str,
    context: str,
) -> None:
    if source == "unknown" or source_article_id == "unknown":
        return
    render_library_control_for_source_identity(
        db=db,
        source=source,
        source_article_id=source_article_id,
        context=context,
    )


def history_period_label(entry: RunHistoryEntry) -> str:
    dates = _entry_dates(entry)
    if not dates:
        return "Legacy digest"
    if len(dates) == 1:
        return _format_date(dates[0])
    if dates == _date_range(dates[0], dates[-1]):
        return f"{_format_date(dates[0])} to {_format_date(dates[-1])}"
    return ", ".join(_format_date(value) for value in dates)


def origin_label(entry: RunHistoryEntry) -> str:
    value = entry.run_origin.upper()
    if value == "SCHEDULED":
        return "Scheduled"
    if value == "MANUAL":
        return "Manual"
    return "Legacy"


def history_status_label(entry: RunHistoryEntry) -> str:
    if entry.empty_source_dates and not entry.retrieved_count:
        return "No submissions"
    if entry.status == APP_RUN_COMPLETED:
        return "Completed"
    if entry.status == APP_RUN_ANALYSIS_UNAVAILABLE:
        return "Analysis unavailable"
    if entry.status == APP_RUN_PARTIAL:
        return "Partial"
    if entry.status == APP_RUN_FAILED:
        return "Failed"
    return entry.status.replace("_", " ").title()


def _entry_dates(entry: RunHistoryEntry) -> tuple[date, ...]:
    raw_dates = entry.requested_source_dates or entry.covered_source_dates
    dates: list[date] = []
    for value in raw_dates:
        try:
            dates.append(date.fromisoformat(value))
        except ValueError:
            continue
    return tuple(sorted(set(dates)))


def _format_date(value: date) -> str:
    return f"{value:%b} {value.day}, {value:%Y}"


def _date_range(start: date, end: date) -> tuple[date, ...]:
    days = (end - start).days
    return tuple(date.fromordinal(start.toordinal() + offset) for offset in range(days + 1))
