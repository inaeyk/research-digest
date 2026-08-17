"""SQLite persistence for Research Digest."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from research_digest.errors import sanitize_error_text
from research_digest.models import (
    AITagSuppression,
    AnalysisResult,
    Article,
    ArticleFeedback,
    ArxivSourceConfig,
    DateSelection,
    FeedbackLabel,
    InterestProfile,
    LibraryCollection,
    LibraryCollectionMembership,
    LibraryEntry,
    LibraryNote,
    LibraryRelevanceContext,
    LibraryTag,
    LibraryTagAssignment,
    ReadingPriority,
    RunOrigin,
    TagOrigin,
    datetime_from_db,
    datetime_to_db,
    utc_now,
)

SOURCE_ARXIV = "arxiv"
SCHEMA_VERSION_KEY = "schema_version"
LAST_MIGRATION_BACKUP_KEY = "last_migration_backup_path"
CURRENT_SCHEMA_VERSION = 11
APP_RUN_STARTING = "STARTING"
APP_RUN_RUNNING = "RUNNING"
APP_RUN_COMPLETED = "COMPLETED"
APP_RUN_FAILED = "FAILED"
APP_RUN_ANALYSIS_UNAVAILABLE = "ANALYSIS_UNAVAILABLE"
APP_RUN_PARTIAL = "PARTIAL"
DIGEST_RUN_LOCK = "digest"


class RunLockError(RuntimeError):
    """Raised when a digest run lock cannot be acquired."""


class RunAlreadyActiveError(RunLockError):
    """Raised when another digest run is already active."""


class MigrationError(RuntimeError):
    """Raised when a database schema migration cannot complete safely."""

    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        super().__init__(message)
        self.backup_path = backup_path


@dataclass(frozen=True)
class RunLock:
    name: str
    owner: str
    acquired_at: datetime


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


class Database:
    """Small sqlite3 wrapper for application persistence.

    The object is safe to cache in Streamlit because it stores only the database
    path. Each public operation opens, commits or rolls back, and closes its own
    sqlite connection.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.last_migration_backup_path: Path | None = None
        self.initialize()

    def close(self) -> None:
        """Retained for callers; operation-scoped connections close themselves."""

    def initialize(self) -> None:
        self.last_migration_backup_path = None
        old_version = self._read_schema_version_if_present()
        if old_version > CURRENT_SCHEMA_VERSION:
            raise MigrationError(
                f"database schema version {old_version} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}"
            )
        if old_version < CURRENT_SCHEMA_VERSION and self._has_existing_schema():
            self.last_migration_backup_path = _backup_database(
                self.path,
                from_version=old_version,
                to_version=CURRENT_SCHEMA_VERSION,
            )
        try:
            with self._immediate_connection() as conn:
                _apply_schema_migrations(
                    conn,
                    old_version=old_version,
                    backup_path=self.last_migration_backup_path,
                )
        except Exception as exc:
            if self.last_migration_backup_path is not None:
                raise MigrationError(
                    "database migration failed; the pre-migration backup is recoverable at "
                    f"{self.last_migration_backup_path}",
                    backup_path=self.last_migration_backup_path,
                ) from exc
            raise

    def get_schema_version(self) -> int:
        with self._connection() as conn:
            return _get_schema_version(conn)

    def get_last_migration_backup_path(self) -> Path | None:
        with self._connection() as conn:
            value = _get_metadata_value(conn, LAST_MIGRATION_BACKUP_KEY)
        return Path(value) if value else None

    def _read_schema_version_if_present(self) -> int:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0
        with self._connection() as conn:
            return _get_schema_version(conn)

    def _has_existing_schema(self) -> bool:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return False
        with self._connection() as conn:
            return _connection_has_existing_schema(conn)

    def list_interest_profiles(self, *, enabled_only: bool = False) -> list[InterestProfile]:
        sql = "SELECT * FROM interest_profiles"
        params: tuple[Any, ...] = ()
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY enabled DESC, name COLLATE NOCASE ASC, id ASC"
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_profile_from_row(row) for row in rows]

    def get_interest_profile(self, profile_id: int) -> InterestProfile | None:
        with self._connection() as conn:
            return _get_interest_profile(conn, profile_id)

    def create_interest_profile(
        self,
        *,
        name: str,
        description: str,
        relevance_threshold: float = 0.6,
        enabled: bool = True,
    ) -> InterestProfile:
        profile = InterestProfile(
            id=None,
            name=name,
            description=description,
            relevance_threshold=relevance_threshold,
            enabled=enabled,
        )
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO interest_profiles (
                    name, description, relevance_threshold, enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.name,
                    profile.description,
                    profile.relevance_threshold,
                    int(profile.enabled),
                    now,
                    now,
                ),
            )
            created = _get_interest_profile(conn, _lastrowid(cursor))
        if created is None:
            raise RuntimeError("failed to load created interest profile")
        return created

    def update_interest_profile(self, profile: InterestProfile) -> InterestProfile:
        if profile.id is None:
            raise ValueError("profile id is required for update")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE interest_profiles
                SET name = ?, description = ?, relevance_threshold = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    profile.name,
                    profile.description,
                    profile.relevance_threshold,
                    int(profile.enabled),
                    datetime_to_db(utc_now()),
                    profile.id,
                ),
            )
            updated = _get_interest_profile(conn, profile.id)
        if updated is None:
            raise ValueError(f"interest profile {profile.id} does not exist")
        return updated

    def get_arxiv_config(self) -> ArxivSourceConfig | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM source_configs WHERE source_name = ?",
                (SOURCE_ARXIV,),
            ).fetchone()
        if row is None:
            return None
        return ArxivSourceConfig(
            enabled=bool(row["enabled"]),
            categories=list(json.loads(row["categories_json"])),
            lookback_hours=int(row["lookback_hours"]),
            max_results=int(row["max_results"]),
        )

    def save_arxiv_config(self, config: ArxivSourceConfig) -> None:
        with self._connection() as conn:
            _save_arxiv_config(conn, config)

    def upsert_article(self, article: Article) -> tuple[Article, bool]:
        with self._connection() as conn:
            return _upsert_article(conn, article)

    def upsert_articles(self, articles: Iterable[Article]) -> tuple[list[Article], int]:
        saved: list[Article] = []
        inserted_count = 0
        with self._connection() as conn:
            for article in articles:
                saved_article, inserted = _upsert_article(conn, article)
                saved.append(saved_article)
                if inserted:
                    inserted_count += 1
        return saved, inserted_count

    def get_article(self, article_id: int) -> Article | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return _article_from_row(row) if row is not None else None

    def get_article_by_source_id(self, source: str, source_article_id: str) -> Article | None:
        with self._connection() as conn:
            return _get_article_by_source_id(conn, source, source_article_id)

    def save_library_article(self, article_id: int) -> LibraryEntry:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_articles (article_id, saved, saved_at, updated_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    saved = 1,
                    saved_at = CASE
                        WHEN library_articles.saved = 0 THEN excluded.saved_at
                        ELSE library_articles.saved_at
                    END,
                    updated_at = excluded.updated_at
                """,
                (article_id, now, now),
            )
            entry = _get_library_entry(conn, article_id)
        if entry is None:
            raise ValueError(f"article {article_id} does not exist")
        return entry

    def unsave_library_article(self, article_id: int) -> None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE library_articles
                SET saved = 0, updated_at = ?
                WHERE article_id = ?
                """,
                (datetime_to_db(utc_now()), article_id),
            )

    def get_library_entry(self, article_id: int) -> LibraryEntry | None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            return _get_library_entry(conn, article_id)

    def list_saved_library_entries(self) -> list[LibraryEntry]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    articles.*,
                    library_articles.saved_at AS library_saved_at,
                    library_articles.updated_at AS library_updated_at
                FROM library_articles
                JOIN articles ON articles.id = library_articles.article_id
                WHERE library_articles.saved = 1
                ORDER BY library_articles.saved_at DESC, articles.title COLLATE NOCASE ASC
                """
            ).fetchall()
        return [_library_entry_from_row(row) for row in rows]

    def list_saved_library_article_ids(self, article_ids: Iterable[int]) -> set[int]:
        ids = sorted({int(article_id) for article_id in article_ids if int(article_id) > 0})
        if not ids:
            return set()
        placeholders = ", ".join("?" for _ in ids)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT article_id
                FROM library_articles
                WHERE saved = 1 AND article_id IN ({placeholders})
                """,
                tuple(ids),
            ).fetchall()
        return {int(row["article_id"]) for row in rows}

    def get_latest_relevance_context(
        self,
        article_id: int,
    ) -> LibraryRelevanceContext | None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    relevance_analyses.profile_id,
                    interest_profiles.name AS profile_name,
                    relevance_analyses.relevance_score,
                    relevance_analyses.reading_priority,
                    relevance_analyses.analyzed_at
                FROM relevance_analyses
                JOIN interest_profiles ON interest_profiles.id = relevance_analyses.profile_id
                WHERE relevance_analyses.article_id = ?
                ORDER BY relevance_analyses.analyzed_at DESC, relevance_analyses.id DESC
                LIMIT 1
                """,
                (article_id,),
            ).fetchone()
        return _library_relevance_context_from_row(row) if row is not None else None

    def upsert_library_tag(
        self,
        *,
        normalized_name: str,
        display_name: str,
    ) -> LibraryTag:
        normalized = normalized_name.strip()
        display = display_name.strip()
        if not normalized:
            raise ValueError("normalized tag name is required")
        if not display:
            raise ValueError("tag display name is required")
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_tags (normalized_name, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (normalized, display, now, now),
            )
            tag = _get_library_tag_by_normalized_name(conn, normalized)
        if tag is None:
            raise RuntimeError("failed to load library tag")
        return tag

    def list_library_tags(self) -> list[LibraryTag]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM library_tags
                ORDER BY display_name COLLATE NOCASE ASC, id ASC
                """
            ).fetchall()
        return [_library_tag_from_row(row) for row in rows]

    def upsert_library_tag_assignment(
        self,
        *,
        article_id: int,
        normalized_name: str,
        display_name: str,
        origin: TagOrigin,
        ai_provenance: dict[str, object] | None = None,
    ) -> LibraryTagAssignment:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        tag = self.upsert_library_tag(
            normalized_name=normalized_name,
            display_name=display_name,
        )
        if tag.id is None:
            raise RuntimeError("library tag id is required")
        origin = TagOrigin(origin)
        if origin == TagOrigin.AI and ai_provenance is None:
            raise ValueError("AI tag provenance is required")
        if origin == TagOrigin.USER and ai_provenance is not None:
            raise ValueError("USER tag provenance must be empty")
        now = datetime_to_db(utc_now())
        provenance_json = (
            json.dumps(ai_provenance, sort_keys=True) if ai_provenance is not None else None
        )
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_tag_assignments (
                    article_id, tag_id, origin, ai_provenance_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id, tag_id, origin) DO UPDATE SET
                    ai_provenance_json = excluded.ai_provenance_json,
                    updated_at = excluded.updated_at
                """,
                (article_id, tag.id, origin.value, provenance_json, now, now),
            )
            assignment = _get_library_tag_assignment(
                conn,
                article_id=article_id,
                tag_id=tag.id,
                origin=origin,
            )
        if assignment is None:
            raise RuntimeError("failed to load library tag assignment")
        return assignment

    def remove_library_tag_assignment(
        self,
        *,
        article_id: int,
        normalized_name: str,
        origin: TagOrigin,
    ) -> None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        normalized = normalized_name.strip()
        if not normalized:
            return
        with self._connection() as conn:
            conn.execute(
                """
                DELETE FROM library_tag_assignments
                WHERE article_id = ?
                    AND origin = ?
                    AND tag_id = (
                        SELECT id FROM library_tags WHERE normalized_name = ?
                    )
                """,
                (article_id, TagOrigin(origin).value, normalized),
            )

    def remove_library_tag_assignments_for_origin(
        self,
        *,
        article_id: int,
        origin: TagOrigin,
    ) -> None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            conn.execute(
                """
                DELETE FROM library_tag_assignments
                WHERE article_id = ? AND origin = ?
                """,
                (article_id, TagOrigin(origin).value),
            )

    def list_library_tag_assignments(self, article_id: int) -> list[LibraryTagAssignment]:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    assignments.id AS assignment_id,
                    assignments.article_id,
                    assignments.origin,
                    assignments.ai_provenance_json,
                    assignments.created_at AS assignment_created_at,
                    assignments.updated_at AS assignment_updated_at,
                    tags.id AS tag_id,
                    tags.normalized_name,
                    tags.display_name,
                    tags.created_at AS tag_created_at,
                    tags.updated_at AS tag_updated_at
                FROM library_tag_assignments AS assignments
                JOIN library_tags AS tags ON tags.id = assignments.tag_id
                WHERE assignments.article_id = ?
                ORDER BY assignments.origin DESC, tags.display_name COLLATE NOCASE ASC
                """,
                (article_id,),
            ).fetchall()
        return [_library_tag_assignment_from_row(row) for row in rows]

    def suppress_ai_library_tag(
        self,
        *,
        article_id: int,
        normalized_name: str,
        display_name: str,
        reason: str,
    ) -> AITagSuppression:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        tag = self.upsert_library_tag(
            normalized_name=normalized_name,
            display_name=display_name,
        )
        if tag.id is None:
            raise RuntimeError("library tag id is required")
        suppressed_at = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_ai_tag_suppressions (
                    article_id, tag_id, suppressed_at, reason
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(article_id, tag_id) DO UPDATE SET
                    suppressed_at = excluded.suppressed_at,
                    reason = excluded.reason
                """,
                (article_id, tag.id, suppressed_at, reason),
            )
            suppression = _get_ai_tag_suppression(
                conn,
                article_id=article_id,
                tag_id=tag.id,
            )
        if suppression is None:
            raise RuntimeError("failed to load AI tag suppression")
        return suppression

    def delete_ai_library_tag_suppressions(self, article_id: int) -> None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM library_ai_tag_suppressions WHERE article_id = ?",
                (article_id,),
            )

    def list_ai_library_tag_suppressions(self, article_id: int) -> list[AITagSuppression]:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    suppressions.article_id,
                    suppressions.suppressed_at,
                    suppressions.reason,
                    tags.id AS tag_id,
                    tags.normalized_name,
                    tags.display_name,
                    tags.created_at AS tag_created_at,
                    tags.updated_at AS tag_updated_at
                FROM library_ai_tag_suppressions AS suppressions
                JOIN library_tags AS tags ON tags.id = suppressions.tag_id
                WHERE suppressions.article_id = ?
                ORDER BY tags.display_name COLLATE NOCASE ASC
                """,
                (article_id,),
            ).fetchall()
        return [_ai_tag_suppression_from_row(row) for row in rows]

    def save_library_note(self, *, article_id: int, note_text: str) -> LibraryNote | None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        text = note_text.strip()
        if not text:
            self.delete_library_note(article_id=article_id)
            return None
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_article_notes (article_id, note_text, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    note_text = excluded.note_text,
                    updated_at = excluded.updated_at
                """,
                (article_id, text, now, now),
            )
            note = _get_library_note(conn, article_id)
        if note is None:
            raise RuntimeError("failed to load library note")
        return note

    def get_library_note(self, article_id: int) -> LibraryNote | None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            return _get_library_note(conn, article_id)

    def delete_library_note(self, *, article_id: int) -> None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM library_article_notes WHERE article_id = ?",
                (article_id,),
            )

    def create_library_collection(
        self,
        *,
        name: str,
        normalized_name: str,
        description: str = "",
    ) -> LibraryCollection:
        normalized = normalized_name.strip()
        display_name = name.strip()
        if not normalized:
            raise ValueError("collection normalized name is required")
        if not display_name:
            raise ValueError("collection name is required")
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_collections (
                    name, normalized_name, description, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (display_name, normalized, description.strip(), now, now),
            )
            collection = _get_library_collection_by_normalized_name(conn, normalized)
        if collection is None:
            raise RuntimeError("failed to load library collection")
        return collection

    def update_library_collection(
        self,
        *,
        collection_id: int,
        name: str,
        normalized_name: str,
        description: str,
    ) -> LibraryCollection:
        if collection_id <= 0:
            raise ValueError("collection id must be positive")
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE library_collections
                SET name = ?, normalized_name = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (name.strip(), normalized_name.strip(), description.strip(), now, collection_id),
            )
            collection = _get_library_collection(conn, collection_id)
        if collection is None:
            raise ValueError(f"collection {collection_id} does not exist")
        return collection

    def delete_library_collection(self, collection_id: int) -> None:
        if collection_id <= 0:
            raise ValueError("collection id must be positive")
        with self._connection() as conn:
            conn.execute("DELETE FROM library_collections WHERE id = ?", (collection_id,))

    def get_library_collection(self, collection_id: int) -> LibraryCollection | None:
        if collection_id <= 0:
            raise ValueError("collection id must be positive")
        with self._connection() as conn:
            return _get_library_collection(conn, collection_id)

    def list_library_collections(self) -> list[LibraryCollection]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM library_collections
                ORDER BY name COLLATE NOCASE ASC, id ASC
                """
            ).fetchall()
        return [_library_collection_from_row(row) for row in rows]

    def add_library_collection_membership(
        self,
        *,
        collection_id: int,
        article_id: int,
    ) -> LibraryCollectionMembership:
        if collection_id <= 0:
            raise ValueError("collection id must be positive")
        if article_id <= 0:
            raise ValueError("article id must be positive")
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_collection_memberships (
                    collection_id, article_id, added_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(collection_id, article_id) DO NOTHING
                """,
                (collection_id, article_id, now),
            )
            membership = _get_library_collection_membership(
                conn,
                collection_id=collection_id,
                article_id=article_id,
            )
        if membership is None:
            raise RuntimeError("failed to load collection membership")
        return membership

    def remove_library_collection_membership(
        self,
        *,
        collection_id: int,
        article_id: int,
    ) -> None:
        if collection_id <= 0:
            raise ValueError("collection id must be positive")
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            conn.execute(
                """
                DELETE FROM library_collection_memberships
                WHERE collection_id = ? AND article_id = ?
                """,
                (collection_id, article_id),
            )

    def list_library_collections_for_article(
        self,
        article_id: int,
    ) -> list[LibraryCollection]:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT collections.*
                FROM library_collection_memberships AS memberships
                JOIN library_collections AS collections
                    ON collections.id = memberships.collection_id
                WHERE memberships.article_id = ?
                ORDER BY collections.name COLLATE NOCASE ASC, collections.id ASC
                """,
                (article_id,),
            ).fetchall()
        return [_library_collection_from_row(row) for row in rows]

    def list_library_collection_memberships(
        self,
        collection_id: int | None = None,
    ) -> list[LibraryCollectionMembership]:
        params: tuple[object, ...] = ()
        where = ""
        if collection_id is not None:
            if collection_id <= 0:
                raise ValueError("collection id must be positive")
            where = "WHERE collection_id = ?"
            params = (collection_id,)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM library_collection_memberships
                {where}
                ORDER BY collection_id ASC, article_id ASC
                """,
                params,
            ).fetchall()
        return [_library_collection_membership_from_row(row) for row in rows]

    def count_articles(self) -> int:
        with self._connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM articles").fetchone()
        if row is None:
            raise RuntimeError("failed to count articles")
        return int(row["count"])

    def get_analysis(
        self,
        *,
        article_id: int,
        profile_id: int,
        profile_fingerprint: str,
    ) -> AnalysisResult | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM relevance_analyses
                WHERE article_id = ? AND profile_id = ? AND profile_fingerprint = ?
                """,
                (article_id, profile_id, profile_fingerprint),
            ).fetchone()
        return _analysis_from_row(row) if row is not None else None

    def upsert_analysis(
        self,
        *,
        article_id: int,
        profile_id: int,
        profile_fingerprint: str,
        analysis: AnalysisResult,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO relevance_analyses (
                    article_id, profile_id, profile_fingerprint, relevance_score, relevance_reason,
                    matched_topics_json, summary, why_it_matters, reading_priority, analyzed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id, profile_id, profile_fingerprint) DO UPDATE SET
                    relevance_score = excluded.relevance_score,
                    relevance_reason = excluded.relevance_reason,
                    matched_topics_json = excluded.matched_topics_json,
                    summary = excluded.summary,
                    why_it_matters = excluded.why_it_matters,
                    reading_priority = excluded.reading_priority,
                    analyzed_at = excluded.analyzed_at
                """,
                (
                    article_id,
                    profile_id,
                    profile_fingerprint,
                    analysis.relevance_score,
                    analysis.relevance_reason,
                    json.dumps(analysis.matched_topics),
                    analysis.summary,
                    analysis.why_it_matters,
                    analysis.reading_priority,
                    datetime_to_db(utc_now()),
                ),
            )

    def get_article_feedback(
        self,
        *,
        article_id: int,
        profile_id: int,
        profile_fingerprint: str,
    ) -> ArticleFeedback | None:
        with self._connection() as conn:
            return _get_article_feedback(
                conn,
                article_id=article_id,
                profile_id=profile_id,
                profile_fingerprint=profile_fingerprint,
            )

    def list_article_feedback(
        self,
        *,
        profile_id: int,
        profile_fingerprint: str,
    ) -> list[ArticleFeedback]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM article_feedback
                WHERE profile_id = ? AND profile_fingerprint = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (profile_id, profile_fingerprint),
            ).fetchall()
        return [_feedback_from_row(row) for row in rows]

    def upsert_article_feedback(
        self,
        *,
        article_id: int,
        profile_id: int,
        profile_fingerprint: str,
        feedback_label: FeedbackLabel,
    ) -> ArticleFeedback:
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO article_feedback (
                    article_id, profile_id, profile_fingerprint, feedback_label,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id, profile_id, profile_fingerprint) DO UPDATE SET
                    feedback_label = excluded.feedback_label,
                    updated_at = excluded.updated_at
                """,
                (article_id, profile_id, profile_fingerprint, feedback_label, now, now),
            )
            feedback = _get_article_feedback(
                conn,
                article_id=article_id,
                profile_id=profile_id,
                profile_fingerprint=profile_fingerprint,
            )
        if feedback is None:
            raise RuntimeError("failed to load saved article feedback")
        return feedback

    def create_app_run(
        self,
        *,
        profile_id: int | None,
        profile_fingerprint: str | None = None,
        source_name: str,
        source_fingerprint: str | None = None,
        run_origin: RunOrigin = RunOrigin.LEGACY,
        date_selection: DateSelection | None = None,
    ) -> int:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO app_runs (
                    profile_id, profile_fingerprint, source_name, source_fingerprint,
                    started_at, status, run_origin, date_selection_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    profile_fingerprint,
                    source_name,
                    source_fingerprint,
                    datetime_to_db(utc_now()),
                    APP_RUN_STARTING,
                    run_origin.value,
                    json.dumps(date_selection.to_mapping(), sort_keys=True)
                    if date_selection is not None
                    else None,
                ),
            )
            return _lastrowid(cursor)

    def mark_app_run_running(self, run_id: int) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE app_runs SET status = ? WHERE id = ?",
                (APP_RUN_RUNNING, run_id),
            )

    def finish_app_run(
        self,
        run_id: int,
        *,
        status: str,
        retrieved_count: int,
        stored_count: int,
        preselected_count: int,
        skipped_analysis_count: int,
        analyzed_count: int,
        relevant_count: int,
        error_message: str | None = None,
        requested_source_dates: Sequence[str] = (),
        covered_source_dates: Sequence[str] = (),
        empty_source_dates: Sequence[str] = (),
        incomplete_source_dates: Sequence[str] = (),
        retrieval_complete: bool = True,
        retrieval_safety_limit: int | None = None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE app_runs
                SET completed_at = ?, status = ?, retrieved_count = ?, stored_count = ?,
                    preselected_count = ?, skipped_analysis_count = ?, analyzed_count = ?,
                    relevant_count = ?, error_message = ?,
                    requested_source_dates_json = ?, covered_source_dates_json = ?,
                    empty_source_dates_json = ?, incomplete_source_dates_json = ?,
                    retrieval_complete = ?, retrieval_safety_limit = ?
                WHERE id = ?
                """,
                (
                    datetime_to_db(utc_now()),
                    status,
                    retrieved_count,
                    stored_count,
                    preselected_count,
                    skipped_analysis_count,
                    analyzed_count,
                    relevant_count,
                    error_message,
                    json.dumps(list(requested_source_dates)),
                    json.dumps(list(covered_source_dates)),
                    json.dumps(list(empty_source_dates)),
                    json.dumps(list(incomplete_source_dates)),
                    int(retrieval_complete),
                    retrieval_safety_limit,
                    run_id,
                ),
            )

    def get_app_runs(self) -> list[sqlite3.Row]:
        with self._connection() as conn:
            return list(
                conn.execute(
                    """
                    SELECT
                        id,
                        profile_id,
                        profile_fingerprint,
                        source_name,
                        source_fingerprint,
                        started_at,
                        completed_at,
                        CASE status
                            WHEN 'running' THEN ?
                            WHEN 'success' THEN ?
                            WHEN 'failed' THEN ?
                            WHEN 'analysis_unavailable' THEN ?
                            ELSE status
                        END AS status,
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
                    ORDER BY id DESC
                    """,
                    (
                        APP_RUN_RUNNING,
                        APP_RUN_COMPLETED,
                        APP_RUN_FAILED,
                        APP_RUN_ANALYSIS_UNAVAILABLE,
                    ),
                ).fetchall()
            )

    def mark_source_date_covered(
        self,
        *,
        profile_id: int,
        profile_fingerprint: str,
        source_name: str,
        source_fingerprint: str,
        source_date: date,
        run_id: int,
        run_origin: RunOrigin,
    ) -> None:
        covered_at = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO source_date_coverage (
                    profile_id, profile_fingerprint, source_name, source_fingerprint,
                    source_date, status, first_covered_run_id, last_covered_run_id,
                    run_origin, covered_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'COVERED', ?, ?, ?, ?, ?)
                ON CONFLICT(
                    profile_id, profile_fingerprint, source_name, source_fingerprint, source_date
                ) DO UPDATE SET
                    status = 'COVERED',
                    last_covered_run_id = excluded.last_covered_run_id,
                    run_origin = excluded.run_origin,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_id,
                    profile_fingerprint,
                    source_name,
                    source_fingerprint,
                    source_date.isoformat(),
                    run_id,
                    run_id,
                    run_origin.value,
                    covered_at,
                    covered_at,
                ),
            )

    def list_covered_source_dates(
        self,
        *,
        profile_id: int,
        profile_fingerprint: str,
        source_name: str,
        source_fingerprint: str,
        start_date: date,
        end_date: date,
    ) -> set[date]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT source_date
                FROM source_date_coverage
                WHERE profile_id = ?
                    AND profile_fingerprint = ?
                    AND source_name = ?
                    AND source_fingerprint = ?
                    AND status = 'COVERED'
                    AND source_date BETWEEN ? AND ?
                """,
                (
                    profile_id,
                    profile_fingerprint,
                    source_name,
                    source_fingerprint,
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            ).fetchall()
        return {date.fromisoformat(str(row["source_date"])) for row in rows}

    def list_source_date_coverage(self) -> list[sqlite3.Row]:
        with self._connection() as conn:
            return list(
                conn.execute(
                    """
                    SELECT *
                    FROM source_date_coverage
                    ORDER BY source_date DESC, profile_id ASC, id DESC
                    """
                ).fetchall()
            )

    def save_run_snapshot(self, *, run_id: int, snapshot_json: str) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO run_snapshots (run_id, snapshot_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (run_id, snapshot_json, datetime_to_db(utc_now())),
            )

    def get_run_snapshot(self, *, run_id: int) -> sqlite3.Row | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM run_snapshots WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return cast(sqlite3.Row | None, row)

    def acquire_run_lock(
        self,
        *,
        owner: str,
        stale_after_seconds: float,
        now: datetime | None = None,
    ) -> RunLock:
        acquired_at = utc_now() if now is None else now
        stale_cutoff = acquired_at - timedelta(seconds=stale_after_seconds)
        acquired_at_text = datetime_to_db(acquired_at)
        with self._immediate_connection() as conn:
            row = conn.execute(
                "SELECT * FROM run_locks WHERE name = ?",
                (DIGEST_RUN_LOCK,),
            ).fetchone()
            if row is not None:
                locked_at = datetime_from_db(str(row["acquired_at"]))
                if locked_at > stale_cutoff:
                    raise RunAlreadyActiveError("another digest run is already active")
                _mark_unfinished_runs_failed(conn, completed_at=acquired_at_text)
                conn.execute("DELETE FROM run_locks WHERE name = ?", (DIGEST_RUN_LOCK,))
            else:
                _mark_unfinished_runs_failed(
                    conn,
                    completed_at=acquired_at_text,
                    started_before=datetime_to_db(stale_cutoff),
                )

            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (DIGEST_RUN_LOCK, owner, acquired_at_text, acquired_at_text),
            )
        return RunLock(name=DIGEST_RUN_LOCK, owner=owner, acquired_at=acquired_at)

    def release_run_lock(self, *, owner: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM run_locks WHERE name = ? AND owner = ?",
                (DIGEST_RUN_LOCK, owner),
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _immediate_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _apply_schema_migrations(
    conn: sqlite3.Connection,
    *,
    old_version: int,
    backup_path: Path | None,
) -> None:
    if old_version > CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"database schema version {old_version} is newer than supported "
            f"version {CURRENT_SCHEMA_VERSION}"
        )

    _create_schema_metadata_table(conn)
    current_version = _get_schema_version(conn)
    if current_version != old_version:
        raise MigrationError(
            "database schema version changed while initialization was in progress"
        )

    for migration in MIGRATIONS:
        if migration.version <= old_version:
            continue
        migration.apply(conn)
        _set_schema_version(conn, migration.version)

    if backup_path is not None:
        _set_metadata_value(conn, LAST_MIGRATION_BACKUP_KEY, str(backup_path))
    _ensure_default_source_config(conn)


def _create_schema_metadata_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _get_schema_version(conn: sqlite3.Connection) -> int:
    value = _get_metadata_value(conn, SCHEMA_VERSION_KEY)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise MigrationError("database schema version metadata is invalid") from exc


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    _set_metadata_value(conn, SCHEMA_VERSION_KEY, str(version))


def _get_metadata_value(conn: sqlite3.Connection, key: str) -> str | None:
    if not _table_exists(conn, "schema_metadata"):
        return None
    row = conn.execute(
        "SELECT value FROM schema_metadata WHERE key = ?",
        (key,),
    ).fetchone()
    return str(row["value"]) if row is not None else None


def _set_metadata_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO schema_metadata (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, datetime_to_db(utc_now())),
    )


def _backup_database(path: Path, *, from_version: int, to_version: int) -> Path:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(
        f"{path.name}.backup-v{from_version}-to-v{to_version}-{timestamp}.sqlite3"
    )
    counter = 1
    while backup_path.exists():
        backup_path = path.with_name(
            f"{path.name}.backup-v{from_version}-to-v{to_version}-{timestamp}-{counter}.sqlite3"
        )
        counter += 1

    source = sqlite3.connect(path)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
    finally:
        source.close()
    return backup_path


def _connection_has_existing_schema(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return len(rows) > 0


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_default_source_config(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM source_configs WHERE source_name = ?",
        (SOURCE_ARXIV,),
    ).fetchone()
    if row is None:
        _save_arxiv_config(conn, ArxivSourceConfig())


def _execute_schema_statements(conn: sqlite3.Connection, statements: Sequence[str]) -> None:
    for statement in statements:
        conn.execute(statement)


def _migration_core_tables(conn: sqlite3.Connection) -> None:
    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS interest_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            relevance_threshold REAL NOT NULL,
            enabled INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS source_configs (
            source_name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL,
            categories_json TEXT NOT NULL,
            lookback_hours INTEGER NOT NULL,
            max_results INTEGER NOT NULL,
            updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_article_id TEXT NOT NULL,
            title TEXT NOT NULL,
            authors_json TEXT NOT NULL,
            abstract TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            published_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            abstract_url TEXT NOT NULL,
            pdf_url TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source, source_article_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS relevance_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            relevance_score REAL NOT NULL,
            relevance_reason TEXT NOT NULL,
            matched_topics_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            why_it_matters TEXT NOT NULL,
            reading_priority TEXT NOT NULL,
            analyzed_at TEXT NOT NULL,
            UNIQUE(article_id, profile_id),
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
            FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS article_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            profile_fingerprint TEXT NOT NULL,
            feedback_label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(article_id, profile_id, profile_fingerprint),
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
            FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS app_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER,
            source_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            retrieved_count INTEGER NOT NULL DEFAULT 0,
            stored_count INTEGER NOT NULL DEFAULT 0,
            analyzed_count INTEGER NOT NULL DEFAULT 0,
            relevant_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE SET NULL
            )
            """,
        ),
    )


def _migration_profile_fingerprints(conn: sqlite3.Connection) -> None:
    _migrate_relevance_analysis_profile_fingerprints(conn)


def _migration_preselection_counts(conn: sqlite3.Connection) -> None:
    _migrate_app_run_preselection_counts(conn)


def _migration_run_lifecycle_history(conn: sqlite3.Connection) -> None:
    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS run_locks (
            name TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS run_snapshots (
            run_id INTEGER PRIMARY KEY,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES app_runs(id) ON DELETE CASCADE
            )
            """,
        ),
    )
    _sanitize_existing_app_run_errors(conn)


def _migration_run_date_metadata(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "app_runs"):
        return
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(app_runs)").fetchall()}
    additions = {
        "run_origin": "TEXT NOT NULL DEFAULT 'LEGACY'",
        "date_selection_json": "TEXT",
        "requested_source_dates_json": "TEXT NOT NULL DEFAULT '[]'",
        "covered_source_dates_json": "TEXT NOT NULL DEFAULT '[]'",
        "empty_source_dates_json": "TEXT NOT NULL DEFAULT '[]'",
        "incomplete_source_dates_json": "TEXT NOT NULL DEFAULT '[]'",
        "retrieval_complete": "INTEGER NOT NULL DEFAULT 1",
        "retrieval_safety_limit": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE app_runs ADD COLUMN {name} {definition}")


def _migration_source_date_coverage(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_date_coverage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            profile_fingerprint TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL,
            source_date TEXT NOT NULL,
            status TEXT NOT NULL,
            first_covered_run_id INTEGER NOT NULL,
            last_covered_run_id INTEGER NOT NULL,
            run_origin TEXT NOT NULL,
            covered_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (
                profile_id, profile_fingerprint, source_name, source_fingerprint, source_date
            ),
            FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE,
            FOREIGN KEY(first_covered_run_id) REFERENCES app_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(last_covered_run_id) REFERENCES app_runs(id) ON DELETE CASCADE
        )
        """
    )


def _migration_app_run_source_fingerprint(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "app_runs"):
        return
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(app_runs)").fetchall()}
    if "source_fingerprint" not in columns:
        conn.execute("ALTER TABLE app_runs ADD COLUMN source_fingerprint TEXT")


def _migration_app_run_profile_fingerprint(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "app_runs"):
        return
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(app_runs)").fetchall()}
    if "profile_fingerprint" not in columns:
        conn.execute("ALTER TABLE app_runs ADD COLUMN profile_fingerprint TEXT")


def _migration_saved_article_library(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS library_articles (
            article_id INTEGER PRIMARY KEY,
            saved INTEGER NOT NULL DEFAULT 1,
            saved_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_library_articles_saved_saved_at
        ON library_articles(saved, saved_at DESC)
        """
    )


def _migration_library_tags(conn: sqlite3.Connection) -> None:
    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS library_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS library_tag_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                origin TEXT NOT NULL,
                ai_provenance_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(article_id, tag_id, origin),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES library_tags(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS library_ai_tag_suppressions (
                article_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                suppressed_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                UNIQUE(article_id, tag_id),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(tag_id) REFERENCES library_tags(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_library_tag_assignments_article
            ON library_tag_assignments(article_id, origin)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_library_ai_tag_suppressions_article
            ON library_ai_tag_suppressions(article_id)
            """,
        ),
    )


def _migration_library_notes_collections(conn: sqlite3.Connection) -> None:
    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS library_article_notes (
                article_id INTEGER PRIMARY KEY,
                note_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS library_collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS library_collection_memberships (
                collection_id INTEGER NOT NULL,
                article_id INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                UNIQUE(collection_id, article_id),
                FOREIGN KEY(collection_id) REFERENCES library_collections(id) ON DELETE CASCADE,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_library_collection_memberships_article
            ON library_collection_memberships(article_id)
            """,
        ),
    )


MIGRATIONS: Sequence[SchemaMigration] = (
    SchemaMigration(1, "core m1/m2 tables", _migration_core_tables),
    SchemaMigration(2, "profile-fingerprinted relevance analyses", _migration_profile_fingerprints),
    SchemaMigration(3, "preselection run counters", _migration_preselection_counts),
    SchemaMigration(
        4,
        "run lifecycle locks and history snapshots",
        _migration_run_lifecycle_history,
    ),
    SchemaMigration(5, "date-native run metadata", _migration_run_date_metadata),
    SchemaMigration(6, "source date coverage", _migration_source_date_coverage),
    SchemaMigration(7, "app run source fingerprint", _migration_app_run_source_fingerprint),
    SchemaMigration(8, "app run profile fingerprint", _migration_app_run_profile_fingerprint),
    SchemaMigration(9, "saved article library", _migration_saved_article_library),
    SchemaMigration(10, "library tags and AI suppressions", _migration_library_tags),
    SchemaMigration(
        11,
        "library notes and collections",
        _migration_library_notes_collections,
    ),
)


def _get_interest_profile(conn: sqlite3.Connection, profile_id: int) -> InterestProfile | None:
    row = conn.execute(
        "SELECT * FROM interest_profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()
    return _profile_from_row(row) if row is not None else None


def _mark_unfinished_runs_failed(
    conn: sqlite3.Connection,
    *,
    completed_at: str,
    started_before: str | None = None,
) -> None:
    params: list[object] = [
        completed_at,
        APP_RUN_FAILED,
        "Previous digest run appears to have stopped before completion.",
        APP_RUN_STARTING,
        APP_RUN_RUNNING,
        "running",
    ]
    started_clause = ""
    if started_before is not None:
        started_clause = " AND started_at <= ?"
        params.append(started_before)
    conn.execute(
        f"""
        UPDATE app_runs
        SET completed_at = ?, status = ?, error_message = ?
        WHERE completed_at IS NULL AND status IN (?, ?, ?){started_clause}
        """,
        tuple(params),
    )


def _save_arxiv_config(conn: sqlite3.Connection, config: ArxivSourceConfig) -> None:
    conn.execute(
        """
        INSERT INTO source_configs (
            source_name, enabled, categories_json, lookback_hours, max_results, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
            enabled = excluded.enabled,
            categories_json = excluded.categories_json,
            lookback_hours = excluded.lookback_hours,
            max_results = excluded.max_results,
            updated_at = excluded.updated_at
        """,
        (
            SOURCE_ARXIV,
            int(config.enabled),
            json.dumps(config.categories),
            config.lookback_hours,
            config.max_results,
            datetime_to_db(utc_now()),
        ),
    )


def _sanitize_existing_app_run_errors(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, error_message FROM app_runs WHERE error_message IS NOT NULL"
    ).fetchall()
    for row in rows:
        original = str(row["error_message"])
        sanitized = sanitize_error_text(original)
        if sanitized != original:
            conn.execute(
                "UPDATE app_runs SET error_message = ? WHERE id = ?",
                (sanitized, int(row["id"])),
            )


def _migrate_app_run_preselection_counts(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "app_runs"):
        return
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(app_runs)").fetchall()}
    if "preselected_count" not in columns:
        conn.execute(
            "ALTER TABLE app_runs ADD COLUMN preselected_count INTEGER NOT NULL DEFAULT 0"
        )
    if "skipped_analysis_count" not in columns:
        conn.execute(
            "ALTER TABLE app_runs ADD COLUMN skipped_analysis_count INTEGER NOT NULL DEFAULT 0"
        )


def _migrate_relevance_analysis_profile_fingerprints(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "relevance_analyses"):
        return
    if not _analysis_table_needs_profile_fingerprint_migration(conn):
        return

    rows = conn.execute(
        """
        SELECT
            ra.id, ra.article_id, ra.profile_id, ra.relevance_score, ra.relevance_reason,
            ra.matched_topics_json, ra.summary, ra.why_it_matters, ra.reading_priority,
            ra.analyzed_at
        FROM relevance_analyses AS ra
        ORDER BY ra.id ASC
        """
    ).fetchall()
    conn.execute("ALTER TABLE relevance_analyses RENAME TO relevance_analyses_old")
    _create_relevance_analyses_table(conn)
    for row in rows:
        conn.execute(
            """
            INSERT INTO relevance_analyses (
                id, article_id, profile_id, profile_fingerprint, relevance_score,
                relevance_reason, matched_topics_json, summary, why_it_matters,
                reading_priority, analyzed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(row["id"]),
                int(row["article_id"]),
                int(row["profile_id"]),
                f"legacy:{int(row['id'])}",
                float(row["relevance_score"]),
                str(row["relevance_reason"]),
                str(row["matched_topics_json"]),
                str(row["summary"]),
                str(row["why_it_matters"]),
                str(row["reading_priority"]),
                str(row["analyzed_at"]),
            ),
        )
    conn.execute("DROP TABLE relevance_analyses_old")


def _analysis_table_needs_profile_fingerprint_migration(conn: sqlite3.Connection) -> bool:
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(relevance_analyses)").fetchall()
    }
    if "profile_fingerprint" not in columns:
        return True

    for index in conn.execute("PRAGMA index_list(relevance_analyses)").fetchall():
        if not bool(index["unique"]):
            continue
        index_columns = [
            str(row["name"])
            for row in conn.execute(f"PRAGMA index_info({str(index['name'])!r})").fetchall()
        ]
        if index_columns == ["article_id", "profile_id"]:
            return True
    return False


def _create_relevance_analyses_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE relevance_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            profile_fingerprint TEXT NOT NULL,
            relevance_score REAL NOT NULL,
            relevance_reason TEXT NOT NULL,
            matched_topics_json TEXT NOT NULL,
            summary TEXT NOT NULL,
            why_it_matters TEXT NOT NULL,
            reading_priority TEXT NOT NULL,
            analyzed_at TEXT NOT NULL,
            UNIQUE(article_id, profile_id, profile_fingerprint),
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
            FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
        )
        """
    )


def _upsert_article(conn: sqlite3.Connection, article: Article) -> tuple[Article, bool]:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO articles (
            source, source_article_id, title, authors_json, abstract, categories_json,
            published_at, updated_at, abstract_url, pdf_url, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _article_values(article) + (datetime_to_db(utc_now()),),
    )
    inserted = cursor.rowcount == 1
    if not inserted:
        conn.execute(
            """
            UPDATE articles
            SET title = ?, authors_json = ?, abstract = ?, categories_json = ?,
                published_at = ?, updated_at = ?, abstract_url = ?, pdf_url = ?
            WHERE source = ? AND source_article_id = ?
            """,
            (
                article.title,
                json.dumps(article.authors),
                article.abstract,
                json.dumps(article.categories),
                datetime_to_db(article.published_at),
                datetime_to_db(article.updated_at),
                article.abstract_url,
                article.pdf_url,
                article.source,
                article.source_article_id,
            ),
        )
    saved = _get_article_by_source_id(conn, article.source, article.source_article_id)
    if saved is None:
        raise RuntimeError("failed to load saved article")
    return saved, inserted


def _get_article_by_source_id(
    conn: sqlite3.Connection,
    source: str,
    source_article_id: str,
) -> Article | None:
    row = conn.execute(
        "SELECT * FROM articles WHERE source = ? AND source_article_id = ?",
        (source, source_article_id),
    ).fetchone()
    return _article_from_row(row) if row is not None else None


def _get_library_entry(conn: sqlite3.Connection, article_id: int) -> LibraryEntry | None:
    row = conn.execute(
        """
        SELECT
            articles.*,
            library_articles.saved_at AS library_saved_at,
            library_articles.updated_at AS library_updated_at
        FROM library_articles
        JOIN articles ON articles.id = library_articles.article_id
        WHERE library_articles.article_id = ? AND library_articles.saved = 1
        """,
        (article_id,),
    ).fetchone()
    return _library_entry_from_row(row) if row is not None else None


def _get_library_tag_by_normalized_name(
    conn: sqlite3.Connection,
    normalized_name: str,
) -> LibraryTag | None:
    row = conn.execute(
        "SELECT * FROM library_tags WHERE normalized_name = ?",
        (normalized_name,),
    ).fetchone()
    return _library_tag_from_row(row) if row is not None else None


def _get_library_tag_assignment(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    tag_id: int,
    origin: TagOrigin,
) -> LibraryTagAssignment | None:
    row = conn.execute(
        """
        SELECT
            assignments.id AS assignment_id,
            assignments.article_id,
            assignments.origin,
            assignments.ai_provenance_json,
            assignments.created_at AS assignment_created_at,
            assignments.updated_at AS assignment_updated_at,
            tags.id AS tag_id,
            tags.normalized_name,
            tags.display_name,
            tags.created_at AS tag_created_at,
            tags.updated_at AS tag_updated_at
        FROM library_tag_assignments AS assignments
        JOIN library_tags AS tags ON tags.id = assignments.tag_id
        WHERE assignments.article_id = ? AND assignments.tag_id = ? AND assignments.origin = ?
        """,
        (article_id, tag_id, origin.value),
    ).fetchone()
    return _library_tag_assignment_from_row(row) if row is not None else None


def _get_ai_tag_suppression(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    tag_id: int,
) -> AITagSuppression | None:
    row = conn.execute(
        """
        SELECT
            suppressions.article_id,
            suppressions.suppressed_at,
            suppressions.reason,
            tags.id AS tag_id,
            tags.normalized_name,
            tags.display_name,
            tags.created_at AS tag_created_at,
            tags.updated_at AS tag_updated_at
        FROM library_ai_tag_suppressions AS suppressions
        JOIN library_tags AS tags ON tags.id = suppressions.tag_id
        WHERE suppressions.article_id = ? AND suppressions.tag_id = ?
        """,
        (article_id, tag_id),
    ).fetchone()
    return _ai_tag_suppression_from_row(row) if row is not None else None


def _get_library_note(conn: sqlite3.Connection, article_id: int) -> LibraryNote | None:
    row = conn.execute(
        "SELECT * FROM library_article_notes WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    return _library_note_from_row(row) if row is not None else None


def _get_library_collection(
    conn: sqlite3.Connection,
    collection_id: int,
) -> LibraryCollection | None:
    row = conn.execute(
        "SELECT * FROM library_collections WHERE id = ?",
        (collection_id,),
    ).fetchone()
    return _library_collection_from_row(row) if row is not None else None


def _get_library_collection_by_normalized_name(
    conn: sqlite3.Connection,
    normalized_name: str,
) -> LibraryCollection | None:
    row = conn.execute(
        "SELECT * FROM library_collections WHERE normalized_name = ?",
        (normalized_name,),
    ).fetchone()
    return _library_collection_from_row(row) if row is not None else None


def _get_library_collection_membership(
    conn: sqlite3.Connection,
    *,
    collection_id: int,
    article_id: int,
) -> LibraryCollectionMembership | None:
    row = conn.execute(
        """
        SELECT *
        FROM library_collection_memberships
        WHERE collection_id = ? AND article_id = ?
        """,
        (collection_id, article_id),
    ).fetchone()
    return _library_collection_membership_from_row(row) if row is not None else None


def _get_article_feedback(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    profile_id: int,
    profile_fingerprint: str,
) -> ArticleFeedback | None:
    row = conn.execute(
        """
        SELECT * FROM article_feedback
        WHERE article_id = ? AND profile_id = ? AND profile_fingerprint = ?
        """,
        (article_id, profile_id, profile_fingerprint),
    ).fetchone()
    return _feedback_from_row(row) if row is not None else None


def _profile_from_row(row: sqlite3.Row) -> InterestProfile:
    return InterestProfile(
        id=int(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        relevance_threshold=float(row["relevance_threshold"]),
        enabled=bool(row["enabled"]),
    )


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    rowid = cursor.lastrowid
    if rowid is None:
        raise RuntimeError("sqlite insert did not return a row id")
    return rowid


def _article_values(article: Article) -> tuple[Any, ...]:
    return (
        article.source,
        article.source_article_id,
        article.title,
        json.dumps(article.authors),
        article.abstract,
        json.dumps(article.categories),
        datetime_to_db(article.published_at),
        datetime_to_db(article.updated_at),
        article.abstract_url,
        article.pdf_url,
    )


def _article_from_row(row: sqlite3.Row) -> Article:
    return Article(
        id=int(row["id"]),
        source=str(row["source"]),
        source_article_id=str(row["source_article_id"]),
        title=str(row["title"]),
        authors=list(json.loads(row["authors_json"])),
        abstract=str(row["abstract"]),
        categories=list(json.loads(row["categories_json"])),
        published_at=datetime_from_db(str(row["published_at"])),
        updated_at=datetime_from_db(str(row["updated_at"])),
        abstract_url=str(row["abstract_url"]),
        pdf_url=str(row["pdf_url"]) if row["pdf_url"] else None,
    )


def _library_entry_from_row(row: sqlite3.Row) -> LibraryEntry:
    return LibraryEntry(
        article=_article_from_row(row),
        saved_at=datetime_from_db(str(row["library_saved_at"])),
        updated_at=datetime_from_db(str(row["library_updated_at"])),
    )


def _analysis_from_row(row: sqlite3.Row) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=float(row["relevance_score"]),
        relevance_reason=str(row["relevance_reason"]),
        matched_topics=list(json.loads(row["matched_topics_json"])),
        summary=str(row["summary"]),
        why_it_matters=str(row["why_it_matters"]),
        reading_priority=cast(ReadingPriority, str(row["reading_priority"])),
    )


def _library_relevance_context_from_row(row: sqlite3.Row) -> LibraryRelevanceContext:
    return LibraryRelevanceContext(
        profile_id=int(row["profile_id"]),
        profile_name=str(row["profile_name"]),
        relevance_score=float(row["relevance_score"]),
        reading_priority=cast(ReadingPriority, str(row["reading_priority"])),
        analyzed_at=datetime_from_db(str(row["analyzed_at"])),
    )


def _library_tag_from_row(row: sqlite3.Row) -> LibraryTag:
    return LibraryTag(
        id=int(row["id"]),
        normalized_name=str(row["normalized_name"]),
        display_name=str(row["display_name"]),
        created_at=datetime_from_db(str(row["created_at"])),
        updated_at=datetime_from_db(str(row["updated_at"])),
    )


def _library_tag_from_joined_row(row: sqlite3.Row) -> LibraryTag:
    return LibraryTag(
        id=int(row["tag_id"]),
        normalized_name=str(row["normalized_name"]),
        display_name=str(row["display_name"]),
        created_at=datetime_from_db(str(row["tag_created_at"])),
        updated_at=datetime_from_db(str(row["tag_updated_at"])),
    )


def _library_tag_assignment_from_row(row: sqlite3.Row) -> LibraryTagAssignment:
    provenance = (
        json.loads(str(row["ai_provenance_json"]))
        if row["ai_provenance_json"] is not None
        else None
    )
    if provenance is not None and not isinstance(provenance, dict):
        provenance = {"invalid_provenance": True}
    return LibraryTagAssignment(
        id=int(row["assignment_id"]),
        article_id=int(row["article_id"]),
        tag=_library_tag_from_joined_row(row),
        origin=TagOrigin(str(row["origin"])),
        ai_provenance=cast(dict[str, object] | None, provenance),
        created_at=datetime_from_db(str(row["assignment_created_at"])),
        updated_at=datetime_from_db(str(row["assignment_updated_at"])),
    )


def _ai_tag_suppression_from_row(row: sqlite3.Row) -> AITagSuppression:
    return AITagSuppression(
        article_id=int(row["article_id"]),
        tag=_library_tag_from_joined_row(row),
        suppressed_at=datetime_from_db(str(row["suppressed_at"])),
        reason=str(row["reason"]),
    )


def _library_note_from_row(row: sqlite3.Row) -> LibraryNote:
    return LibraryNote(
        article_id=int(row["article_id"]),
        note_text=str(row["note_text"]),
        created_at=datetime_from_db(str(row["created_at"])),
        updated_at=datetime_from_db(str(row["updated_at"])),
    )


def _library_collection_from_row(row: sqlite3.Row) -> LibraryCollection:
    return LibraryCollection(
        id=int(row["id"]),
        name=str(row["name"]),
        normalized_name=str(row["normalized_name"]),
        description=str(row["description"]),
        created_at=datetime_from_db(str(row["created_at"])),
        updated_at=datetime_from_db(str(row["updated_at"])),
    )


def _library_collection_membership_from_row(
    row: sqlite3.Row,
) -> LibraryCollectionMembership:
    return LibraryCollectionMembership(
        collection_id=int(row["collection_id"]),
        article_id=int(row["article_id"]),
        added_at=datetime_from_db(str(row["added_at"])),
    )


def _feedback_from_row(row: sqlite3.Row) -> ArticleFeedback:
    return ArticleFeedback(
        id=int(row["id"]),
        article_id=int(row["article_id"]),
        profile_id=int(row["profile_id"]),
        profile_fingerprint=str(row["profile_fingerprint"]),
        feedback_label=cast(FeedbackLabel, str(row["feedback_label"])),
        created_at=datetime_from_db(str(row["created_at"])),
        updated_at=datetime_from_db(str(row["updated_at"])),
    )
