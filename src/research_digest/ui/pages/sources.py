"""Source configuration page."""

from __future__ import annotations

from research_digest.errors import sanitize_error
from research_digest.models import (
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
        st.caption(
            "Manual digests choose arXiv source dates on Today. "
            "Research Digest retrieves all eligible articles for those dates."
        )
        enabled = st.toggle("arXiv enabled", value=config.enabled)
        category_text = st.text_area(
            "Categories",
            value="\n".join(config.categories or []),
            help="Enter arXiv categories separated by commas or new lines.",
            height=120,
        )
        submitted = st.form_submit_button("Save", icon=":material/save:")
        if submitted:
            try:
                db.save_arxiv_config(updated_arxiv_config(config, enabled, category_text))
            except ModelValidationError as exc:
                st.error(sanitize_error(exc))
            else:
                st.success("Source configuration saved.")
                st.rerun()


def _parse_categories(value: str) -> list[str]:
    normalized = value.replace(",", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def updated_arxiv_config(
    existing: ArxivSourceConfig,
    enabled: bool,
    category_text: str,
) -> ArxivSourceConfig:
    return ArxivSourceConfig(
        enabled=enabled,
        categories=_parse_categories(category_text),
        lookback_hours=existing.lookback_hours,
        max_results=existing.max_results,
    )
