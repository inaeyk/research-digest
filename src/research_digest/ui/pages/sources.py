"""Source configuration page."""

from __future__ import annotations

from research_digest.errors import sanitize_error
from research_digest.models import (
    MAX_ARXIV_LOOKBACK_HOURS,
    MAX_ARXIV_RESULTS,
    ArxivSourceConfig,
    ModelValidationError,
)
from research_digest.ui.common import get_database


def render() -> None:
    import streamlit as st

    st.title("Sources")
    db = get_database()
    config = db.get_arxiv_config() or ArxivSourceConfig()

    with st.form("arxiv_source_config"):
        enabled = st.toggle("arXiv enabled", value=config.enabled)
        category_text = st.text_area(
            "Categories",
            value="\n".join(config.categories or []),
            help="Enter arXiv categories separated by commas or new lines.",
            height=120,
        )
        lookback_hours = st.number_input(
            "Lookback hours",
            min_value=1,
            max_value=MAX_ARXIV_LOOKBACK_HOURS,
            value=config.lookback_hours,
            step=1,
        )
        max_results = st.number_input(
            "Max results",
            min_value=1,
            max_value=MAX_ARXIV_RESULTS,
            value=config.max_results,
            step=5,
        )
        submitted = st.form_submit_button("Save")
        if submitted:
            try:
                db.save_arxiv_config(
                    ArxivSourceConfig(
                        enabled=enabled,
                        categories=_parse_categories(category_text),
                        lookback_hours=int(lookback_hours),
                        max_results=int(max_results),
                    )
                )
            except ModelValidationError as exc:
                st.error(sanitize_error(exc))
            else:
                st.success("Source configuration saved.")
                st.rerun()


def _parse_categories(value: str) -> list[str]:
    normalized = value.replace(",", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]
