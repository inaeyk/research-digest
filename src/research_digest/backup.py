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
            "library_tags": _library_tags(conn),
            "library_tag_assignments": _library_tag_assignments(conn),
            "library_ai_tag_suppressions": _library_ai_tag_suppressions(conn),
            "library_article_notes": _library_article_notes(conn),
            "library_collections": _library_collections(conn),
            "library_collection_memberships": _library_collection_memberships(conn),
            "library_article_connections": _library_article_connections(conn),
            "library_context_suggestions": _library_context_suggestions(conn),
            "collection_intelligence_snapshots": _collection_intelligence_snapshots(conn),
            "suggested_interest_profiles": _suggested_interest_profiles(conn),
            "quantitative_relevance_calibrations": _quantitative_relevance_calibrations(conn),
            "preselection_decisions": _preselection_decisions(conn),
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
            feedback.profile_match,
            feedback.personal_interest,
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
            "feedback_label": (
                str(row["feedback_label"]) if row["feedback_label"] is not None else None
            ),
            "profile_match": (
                str(row["profile_match"]) if row["profile_match"] is not None else None
            ),
            "personal_interest": (
                str(row["personal_interest"])
                if row["personal_interest"] is not None
                else None
            ),
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
            retrieval_safety_limit,
            progress_stage,
            progress_message
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
            "progress_stage": (
                str(row["progress_stage"]) if row["progress_stage"] is not None else None
            ),
            "progress_message": (
                str(row["progress_message"]) if row["progress_message"] is not None else None
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


def _preselection_decisions(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "preselection_decisions"):
        return []
    rows = conn.execute(
        """
        SELECT
            decisions.id,
            decisions.run_id,
            decisions.article_id,
            decisions.profile_id,
            decisions.profile_fingerprint,
            decisions.source_name,
            decisions.source_fingerprint,
            decisions.preselection_score,
            decisions.preselection_threshold,
            decisions.passed,
            decisions.stage,
            decisions.decision_origin,
            decisions.preselector_version,
            decisions.reason,
            decisions.created_at,
            articles.source AS article_source,
            articles.source_article_id AS article_source_article_id,
            articles.title AS article_title
        FROM preselection_decisions AS decisions
        LEFT JOIN articles ON articles.id = decisions.article_id
        ORDER BY decisions.run_id ASC, decisions.id ASC
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "run_id": int(row["run_id"]),
            "article_id": int(row["article_id"]),
            "profile_id": int(row["profile_id"]),
            "profile_fingerprint": str(row["profile_fingerprint"]),
            "source_name": str(row["source_name"]),
            "source_fingerprint": (
                str(row["source_fingerprint"])
                if row["source_fingerprint"] is not None
                else None
            ),
            "preselection_score": (
                float(row["preselection_score"])
                if row["preselection_score"] is not None
                else None
            ),
            "preselection_threshold": (
                float(row["preselection_threshold"])
                if row["preselection_threshold"] is not None
                else None
            ),
            "passed": bool(row["passed"]),
            "stage": str(row["stage"]),
            "decision_origin": str(row["decision_origin"]),
            "preselector_version": str(row["preselector_version"]),
            "reason": str(row["reason"]) if row["reason"] is not None else None,
            "created_at": str(row["created_at"]),
            "article": {
                "source": str(row["article_source"]) if row["article_source"] else None,
                "source_article_id": (
                    str(row["article_source_article_id"])
                    if row["article_source_article_id"]
                    else None
                ),
                "title": str(row["article_title"]) if row["article_title"] else None,
            },
        }
        for row in rows
    ]


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


def _library_tags(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_tags"):
        return []
    rows = conn.execute(
        """
        SELECT id, normalized_name, display_name, created_at, updated_at
        FROM library_tags
        ORDER BY id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "normalized_name": str(row["normalized_name"]),
            "display_name": str(row["display_name"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def _library_tag_assignments(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_tag_assignments"):
        return []
    rows = conn.execute(
        """
        SELECT
            assignments.id,
            assignments.article_id,
            assignments.origin,
            assignments.ai_provenance_json,
            assignments.created_at,
            assignments.updated_at,
            tags.normalized_name,
            tags.display_name,
            articles.source,
            articles.source_article_id,
            articles.title
        FROM library_tag_assignments AS assignments
        JOIN library_tags AS tags ON tags.id = assignments.tag_id
        LEFT JOIN articles ON articles.id = assignments.article_id
        ORDER BY assignments.id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "article_id": int(row["article_id"]),
            "origin": str(row["origin"]),
            "ai_provenance": _json_object_or_none(row["ai_provenance_json"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "tag": {
                "normalized_name": str(row["normalized_name"]),
                "display_name": str(row["display_name"]),
            },
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


def _library_ai_tag_suppressions(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_ai_tag_suppressions"):
        return []
    rows = conn.execute(
        """
        SELECT
            suppressions.article_id,
            suppressions.suppressed_at,
            suppressions.reason,
            tags.normalized_name,
            tags.display_name,
            articles.source,
            articles.source_article_id,
            articles.title
        FROM library_ai_tag_suppressions AS suppressions
        JOIN library_tags AS tags ON tags.id = suppressions.tag_id
        LEFT JOIN articles ON articles.id = suppressions.article_id
        ORDER BY suppressions.article_id, tags.normalized_name
        """
    ).fetchall()
    return [
        {
            "article_id": int(row["article_id"]),
            "suppressed_at": str(row["suppressed_at"]),
            "reason": str(row["reason"]),
            "tag": {
                "normalized_name": str(row["normalized_name"]),
                "display_name": str(row["display_name"]),
            },
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


def _library_article_notes(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_article_notes"):
        return []
    rows = conn.execute(
        """
        SELECT
            notes.article_id,
            notes.note_text,
            notes.created_at,
            notes.updated_at,
            articles.source,
            articles.source_article_id,
            articles.title
        FROM library_article_notes AS notes
        LEFT JOIN articles ON articles.id = notes.article_id
        ORDER BY notes.article_id
        """
    ).fetchall()
    return [
        {
            "article_id": int(row["article_id"]),
            "note_text": str(row["note_text"]),
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


def _library_collections(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_collections"):
        return []
    rows = conn.execute(
        """
        SELECT id, name, normalized_name, description, created_at, updated_at
        FROM library_collections
        ORDER BY id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "normalized_name": str(row["normalized_name"]),
            "description": str(row["description"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def _library_collection_memberships(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_collection_memberships"):
        return []
    rows = conn.execute(
        """
        SELECT
            memberships.collection_id,
            memberships.article_id,
            memberships.added_at,
            collections.name AS collection_name,
            collections.normalized_name AS collection_normalized_name,
            articles.source,
            articles.source_article_id,
            articles.title
        FROM library_collection_memberships AS memberships
        JOIN library_collections AS collections ON collections.id = memberships.collection_id
        LEFT JOIN articles ON articles.id = memberships.article_id
        ORDER BY memberships.collection_id, memberships.article_id
        """
    ).fetchall()
    return [
        {
            "collection_id": int(row["collection_id"]),
            "article_id": int(row["article_id"]),
            "added_at": str(row["added_at"]),
            "collection": {
                "name": str(row["collection_name"]),
                "normalized_name": str(row["collection_normalized_name"]),
            },
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


def _library_article_connections(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_article_connections"):
        return []
    rows = conn.execute(
        """
        SELECT
            connections.id,
            connections.article_id_a,
            connections.article_id_b,
            connections.relation_label,
            connections.rationale,
            connections.origin,
            connections.provenance_json,
            connections.confidence,
            connections.generated_at,
            connections.dismissed_at,
            article_a.source AS source_a,
            article_a.source_article_id AS source_article_id_a,
            article_a.title AS title_a,
            article_b.source AS source_b,
            article_b.source_article_id AS source_article_id_b,
            article_b.title AS title_b
        FROM library_article_connections AS connections
        LEFT JOIN articles AS article_a ON article_a.id = connections.article_id_a
        LEFT JOIN articles AS article_b ON article_b.id = connections.article_id_b
        ORDER BY connections.article_id_a, connections.article_id_b
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "article_id_a": int(row["article_id_a"]),
            "article_id_b": int(row["article_id_b"]),
            "relation_label": str(row["relation_label"]),
            "rationale": str(row["rationale"]),
            "origin": str(row["origin"]),
            "provenance": json.loads(str(row["provenance_json"])),
            "confidence": (
                float(row["confidence"]) if row["confidence"] is not None else None
            ),
            "generated_at": str(row["generated_at"]),
            "dismissed_at": (
                str(row["dismissed_at"]) if row["dismissed_at"] is not None else None
            ),
            "article_a": {
                "source": str(row["source_a"]) if row["source_a"] is not None else None,
                "source_article_id": (
                    str(row["source_article_id_a"])
                    if row["source_article_id_a"] is not None
                    else None
                ),
                "title": str(row["title_a"]) if row["title_a"] is not None else None,
            },
            "article_b": {
                "source": str(row["source_b"]) if row["source_b"] is not None else None,
                "source_article_id": (
                    str(row["source_article_id_b"])
                    if row["source_article_id_b"] is not None
                    else None
                ),
                "title": str(row["title_b"]) if row["title_b"] is not None else None,
            },
        }
        for row in rows
    ]


def _library_context_suggestions(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "library_context_suggestions"):
        return []
    rows = conn.execute(
        """
        SELECT
            suggestions.id,
            suggestions.run_id,
            suggestions.article_id,
            suggestions.related_article_id,
            suggestions.collection_id,
            suggestions.relation_label,
            suggestions.rationale,
            suggestions.origin,
            suggestions.provenance_json,
            suggestions.confidence,
            suggestions.created_at,
            suggestions.dismissed_at,
            article.source AS article_source,
            article.source_article_id AS article_source_article_id,
            article.title AS article_title,
            related.source AS related_source,
            related.source_article_id AS related_source_article_id,
            related.title AS related_title,
            collections.name AS collection_name
        FROM library_context_suggestions AS suggestions
        LEFT JOIN articles AS article ON article.id = suggestions.article_id
        LEFT JOIN articles AS related ON related.id = suggestions.related_article_id
        LEFT JOIN library_collections AS collections ON collections.id = suggestions.collection_id
        ORDER BY suggestions.article_id, suggestions.related_article_id, suggestions.id
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
            "article_id": int(row["article_id"]),
            "related_article_id": int(row["related_article_id"]),
            "collection_id": (
                int(row["collection_id"]) if row["collection_id"] is not None else None
            ),
            "relation_label": str(row["relation_label"]),
            "rationale": str(row["rationale"]),
            "origin": str(row["origin"]),
            "provenance": json.loads(str(row["provenance_json"])),
            "confidence": (
                float(row["confidence"]) if row["confidence"] is not None else None
            ),
            "created_at": str(row["created_at"]),
            "dismissed_at": (
                str(row["dismissed_at"]) if row["dismissed_at"] is not None else None
            ),
            "article": {
                "source": str(row["article_source"]) if row["article_source"] is not None else None,
                "source_article_id": (
                    str(row["article_source_article_id"])
                    if row["article_source_article_id"] is not None
                    else None
                ),
                "title": str(row["article_title"]) if row["article_title"] is not None else None,
            },
            "related_article": {
                "source": str(row["related_source"]) if row["related_source"] is not None else None,
                "source_article_id": (
                    str(row["related_source_article_id"])
                    if row["related_source_article_id"] is not None
                    else None
                ),
                "title": str(row["related_title"]) if row["related_title"] is not None else None,
            },
            "collection": {
                "name": str(row["collection_name"]) if row["collection_name"] is not None else None,
            },
        }
        for row in rows
    ]


def _collection_intelligence_snapshots(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "collection_intelligence_snapshots"):
        return []
    rows = conn.execute(
        """
        SELECT
            snapshots.id,
            snapshots.collection_id,
            snapshots.title,
            snapshots.summary,
            snapshots.evidence_json,
            snapshots.origin,
            snapshots.provenance_json,
            snapshots.generated_at,
            snapshots.dismissed_at,
            collections.name AS collection_name
        FROM collection_intelligence_snapshots AS snapshots
        LEFT JOIN library_collections AS collections ON collections.id = snapshots.collection_id
        ORDER BY snapshots.collection_id, snapshots.generated_at DESC, snapshots.id DESC
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "collection_id": int(row["collection_id"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "evidence": json.loads(str(row["evidence_json"])),
            "origin": str(row["origin"]),
            "provenance": json.loads(str(row["provenance_json"])),
            "generated_at": str(row["generated_at"]),
            "dismissed_at": (
                str(row["dismissed_at"]) if row["dismissed_at"] is not None else None
            ),
            "collection": {
                "name": str(row["collection_name"]) if row["collection_name"] is not None else None,
            },
        }
        for row in rows
    ]


def _quantitative_relevance_calibrations(
    conn: sqlite3.Connection,
) -> list[dict[str, object]]:
    if not _table_exists(conn, "quantitative_relevance_calibrations"):
        return []
    rows = conn.execute(
        """
        SELECT
            calibrations.id,
            calibrations.run_id,
            calibrations.article_id,
            calibrations.profile_id,
            calibrations.profile_fingerprint,
            calibrations.model_relevance_score,
            calibrations.state,
            calibrations.user_relevance_score,
            calibrations.created_at,
            calibrations.completed_at,
            articles.source AS article_source,
            articles.source_article_id AS article_source_article_id,
            articles.title AS article_title
        FROM quantitative_relevance_calibrations AS calibrations
        LEFT JOIN articles ON articles.id = calibrations.article_id
        ORDER BY calibrations.created_at DESC, calibrations.id DESC
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "run_id": int(row["run_id"]),
            "article_id": int(row["article_id"]) if row["article_id"] is not None else None,
            "profile_id": int(row["profile_id"]),
            "profile_fingerprint": str(row["profile_fingerprint"]),
            "model_relevance_score": (
                float(row["model_relevance_score"])
                if row["model_relevance_score"] is not None
                else None
            ),
            "state": str(row["state"]),
            "user_relevance_score": (
                float(row["user_relevance_score"])
                if row["user_relevance_score"] is not None
                else None
            ),
            "created_at": str(row["created_at"]),
            "completed_at": (
                str(row["completed_at"]) if row["completed_at"] is not None else None
            ),
            "article": {
                "source": str(row["article_source"]) if row["article_source"] is not None else None,
                "source_article_id": (
                    str(row["article_source_article_id"])
                    if row["article_source_article_id"] is not None
                    else None
                ),
                "title": str(row["article_title"]) if row["article_title"] is not None else None,
            },
        }
        for row in rows
    ]


def _suggested_interest_profiles(conn: sqlite3.Connection) -> list[dict[str, object]]:
    if not _table_exists(conn, "suggested_interest_profiles"):
        return []
    rows = conn.execute(
        """
        SELECT
            suggestions.id,
            suggestions.profile_id,
            suggestions.profile_fingerprint,
            suggestions.suggested_name,
            suggestions.suggested_description,
            suggestions.evidence_article_ids_json,
            suggestions.explanation,
            suggestions.suggestion_key,
            suggestions.provenance_json,
            suggestions.created_at,
            suggestions.dismissed_at,
            suggestions.accepted_profile_id,
            profiles.name AS profile_name,
            accepted.name AS accepted_profile_name
        FROM suggested_interest_profiles AS suggestions
        LEFT JOIN interest_profiles AS profiles ON profiles.id = suggestions.profile_id
        LEFT JOIN interest_profiles AS accepted ON accepted.id = suggestions.accepted_profile_id
        ORDER BY suggestions.profile_id, suggestions.created_at DESC, suggestions.id DESC
        """
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "profile_id": int(row["profile_id"]),
            "profile_fingerprint": str(row["profile_fingerprint"]),
            "suggested_name": str(row["suggested_name"]),
            "suggested_description": str(row["suggested_description"]),
            "evidence_article_ids": _json_list(row["evidence_article_ids_json"]),
            "explanation": str(row["explanation"]),
            "suggestion_key": str(row["suggestion_key"]),
            "provenance": json.loads(str(row["provenance_json"])),
            "created_at": str(row["created_at"]),
            "dismissed_at": (
                str(row["dismissed_at"]) if row["dismissed_at"] is not None else None
            ),
            "accepted_profile_id": (
                int(row["accepted_profile_id"])
                if row["accepted_profile_id"] is not None
                else None
            ),
            "profile": {
                "name": str(row["profile_name"]) if row["profile_name"] is not None else None,
            },
            "accepted_profile": {
                "name": (
                    str(row["accepted_profile_name"])
                    if row["accepted_profile_name"] is not None
                    else None
                ),
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
