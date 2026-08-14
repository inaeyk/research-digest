"""Application configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_DB_FILENAME = "research_digest.sqlite3"
DEFAULT_ANALYZER_PROVIDER = "codex"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_CODEX_TIMEOUT_SECONDS = 180.0

AnalyzerProvider = Literal["codex", "openai"]


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration loaded from environment variables."""

    db_path: Path
    analyzer_provider: AnalyzerProvider
    openai_api_key: str | None
    openai_model: str
    codex_model: str | None
    codex_timeout_seconds: float


def load_config() -> AppConfig:
    """Load configuration from environment variables."""

    db_path = Path(os.environ.get("RESEARCH_DIGEST_DB", DEFAULT_DB_FILENAME))
    api_key = os.environ.get("OPENAI_API_KEY")
    return AppConfig(
        db_path=db_path,
        analyzer_provider=_load_analyzer_provider(),
        openai_api_key=api_key if api_key else None,
        openai_model=os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        codex_model=os.environ.get("RESEARCH_DIGEST_CODEX_MODEL") or None,
        codex_timeout_seconds=_load_codex_timeout(),
    )


def _load_analyzer_provider() -> AnalyzerProvider:
    value = os.environ.get("RESEARCH_DIGEST_ANALYZER", DEFAULT_ANALYZER_PROVIDER).strip().lower()
    if value == "codex":
        return "codex"
    if value == "openai":
        return "openai"
    raise ConfigError("RESEARCH_DIGEST_ANALYZER must be either 'codex' or 'openai'")


def _load_codex_timeout() -> float:
    value = os.environ.get("RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS")
    if value is None or not value.strip():
        return DEFAULT_CODEX_TIMEOUT_SECONDS
    try:
        timeout = float(value)
    except ValueError as exc:
        raise ConfigError("RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS must be numeric") from exc
    if timeout <= 0:
        raise ConfigError("RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS must be positive")
    return timeout
