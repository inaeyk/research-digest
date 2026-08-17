"""User data backup and export helpers."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from research_digest.config import DEFAULT_DB_FILENAME, ENV_DB_PATH, resolve_data_dir
from research_digest.db import CURRENT_SCHEMA_VERSION
from research_digest.errors import sanitize_error, sanitize_error_text

DEFAULT_BACKUP_DIRNAME = "backups"


class BackupError(RuntimeError):
    """Raised when a user data backup or export cannot complete safely."""


@dataclass(frozen=True)
class BackupResult:
    db_path: Path
    backup_path: Path
    export_path: Path | None
    schema_version: int

    def to_mapping(self) -> dict[str, object]:
        return {
            "status": "completed",
            "data_path": str(self.db_path),
            "backup_path": str(self.backup_path),
            "export_path": str(self.export_path) if self.export_path is not None else None,
            "schema_version": self.schema_version,
        }


def run_backup(
    *,
    output_path: Path | None = None,
    export_json: bool = False,
    timestamp: datetime | None = None,
) -> BackupResult:
    db_path = resolve_active_db_path_read_only()
    schema_version = _validate_source_database(db_path)
    backup_path = _resolve_backup_path(
        db_path=db_path,
        output_path=output_path,
        timestamp=timestamp or datetime.now(UTC),
    )
    export_path = backup_path.with_suffix(".export.json") if export_json else None
    if export_path is not None and export_path.exists():
        raise BackupError(f"export path already exists: {export_path}")
    _backup_sqlite_database(source_path=db_path, destination_path=backup_path)
    if export_path is not None:
        _write_json_export(db_path=db_path, export_path=export_path, schema_version=schema_version)
    return BackupResult(
        db_path=db_path,
        backup_path=backup_path,
        export_path=export_path,
        schema_version=schema_version,
    )


def resolve_active_db_path_read_only() -> Path:
    explicit = os.environ.get(ENV_DB_PATH)
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    return resolve_data_dir() / DEFAULT_DB_FILENAME


def _validate_source_database(db_path: Path) -> int:
    if not db_path.exists():
        raise BackupError(f"database does not exist: {db_path}")
    if not db_path.is_file():
        raise BackupError(f"database path is not a file: {db_path}")
    try:
        with _read_only_connection(db_path) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row is None or row[0] != "ok":
                raise BackupError("SQLite integrity check failed.")
            schema_version = _read_schema_version(conn)
    except BackupError:
        raise
    except sqlite3.Error as exc:
        raise BackupError(sanitize_error(exc)) from exc
    if schema_version != CURRENT_SCHEMA_VERSION:
        raise BackupError(
            f"schema version {schema_version} is not supported by this release."
        )
    return schema_version


def _resolve_backup_path(
    *,
    db_path: Path,
    output_path: Path | None,
    timestamp: datetime,
) -> Path:
    if output_path is None:
        directory = db_path.parent / DEFAULT_BACKUP_DIRNAME
        filename = "research_digest-" + timestamp.strftime("%Y%m%dT%H%M%SZ") + ".sqlite3"
        return _unique_path(directory / filename)
    candidate = output_path.expanduser().resolve()
    if candidate.suffix:
        if candidate.exists():
            raise BackupError(f"backup path already exists: {candidate}")
        return candidate
    filename = "research_digest-" + timestamp.strftime("%Y%m%dT%H%M%SZ") + ".sqlite3"
    return _unique_path(candidate / filename)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _backup_sqlite_database(*, source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(destination_path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with _read_only_connection(source_path) as source, sqlite3.connect(
            temporary
        ) as destination:
            source.backup(destination)
            destination.commit()
        with sqlite3.connect(temporary) as check:
            row = check.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise BackupError("backup integrity check failed.")
        os.replace(temporary, destination_path)
    except Exception as exc:
        if temporary.exists():
            temporary.unlink()
        if isinstance(exc, BackupError):
            raise
        raise BackupError(sanitize_error(exc)) from exc


def _write_json_export(*, db_path: Path, export_path: Path, schema_version: int) -> None:
    if export_path.exists():
        raise BackupError(f"export path already exists: {export_path}")
    payload = export_user_data(db_path=db_path, schema_version=schema_version)
    temporary = export_path.with_name(export_path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, export_path)
    except Exception as exc:
        if temporary.exists():
            temporary.unlink()
        raise BackupError(sanitize_error(exc)) from exc


def export_user_data(*, db_path: Path, schema_version: int | None = None) -> dict[str, object]:
    with _read_only_connection(db_path) as conn:
        version = schema_version if schema_version is not None else _read_schema_version(conn)
        return {
            "export_version": 1,
            "schema_version": version,
            "profiles": _profiles(conn),
            "source_settings": _source_settings(conn),
            "feedback": _feedback(conn),
            "runs": _runs(conn),
            "run_snapshots": _run_snapshots(conn),
            "source_date_coverage": _source_date_coverage(conn),
            "library_articles": _library_articles(conn),
        }


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = path.expanduser().resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


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
        raise BackupError("database schema version metadata is invalid") from exc


def _profiles(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "interest_profiles"):
        return []
    rows = conn.execute(
        """
        SELECT id, name, description, relevance_threshold, enabled
        FROM interest_profiles
        ORDER BY id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
            "relevance_threshold": float(row["relevance_threshold"]),
            "enabled": bool(row["enabled"]),
        }
        for row in rows
    ]


def _source_settings(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "source_configs"):
        return []
    rows = conn.execute(
        """
        SELECT source_name, enabled, categories_json, lookback_hours, max_results
        FROM source_configs
        ORDER BY source_name
        """
    ).fetchall()
    return [
        {
            "source_name": str(row["source_name"]),
            "enabled": bool(row["enabled"]),
            "categories": _json_list(row["categories_json"]),
            "lookback_hours": int(row["lookback_hours"]),
            "max_results": int(row["max_results"]),
        }
        for row in rows
    ]


def _feedback(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "article_feedback"):
        return []
    rows = conn.execute(
        """
        SELECT
            feedback.id,
            feedback.article_id,
            feedback.profile_id,
            feedback.profile_fingerprint,
            feedback.feedback_label,
            feedback.created_at,
            feedback.updated_at,
            articles.source,
            articles.source_article_id,
            articles.title
        FROM article_feedback AS feedback
        LEFT JOIN articles ON articles.id = feedback.article_id
        ORDER BY feedback.id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "article_id": int(row["article_id"]),
            "profile_id": int(row["profile_id"]),
            "profile_fingerprint": str(row["profile_fingerprint"]),
            "feedback_label": str(row["feedback_label"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "article": {
                "source": str(row["source"]) if row["source"] is not None else None,
                "source_article_id": (
                    str(row["source_article_id"])
                    if row["source_article_id"] is not None
                    else None
                ),
                "title": str(row["title"]) if row["title"] is not None else None,
            },
        }
        for row in rows
    ]


def _runs(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "app_runs"):
        return []
    rows = conn.execute(
        """
        SELECT
            id,
            profile_id,
            source_name,
            started_at,
            completed_at,
            status,
            retrieved_count,
            stored_count,
            preselected_count,
            skipped_analysis_count,
            analyzed_count,
            relevant_count,
            error_message,
            run_origin,
            date_selection_json,
            requested_source_dates_json,
            covered_source_dates_json,
            empty_source_dates_json,
            incomplete_source_dates_json,
            retrieval_complete,
            retrieval_safety_limit
        FROM app_runs
        ORDER BY id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "profile_id": int(row["profile_id"]) if row["profile_id"] is not None else None,
            "source_name": str(row["source_name"]),
            "started_at": str(row["started_at"]),
            "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
            "status": str(row["status"]),
            "retrieved_count": int(row["retrieved_count"]),
            "stored_count": int(row["stored_count"]),
            "preselected_count": int(row["preselected_count"]),
            "skipped_analysis_count": int(row["skipped_analysis_count"]),
            "analyzed_count": int(row["analyzed_count"]),
            "relevant_count": int(row["relevant_count"]),
            "error_message": (
                sanitize_error_text(str(row["error_message"]))
                if row["error_message"] is not None
                else None
            ),
            "run_origin": str(row["run_origin"]),
            "date_selection": _json_object_or_none(row["date_selection_json"]),
            "requested_source_dates": _json_list(row["requested_source_dates_json"]),
            "covered_source_dates": _json_list(row["covered_source_dates_json"]),
            "empty_source_dates": _json_list(row["empty_source_dates_json"]),
            "incomplete_source_dates": _json_list(row["incomplete_source_dates_json"]),
            "retrieval_complete": bool(row["retrieval_complete"]),
            "retrieval_safety_limit": (
                int(row["retrieval_safety_limit"])
                if row["retrieval_safety_limit"] is not None
                else None
            ),
        }
        for row in rows
    ]


def _run_snapshots(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "run_snapshots"):
        return []
    rows = conn.execute(
        """
        SELECT run_id, snapshot_json, created_at
        FROM run_snapshots
        ORDER BY run_id
        """
    ).fetchall()
    snapshots: list[dict[str, object]] = []
    for row in rows:
        payload = json.loads(str(row["snapshot_json"]))
        if not isinstance(payload, dict):
            raise BackupError("run snapshot export payload must be a JSON object")
        snapshots.append(
            {
                "run_id": int(row["run_id"]),
                "created_at": str(row["created_at"]),
                "snapshot": payload,
            }
        )
    return snapshots


def _source_date_coverage(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "source_date_coverage"):
        return []
    rows = conn.execute(
        """
        SELECT
            id,
            profile_id,
            profile_fingerprint,
            source_name,
            source_fingerprint,
            source_date,
            status,
            first_covered_run_id,
            last_covered_run_id,
            run_origin,
            covered_at,
            updated_at
        FROM source_date_coverage
        ORDER BY source_date, profile_id, id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "profile_id": int(row["profile_id"]),
            "profile_fingerprint": str(row["profile_fingerprint"]),
            "source_name": str(row["source_name"]),
            "source_fingerprint": str(row["source_fingerprint"]),
            "source_date": str(row["source_date"]),
            "status": str(row["status"]),
            "first_covered_run_id": int(row["first_covered_run_id"]),
            "last_covered_run_id": int(row["last_covered_run_id"]),
            "run_origin": str(row["run_origin"]),
            "covered_at": str(row["covered_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def _library_articles(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_articles"):
        return []
    rows = conn.execute(
        """
        SELECT
            library_articles.article_id,
            library_articles.saved,
            library_articles.saved_at,
            library_articles.updated_at,
            articles.source,
            articles.source_article_id,
            articles.title
        FROM library_articles
        LEFT JOIN articles ON articles.id = library_articles.article_id
        ORDER BY library_articles.article_id
        """
    ).fetchall()
    return [
        {
            "article_id": int(row["article_id"]),
            "saved": bool(row["saved"]),
            "saved_at": str(row["saved_at"]),
            "updated_at": str(row["updated_at"]),
            "article": {
                "source": str(row["source"]) if row["source"] is not None else None,
                "source_article_id": (
                    str(row["source_article_id"])
                    if row["source_article_id"] is not None
                    else None
                ),
                "title": str(row["title"]) if row["title"] is not None else None,
            },
        }
        for row in rows
    ]


def _json_list(value: object) -> list[object]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise BackupError("expected JSON list in source settings")
    return parsed


def _json_object_or_none(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise BackupError("expected JSON object in run metadata")
    return parsed


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None
