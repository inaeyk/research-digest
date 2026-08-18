"""Today page."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypeAlias, TypeGuard

from research_digest.analysis.providers import build_configured_preselector
from research_digest.calibration import CalibrationSummary, build_calibration_summary
from research_digest.config import (
    DEFAULT_AUTOMATIC_LIBRARY_CONTEXT_THRESHOLD,
    ConfigError,
    load_config,
)
from research_digest.coverage import build_date_coverage_statuses
from research_digest.db import SOURCE_ARXIV, Database
from research_digest.errors import sanitize_error
from research_digest.library_context import (
    dismiss_context_suggestion,
    generate_library_context_for_item,
    list_display_context_suggestions,
)
from research_digest.models import (
    AnalysisOrigin,
    Article,
    ArticleFeedback,
    ArxivSourceConfig,
    DateSelection,
    DateSelectionKind,
    DigestItem,
    DigestResult,
    FeedbackAnswer,
    InterestProfile,
    ModelValidationError,
    RunOrigin,
    above_threshold_digest_items,
    below_threshold_digest_items,
    canonical_arxiv_categories,
    is_above_threshold,
    profile_semantic_fingerprint,
    profile_semantic_signature,
    sorted_digest_items,
)
from research_digest.pipeline import DigestPipelineError
from research_digest.quantitative_calibration import (
    dismiss_quantitative_calibration,
    submit_quantitative_calibration,
)
from research_digest.service import run_digest_for_profile
from research_digest.sources.arxiv import ArxivSource
from research_digest.sources.base import LatestAvailableDateResolver, SourceError
from research_digest.synthesis import CrossPaperSynthesis, build_cross_paper_synthesis
from research_digest.ui.abstracts import render_abstract_control
from research_digest.ui.common import get_analyzer, get_database, get_library_context_generator
from research_digest.ui.date_status import month_bounds, render_date_status_grid
from research_digest.ui.library_controls import render_library_control
from research_digest.ui.tag_controls import context_action_key

DigestInputSignature: TypeAlias = tuple[str, str]
DigestView: TypeAlias = Literal["relevant", "all_analyzed", "below_threshold"]
DateSelectionMode: TypeAlias = Literal[
    "latest_available",
    "single_date",
    "date_range",
    "selected_dates",
]
FeedbackControlAnswer: TypeAlias = Literal["YES", "NO", "UNANSWERED"]
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
_FEEDBACK_OPTIONS: tuple[FeedbackControlAnswer, ...] = ("YES", "NO", "UNANSWERED")
_FEEDBACK_LABELS: dict[FeedbackControlAnswer, str] = {
    "YES": "Yes",
    "NO": "No",
    "UNANSWERED": "Unanswered",
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
    st.caption(
        f"arXiv is {state}. Categories: {categories}. "
        "Source dates use America/Chicago."
    )

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
        active_config = load_config()
        default_selection = active_config.default_date_selection
    except ConfigError:
        active_config = None
        default_selection = DateSelection.latest_available()
    date_control = _render_date_selection_control(
        default_selection,
        source_config=source_config,
    )
    st.info(f"Digest period: {date_control.period_label}", icon=":material/event:")
    if date_control.selection is not None and profile.id is not None:
        selected_dates = date_control.selection.selected_dates()
        anchor = selected_dates[0] if selected_dates else date.today()
        start_date, end_date = month_bounds(anchor)
        render_date_status_grid(
            statuses=build_date_coverage_statuses(
                db=db,
                profile=profile,
                source_name=SOURCE_ARXIV,
                source_config=source_config,
                start_date=start_date,
                end_date=end_date,
                selected_dates=selected_dates,
            ),
            title=f"Digest status for {anchor:%B %Y}",
        )
    if date_control.disabled_reason is not None:
        st.warning(date_control.disabled_reason, icon=":material/warning:")
    date_selection = date_control.selection
    current_signature = (
        digest_input_signature(profile, source_config, date_selection)
        if date_selection is not None
        else None
    )

    if st.button(
        "Run digest",
        type="primary",
        icon=":material/play_arrow:",
        disabled=date_selection is None,
    ):
        with st.spinner("Fetching and analyzing selected source date(s)..."):
            try:
                source = ArxivSource()
                analyzer, analyzer_message = get_analyzer()
                library_context_generator = None
                if active_config is None or active_config.automatic_library_connections_enabled:
                    library_context_generator, _library_context_message = (
                        get_library_context_generator()
                    )
                if analyzer_message is not None:
                    st.warning(
                        "Analysis provider needs attention: "
                        f"{sanitize_error(analyzer_message)}. "
                        "Run `research-digest doctor` for details.",
                        icon=":material/warning:",
                    )
                if profile.id is None:
                    raise DigestPipelineError("selected interest profile is missing an id")
                if date_selection is None:
                    raise DigestPipelineError("select source date(s) before running a digest")
                preselector_connection = (
                    build_configured_preselector(active_config)
                    if active_config is not None
                    else None
                )
                if preselector_connection is not None and preselector_connection.message:
                    st.warning(
                        "Stage-1 abstract preselection is unavailable, so cache-miss "
                        "papers will be allowed through to full analysis: "
                        f"{sanitize_error(preselector_connection.message)}",
                        icon=":material/warning:",
                    )
                service_result = run_digest_for_profile(
                    db=db,
                    source=source,
                    analyzer=analyzer,
                    profile_id=profile.id,
                    date_selection=date_selection,
                    run_origin=RunOrigin.MANUAL,
                    preselector=(
                        preselector_connection.preselector
                        if preselector_connection is not None
                        else None
                    ),
                    library_context_generator=library_context_generator,
                    automatic_library_context_threshold=(
                        active_config.automatic_library_context_threshold
                        if active_config is not None
                        else DEFAULT_AUTOMATIC_LIBRARY_CONTEXT_THRESHOLD
                    ),
                    relevance_calibration_prompt_probability=(
                        active_config.relevance_calibration_prompt_probability
                        if active_config is not None
                        else 0.20
                    ),
                )
                result = service_result.digest
            except (DigestPipelineError, SourceError, ModelValidationError) as exc:
                st.error(sanitize_error(exc), icon=":material/error:")
            except Exception as exc:
                st.error(f"Digest run failed: {sanitize_error(exc)}", icon=":material/error:")
            else:
                st.session_state[_LAST_DIGEST_RESULT_KEY] = result
                st.session_state[_LAST_DIGEST_SIGNATURE_KEY] = current_signature
                st.rerun()

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
        _render_quantitative_calibration_prompt(db, result)
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
            "categories": list(canonical_arxiv_categories(source_config.categories or ())),
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
        selection = DateSelection.latest_available()
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
    if not result.analysis_complete:
        st.warning(
            "Analysis is incomplete for "
            f"{len(result.unresolved_articles)} paper(s): "
            + ", ".join(
                f"{article.source}:{article.source_article_id}"
                for article in result.unresolved_articles[:10]
            ),
            icon=":material/warning:",
        )


def _render_empty_metrics() -> None:
    import streamlit as st

    col1, col2, col3 = st.columns(3)
    col1.metric("Retrieved", "-")
    col2.metric("Already analyzed / reused", "-")
    col3.metric("Screened this run", "-")
    col4, col5, col6 = st.columns(3)
    col4.metric("Passed preselection", "-")
    col5.metric("Preselected out", "-")
    col6.metric("New full analyses", "-")
    col7, col8, col9 = st.columns(3)
    col7.metric("Reused full analyses", "-")
    col8.metric("Total analyzed", "-")
    col9.metric("Relevant", "-")


def _render_metrics(result: DigestResult) -> None:
    import streamlit as st

    col1, col2, col3 = st.columns(3)
    col1.metric("Retrieved", result.retrieved_count)
    col2.metric("Already analyzed / reused", result.reused_analysis_count)
    col3.metric("Screened this run", result.preselected_count + result.skipped_analysis_count)
    col4, col5, col6 = st.columns(3)
    col4.metric("Passed preselection", result.preselected_count)
    col5.metric("Preselected out", result.skipped_analysis_count)
    col6.metric("New full analyses", result.new_analysis_count)
    col7, col8, col9 = st.columns(3)
    col7.metric("Reused full analyses", result.reused_analysis_count)
    col8.metric("Total analyzed", result.analyzed_count)
    col9.metric("Relevant", result.above_threshold_count)


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
    else:
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
                context=f"today:{result.run_id}:{view}",
            )
    _render_preselected_out_articles(result, db)
    _render_unresolved_articles(result, db)


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
    *,
    context: str,
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
        render_abstract_control(
            source=article.source,
            source_article_id=article.source_article_id,
            abstract=article.abstract,
            context=f"{context}:{article.source}:{article.source_article_id}",
        )
        render_library_control(
            db=db,
            article=article,
            context=f"{context}:library:{article.source}:{article.source_article_id}",
            profile=profile,
            profile_fingerprint_value=profile_fingerprint_value,
        )
        _render_library_context(item, db, result_run_id_from_context(context))
        _render_feedback_control(
            item,
            db,
            profile,
            profile_fingerprint_value,
            current_feedback,
        )


def result_run_id_from_context(context: str) -> int | None:
    parts = context.split(":")
    if len(parts) < 2 or parts[0] != "today":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _render_library_context(item: DigestItem, db: Database, run_id: int | None) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    suggestions = list_display_context_suggestions(db, article_id=article_id)
    if suggestions:
        st.markdown("**Connections to your Library**")
        for display in suggestions:
            suggestion = display.suggestion
            collection_label = (
                f" | Collection: {display.collection.name}"
                if display.collection is not None
                else ""
            )
            confidence = (
                f" | confidence {suggestion.confidence:.2f}"
                if suggestion.confidence is not None
                else ""
            )
            with st.container(border=True):
                st.caption(
                    f"Suggested relationship{collection_label}{confidence}"
                )
                st.markdown(f"**{display.related_article.title}**")
                st.caption(suggestion.relation_label)
                st.write(suggestion.rationale)
                if suggestion.id is not None and st.button(
                    "Dismiss Library context",
                    key=context_action_key(
                        action="dismiss",
                        article_id=article_id,
                        suggestion_id=suggestion.id,
                    ),
                    icon=":material/close:",
                ):
                    dismiss_context_suggestion(db, suggestion_id=suggestion.id)
                    st.rerun()
    _render_library_context_generation(item, db, run_id)


def _render_library_context_generation(
    item: DigestItem,
    db: Database,
    run_id: int | None,
) -> None:
    import streamlit as st

    article_id = item.article.id
    if article_id is None:
        return
    if st.button(
        "Find Library connections",
        key=context_action_key(action="generate", article_id=article_id),
        icon=":material/psychology:",
    ):
        generator, message = get_library_context_generator()
        if generator is None:
            st.warning(
                message or "Library context generation is unavailable.",
                icon=":material/warning:",
            )
            return
        with st.spinner("Finding Library connections..."):
            try:
                suggestions = generate_library_context_for_item(
                    db,
                    run_id=run_id,
                    article=item.article,
                    analysis=item.analysis,
                    generator=generator,
                )
            except Exception as exc:
                st.error(
                    f"Library context generation failed: {sanitize_error(exc)}",
                    icon=":material/error:",
                )
                return
        if suggestions:
            st.success(
                f"Added {len(suggestions)} Library context suggestion(s).",
                icon=":material/check_circle:",
            )
        else:
            st.info("No grounded Library context was found.")
        st.rerun()


def _render_preselected_out_articles(result: DigestResult, db: Database) -> None:
    import streamlit as st

    if not result.skipped_articles:
        return
    st.markdown("**Preselected out**")
    st.caption(
        "These papers were retrieved and stored, then skipped by Stage-1 abstract "
        "preselection before full analysis."
    )
    for article in sorted(result.skipped_articles, key=_article_sort_key):
        with st.container(border=True):
            st.subheader(article.title)
            authors = ", ".join(article.authors) if article.authors else "Unknown authors"
            categories = ", ".join(article.categories) if article.categories else "Uncategorized"
            st.caption(
                f"{article.source}:{article.source_article_id} | {authors} | "
                f"Published {article.published_at:%Y-%m-%d %H:%M UTC} | "
                f"Categories: {categories}"
            )
            if article.abstract_url:
                st.link_button("arXiv", article.abstract_url)
            render_abstract_control(
                source=article.source,
                source_article_id=article.source_article_id,
                abstract=article.abstract,
                context=f"today:{result.run_id}:preselected:{article.source}:{article.source_article_id}",
            )
            render_library_control(
                db=db,
                article=article,
                context=(
                    f"today:{result.run_id}:preselected:library:"
                    f"{article.source}:{article.source_article_id}"
                ),
                profile=result.profile,
                profile_fingerprint_value=profile_semantic_fingerprint(result.profile),
            )


def _article_sort_key(article: Article) -> tuple[str, str, str]:
    return (article.title.lower(), article.source, article.source_article_id)


def _render_unresolved_articles(result: DigestResult, db: Database) -> None:
    import streamlit as st

    if not result.unresolved_articles:
        return
    st.markdown("**Analysis unavailable**")
    st.caption("These papers were retrieved but did not receive a valid analysis yet.")
    for article in sorted(result.unresolved_articles, key=_article_sort_key):
        with st.container(border=True):
            st.subheader(article.title)
            st.caption(f"{article.source}:{article.source_article_id}")
            if article.abstract_url:
                st.link_button("arXiv", article.abstract_url)
            render_abstract_control(
                source=article.source,
                source_article_id=article.source_article_id,
                abstract=article.abstract,
                context=f"today:{result.run_id}:unresolved:{article.source}:{article.source_article_id}",
            )
            render_library_control(
                db=db,
                article=article,
                context=(
                    f"today:{result.run_id}:unresolved:library:"
                    f"{article.source}:{article.source_article_id}"
                ),
                profile=result.profile,
                profile_fingerprint_value=profile_semantic_fingerprint(result.profile),
            )


def _render_quantitative_calibration_prompt(db: Database, result: DigestResult) -> None:
    import streamlit as st

    prompt = db.get_quantitative_calibration_for_run(result.run_id)
    if prompt is None or prompt.state == "SKIPPED":
        return
    if prompt.state == "COMPLETED":
        if prompt.user_relevance_score is None or prompt.model_relevance_score is None:
            return
        with st.container(border=True):
            st.markdown("**Relevance calibration saved**")
            st.caption(
                f"Your score: {prompt.user_relevance_score:.2f}. "
                f"Research Digest score: {prompt.model_relevance_score:.2f}. "
                f"Difference: {prompt.user_relevance_score - prompt.model_relevance_score:+.2f}."
            )
        return
    if prompt.state == "DISMISSED":
        return
    if prompt.article_id is None or prompt.id is None:
        return
    article = db.get_article(prompt.article_id)
    if article is None:
        return
    with st.container(border=True):
        st.markdown("**Help calibrate Research Digest**")
        st.markdown(f'How relevant is this paper to "{result.profile.name}"?')
        st.caption("0 = no meaningful connection to this profile")
        st.caption("0.5 = related / adjacent")
        st.caption("1 = directly central to this profile")
        st.markdown(f"**{article.title}**")
        st.caption(result.profile.description)
        st.text(article.abstract or "Abstract unavailable")
        with st.form(f"quantitative_calibration_{prompt.id}", border=False):
            user_score = st.slider(
                "Your relevance score",
                min_value=0.0,
                max_value=1.0,
                value=0.5,
                step=0.01,
            )
            with st.container(horizontal=True):
                submitted = st.form_submit_button(
                    "Submit",
                    type="primary",
                    icon=":material/check:",
                )
                dismissed = st.form_submit_button("Not now", icon=":material/close:")
        if submitted:
            submit_quantitative_calibration(
                db,
                calibration_id=prompt.id,
                user_relevance_score=float(user_score),
            )
            st.success("Calibration score saved.", icon=":material/check_circle:")
            st.rerun()
        if dismissed:
            dismiss_quantitative_calibration(db, calibration_id=prompt.id)
            st.info("Calibration prompt dismissed.", icon=":material/info:")
            st.rerun()


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
    st.markdown("**Help Research Digest learn**")
    st.caption(
        "Judge profile fit separately from whether you personally want to read the paper."
    )
    profile_match = st.segmented_control(
        f'Does this paper match "{profile.name}"?',
        options=_FEEDBACK_OPTIONS,
        default=current_feedback.profile_match if current_feedback is not None else None,
        required=False,
        format_func=lambda label: _FEEDBACK_LABELS[label],
        key=(
            f"feedback_profile_match_{profile.id}_{item.article.id}_"
            f"{profile_fingerprint_value}"
        ),
        width="stretch",
    )
    st.caption(
        "Judge whether the paper fits this profile description, regardless of whether "
        "you personally want to read it."
    )
    personal_interest = st.segmented_control(
        "Are you personally interested in this paper?",
        options=_FEEDBACK_OPTIONS,
        default=current_feedback.personal_interest if current_feedback is not None else None,
        required=False,
        format_func=lambda label: _FEEDBACK_LABELS[label],
        key=(
            f"feedback_personal_interest_{profile.id}_{item.article.id}_"
            f"{profile_fingerprint_value}"
        ),
        width="stretch",
    )
    st.caption(
        "This may include papers outside the current profile. Your answer can help "
        "Research Digest discover other interests you may want to follow."
    )
    if persist_feedback_selection(
        item=item,
        db=db,
        profile=profile,
        profile_fingerprint_value=profile_fingerprint_value,
        current_feedback=current_feedback,
        profile_match=_feedback_answer_value(profile_match),
        personal_interest=_feedback_answer_value(personal_interest),
        clear_profile_match=profile_match == "UNANSWERED",
        clear_personal_interest=personal_interest == "UNANSWERED",
    ):
        st.success("Feedback saved.", icon=":material/check_circle:")


def _feedback_answer_value(value: FeedbackControlAnswer | None) -> FeedbackAnswer | None:
    if value == "UNANSWERED":
        return None
    return value


def persist_feedback_selection(
    *,
    item: DigestItem,
    db: Database,
    profile: InterestProfile,
    profile_fingerprint_value: str,
    current_feedback: ArticleFeedback | None,
    profile_match: FeedbackAnswer | None = None,
    personal_interest: FeedbackAnswer | None = None,
    clear_profile_match: bool = False,
    clear_personal_interest: bool = False,
) -> bool:
    if item.article.id is None or profile.id is None:
        return False
    if (
        profile_match is None
        and personal_interest is None
        and not clear_profile_match
        and not clear_personal_interest
    ):
        return False
    if current_feedback is None and (clear_profile_match or clear_personal_interest):
        return False
    if (
        current_feedback is not None
        and (
            (profile_match is None and not clear_profile_match)
            or profile_match == current_feedback.profile_match
        )
        and (
            (personal_interest is None and not clear_personal_interest)
            or personal_interest == current_feedback.personal_interest
        )
        and not (clear_profile_match and current_feedback.profile_match is not None)
        and not (clear_personal_interest and current_feedback.personal_interest is not None)
    ):
        return False
    db.upsert_article_feedback(
        article_id=item.article.id,
        profile_id=profile.id,
        profile_fingerprint=profile_fingerprint_value,
        profile_match=profile_match,
        personal_interest=personal_interest,
        clear_profile_match=clear_profile_match,
        clear_personal_interest=clear_personal_interest,
    )
    return True
