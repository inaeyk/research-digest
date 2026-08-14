"""Shared Streamlit UI helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from research_digest.analysis.base import AnalyzerUnavailable, LLMAnalyzer
from research_digest.analysis.codex_cli import CodexCLIAnalyzer
from research_digest.analysis.openai import OpenAIAnalyzer
from research_digest.config import ConfigError, load_config
from research_digest.db import Database


def get_database() -> Database:
    import streamlit as st

    @st.cache_resource  # type: ignore[untyped-decorator]
    def _connect(db_path: Path) -> Database:
        return Database(db_path)

    return cast(Database, _connect(load_config().db_path))


def get_analyzer() -> tuple[LLMAnalyzer | None, str | None]:
    import streamlit as st

    @st.cache_resource(show_spinner=False)  # type: ignore[untyped-decorator]
    def _connect_analyzer(
        provider: str,
        api_key_present: bool,
        openai_model: str,
        codex_model: str | None,
        codex_timeout_seconds: float,
    ) -> tuple[LLMAnalyzer | None, str | None]:
        try:
            if provider == "codex":
                return (
                    CodexCLIAnalyzer(
                        model=codex_model,
                        timeout_seconds=codex_timeout_seconds,
                    ),
                    None,
                )
            if provider == "openai":
                if not api_key_present:
                    return None, "OPENAI_API_KEY is not set."
                return OpenAIAnalyzer(model=openai_model), None
            return None, f"Unsupported analyzer provider: {provider}"
        except AnalyzerUnavailable as exc:
            return None, str(exc)

    try:
        config = load_config()
    except ConfigError as exc:
        return None, str(exc)
    return cast(
        tuple[LLMAnalyzer | None, str | None],
        _connect_analyzer(
            config.analyzer_provider,
            config.openai_api_key is not None,
            config.openai_model,
            config.codex_model,
            config.codex_timeout_seconds,
        ),
    )
