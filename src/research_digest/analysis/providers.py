"""Configured analyzer provider construction."""

from __future__ import annotations

from dataclasses import dataclass

from research_digest.analysis.base import AnalyzerUnavailable, LLMAnalyzer
from research_digest.analysis.codex_cli import CodexCLIAnalyzer
from research_digest.analysis.openai import OpenAIAnalyzer
from research_digest.config import AppConfig, ConfigError, load_config


@dataclass(frozen=True)
class AnalyzerConnection:
    analyzer: LLMAnalyzer | None
    message: str | None


def build_configured_analyzer(config: AppConfig | None = None) -> AnalyzerConnection:
    """Build the analyzer selected by runtime configuration.

    Provider unavailability is represented as data so Streamlit and headless CLI
    runs can share the same behavior without importing UI code.
    """

    try:
        active_config = config or load_config()
    except ConfigError as exc:
        return AnalyzerConnection(analyzer=None, message=str(exc))

    try:
        if active_config.analyzer_provider == "codex":
            return AnalyzerConnection(
                analyzer=CodexCLIAnalyzer(
                    model=active_config.codex_model,
                    timeout_seconds=active_config.codex_timeout_seconds,
                ),
                message=None,
            )
        if active_config.analyzer_provider == "openai":
            if active_config.openai_api_key is None:
                return AnalyzerConnection(analyzer=None, message="OPENAI_API_KEY is not set.")
            return AnalyzerConnection(
                analyzer=OpenAIAnalyzer(
                    api_key=active_config.openai_api_key,
                    model=active_config.openai_model,
                ),
                message=None,
            )
    except AnalyzerUnavailable as exc:
        return AnalyzerConnection(analyzer=None, message=str(exc))

    return AnalyzerConnection(
        analyzer=None,
        message=f"Unsupported analyzer provider: {active_config.analyzer_provider}",
    )
