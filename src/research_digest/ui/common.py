"""Shared Streamlit UI helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from research_digest.ai_providers import LibrarySummaryProvider, ResearchConversationProvider
from research_digest.analysis.base import LLMAnalyzer
from research_digest.analysis.codex_connections import CodexLibraryConnectionGenerator
from research_digest.analysis.codex_context import CodexLibraryContextGenerator
from research_digest.analysis.codex_tags import CodexAITagGenerator
from research_digest.analysis.providers import build_configured_analyzer
from research_digest.config import AnalyzerProvider, AppConfig, ConfigError, load_config
from research_digest.connections import LibraryConnectionGenerator
from research_digest.conversation_providers import (
    ResearchConversationRoute,
    build_configured_research_conversation_provider,
    configured_research_conversation_route,
)
from research_digest.db import Database
from research_digest.library_context import LibraryContextGenerator
from research_digest.summary_providers import build_configured_library_summary_provider
from research_digest.tags import AITagGenerator


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
                data_dir=active_config.data_dir,
                config_dir=active_config.config_dir,
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


def get_library_summary_provider() -> tuple[LibrarySummaryProvider | None, str | None]:
    """Build the configured summary adapter only after an explicit UI action."""

    import streamlit as st

    @st.cache_resource(show_spinner=False)  # type: ignore[untyped-decorator]
    def _connect(
        provider_name: AnalyzerProvider,
        api_key_present: bool,
        openai_model: str,
        codex_model: str | None,
        codex_timeout_seconds: float,
    ) -> tuple[LibrarySummaryProvider | None, str | None]:
        active = load_config()
        connection = build_configured_library_summary_provider(
            AppConfig(
                db_path=active.db_path,
                data_dir=active.data_dir,
                config_dir=active.config_dir,
                analyzer_provider=provider_name,
                openai_api_key=active.openai_api_key if api_key_present else None,
                openai_model=openai_model,
                codex_model=codex_model,
                codex_timeout_seconds=codex_timeout_seconds,
            )
        )
        return connection.provider, connection.message

    try:
        config = load_config()
    except ConfigError as exc:
        return None, str(exc)
    return cast(
        tuple[LibrarySummaryProvider | None, str | None],
        _connect(
            config.analyzer_provider,
            config.openai_api_key is not None,
            config.openai_model,
            config.codex_model,
            config.codex_timeout_seconds,
        ),
    )


def get_research_conversation_route() -> ResearchConversationRoute:
    """Read the configured route for zero-AI discussion creation provenance."""

    return configured_research_conversation_route(load_config())


def get_research_conversation_provider() -> tuple[ResearchConversationProvider | None, str | None]:
    """Construct the configured adapter only after explicit Send or Retry."""

    import streamlit as st

    @st.cache_resource(show_spinner=False)  # type: ignore[untyped-decorator]
    def _connect(
        provider_name: AnalyzerProvider,
        api_key_present: bool,
        openai_model: str,
        codex_model: str | None,
        codex_timeout_seconds: float,
    ) -> tuple[ResearchConversationProvider | None, str | None]:
        active = load_config()
        connection = build_configured_research_conversation_provider(
            AppConfig(
                db_path=active.db_path,
                data_dir=active.data_dir,
                config_dir=active.config_dir,
                analyzer_provider=provider_name,
                openai_api_key=active.openai_api_key if api_key_present else None,
                openai_model=openai_model,
                codex_model=codex_model,
                codex_timeout_seconds=codex_timeout_seconds,
            )
        )
        return connection.provider, connection.message

    try:
        config = load_config()
    except ConfigError as exc:
        return None, str(exc)
    return cast(
        tuple[ResearchConversationProvider | None, str | None],
        _connect(
            config.analyzer_provider,
            config.openai_api_key is not None,
            config.openai_model,
            config.codex_model,
            config.codex_timeout_seconds,
        ),
    )


def get_ai_tag_generator() -> tuple[AITagGenerator | None, str | None]:
    import streamlit as st

    @st.cache_resource(show_spinner=False)  # type: ignore[untyped-decorator]
    def _connect_ai_tag_generator(
        codex_model: str | None,
        codex_timeout_seconds: float,
    ) -> tuple[AITagGenerator | None, str | None]:
        try:
            return (
                CodexAITagGenerator(
                    model=codex_model,
                    timeout_seconds=codex_timeout_seconds,
                ),
                None,
            )
        except Exception as exc:
            return None, str(exc)

    try:
        config = load_config()
    except ConfigError as exc:
        return None, str(exc)
    return cast(
        tuple[AITagGenerator | None, str | None],
        _connect_ai_tag_generator(config.codex_model, config.codex_timeout_seconds),
    )


def get_connection_generator() -> tuple[LibraryConnectionGenerator | None, str | None]:
    import streamlit as st

    @st.cache_resource(show_spinner=False)  # type: ignore[untyped-decorator]
    def _connect_connection_generator(
        codex_model: str | None,
        codex_timeout_seconds: float,
    ) -> tuple[LibraryConnectionGenerator | None, str | None]:
        try:
            return (
                CodexLibraryConnectionGenerator(
                    model=codex_model,
                    timeout_seconds=codex_timeout_seconds,
                ),
                None,
            )
        except Exception as exc:
            return None, str(exc)

    try:
        config = load_config()
    except ConfigError as exc:
        return None, str(exc)
    return cast(
        tuple[LibraryConnectionGenerator | None, str | None],
        _connect_connection_generator(config.codex_model, config.codex_timeout_seconds),
    )


def get_library_context_generator() -> tuple[LibraryContextGenerator | None, str | None]:
    import streamlit as st

    @st.cache_resource(show_spinner=False)  # type: ignore[untyped-decorator]
    def _connect_context_generator(
        codex_model: str | None,
        codex_timeout_seconds: float,
    ) -> tuple[LibraryContextGenerator | None, str | None]:
        try:
            return (
                CodexLibraryContextGenerator(
                    model=codex_model,
                    timeout_seconds=codex_timeout_seconds,
                ),
                None,
            )
        except Exception as exc:
            return None, str(exc)

    try:
        config = load_config()
    except ConfigError as exc:
        return None, str(exc)
    return cast(
        tuple[LibraryContextGenerator | None, str | None],
        _connect_context_generator(config.codex_model, config.codex_timeout_seconds),
    )
