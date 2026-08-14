"""Today page."""

from __future__ import annotations

import json
from typing import TypeAlias

from research_digest.errors import sanitize_error
from research_digest.models import ArxivSourceConfig, DigestResult, ModelValidationError
from research_digest.pipeline import DigestPipelineError, run_digest
from research_digest.sources.arxiv import ArxivSource
from research_digest.sources.base import SourceError
from research_digest.ui.common import get_analyzer, get_database

DigestInputSignature: TypeAlias = tuple[int | None, str]
_LAST_DIGEST_RESULT_KEY = "last_digest_result"
_LAST_DIGEST_SIGNATURE_KEY = "last_digest_signature"


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
        st.info("Create and enable an interest profile before running a digest.")
        return

    profile = st.selectbox(
        "Interest profile",
        options=profiles,
        format_func=lambda item: f"{item.name} (threshold {item.relevance_threshold:.2f})",
    )
    current_signature = digest_input_signature(profile.id, source_config)

    analyzer, analyzer_message = get_analyzer()
    if analyzer_message is not None:
        st.warning(f"Analysis unavailable: {sanitize_error(analyzer_message)}")

    if st.button("Run Digest", type="primary"):
        with st.spinner("Fetching and analyzing recent papers..."):
            try:
                result = run_digest(
                    db=db,
                    source=ArxivSource(),
                    analyzer=analyzer,
                    profile_id=profile.id,
                )
            except (DigestPipelineError, SourceError, ModelValidationError) as exc:
                st.error(sanitize_error(exc))
            except Exception as exc:
                st.error(f"Digest run failed: {sanitize_error(exc)}")
            else:
                st.session_state[_LAST_DIGEST_RESULT_KEY] = result
                st.session_state[_LAST_DIGEST_SIGNATURE_KEY] = current_signature

    result = st.session_state.get(_LAST_DIGEST_RESULT_KEY)
    result_signature = st.session_state.get(_LAST_DIGEST_SIGNATURE_KEY)
    if isinstance(result, DigestResult) and result_signature == current_signature:
        _render_run_confirmation(result)
        _render_metrics(result)
        if not result.analysis_available:
            st.info("Papers were fetched and stored, but no new analysis was run.")
        _render_items(result)
    else:
        st.session_state.pop(_LAST_DIGEST_RESULT_KEY, None)
        st.session_state.pop(_LAST_DIGEST_SIGNATURE_KEY, None)
        _render_empty_metrics()


def digest_input_signature(
    profile_id: int | None,
    source_config: ArxivSourceConfig,
) -> DigestInputSignature:
    return profile_id, source_config_fingerprint(source_config)


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


def _render_metrics(result: DigestResult) -> None:
    import streamlit as st

    col1, col2, col3 = st.columns(3)
    col1.metric("Retrieved", result.retrieved_count)
    col2.metric("Analyzed", result.analyzed_count)
    col3.metric("Above threshold", result.relevant_count)


def _render_items(result: DigestResult) -> None:
    import streamlit as st

    if not result.items:
        st.info("No papers are above the relevance threshold for this run.")
        return

    for item in result.items:
        article = item.article
        analysis = item.analysis
        with st.container(border=True):
            st.subheader(article.title)
            authors = ", ".join(article.authors) if article.authors else "Unknown authors"
            st.caption(
                f"{authors} | Published {article.published_at:%Y-%m-%d %H:%M UTC} | "
                f"Categories: {', '.join(article.categories)}"
            )
            score_col, priority_col = st.columns([1, 1])
            score_col.metric("Relevance", f"{analysis.relevance_score:.2f}")
            priority_col.metric("Priority", analysis.reading_priority)
            st.write(analysis.relevance_reason)
            st.markdown("**Summary**")
            st.write(analysis.summary)
            st.markdown("**Why it matters**")
            st.write(analysis.why_it_matters)
            if analysis.matched_topics:
                st.markdown("**Matched topics**")
                st.write(", ".join(analysis.matched_topics))
            link_col, pdf_col = st.columns([1, 1])
            link_col.link_button("arXiv", article.abstract_url)
            if article.pdf_url:
                pdf_col.link_button("PDF", article.pdf_url)
