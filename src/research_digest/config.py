"""Application configuration helpers."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_DB_FILENAME = "research_digest.sqlite3"
APP_NAME = "Research Digest"
APP_AUTHOR = "Research Digest"
DEFAULT_ANALYZER_PROVIDER = "codex"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_CODEX_TIMEOUT_SECONDS = 180.0
ENV_DB_PATH = "RESEARCH_DIGEST_DB"
ENV_DATA_DIR = "RESEARCH_DIGEST_DATA_DIR"
ENV_CONFIG_DIR = "RESEARCH_DIGEST_CONFIG_DIR"
ENV_LEGACY_DB = "RESEARCH_DIGEST_LEGACY_DB"

AnalyzerProvider = Literal["codex", "openai"]


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration loaded from environment variables."""

    db_path: Path
    data_dir: Path
    config_dir: Path
    analyzer_provider: AnalyzerProvider
    openai_api_key: str | None
    openai_model: str
    codex_model: str | None
    codex_timeout_seconds: float


def load_config() -> AppConfig:
    """Load configuration from environment variables."""

    data_dir = resolve_data_dir()
    config_dir = resolve_config_dir()
    db_path = _resolve_db_path(data_dir)
    api_key = os.environ.get("OPENAI_API_KEY")
    return AppConfig(
        db_path=db_path,
        data_dir=data_dir,
        config_dir=config_dir,
        analyzer_provider=_load_analyzer_provider(),
        openai_api_key=api_key if api_key else None,
        openai_model=os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        codex_model=os.environ.get("RESEARCH_DIGEST_CODEX_MODEL") or None,
        codex_timeout_seconds=_load_codex_timeout(),
    )


def resolve_data_dir() -> Path:
    override = os.environ.get(ENV_DATA_DIR)
    if override and override.strip():
        return Path(override).expanduser().resolve()
    return _platform_user_data_dir().resolve()


def resolve_config_dir() -> Path:
    override = os.environ.get(ENV_CONFIG_DIR)
    if override and override.strip():
        return Path(override).expanduser().resolve()
    return _platform_user_config_dir().resolve()


def active_data_location() -> Path:
    return load_config().db_path


def _resolve_db_path(data_dir: Path) -> Path:
    explicit = os.environ.get(ENV_DB_PATH)
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / DEFAULT_DB_FILENAME
    _adopt_legacy_db(db_path)
    if db_path.exists() and not _is_valid_sqlite_db(db_path):
        legacy_path = _legacy_db_path()
        if legacy_path.exists() and legacy_path != db_path and _is_valid_sqlite_db(legacy_path):
            _copy_validated_db(legacy_path, db_path)
        else:
            raise ConfigError(f"active database is not a valid SQLite database: {db_path}")
    return db_path


def _adopt_legacy_db(db_path: Path) -> None:
    legacy_path = _legacy_db_path()
    if db_path.exists() or not legacy_path.exists() or legacy_path == db_path:
        return
    _copy_validated_db(legacy_path, db_path)


def _legacy_db_path() -> Path:
    legacy_override = os.environ.get(ENV_LEGACY_DB)
    if legacy_override and legacy_override.strip():
        return Path(legacy_override).expanduser().resolve()
    return (Path.cwd() / DEFAULT_DB_FILENAME).resolve()


def _copy_validated_db(source: Path, destination: Path) -> None:
    if not _is_valid_sqlite_db(source):
        raise ConfigError(f"legacy database is not a valid SQLite database: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".adopt.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        shutil.copy2(source, temporary)
        if not _is_valid_sqlite_db(temporary):
            raise ConfigError("copied legacy database failed SQLite integrity validation")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _is_valid_sqlite_db(path: Path) -> bool:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error:
        return False
    return row is not None and row[0] == "ok"


def _platform_user_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    root = os.environ.get("XDG_DATA_HOME")
    if root and root.strip():
        return Path(root) / "research-digest"
    return Path.home() / ".local" / "share" / "research-digest"


def _platform_user_config_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    root = os.environ.get("XDG_CONFIG_HOME")
    if root and root.strip():
        return Path(root) / "research-digest"
    return Path.home() / ".config" / "research-digest"


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
