"""Safe bounded diagnostics for Research Digest."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from research_digest.config import (
    CONFIG_VERSION,
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_DB_FILENAME,
    ENV_DB_PATH,
    AppConfig,
    ConfigError,
    PersistedConfig,
    _default_persisted_config,
    _load_analyzer_provider,
    _load_codex_timeout,
    _load_required_string_override,
    _load_string_override,
    _persisted_config_from_payload,
    _read_config_version,
    _read_json_object,
    _validate_config_keys,
    resolve_config_dir,
    resolve_data_dir,
)
from research_digest.db import CURRENT_SCHEMA_VERSION, Database, MigrationError
from research_digest.errors import sanitize_error, sanitize_error_text
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    SchedulerBackend,
    scheduler_codex_path_warning,
    select_scheduler_backend,
)

ARXIV_HEALTH_URL = "https://export.arxiv.org/api/query?search_query=cat:hep-th&max_results=0"
MAX_NETWORK_TIMEOUT_SECONDS = 60.0


class DoctorSeverity(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    severity: DoctorSeverity
    message: str

    def to_mapping(self) -> dict[str, str]:
        return {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def failure_count(self) -> int:
        return sum(check.severity == DoctorSeverity.FAILURE for check in self.checks)

    @property
    def warning_count(self) -> int:
        return sum(check.severity == DoctorSeverity.WARNING for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 1 if self.failure_count else 0

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": "failed" if self.failure_count else "completed",
            "failure_count": self.failure_count,
            "warning_count": self.warning_count,
            "checks": [check.to_mapping() for check in self.checks],
        }


NetworkChecker = Callable[[str, float], None]


@dataclass(frozen=True)
class DoctorTarget:
    config: AppConfig
    db_path: Path
    setup_checks: tuple[DoctorCheck, ...]


class ReadOnlyDoctorDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get_schema_version(self) -> int:
        with self._connection() as conn:
            return _read_schema_version(conn)

    def get_app_runs(self) -> list[sqlite3.Row]:
        with self._connection() as conn:
            if not _table_exists(conn, "app_runs"):
                return []
            return list(
                conn.execute(
                    """
                    SELECT
                        id,
                        profile_id,
                        source_name,
                        started_at,
                        completed_at,
                        CASE status
                            WHEN 'running' THEN 'RUNNING'
                            WHEN 'success' THEN 'COMPLETED'
                            WHEN 'failed' THEN 'FAILED'
                            WHEN 'analysis_unavailable' THEN 'ANALYSIS_UNAVAILABLE'
                            ELSE status
                        END AS status,
                        retrieved_count,
                        stored_count,
                        preselected_count,
                        skipped_analysis_count,
                        analyzed_count,
                        relevant_count,
                        error_message
                    FROM app_runs
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchall()
            )

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn


def run_doctor(
    *,
    config: AppConfig,
    db: Database | ReadOnlyDoctorDatabase,
    scheduler_backend: SchedulerBackend | None = None,
    include_network: bool = False,
    network_timeout_seconds: float = 5.0,
    network_checker: NetworkChecker | None = None,
) -> DoctorReport:
    network_timeout_check = validate_network_timeout(network_timeout_seconds)
    effective_network_timeout = (
        network_timeout_seconds if network_timeout_check is None else MAX_NETWORK_TIMEOUT_SECONDS
    )
    effective_include_network = include_network and network_timeout_check is None
    checks = [
        _python_check(),
        _directory_check("data_directory", config.data_dir),
        _directory_check("config_directory", config.config_dir),
        _sqlite_check(config.db_path),
        _schema_check(db),
        _config_version_check(config),
        _provider_check(config),
        _scheduler_check(config, scheduler_backend),
        _last_run_check(db),
    ]
    if network_timeout_check is not None:
        checks.append(network_timeout_check)
    checks.append(
        _network_check(
            include_network=effective_include_network,
            timeout_seconds=effective_network_timeout,
            checker=network_checker or _default_network_checker,
        )
    )
    return DoctorReport(checks=tuple(checks))


def run_doctor_from_environment(
    *,
    scheduler_backend: SchedulerBackend | None = None,
    include_network: bool = False,
    network_timeout_seconds: float = 5.0,
    network_checker: NetworkChecker | None = None,
) -> DoctorReport:
    target = inspect_doctor_target()
    db = ReadOnlyDoctorDatabase(target.db_path)
    report = run_doctor(
        config=target.config,
        db=db,
        scheduler_backend=scheduler_backend,
        include_network=include_network,
        network_timeout_seconds=network_timeout_seconds,
        network_checker=network_checker,
    )
    return DoctorReport(checks=(*target.setup_checks, *report.checks))


def validate_network_timeout(value: float) -> DoctorCheck | None:
    if not isinstance(value, (int, float)) or value <= 0 or value != value:
        return DoctorCheck(
            "network_timeout",
            DoctorSeverity.FAILURE,
            "Network timeout must be a positive finite number.",
        )
    if value == float("inf") or value > MAX_NETWORK_TIMEOUT_SECONDS:
        return DoctorCheck(
            "network_timeout",
            DoctorSeverity.FAILURE,
            f"Network timeout must be at most {MAX_NETWORK_TIMEOUT_SECONDS:g} seconds.",
        )
    return None


def inspect_doctor_target() -> DoctorTarget:
    data_dir = resolve_data_dir()
    config_dir = resolve_config_dir()
    db_path = _resolve_db_path_read_only(data_dir)
    persisted_config, config_check = _read_config_read_only(config_dir)
    api_key = os.environ.get("OPENAI_API_KEY")
    setup_checks = [config_check]
    try:
        config = AppConfig(
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
        )
    except ConfigError as exc:
        defaults = _default_persisted_config()
        config = AppConfig(
            db_path=db_path,
            data_dir=data_dir,
            config_dir=config_dir,
            analyzer_provider=defaults.analyzer_provider,
            openai_api_key=api_key if api_key else None,
            openai_model=defaults.openai_model,
            codex_model=defaults.codex_model,
            codex_timeout_seconds=defaults.codex_timeout_seconds,
            config_version=defaults.config_version,
            config_path=config_dir / DEFAULT_CONFIG_FILENAME,
        )
        setup_checks.append(
            DoctorCheck("environment_config", DoctorSeverity.FAILURE, sanitize_error(exc))
        )
    return DoctorTarget(config=config, db_path=db_path, setup_checks=tuple(setup_checks))


def _python_check() -> DoctorCheck:
    version = sys.version_info
    if version < (3, 11):
        return DoctorCheck(
            "python",
            DoctorSeverity.FAILURE,
            f"Python {version.major}.{version.minor} is unsupported; Python 3.11+ is required.",
        )
    return DoctorCheck(
        "python",
        DoctorSeverity.PASS,
        f"Python {version.major}.{version.minor}.{version.micro} is supported.",
    )


def _directory_check(name: str, path: Path) -> DoctorCheck:
    if not path.exists():
        return DoctorCheck(name, DoctorSeverity.WARNING, f"{path} does not exist yet.")
    if not path.is_dir():
        return DoctorCheck(name, DoctorSeverity.FAILURE, f"{path} is not a directory.")
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        return DoctorCheck(name, DoctorSeverity.FAILURE, f"{path} is not readable and writable.")
    return DoctorCheck(name, DoctorSeverity.PASS, f"{path} is readable and writable.")


def _sqlite_check(path: Path) -> DoctorCheck:
    if not path.exists():
        return DoctorCheck("sqlite", DoctorSeverity.WARNING, f"{path} does not exist yet.")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        return DoctorCheck("sqlite", DoctorSeverity.FAILURE, sanitize_error(exc))
    if row is None or row[0] != "ok":
        return DoctorCheck("sqlite", DoctorSeverity.FAILURE, "SQLite integrity check failed.")
    return DoctorCheck("sqlite", DoctorSeverity.PASS, "SQLite database is readable and valid.")


def _schema_check(db: Database | ReadOnlyDoctorDatabase) -> DoctorCheck:
    if isinstance(db, ReadOnlyDoctorDatabase) and not db.path.exists():
        return DoctorCheck("schema_version", DoctorSeverity.WARNING, "Database does not exist yet.")
    try:
        version = db.get_schema_version()
    except Exception as exc:
        return DoctorCheck("schema_version", DoctorSeverity.FAILURE, sanitize_error(exc))
    if version != CURRENT_SCHEMA_VERSION:
        return DoctorCheck(
            "schema_version",
            DoctorSeverity.FAILURE,
            f"schema version {version} is not supported by this release.",
        )
    return DoctorCheck("schema_version", DoctorSeverity.PASS, f"schema version {version}.")


def _config_version_check(config: AppConfig) -> DoctorCheck:
    if config.config_version != CONFIG_VERSION:
        return DoctorCheck(
            "config_version",
            DoctorSeverity.FAILURE,
            f"config version {config.config_version} is not supported by this release.",
        )
    return DoctorCheck("config_version", DoctorSeverity.PASS, f"config version {CONFIG_VERSION}.")


def _provider_check(config: AppConfig) -> DoctorCheck:
    if config.analyzer_provider == "codex":
        if shutil.which("codex") is None:
            return DoctorCheck(
                "provider",
                DoctorSeverity.FAILURE,
                "Codex analyzer is configured, but the `codex` executable is not on PATH.",
            )
        return DoctorCheck("provider", DoctorSeverity.PASS, "Codex analyzer is configured.")
    if config.analyzer_provider == "openai":
        if config.openai_api_key is None:
            return DoctorCheck(
                "provider",
                DoctorSeverity.FAILURE,
                "OpenAI analyzer is configured, but OPENAI_API_KEY is not set.",
            )
        return DoctorCheck("provider", DoctorSeverity.PASS, "OpenAI analyzer is configured.")
    return DoctorCheck("provider", DoctorSeverity.FAILURE, "Analyzer provider is unsupported.")


def _scheduler_check(config: AppConfig, scheduler_backend: SchedulerBackend | None) -> DoctorCheck:
    try:
        backend = scheduler_backend or select_scheduler_backend()
        status = backend.status(task_name=DEFAULT_TASK_NAME)
    except Exception as exc:
        return DoctorCheck("scheduler", DoctorSeverity.WARNING, sanitize_error(exc))
    if status.installed:
        codex_warning = scheduler_codex_path_warning(config, status)
        if codex_warning is not None:
            return DoctorCheck("scheduler", DoctorSeverity.WARNING, codex_warning)
        return DoctorCheck("scheduler", DoctorSeverity.PASS, "Schedule is installed.")
    return DoctorCheck(
        "scheduler",
        DoctorSeverity.WARNING,
        sanitize_error_text(status.message or "Schedule is not installed."),
    )


def _last_run_check(db: Database | ReadOnlyDoctorDatabase) -> DoctorCheck:
    try:
        runs = db.get_app_runs()
    except Exception as exc:
        return DoctorCheck("last_run", DoctorSeverity.WARNING, sanitize_error(exc))
    if not runs:
        return DoctorCheck("last_run", DoctorSeverity.WARNING, "No digest runs have been recorded.")
    latest = runs[0]
    status = str(latest["status"])
    if status == "FAILED":
        return DoctorCheck("last_run", DoctorSeverity.FAILURE, "Last digest run failed.")
    if status in {"STARTING", "RUNNING"}:
        return DoctorCheck("last_run", DoctorSeverity.WARNING, f"Last digest run is {status}.")
    return DoctorCheck("last_run", DoctorSeverity.PASS, f"Last digest run is {status}.")


def _network_check(
    *,
    include_network: bool,
    timeout_seconds: float,
    checker: NetworkChecker,
) -> DoctorCheck:
    if not include_network:
        return DoctorCheck("network", DoctorSeverity.WARNING, "Network checks skipped.")
    try:
        checker(ARXIV_HEALTH_URL, timeout_seconds)
    except Exception as exc:
        return DoctorCheck("network", DoctorSeverity.WARNING, sanitize_error(exc))
    return DoctorCheck("network", DoctorSeverity.PASS, "arXiv network check succeeded.")


def _resolve_db_path_read_only(data_dir: Path) -> Path:
    explicit = os.environ.get(ENV_DB_PATH)
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    return data_dir / DEFAULT_DB_FILENAME


def _read_config_read_only(config_dir: Path) -> tuple[PersistedConfig, DoctorCheck]:
    config_path = config_dir / DEFAULT_CONFIG_FILENAME
    if not config_path.exists():
        return (
            _default_persisted_config(),
            DoctorCheck(
                "config_file",
                DoctorSeverity.WARNING,
                f"{config_path} does not exist yet.",
            ),
        )
    try:
        payload = _read_json_object(config_path)
        _validate_config_keys(payload)
        version = _read_config_version(payload)
        if version > CONFIG_VERSION:
            return (
                _default_persisted_config(),
                DoctorCheck(
                    "config_file",
                    DoctorSeverity.FAILURE,
                    "configuration version "
                    f"{version} is newer than supported version {CONFIG_VERSION}",
                ),
            )
        if version < CONFIG_VERSION:
            return (
                _default_persisted_config(),
                DoctorCheck(
                    "config_file",
                    DoctorSeverity.FAILURE,
                    f"configuration version {version} requires upgrade before use.",
                ),
            )
        return (
            _persisted_config_from_payload(payload),
            DoctorCheck("config_file", DoctorSeverity.PASS, f"{config_path} is readable."),
        )
    except Exception as exc:
        return (
            _default_persisted_config(),
            DoctorCheck("config_file", DoctorSeverity.FAILURE, sanitize_error(exc)),
        )


def _read_schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_metadata"):
        return 0
    row = conn.execute(
        "SELECT value FROM schema_metadata WHERE key = 'schema_version'",
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError) as exc:
        raise MigrationError("database schema version metadata is invalid") from exc


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _default_network_checker(url: str, timeout_seconds: float) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "research-digest/doctor"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds):
            return
    except urllib.error.URLError as exc:
        raise RuntimeError(f"network check failed: {exc.reason}") from exc
