"""Configured analyzer provider construction."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from research_digest.analysis.base import AnalyzerUnavailable, LLMAnalyzer
from research_digest.analysis.codex_cli import CodexCLIAnalyzer
from research_digest.analysis.openai import OpenAIAnalyzer
from research_digest.config import AppConfig, ConfigError, load_config


@dataclass(frozen=True)
class AnalyzerConnection:
    analyzer: LLMAnalyzer | None
    message: str | None


AnalyzerFactory = Callable[[AppConfig], AnalyzerConnection]


class AnalyzerRegistry:
    """Explicit registry for configured analyzer factories."""

    def __init__(self, factories: Mapping[str, AnalyzerFactory] | None = None) -> None:
        self._factories = dict(factories or {})

    def register(self, name: str, factory: AnalyzerFactory) -> None:
        if not name.strip():
            raise ValueError("analyzer provider name is required")
        self._factories[name] = factory

    def get(self, name: str) -> AnalyzerFactory | None:
        return self._factories.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def build_configured_analyzer(
    config: AppConfig | None = None,
    *,
    registry: AnalyzerRegistry | None = None,
) -> AnalyzerConnection:
    """Build the analyzer selected by runtime configuration.

    Provider unavailability is represented as data so Streamlit and headless CLI
    runs can share the same behavior without importing UI code.
    """

    try:
        active_config = config or load_config()
    except ConfigError as exc:
        return AnalyzerConnection(analyzer=None, message=str(exc))

    try:
        active_registry = registry or build_default_analyzer_registry()
        factory = active_registry.get(active_config.analyzer_provider)
        if factory is None:
            return AnalyzerConnection(
                analyzer=None,
                message=f"Unsupported analyzer provider: {active_config.analyzer_provider}",
            )
        return factory(active_config)
    except AnalyzerUnavailable as exc:
        return AnalyzerConnection(analyzer=None, message=str(exc))


def build_default_analyzer_registry() -> AnalyzerRegistry:
    return AnalyzerRegistry(
        {
            "codex": _build_codex_analyzer,
            "openai": _build_openai_analyzer,
        }
    )


def _build_codex_analyzer(config: AppConfig) -> AnalyzerConnection:
    return AnalyzerConnection(
        analyzer=CodexCLIAnalyzer(
            model=config.codex_model,
            timeout_seconds=config.codex_timeout_seconds,
        ),
        message=None,
    )


def _build_openai_analyzer(config: AppConfig) -> AnalyzerConnection:
    if config.openai_api_key is None:
        return AnalyzerConnection(analyzer=None, message="OPENAI_API_KEY is not set.")
    return AnalyzerConnection(
        analyzer=OpenAIAnalyzer(
            api_key=config.openai_api_key,
            model=config.openai_model,
        ),
        message=None,
    )
