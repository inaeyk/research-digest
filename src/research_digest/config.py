"""Application configuration helpers."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from research_digest.models import DateSelection, ModelValidationError

AnalyzerProvider = Literal["codex", "openai"]

DEFAULT_DB_FILENAME = "research_digest.sqlite3"
DEFAULT_CONFIG_FILENAME = "config.json"
CONFIG_VERSION = 2
APP_NAME = "Research Digest"
APP_AUTHOR = "Research Digest"
DEFAULT_ANALYZER_PROVIDER: AnalyzerProvider = "codex"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_CODEX_TIMEOUT_SECONDS = 180.0
ENV_DB_PATH = "RESEARCH_DIGEST_DB"
ENV_DATA_DIR = "RESEARCH_DIGEST_DATA_DIR"
ENV_CONFIG_DIR = "RESEARCH_DIGEST_CONFIG_DIR"
ENV_LEGACY_DB = "RESEARCH_DIGEST_LEGACY_DB"
CONFIG_KEYS = {
    "config_version",
    "analyzer_provider",
    "openai_model",
    "codex_model",
    "codex_timeout_seconds",
    "default_date_selection",
}
SECRET_CONFIG_KEYS = {
    "OPENAI_API_KEY",
    "api_key",
    "openai_api_key",
    "secret",
    "token",
}


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True)
class PersistedConfig:
    config_version: int
    analyzer_provider: AnalyzerProvider
    openai_model: str
    codex_model: str | None
    codex_timeout_seconds: float
    default_date_selection: DateSelection


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
    config_version: int = CONFIG_VERSION
    config_path: Path | None = None
    last_config_backup_path: Path | None = None
    default_date_selection: DateSelection = field(default_factory=DateSelection.latest_available)


def load_config() -> AppConfig:
    """Load configuration from environment variables."""

    data_dir = resolve_data_dir()
    config_dir = resolve_config_dir()
    db_path = _resolve_db_path(data_dir)
    persisted_config, backup_path = _load_persisted_config(config_dir)
    api_key = os.environ.get("OPENAI_API_KEY")
    return AppConfig(
        db_path=db_path,
        data_dir=data_dir,
        config_dir=config_dir,
        analyzer_provider=_load_analyzer_provider(persisted_config.analyzer_provider),
        openai_api_key=api_key if api_key else None,
        openai_model=_load_required_string_override(
            "OPENAI_MODEL",
            default=persisted_config.openai_model,
        ),
        codex_model=_load_string_override(
            "RESEARCH_DIGEST_CODEX_MODEL",
            default=persisted_config.codex_model,
            optional=True,
        ),
        codex_timeout_seconds=_load_codex_timeout(persisted_config.codex_timeout_seconds),
        config_version=persisted_config.config_version,
        config_path=config_dir / DEFAULT_CONFIG_FILENAME,
        last_config_backup_path=backup_path,
        default_date_selection=persisted_config.default_date_selection,
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


def _load_persisted_config(config_dir: Path) -> tuple[PersistedConfig, Path | None]:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / DEFAULT_CONFIG_FILENAME
    if not config_path.exists():
        persisted = _default_persisted_config()
        _write_persisted_config(config_path, persisted)
        return persisted, None

    payload = _read_json_object(config_path)
    _validate_config_keys(payload)
    version = _read_config_version(payload)
    if version > CONFIG_VERSION:
        raise ConfigError(
            f"configuration version {version} is newer than supported version {CONFIG_VERSION}"
        )
    if version == CONFIG_VERSION:
        return _persisted_config_from_payload(payload), None

    backup_path = _backup_config_file(config_path, from_version=version, to_version=CONFIG_VERSION)
    upgraded = _upgrade_persisted_config(payload, from_version=version)
    _write_persisted_config(config_path, upgraded)
    return upgraded, backup_path


def _default_persisted_config() -> PersistedConfig:
    return PersistedConfig(
        config_version=CONFIG_VERSION,
        analyzer_provider=DEFAULT_ANALYZER_PROVIDER,
        openai_model=DEFAULT_OPENAI_MODEL,
        codex_model=None,
        codex_timeout_seconds=DEFAULT_CODEX_TIMEOUT_SECONDS,
        default_date_selection=DateSelection.latest_available(),
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"could not read configuration file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"configuration file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("configuration file must contain a JSON object")
    return payload


def _validate_config_keys(payload: dict[str, Any]) -> None:
    keys = set(payload)
    forbidden = keys & SECRET_CONFIG_KEYS
    if forbidden:
        raise ConfigError("configuration file must not contain secrets or API keys")
    unknown = keys - CONFIG_KEYS
    if unknown:
        raise ConfigError(
            "configuration file contains unsupported keys: " + ", ".join(sorted(unknown))
        )


def _read_config_version(payload: dict[str, Any]) -> int:
    raw_version = payload.get("config_version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise ConfigError("config_version must be an integer")
    if raw_version < 0:
        raise ConfigError("config_version must be non-negative")
    return raw_version


def _persisted_config_from_payload(payload: dict[str, Any]) -> PersistedConfig:
    version = _read_config_version(payload)
    if version != CONFIG_VERSION:
        raise ConfigError(f"configuration version {version} has not been upgraded")
    return PersistedConfig(
        config_version=version,
        analyzer_provider=_coerce_analyzer_provider(payload.get("analyzer_provider")),
        openai_model=_coerce_non_empty_string(
            payload.get("openai_model"),
            field_name="openai_model",
        ),
        codex_model=_coerce_optional_non_empty_string(
            payload.get("codex_model"),
            field_name="codex_model",
        ),
        codex_timeout_seconds=_coerce_positive_float(
            payload.get("codex_timeout_seconds"),
            field_name="codex_timeout_seconds",
        ),
        default_date_selection=_coerce_date_selection(payload.get("default_date_selection")),
    )


def _upgrade_persisted_config(
    payload: dict[str, Any],
    *,
    from_version: int,
) -> PersistedConfig:
    if from_version not in {0, 1}:
        raise ConfigError(f"unsupported configuration version: {from_version}")

    defaults = _default_persisted_config()
    upgraded_payload = {
        "config_version": CONFIG_VERSION,
        "analyzer_provider": payload.get("analyzer_provider", defaults.analyzer_provider),
        "openai_model": payload.get("openai_model", defaults.openai_model),
        "codex_model": payload.get("codex_model", defaults.codex_model),
        "codex_timeout_seconds": payload.get(
            "codex_timeout_seconds",
            defaults.codex_timeout_seconds,
        ),
        "default_date_selection": payload.get(
            "default_date_selection",
            defaults.default_date_selection.to_mapping(),
        ),
    }
    return _persisted_config_from_payload(upgraded_payload)


def _write_persisted_config(path: Path, config: PersistedConfig) -> None:
    payload = {
        "config_version": config.config_version,
        "analyzer_provider": config.analyzer_provider,
        "openai_model": config.openai_model,
        "codex_model": config.codex_model,
        "codex_timeout_seconds": config.codex_timeout_seconds,
        "default_date_selection": config.default_date_selection.to_mapping(),
    }
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _backup_config_file(path: Path, *, from_version: int, to_version: int) -> Path:
    backup_path = path.with_name(f"{path.name}.bak-v{from_version}-to-v{to_version}")
    counter = 1
    while backup_path.exists():
        backup_path = path.with_name(f"{path.name}.bak-v{from_version}-to-v{to_version}-{counter}")
        counter += 1
    shutil.copy2(path, backup_path)
    return backup_path


def _coerce_analyzer_provider(value: object) -> AnalyzerProvider:
    if not isinstance(value, str):
        raise ConfigError("analyzer_provider must be a string")
    normalized = value.strip().lower()
    if normalized == "codex":
        return "codex"
    if normalized == "openai":
        return "openai"
    raise ConfigError("analyzer_provider must be either 'codex' or 'openai'")


def _coerce_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty string")
    return value.strip()


def _coerce_optional_non_empty_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _coerce_non_empty_string(value, field_name=field_name)


def _coerce_positive_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field_name} must be numeric")
    number = float(value)
    if number <= 0:
        raise ConfigError(f"{field_name} must be positive")
    return number


def _coerce_date_selection(value: object) -> DateSelection:
    if value is None:
        return DateSelection.latest_available()
    if not isinstance(value, dict):
        raise ConfigError("default_date_selection must be an object")
    try:
        return DateSelection.from_mapping(value)
    except (ModelValidationError, ValueError) as exc:
        raise ConfigError("default_date_selection is invalid") from exc


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


def _load_analyzer_provider(default: AnalyzerProvider) -> AnalyzerProvider:
    value = os.environ.get("RESEARCH_DIGEST_ANALYZER")
    if value is None or not value.strip():
        return default
    try:
        return _coerce_analyzer_provider(value)
    except ConfigError as exc:
        raise ConfigError("RESEARCH_DIGEST_ANALYZER must be either 'codex' or 'openai'") from exc


def _load_codex_timeout(default: float) -> float:
    value = os.environ.get("RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS")
    if value is None or not value.strip():
        return default
    try:
        timeout = float(value)
    except ValueError as exc:
        raise ConfigError("RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS must be numeric") from exc
    if timeout <= 0:
        raise ConfigError("RESEARCH_DIGEST_CODEX_TIMEOUT_SECONDS must be positive")
    return timeout


def _load_string_override(env_name: str, *, default: str | None, optional: bool) -> str | None:
    value = os.environ.get(env_name)
    if value is None:
        return default
    if optional and not value.strip():
        raise ConfigError(f"{env_name} must be a non-empty string when set")
    if not optional and not value.strip():
        raise ConfigError(f"{env_name} must be a non-empty string")
    return value.strip()


def _load_required_string_override(env_name: str, *, default: str) -> str:
    value = _load_string_override(env_name, default=default, optional=False)
    if value is None:
        raise ConfigError(f"{env_name} must be a non-empty string")
    return value
