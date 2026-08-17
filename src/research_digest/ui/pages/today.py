"""Today page."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypeAlias, TypeGuard

from research_digest.calibration import CalibrationSummary, build_calibration_summary
from research_digest.config import ConfigError, load_config
from research_digest.db import Database
from research_digest.errors import sanitize_error
from research_digest.models import (
    AnalysisOrigin,
    ArticleFeedback,
    ArxivSourceConfig,
    DateSelection,
    DateSelectionKind,
    DigestItem,
    DigestResult,
    FeedbackLabel,
    InterestProfile,
    ModelValidationError,
    RunOrigin,
    above_threshold_digest_items,
    below_threshold_digest_items,
    is_above_threshold,
    profile_semantic_fingerprint,
    profile_semantic_signature,
    sorted_digest_items,
)
from research_digest.pipeline import DigestPipelineError
from research_digest.service import run_digest_for_profile
from research_digest.sources.arxiv import ArxivSource
from research_digest.sources.base import LatestAvailableDateResolver, SourceError
from research_digest.synthesis import CrossPaperSynthesis, build_cross_paper_synthesis
from research_digest.ui.common import get_analyzer, get_database

DigestInputSignature: TypeAlias = tuple[str, str]
DigestView: TypeAlias = Literal["relevant", "all_analyzed", "below_threshold"]
DateSelectionMode: TypeAlias = Literal[
    "latest_available",
    "single_date",
    "date_range",
    "selected_dates",
]
_LAST_DIGEST_RESULT_KEY = "last_digest_result"
_LAST_DIGEST_SIGNATURE_KEY = "last_digest_signature"
_SELECTED_DATES_KEY = "today_selected_dates"
_RELEVANT_VIEW: DigestView = "relevant"
_DEFAULT_SELECTED_DATES: tuple[date, ...] = (date.today(),)
_DATE_SELECTION_MODES: tuple[DateSelectionMode, ...] = (
    "latest_available",
    "single_date",
    "date_range",
    "selected_dates",
)
_DATE_SELECTION_MODE_TITLES: dict[DateSelectionMode, str] = {
    "latest_available": "Latest available",
    "single_date": "Single date",
    "date_range": "Date range",
    "selected_dates": "Selected dates",
}
_VIEW_OPTIONS: tuple[DigestView, ...] = ("relevant", "all_analyzed", "below_threshold")
_VIEW_TITLES: dict[DigestView, str] = {
    "relevant": "Relevant",
    "all_analyzed": "All analyzed",
    "below_threshold": "Below threshold",
}
_FEEDBACK_OPTIONS: tuple[FeedbackLabel, ...] = ("RELEVANT", "NOT_RELEVANT")
_FEEDBACK_LABELS: dict[FeedbackLabel, str] = {
    "RELEVANT": "Relevant",
    "NOT_RELEVANT": "Not relevant",
}


@dataclass(frozen=True)
class DateSelectionControl:
    selection: DateSelection | None
    period_label: str
    disabled_reason: str | None = None


def render() -> None:
    import streamlit as st

    st.title("Today")

    db = get_database()
    profiles = db.list_interest_profiles(enabled_only=True)
    source_config = db.get_arxiv_config()
    if source_config is None:
        st.error("arXiv source configuration is missing.")
        return

    categories = ", ".join(source_config.categories or [])
    state = "enabled" if source_config.enabled else "disabled"
    st.caption(f"arXiv is {state}. Categories: {categories}. Source dates use UTC.")

    if not profiles:
        st.info(
            "Create and enable an interest profile on the Interests page before running a digest.",
            icon=":material/info:",
        )
        return

    profile = st.selectbox(
        "Interest profile",
        options=profiles,
        format_func=lambda item: f"{item.name} (threshold {item.relevance_threshold:.2f})",
    )
    try:
        default_selection = load_config().default_date_selection
    except ConfigError:
        default_selection = DateSelection.latest_available()
    source = ArxivSource()
    date_control = _render_date_selection_control(
        default_selection,
        latest_resolver=source,
        source_config=source_config,
    )
    st.info(f"Digest period: {date_control.period_label}", icon=":material/event:")
    if date_control.disabled_reason is not None:
        st.warning(date_control.disabled_reason, icon=":material/warning:")
    date_selection = date_control.selection
    current_signature = (
        digest_input_signature(profile, source_config, date_selection)
        if date_selection is not None
        else None
    )

    analyzer, analyzer_message = get_analyzer()
    if analyzer_message is not None:
        st.warning(
            "Analysis provider needs attention: "
            f"{sanitize_error(analyzer_message)}. Run `research-digest doctor` for details.",
            icon=":material/warning:",
        )

    if st.button(
        "Run digest",
        type="primary",
        icon=":material/play_arrow:",
        disabled=date_selection is None,
    ):
        with st.spinner("Fetching and analyzing selected source date(s)..."):
            try:
                if profile.id is None:
                    raise DigestPipelineError("selected interest profile is missing an id")
                if date_selection is None:
                    raise DigestPipelineError("select source date(s) before running a digest")
                service_result = run_digest_for_profile(
                    db=db,
                    source=source,
                    analyzer=analyzer,
                    profile_id=profile.id,
                    date_selection=date_selection,
                    run_origin=RunOrigin.MANUAL,
                )
                result = service_result.digest
            except (DigestPipelineError, SourceError, ModelValidationError) as exc:
                st.error(sanitize_error(exc), icon=":material/error:")
            except Exception as exc:
                st.error(f"Digest run failed: {sanitize_error(exc)}", icon=":material/error:")
            else:
                st.session_state[_LAST_DIGEST_RESULT_KEY] = result
                st.session_state[_LAST_DIGEST_SIGNATURE_KEY] = current_signature

    result = st.session_state.get(_LAST_DIGEST_RESULT_KEY)
    result_signature = st.session_state.get(_LAST_DIGEST_SIGNATURE_KEY)
    if (
        current_signature is not None
        and is_current_digest_result(result, result_signature, current_signature)
    ):
        _render_run_confirmation(result)
        _render_metrics(result)
        if not result.analysis_available:
            if result.analyzed_count:
                st.info("Analysis provider unavailable; showing reused analyses for this run.")
            else:
                st.info("Papers were fetched and stored, but no analyses are available.")
        _render_items(result, db)
    else:
        st.session_state.pop(_LAST_DIGEST_RESULT_KEY, None)
        st.session_state.pop(_LAST_DIGEST_SIGNATURE_KEY, None)
        _render_empty_metrics()


def digest_input_signature(
    profile: InterestProfile,
    source_config: ArxivSourceConfig,
    date_selection: DateSelection,
) -> DigestInputSignature:
    return profile_fingerprint(profile), source_config_fingerprint(source_config, date_selection)


def profile_fingerprint(profile: InterestProfile) -> str:
    return profile_semantic_signature(profile)


def source_config_fingerprint(
    source_config: ArxivSourceConfig,
    date_selection: DateSelection | None = None,
) -> str:
    return json.dumps(
        {
            "enabled": source_config.enabled,
            "categories": source_config.categories,
            "date_selection": (
                date_selection.to_mapping() if date_selection is not None else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def is_current_digest_result(
    result: object,
    result_signature: object,
    current_signature: DigestInputSignature,
) -> TypeGuard[DigestResult]:
    return isinstance(result, DigestResult) and result_signature == current_signature


def digest_view_items(result: DigestResult, view: DigestView) -> list[DigestItem]:
    if view == "relevant":
        return above_threshold_digest_items(result)
    if view == "all_analyzed":
        return sorted_digest_items(result.items)
    if view == "below_threshold":
        return below_threshold_digest_items(result)
    raise ValueError(f"unknown digest view: {view}")


def digest_view_counts(result: DigestResult) -> dict[DigestView, int]:
    return {view: len(digest_view_items(result, view)) for view in _VIEW_OPTIONS}


def digest_view_label(view: DigestView, count: int) -> str:
    return f"{_VIEW_TITLES[view]} ({count})"


def coerce_digest_view(value: object) -> DigestView:
    if value in _VIEW_OPTIONS:
        return value
    return _RELEVANT_VIEW


def coerce_date_selection_mode(value: object) -> DateSelectionMode:
    if value in _DATE_SELECTION_MODES:
        return value
    return "latest_available"


def date_selection_mode_label(mode: DateSelectionMode) -> str:
    return _DATE_SELECTION_MODE_TITLES[mode]


def mode_for_date_selection(selection: DateSelection) -> DateSelectionMode:
    if selection.kind == DateSelectionKind.SINGLE_DATE:
        return "single_date"
    if selection.kind == DateSelectionKind.DATE_RANGE:
        return "date_range"
    if selection.kind == DateSelectionKind.EXPLICIT_DATES:
        return "selected_dates"
    return "latest_available"


def digest_period_label(selection: DateSelection) -> str:
    dates = selection.selected_dates()
    if selection.kind == DateSelectionKind.LATEST_AVAILABLE:
        return "Latest available source date"
    if selection.kind == DateSelectionKind.SINGLE_DATE:
        return _format_date(dates[0])
    if selection.kind == DateSelectionKind.DATE_RANGE:
        return f"{_format_date(dates[0])} to {_format_date(dates[-1])}"
    return ", ".join(_format_date(value) for value in dates)


def result_period_label(result: DigestResult) -> str:
    if result.date_selection is not None:
        if result.requested_source_dates:
            return digest_period_label(
                _selection_for_resolved_dates(result.date_selection, result.requested_source_dates)
            )
        return digest_period_label(result.date_selection)
    return "Legacy digest"


def _selection_for_resolved_dates(
    selection: DateSelection,
    dates: tuple[date, ...],
) -> DateSelection:
    if selection.kind == DateSelectionKind.LATEST_AVAILABLE and len(dates) == 1:
        return DateSelection.single_date(dates[0])
    return selection


def _format_date(value: date) -> str:
    return f"{value:%b} {value.day}, {value:%Y}"


def _render_date_selection_control(
    default_selection: DateSelection,
    *,
    latest_resolver: LatestAvailableDateResolver[ArxivSourceConfig],
    source_config: ArxivSourceConfig,
) -> DateSelectionControl:
    import streamlit as st

    default_mode = mode_for_date_selection(default_selection)
    selected_mode = st.segmented_control(
        "Source dates",
        options=_DATE_SELECTION_MODES,
        default=default_mode,
        required=True,
        format_func=date_selection_mode_label,
        width="stretch",
    )
    mode = coerce_date_selection_mode(selected_mode)
    if mode == "latest_available":
        with st.spinner("Checking latest arXiv source date..."):
            try:
                latest_date = resolve_latest_available_source_date(latest_resolver, source_config)
            except SourceError as exc:
                return DateSelectionControl(
                    selection=None,
                    period_label="Latest available source date",
                    disabled_reason=(
                        "Could not resolve the latest arXiv source date: "
                        f"{sanitize_error(exc)}"
                    ),
                )
        if latest_date is None:
            return DateSelectionControl(
                selection=None,
                period_label="Latest available source date",
                disabled_reason="No eligible arXiv source date is currently available.",
            )
        selection = DateSelection.single_date(latest_date)
        return DateSelectionControl(
            selection=selection,
            period_label=digest_period_label(selection),
        )
    if mode == "single_date":
        default_date = default_selection.dates[0] if default_selection.dates else date.today()
        selected = st.date_input("Date", value=default_date)
        selection = DateSelection.single_date(_coerce_date_input(selected))
        return DateSelectionControl(
            selection=selection,
            period_label=digest_period_label(selection),
        )
    if mode == "date_range":
        default_dates = default_selection.selected_dates()
        start_default = default_dates[0] if default_dates else date.today()
        end_default = default_dates[-1] if default_dates else start_default
        selected_range = st.date_input("Date range", value=(start_default, end_default))
        coerced_range = _coerce_date_range_input(selected_range)
        if coerced_range is None:
            return DateSelectionControl(
                selection=None,
                period_label="Select a start and end date",
                disabled_reason="Select both the start and end dates before running a digest.",
            )
        start, end = coerced_range
        selection = DateSelection.date_range(start, end)
        return DateSelectionControl(
            selection=selection,
            period_label=digest_period_label(selection),
        )
    selected_dates = _selected_dates_state(default_selection)
    add_date = st.date_input(
        "Add date",
        value=selected_dates[-1] if selected_dates else date.today(),
    )
    with st.container(horizontal=True):
        if st.button("Add date", icon=":material/add:"):
            st.session_state[_SELECTED_DATES_KEY] = tuple(
                sorted({*selected_dates, _coerce_date_input(add_date)})
            )
            st.rerun()
        if st.button("Remove last date", icon=":material/remove:") and selected_dates:
            st.session_state[_SELECTED_DATES_KEY] = tuple(selected_dates[:-1])
            st.rerun()
    current_dates = _selected_dates_state(default_selection)
    if current_dates:
        st.caption("Selected: " + ", ".join(_format_date(value) for value in current_dates))
    selection = DateSelection.explicit_dates(current_dates or _DEFAULT_SELECTED_DATES)
    return DateSelectionControl(selection=selection, period_label=digest_period_label(selection))


def resolve_latest_available_source_date(
    resolver: LatestAvailableDateResolver[ArxivSourceConfig],
    source_config: ArxivSourceConfig,
) -> date | None:
    return resolver.resolve_latest_available_date(source_config)


def _selected_dates_state(default_selection: DateSelection) -> tuple[date, ...]:
    import streamlit as st

    existing = st.session_state.get(_SELECTED_DATES_KEY)
    if isinstance(existing, tuple) and all(isinstance(value, date) for value in existing):
        return existing
    if default_selection.kind == DateSelectionKind.EXPLICIT_DATES:
        dates = default_selection.selected_dates()
    else:
        dates = _DEFAULT_SELECTED_DATES
    st.session_state[_SELECTED_DATES_KEY] = dates
    return dates


def _coerce_date_input(value: object) -> date:
    if isinstance(value, date):
        return value
    raise ModelValidationError("expected a calendar date")


def _coerce_date_range_input(value: object) -> tuple[date, date] | None:
    if (
        isinstance(value, tuple)
        and len(value) < 2
        and all(isinstance(item, date) for item in value)
    ):
        return None
    if (
        isinstance(value, list)
        and len(value) < 2
        and all(isinstance(item, date) for item in value)
    ):
        return None
    if (
        isinstance(value, (tuple, list))
        and len(value) == 2
        and isinstance(value[0], date)
        and isinstance(value[1], date)
    ):
        return value[0], value[1]
    raise ModelValidationError("select a start and end date")


def _render_run_confirmation(result: DigestResult) -> None:
    import streamlit as st

    completed_at = result.completed_at or result.started_at
    st.success(
        f"Digest for {result_period_label(result)} completed: "
        f"#{result.run_id} at {completed_at:%Y-%m-%d %H:%M:%S UTC}"
    )
    if not result.retrieval_complete:
        incomplete = ", ".join(_format_date(value) for value in result.incomplete_source_dates)
        st.warning(
            "Retrieval is incomplete"
            + (f" for {incomplete}" if incomplete else "")
            + (
                f"; fetched {result.retrieved_count} before safety limit "
                f"{result.retrieval_safety_limit}."
                if result.retrieval_safety_limit is not None
                else "."
            ),
            icon=":material/warning:",
        )


def _render_empty_metrics() -> None:
    import streamlit as st

    col1, col2, col3 = st.columns(3)
    col1.metric("Retrieved", "-")
    col2.metric("Analyzed", "-")
    col3.metric("Above threshold", "-")
    col4, col5, col6 = st.columns(3)
    col4.metric("New analyses", "-")
    col5.metric("Reused analyses", "-")
    col6.metric("Skipped new analysis", "-")


def _render_metrics(result: DigestResult) -> None:
    import streamlit as st

    col1, col2, col3 = st.columns(3)
    col1.metric("Retrieved", result.retrieved_count)
    col2.metric("Analyzed", result.analyzed_count)
    col3.metric("Above threshold", result.above_threshold_count)
    col4, col5, col6 = st.columns(3)
    col4.metric("New analyses", result.new_analysis_count)
    col5.metric("Reused analyses", result.reused_analysis_count)
    col6.metric("Skipped new analysis", result.skipped_analysis_count)


def _render_items(result: DigestResult, db: Database) -> None:
    import streamlit as st

    threshold = result.profile.relevance_threshold
    st.caption(f"Current profile threshold: {threshold:.2f}. Relevant means score >= threshold.")
    feedback_by_article_id = load_feedback_by_article_id(db, result)
    _render_calibration(
        build_calibration_summary(
            items=result.items,
            feedback_by_article_id=feedback_by_article_id,
            threshold=threshold,
        )
    )
    _render_cross_paper_synthesis(
        build_cross_paper_synthesis(items=result.items, threshold=threshold)
    )

    counts = digest_view_counts(result)
    selected = st.segmented_control(
        "Result view",
        options=_VIEW_OPTIONS,
        default=_RELEVANT_VIEW,
        required=True,
        format_func=lambda view: digest_view_label(view, counts[view]),
        key=f"digest_view_{result.run_id}",
        width="stretch",
    )
    view = coerce_digest_view(selected)
    items = digest_view_items(result, view)

    if not items:
        st.info(_empty_view_message(view))
        return

    fingerprint = profile_semantic_fingerprint(result.profile)
    for item in items:
        current_feedback = (
            feedback_by_article_id.get(item.article.id)
            if item.article.id is not None
            else None
        )
        _render_item(
            item,
            threshold,
            db,
            result.profile,
            fingerprint,
            current_feedback,
        )


def load_feedback_by_article_id(
    db: Database,
    result: DigestResult,
) -> dict[int, ArticleFeedback]:
    if result.profile.id is None:
        return {}
    fingerprint = profile_semantic_fingerprint(result.profile)
    return {
        feedback.article_id: feedback
        for feedback in db.list_article_feedback(
            profile_id=result.profile.id,
            profile_fingerprint=fingerprint,
        )
    }


def _render_calibration(summary: CalibrationSummary) -> None:
    import streamlit as st

    if summary.feedback_count == 0:
        return
    st.markdown("**Feedback calibration**")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Feedback", summary.feedback_count)
    col2.metric("False positives", summary.false_positive_count)
    col3.metric("False negatives", summary.false_negative_count)
    col4.metric("Precision", _format_optional_ratio(summary.precision))


def _format_optional_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _render_cross_paper_synthesis(synthesis: CrossPaperSynthesis) -> None:
    import streamlit as st

    if synthesis.relevant_count == 0:
        return
    with st.container(border=True):
        st.markdown("**Cross-paper synthesis**")
        metric_col, priority_col = st.columns(2)
        metric_col.metric("Relevant papers", synthesis.relevant_count)
        priority_col.metric("High priority", len(synthesis.high_priority_titles))
        if synthesis.recurring_topics:
            st.markdown("**Recurring topics**")
            for topic in synthesis.recurring_topics:
                st.write(
                    f"{topic.topic} appears in {topic.paper_count} papers: "
                    + "; ".join(topic.paper_titles)
                )
        elif synthesis.high_priority_titles:
            st.markdown("**High-priority papers**")
            for title in synthesis.high_priority_titles:
                st.write(title)
        if synthesis.category_counts:
            st.caption(
                "Categories: "
                + ", ".join(
                    f"{category} ({count})"
                    for category, count in synthesis.category_counts[:5]
                )
            )


def _empty_view_message(view: DigestView) -> str:
    if view == "relevant":
        return "No papers are above the relevance threshold for this run."
    if view == "below_threshold":
        return "No analyzed papers are below the relevance threshold for this run."
    return "No analyzed papers are available for this run."


def _render_item(
    item: DigestItem,
    threshold: float,
    db: Database,
    profile: InterestProfile,
    profile_fingerprint_value: str,
    current_feedback: ArticleFeedback | None,
) -> None:
    import streamlit as st

    article = item.article
    analysis = item.analysis
    origin_label = "NEW" if item.analysis_origin == AnalysisOrigin.NEW_THIS_RUN else "REUSED"
    threshold_status = (
        "Above threshold" if is_above_threshold(item, threshold) else "Below threshold"
    )

    with st.container(border=True):
        st.subheader(article.title)
        authors = ", ".join(article.authors) if article.authors else "Unknown authors"
        categories = ", ".join(article.categories) if article.categories else "Uncategorized"
        st.caption(
            f"{article.source}:{article.source_article_id} | {authors} | "
            f"Published {article.published_at:%Y-%m-%d %H:%M UTC} | "
            f"Categories: {categories}"
        )
        score_col, priority_col, origin_col, status_col = st.columns(4)
        score_col.metric("Relevance score", f"{analysis.relevance_score:.2f}")
        priority_col.metric("Priority", analysis.reading_priority)
        origin_col.metric("Analysis", origin_label)
        status_col.metric("Threshold status", threshold_status)
        st.markdown("**Relevance reason**")
        st.write(analysis.relevance_reason)
        st.markdown("**Summary**")
        st.write(analysis.summary)
        st.markdown("**Why it matters**")
        st.write(analysis.why_it_matters)
        st.markdown("**Matched topics**")
        st.write(", ".join(analysis.matched_topics) if analysis.matched_topics else "None")
        link_col, pdf_col = st.columns([1, 1])
        link_col.link_button("arXiv", article.abstract_url)
        if article.pdf_url:
            pdf_col.link_button("PDF", article.pdf_url)
        _render_feedback_control(
            item,
            db,
            profile,
            profile_fingerprint_value,
            current_feedback,
        )


def _render_feedback_control(
    item: DigestItem,
    db: Database,
    profile: InterestProfile,
    profile_fingerprint_value: str,
    current_feedback: ArticleFeedback | None,
) -> None:
    import streamlit as st

    if item.article.id is None or profile.id is None:
        return
    selected = st.segmented_control(
        "Feedback",
        options=_FEEDBACK_OPTIONS,
        default=current_feedback.feedback_label if current_feedback is not None else None,
        required=False,
        format_func=lambda label: _FEEDBACK_LABELS[label],
        key=f"feedback_{profile.id}_{item.article.id}_{profile_fingerprint_value}",
        width="stretch",
    )
    if persist_feedback_selection(
        item=item,
        db=db,
        profile=profile,
        profile_fingerprint_value=profile_fingerprint_value,
        current_feedback=current_feedback,
        selected=selected,
    ):
        st.rerun()


def persist_feedback_selection(
    *,
    item: DigestItem,
    db: Database,
    profile: InterestProfile,
    profile_fingerprint_value: str,
    current_feedback: ArticleFeedback | None,
    selected: FeedbackLabel | None,
) -> bool:
    if item.article.id is None or profile.id is None:
        return False
    if selected is None:
        return False
    if current_feedback is not None and selected == current_feedback.feedback_label:
        return False
    db.upsert_article_feedback(
        article_id=item.article.id,
        profile_id=profile.id,
        profile_fingerprint=profile_fingerprint_value,
        feedback_label=selected,
    )
    return True
