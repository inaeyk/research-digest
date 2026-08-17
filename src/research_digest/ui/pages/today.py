"""Today page."""

from __future__ import annotations

import json
from typing import Literal, TypeAlias, TypeGuard

from research_digest.calibration import CalibrationSummary, build_calibration_summary
from research_digest.db import Database
from research_digest.errors import sanitize_error
from research_digest.models import (
    AnalysisOrigin,
    ArticleFeedback,
    ArxivSourceConfig,
    DigestItem,
    DigestResult,
    FeedbackLabel,
    InterestProfile,
    ModelValidationError,
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
from research_digest.sources.base import SourceError
from research_digest.synthesis import CrossPaperSynthesis, build_cross_paper_synthesis
from research_digest.ui.common import get_analyzer, get_database

DigestInputSignature: TypeAlias = tuple[str, str]
DigestView: TypeAlias = Literal["relevant", "all_analyzed", "below_threshold"]
_LAST_DIGEST_RESULT_KEY = "last_digest_result"
_LAST_DIGEST_SIGNATURE_KEY = "last_digest_signature"
_RELEVANT_VIEW: DigestView = "relevant"
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
        f"Lookback: {source_config.lookback_hours} hours. "
        f"Max results: {source_config.max_results}."
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
    current_signature = digest_input_signature(profile, source_config)

    analyzer, analyzer_message = get_analyzer()
    if analyzer_message is not None:
        st.warning(
            "Analysis provider needs attention: "
            f"{sanitize_error(analyzer_message)}. Run `research-digest doctor` for details.",
            icon=":material/warning:",
        )

    if st.button("Run digest", type="primary", icon=":material/play_arrow:"):
        with st.spinner("Fetching and analyzing recent papers..."):
            try:
                if profile.id is None:
                    raise DigestPipelineError("selected interest profile is missing an id")
                service_result = run_digest_for_profile(
                    db=db,
                    source=ArxivSource(),
                    analyzer=analyzer,
                    profile_id=profile.id,
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
    if is_current_digest_result(result, result_signature, current_signature):
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
) -> DigestInputSignature:
    return profile_fingerprint(profile), source_config_fingerprint(source_config)


def profile_fingerprint(profile: InterestProfile) -> str:
    return profile_semantic_signature(profile)


def source_config_fingerprint(source_config: ArxivSourceConfig) -> str:
    return json.dumps(
        {
            "enabled": source_config.enabled,
            "categories": source_config.categories,
            "lookback_hours": source_config.lookback_hours,
            "max_results": source_config.max_results,
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


def _render_run_confirmation(result: DigestResult) -> None:
    import streamlit as st

    completed_at = result.completed_at or result.started_at
    st.success(f"Run completed: #{result.run_id} at {completed_at:%Y-%m-%d %H:%M:%S UTC}")


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
