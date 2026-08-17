"""Streamlit entrypoint for Research Digest."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_digest.ui.pages import history, interests, settings, sources, today


def _build_pages(st_module: Any) -> list[Any]:
    return [
        st_module.Page(
            today.render,
            title="Today",
            icon=":material/today:",
            default=True,
        ),
        st_module.Page(
            history.render,
            title="History",
            icon=":material/history:",
            url_path="history",
        ),
        st_module.Page(
            interests.render,
            title="Interests",
            icon=":material/person_search:",
            url_path="interests",
        ),
        st_module.Page(
            sources.render,
            title="Sources",
            icon=":material/travel_explore:",
            url_path="sources",
        ),
        st_module.Page(
            settings.render,
            title="Settings",
            icon=":material/settings:",
            url_path="settings",
        ),
    ]


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Research Digest", layout="wide")
    navigation = st.navigation(_build_pages(st))
    navigation.run()


if __name__ == "__main__":
    main()
