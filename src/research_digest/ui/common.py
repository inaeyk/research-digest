"""Shared Streamlit UI helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from research_digest.analysis.base import LLMAnalyzer
from research_digest.analysis.providers import build_configured_analyzer
from research_digest.config import AnalyzerProvider, AppConfig, ConfigError, load_config
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
        provider: AnalyzerProvider,
        api_key_present: bool,
        openai_model: str,
        codex_model: str | None,
        codex_timeout_seconds: float,
    ) -> tuple[LLMAnalyzer | None, str | None]:
        active_config = load_config()
        connection = build_configured_analyzer(
            AppConfig(
                db_path=active_config.db_path,
                analyzer_provider=provider,
                openai_api_key=active_config.openai_api_key if api_key_present else None,
                openai_model=openai_model,
                codex_model=codex_model,
                codex_timeout_seconds=codex_timeout_seconds,
            )
        )
        return connection.analyzer, connection.message

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
