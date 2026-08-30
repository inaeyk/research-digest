"""SQLite persistence for Research Digest."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from research_digest.conversation_provenance import parse_rolling_summary_boundary
from research_digest.errors import sanitize_error_text
from research_digest.models import (
    AIArtifact,
    AIArtifactProvenance,
    AIArtifactRetentionClass,
    AIArtifactType,
    AIConversation,
    AIConversationMessage,
    AIConversationRole,
    AITagSuppression,
    AnalysisResult,
    AnalysisSummaryReference,
    AnalysisSummaryStorage,
    Article,
    ArticleFeedback,
    ArxivSourceConfig,
    CollectionIntelligenceSnapshot,
    ConnectionOrigin,
    DateSelection,
    FeedbackAnswer,
    FeedbackLabel,
    InterestProfile,
    LibraryCollection,
    LibraryCollectionMembership,
    LibraryConnection,
    LibraryContextOrigin,
    LibraryContextSuggestion,
    LibraryEntry,
    LibraryNote,
    LibraryRelevanceContext,
    LibrarySearchDocument,
    LibrarySummarySource,
    LibraryTag,
    LibraryTagAssignment,
    QuantitativeCalibrationState,
    QuantitativeRelevanceCalibration,
    ReadingPriority,
    ReadingState,
    ResolvedLibrarySummary,
    RunOrigin,
    SuggestedInterestProfile,
    TagOrigin,
    canonical_arxiv_categories,
    datetime_from_db,
    datetime_to_db,
    source_date_from_datetime,
    utc_now,
)
from research_digest.retention import temporary_artifact_expiration
from research_digest.run_locks import RunOwnerState, process_run_owner_state

if TYPE_CHECKING:
    from research_digest.preselection import AbstractPreselectionDecision

SOURCE_ARXIV = "arxiv"
SCHEMA_VERSION_KEY = "schema_version"
LAST_MIGRATION_BACKUP_KEY = "last_migration_backup_path"
CURRENT_SCHEMA_VERSION = 20
APP_RUN_STARTING = "STARTING"
APP_RUN_RUNNING = "RUNNING"
APP_RUN_COMPLETED = "COMPLETED"
APP_RUN_FAILED = "FAILED"
APP_RUN_ANALYSIS_UNAVAILABLE = "ANALYSIS_UNAVAILABLE"
APP_RUN_PARTIAL = "PARTIAL"
APP_RUN_CANCELLED = "CANCELLED"
DIGEST_RUN_LOCK = "digest"


class RunLockError(RuntimeError):
    """Raised when a digest run lock cannot be acquired."""


class RunAlreadyActiveError(RunLockError):
    """Raised when another digest run is already active."""


class AIConversationBusyError(RuntimeError):
    """Raised when another local session is already sending to a discussion."""


class AIConversationConflictError(RuntimeError):
    """Raised when a conversation changed during an optimistic turn append."""


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
class AbandonedRunRecovery:
    run_id: int
    recovered: bool
    status_before: str
    status_after: str
    retrieved_count: int
    stored_count: int
    preselected_count: int
    skipped_analysis_count: int
    analyzed_count: int
    relevant_count: int
    message: str


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

    def list_articles_for_source_date(
        self,
        *,
        source_name: str,
        source_date: date,
        categories: Iterable[str],
    ) -> tuple[Article, ...]:
        """Reconstruct an arXiv corpus for an already-proven covered source date."""

        category_set = set(canonical_arxiv_categories(tuple(categories)))
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM articles
                WHERE source = ?
                ORDER BY published_at DESC, id ASC
                """,
                (source_name,),
            ).fetchall()
        articles = (_article_from_row(row) for row in rows)
        return tuple(
            article
            for article in articles
            if source_date_from_datetime(article.published_at) == source_date
            and category_set.intersection(article.categories)
        )

    def save_library_article(self, article_id: int) -> LibraryEntry:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        saved_at = utc_now()
        now = datetime_to_db(saved_at)
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
            preferred_artifact_id = _preferred_summary_artifact_id(
                conn,
                article_id=article_id,
                now_text=now,
            )
            _retain_only_preferred_summary_artifact(
                conn,
                article_id=article_id,
                preferred_artifact_id=preferred_artifact_id,
                effective_at=saved_at,
            )
            entry = _get_library_entry(conn, article_id)
        if entry is None:
            raise ValueError(f"article {article_id} does not exist")
        return entry

    def unsave_library_article(self, article_id: int) -> None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        unsaved_at = utc_now()
        unsaved_at_text = datetime_to_db(unsaved_at)
        expires_at = datetime_to_db(temporary_artifact_expiration(unsaved_at))
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE library_articles
                SET saved = 0, updated_at = ?
                WHERE article_id = ?
                """,
                (unsaved_at_text, article_id),
            )
            conn.execute(
                """
                UPDATE ai_artifacts
                SET retention_class = ?, expires_at = ?
                WHERE article_id = ?
                  AND artifact_type IN (?, ?)
                  AND retention_class = ?
                """,
                (
                    AIArtifactRetentionClass.TEMPORARY.value,
                    expires_at,
                    article_id,
                    AIArtifactType.DIGEST_SUMMARY.value,
                    AIArtifactType.LIBRARY_SUMMARY.value,
                    AIArtifactRetentionClass.LIBRARY.value,
                ),
            )

    def set_library_reading_state(
        self,
        article_id: int,
        reading_state: ReadingState | None,
    ) -> LibraryEntry:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        normalized = ReadingState(reading_state).value if reading_state is not None else None
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE library_articles
                SET reading_state = ?, updated_at = ?
                WHERE article_id = ? AND saved = 1
                """,
                (normalized, datetime_to_db(utc_now()), article_id),
            )
            entry = _get_library_entry(conn, article_id)
        if cursor.rowcount != 1 or entry is None:
            raise ValueError(f"article {article_id} is not saved in the Library")
        return entry

    def set_library_interest_rating(
        self,
        article_id: int,
        interest_rating: int | None,
    ) -> LibraryEntry:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        if interest_rating is not None and (
            isinstance(interest_rating, bool)
            or not isinstance(interest_rating, int)
            or not 1 <= interest_rating <= 5
        ):
            raise ValueError("Library interest rating must be an integer between 1 and 5")
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE library_articles
                SET interest_rating = ?, updated_at = ?
                WHERE article_id = ? AND saved = 1
                """,
                (interest_rating, datetime_to_db(utc_now()), article_id),
            )
            entry = _get_library_entry(conn, article_id)
        if cursor.rowcount != 1 or entry is None:
            raise ValueError(f"article {article_id} is not saved in the Library")
        return entry

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
                    library_articles.updated_at AS library_updated_at,
                    library_articles.reading_state AS library_reading_state,
                    library_articles.interest_rating AS library_interest_rating
                FROM library_articles
                JOIN articles ON articles.id = library_articles.article_id
                WHERE library_articles.saved = 1
                ORDER BY library_articles.saved_at DESC, articles.title COLLATE NOCASE ASC
                """
            ).fetchall()
        return [_library_entry_from_row(row) for row in rows]

    def list_saved_library_notes(self) -> dict[int, LibraryNote]:
        """Load every saved-paper note in one bounded query."""

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT notes.*
                FROM library_article_notes AS notes
                JOIN library_articles
                    ON library_articles.article_id = notes.article_id
                WHERE library_articles.saved = 1
                ORDER BY notes.article_id ASC
                """
            ).fetchall()
        notes = (_library_note_from_row(row) for row in rows)
        return {note.article_id: note for note in notes}

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

    def create_ai_artifact(
        self,
        *,
        article_id: int,
        artifact_type: AIArtifactType,
        content: str,
        provider: str,
        model_id: str,
        reasoning_effort: str | None,
        generator_version: str,
        input_fingerprint: str,
        retention_class: AIArtifactRetentionClass,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> AIArtifact:
        created = created_at or utc_now()
        normalized_retention = AIArtifactRetentionClass(retention_class)
        expires: datetime | None
        if normalized_retention == AIArtifactRetentionClass.TEMPORARY:
            expires = expires_at or temporary_artifact_expiration(created)
        else:
            expires = expires_at
        artifact = AIArtifact(
            id=None,
            article_id=article_id,
            artifact_type=AIArtifactType(artifact_type),
            content=content,
            created_at=created,
            provider=provider,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            generator_version=generator_version,
            input_fingerprint=input_fingerprint,
            retention_class=normalized_retention,
            expires_at=expires,
        )
        with self._connection() as conn:
            if (
                artifact.retention_class == AIArtifactRetentionClass.LIBRARY
                and not _is_article_saved(conn, article_id)
            ):
                raise ValueError("LIBRARY artifacts require a saved Library article")
            return _insert_ai_artifact(conn, artifact)

    def get_ai_artifact(self, artifact_id: int) -> AIArtifact | None:
        if artifact_id <= 0:
            raise ValueError("AI artifact id must be positive")
        with self._connection() as conn:
            return _get_ai_artifact(conn, artifact_id)

    def get_ai_artifacts_by_ids(self, artifact_ids: Iterable[int]) -> dict[int, AIArtifact]:
        ids = sorted({int(artifact_id) for artifact_id in artifact_ids if int(artifact_id) > 0})
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ai_artifacts WHERE id IN ({placeholders}) ORDER BY id",
                tuple(ids),
            ).fetchall()
        artifacts = (_ai_artifact_from_row(row) for row in rows)
        return {artifact.id: artifact for artifact in artifacts if artifact.id is not None}

    def get_legacy_analysis_summaries(self, analysis_ids: Iterable[int]) -> dict[int, str]:
        ids = sorted({int(analysis_id) for analysis_id in analysis_ids if int(analysis_id) > 0})
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT id, summary
                FROM relevance_analyses
                WHERE id IN ({placeholders})
                  AND summary_artifact_id IS NULL
                  AND trim(summary) != ''
                ORDER BY id
                """,
                tuple(ids),
            ).fetchall()
        return {int(row["id"]): str(row["summary"]) for row in rows}

    def list_ai_artifacts(
        self,
        article_id: int,
        *,
        artifact_type: AIArtifactType | None = None,
    ) -> list[AIArtifact]:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        params: list[object] = [article_id]
        type_filter = ""
        if artifact_type is not None:
            type_filter = "AND artifact_type = ?"
            params.append(AIArtifactType(artifact_type).value)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM ai_artifacts
                WHERE article_id = ? {type_filter}
                ORDER BY created_at DESC, id DESC
                """,
                tuple(params),
            ).fetchall()
        return [_ai_artifact_from_row(row) for row in rows]

    def get_latest_usable_ai_artifact(
        self,
        *,
        article_id: int,
        artifact_type: AIArtifactType,
        now: datetime | None = None,
    ) -> AIArtifact | None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        now_text = datetime_to_db(now or utc_now())
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM ai_artifacts
                WHERE article_id = ?
                    AND artifact_type = ?
                    AND (
                        retention_class != ?
                        OR expires_at >= ?
                    )
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (
                    article_id,
                    AIArtifactType(artifact_type).value,
                    AIArtifactRetentionClass.TEMPORARY.value,
                    now_text,
                ),
            ).fetchone()
        return _ai_artifact_from_row(row) if row is not None else None

    def get_compatible_ai_artifact(
        self,
        *,
        article_id: int,
        artifact_type: AIArtifactType,
        provider: str,
        model_id: str,
        generator_version: str,
        input_fingerprint: str,
        now: datetime | None = None,
    ) -> AIArtifact | None:
        """Return the newest live artifact with the exact generation identity."""

        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            row = _get_compatible_ai_artifact(
                conn,
                article_id=article_id,
                artifact_type=artifact_type,
                provider=provider,
                model_id=model_id,
                generator_version=generator_version,
                input_fingerprint=input_fingerprint,
                now_text=datetime_to_db(now or utc_now()),
            )
        return _ai_artifact_from_row(row) if row is not None else None

    def persist_generated_digest_analysis(
        self,
        *,
        article_id: int,
        profile_id: int,
        profile_fingerprint: str,
        analysis: AnalysisResult,
        provenance: AIArtifactProvenance,
        created_at: datetime | None = None,
    ) -> AIArtifact:
        """Atomically store one new digest summary body and link analysis facts."""

        created = created_at or utc_now()
        with self._immediate_connection() as conn:
            saved_article = _is_article_saved(conn, article_id)
            existing_library_summary = _latest_usable_artifact_row(
                conn,
                article_id=article_id,
                artifact_type=AIArtifactType.LIBRARY_SUMMARY,
                now_text=datetime_to_db(created),
            )
            retain_digest = saved_article and existing_library_summary is None
            retention_class = (
                AIArtifactRetentionClass.LIBRARY
                if retain_digest
                else AIArtifactRetentionClass.TEMPORARY
            )
            artifact = AIArtifact(
                id=None,
                article_id=article_id,
                artifact_type=AIArtifactType.DIGEST_SUMMARY,
                content=analysis.summary,
                created_at=created,
                provider=provenance.provider,
                model_id=provenance.model_id,
                reasoning_effort=provenance.reasoning_effort,
                generator_version=provenance.generator_version,
                input_fingerprint=provenance.input_fingerprint,
                retention_class=retention_class,
                expires_at=(None if retain_digest else temporary_artifact_expiration(created)),
            )
            saved_artifact = _insert_ai_artifact(conn, artifact)
            assert saved_artifact.id is not None
            conn.execute(
                """
                INSERT INTO relevance_analyses (
                    article_id, profile_id, profile_fingerprint, relevance_score,
                    relevance_reason, matched_topics_json, summary, summary_artifact_id,
                    why_it_matters, reading_priority, analyzed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                ON CONFLICT(article_id, profile_id, profile_fingerprint) DO UPDATE SET
                    relevance_score = excluded.relevance_score,
                    relevance_reason = excluded.relevance_reason,
                    matched_topics_json = excluded.matched_topics_json,
                    summary = '',
                    summary_artifact_id = excluded.summary_artifact_id,
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
                    saved_artifact.id,
                    analysis.why_it_matters,
                    analysis.reading_priority,
                    datetime_to_db(created),
                ),
            )
            if saved_article:
                preferred_id = (
                    int(existing_library_summary["id"])
                    if existing_library_summary is not None
                    else saved_artifact.id
                )
                _retain_only_preferred_summary_artifact(
                    conn,
                    article_id=article_id,
                    preferred_artifact_id=preferred_id,
                    effective_at=created,
                )
            return saved_artifact

    def persist_library_summary(
        self,
        *,
        article_id: int,
        content: str,
        provenance: AIArtifactProvenance,
        regenerate: bool,
        created_at: datetime | None = None,
    ) -> tuple[AIArtifact, bool]:
        """Atomically reuse or replace the preferred explicit Library summary."""

        created = created_at or utc_now()
        now_text = datetime_to_db(created)
        with self._immediate_connection() as conn:
            if not _is_article_saved(conn, article_id):
                raise ValueError("Library summary generation requires a saved paper")
            if not regenerate:
                existing = _get_compatible_ai_artifact(
                    conn,
                    article_id=article_id,
                    artifact_type=AIArtifactType.LIBRARY_SUMMARY,
                    provider=provenance.provider,
                    model_id=provenance.model_id,
                    generator_version=provenance.generator_version,
                    input_fingerprint=provenance.input_fingerprint,
                    now_text=now_text,
                )
                if existing is not None:
                    artifact = _ai_artifact_from_row(existing)
                    assert artifact.id is not None
                    _retain_only_preferred_summary_artifact(
                        conn,
                        article_id=article_id,
                        preferred_artifact_id=artifact.id,
                        effective_at=created,
                    )
                    retained = _get_ai_artifact(conn, artifact.id)
                    if retained is None:
                        raise RuntimeError("reused Library summary disappeared")
                    return retained, True
            artifact = AIArtifact(
                id=None,
                article_id=article_id,
                artifact_type=AIArtifactType.LIBRARY_SUMMARY,
                content=content,
                created_at=created,
                provider=provenance.provider,
                model_id=provenance.model_id,
                reasoning_effort=provenance.reasoning_effort,
                generator_version=provenance.generator_version,
                input_fingerprint=provenance.input_fingerprint,
                retention_class=AIArtifactRetentionClass.LIBRARY,
                expires_at=None,
            )
            saved_artifact = _insert_ai_artifact(conn, artifact)
            assert saved_artifact.id is not None
            _retain_only_preferred_summary_artifact(
                conn,
                article_id=article_id,
                preferred_artifact_id=saved_artifact.id,
                effective_at=created,
            )
            return saved_artifact, False

    def set_ai_artifact_retention(
        self,
        artifact_id: int,
        *,
        retention_class: AIArtifactRetentionClass,
        effective_at: datetime | None = None,
    ) -> AIArtifact:
        if artifact_id <= 0:
            raise ValueError("AI artifact id must be positive")
        normalized = AIArtifactRetentionClass(retention_class)
        transition_at = effective_at or utc_now()
        expires_at = (
            datetime_to_db(temporary_artifact_expiration(transition_at))
            if normalized == AIArtifactRetentionClass.TEMPORARY
            else None
        )
        with self._connection() as conn:
            existing = _get_ai_artifact(conn, artifact_id)
            if existing is None:
                raise ValueError(f"AI artifact {artifact_id} does not exist")
            if normalized == AIArtifactRetentionClass.LIBRARY and not _is_article_saved(
                conn, existing.article_id
            ):
                raise ValueError("LIBRARY artifacts require a saved Library article")
            conn.execute(
                """
                UPDATE ai_artifacts
                SET retention_class = ?, expires_at = ?
                WHERE id = ?
                """,
                (normalized.value, expires_at, artifact_id),
            )
            updated = _get_ai_artifact(conn, artifact_id)
        if updated is None:
            raise RuntimeError("failed to load updated AI artifact")
        return updated

    def collect_expired_ai_artifacts(self, *, now: datetime | None = None) -> int:
        """Delete only expired temporary derived data with no durable owner."""

        now_text = datetime_to_db(now or utc_now())
        with self._immediate_connection() as conn:
            rows = conn.execute(
                """
                SELECT artifacts.id
                FROM ai_artifacts AS artifacts
                WHERE artifacts.retention_class = ?
                    AND artifacts.expires_at < ?
                    AND NOT EXISTS (
                        SELECT 1
                        FROM ai_conversations
                        WHERE ai_conversations.rolling_summary_artifact_id = artifacts.id
                    )
                ORDER BY artifacts.id
                """,
                (AIArtifactRetentionClass.TEMPORARY.value, now_text),
            ).fetchall()
            artifact_ids = [int(row["id"]) for row in rows]
            if artifact_ids:
                placeholders = ", ".join("?" for _ in artifact_ids)
                conn.execute(
                    f"DELETE FROM ai_artifacts WHERE id IN ({placeholders})",
                    tuple(artifact_ids),
                )
        return len(artifact_ids)

    def get_latest_legacy_digest_summary(
        self,
        article_id: int,
    ) -> ResolvedLibrarySummary | None:
        """Resolve the existing authoritative analysis cache without copying prose."""

        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT summary, analyzed_at
                FROM relevance_analyses
                WHERE article_id = ?
                  AND summary_artifact_id IS NULL
                  AND trim(summary) != ''
                ORDER BY analyzed_at DESC, id DESC
                LIMIT 1
                """,
                (article_id,),
            ).fetchone()
        if row is None:
            return None
        return ResolvedLibrarySummary(
            article_id=article_id,
            content=str(row["summary"]),
            source=LibrarySummarySource.LEGACY_DIGEST_ANALYSIS,
            created_at=datetime_from_db(str(row["analyzed_at"])),
        )

    def create_ai_conversation(
        self,
        *,
        article_id: int,
        title: str,
        provider: str,
        model_id: str,
        conversation_version: int = 1,
        rolling_summary_artifact_id: int | None = None,
        created_at: datetime | None = None,
    ) -> AIConversation:
        timestamp = created_at or utc_now()
        conversation = AIConversation(
            id=None,
            article_id=article_id,
            title=title,
            created_at=timestamp,
            updated_at=timestamp,
            provider=provider,
            model_id=model_id,
            conversation_version=conversation_version,
            rolling_summary_artifact_id=rolling_summary_artifact_id,
        )
        with self._connection() as conn:
            _validate_rolling_summary_artifact(
                conn,
                article_id=conversation.article_id,
                artifact_id=conversation.rolling_summary_artifact_id,
            )
            cursor = conn.execute(
                """
                INSERT INTO ai_conversations (
                    article_id, title, created_at, updated_at, provider, model_id,
                    conversation_version, rolling_summary_artifact_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation.article_id,
                    conversation.title,
                    datetime_to_db(conversation.created_at),
                    datetime_to_db(conversation.updated_at),
                    conversation.provider,
                    conversation.model_id,
                    conversation.conversation_version,
                    conversation.rolling_summary_artifact_id,
                ),
            )
            saved = _get_ai_conversation(conn, _lastrowid(cursor))
        if saved is None:
            raise RuntimeError("failed to load created AI conversation")
        return saved

    def get_ai_conversation(self, conversation_id: int) -> AIConversation | None:
        if conversation_id <= 0:
            raise ValueError("AI conversation id must be positive")
        with self._connection() as conn:
            return _get_ai_conversation(conn, conversation_id)

    def rename_ai_conversation(
        self,
        conversation_id: int,
        title: str,
    ) -> AIConversation:
        if conversation_id <= 0:
            raise ValueError("AI conversation id must be positive")
        with self._connection() as conn:
            existing = _get_ai_conversation(conn, conversation_id)
            if existing is None:
                raise ValueError(f"AI conversation {conversation_id} does not exist")
            candidate = AIConversation(
                id=existing.id,
                article_id=existing.article_id,
                title=title,
                created_at=existing.created_at,
                updated_at=utc_now(),
                provider=existing.provider,
                model_id=existing.model_id,
                conversation_version=existing.conversation_version,
                rolling_summary_artifact_id=existing.rolling_summary_artifact_id,
            )
            conn.execute(
                "UPDATE ai_conversations SET title = ?, updated_at = ? WHERE id = ?",
                (
                    candidate.title,
                    datetime_to_db(candidate.updated_at),
                    conversation_id,
                ),
            )
            updated = _get_ai_conversation(conn, conversation_id)
        if updated is None:
            raise RuntimeError("failed to load renamed AI conversation")
        return updated

    def list_ai_conversations(self, article_id: int) -> list[AIConversation]:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ai_conversations
                WHERE article_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (article_id,),
            ).fetchall()
        return [_ai_conversation_from_row(row) for row in rows]

    def set_ai_conversation_rolling_summary(
        self,
        conversation_id: int,
        artifact_id: int | None,
    ) -> AIConversation:
        if conversation_id <= 0:
            raise ValueError("AI conversation id must be positive")
        with self._connection() as conn:
            conversation = _get_ai_conversation(conn, conversation_id)
            if conversation is None:
                raise ValueError(f"AI conversation {conversation_id} does not exist")
            _validate_rolling_summary_artifact(
                conn,
                article_id=conversation.article_id,
                artifact_id=artifact_id,
            )
            conn.execute(
                """
                UPDATE ai_conversations
                SET rolling_summary_artifact_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (artifact_id, datetime_to_db(utc_now()), conversation_id),
            )
            updated = _get_ai_conversation(conn, conversation_id)
        if updated is None:
            raise RuntimeError("failed to load updated AI conversation")
        return updated

    def replace_ai_conversation_rolling_summary(
        self,
        *,
        conversation_id: int,
        content: str,
        provenance: AIArtifactProvenance,
        summarized_through_sequence: int,
        created_at: datetime | None = None,
    ) -> AIArtifact:
        """Atomically install one rolling summary and release its predecessor."""

        if conversation_id <= 0:
            raise ValueError("AI conversation id must be positive")
        if summarized_through_sequence <= 0:
            raise ValueError("summarized-through sequence must be positive")
        try:
            fingerprint_boundary = parse_rolling_summary_boundary(
                conversation_id=conversation_id,
                input_fingerprint=provenance.input_fingerprint,
            )
        except ValueError as exc:
            raise ValueError("rolling-summary input fingerprint is invalid") from exc
        if fingerprint_boundary != summarized_through_sequence:
            raise ValueError("rolling-summary boundary does not match its input fingerprint")
        created = created_at or utc_now()
        with self._immediate_connection() as conn:
            conversation = _get_ai_conversation(conn, conversation_id)
            if conversation is None:
                raise ValueError(f"AI conversation {conversation_id} does not exist")
            if not _is_article_saved(conn, conversation.article_id):
                raise ValueError("rolling-summary generation requires a saved Library paper")
            boundary = conn.execute(
                """
                SELECT role
                FROM ai_conversation_messages
                WHERE conversation_id = ? AND sequence_number = ?
                """,
                (conversation_id, summarized_through_sequence),
            ).fetchone()
            if boundary is None or str(boundary["role"]) != AIConversationRole.ASSISTANT.value:
                raise ValueError("rolling summary must end at a stored assistant message")
            artifact = AIArtifact(
                id=None,
                article_id=conversation.article_id,
                artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
                content=content,
                created_at=created,
                provider=provenance.provider,
                model_id=provenance.model_id,
                reasoning_effort=provenance.reasoning_effort,
                generator_version=provenance.generator_version,
                input_fingerprint=provenance.input_fingerprint,
                retention_class=AIArtifactRetentionClass.LIBRARY,
                expires_at=None,
            )
            saved = _insert_ai_artifact(conn, artifact)
            if saved.id is None:
                raise RuntimeError("persisted rolling summary id is required")
            previous_id = conversation.rolling_summary_artifact_id
            conn.execute(
                """
                UPDATE ai_conversations
                SET rolling_summary_artifact_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (saved.id, datetime_to_db(created), conversation_id),
            )
            if previous_id is not None and previous_id != saved.id:
                still_referenced = conn.execute(
                    """
                    SELECT 1
                    FROM ai_conversations
                    WHERE rolling_summary_artifact_id = ?
                    LIMIT 1
                    """,
                    (previous_id,),
                ).fetchone()
                if still_referenced is None:
                    conn.execute(
                        """
                        UPDATE ai_artifacts
                        SET retention_class = ?, expires_at = ?
                        WHERE id = ? AND retention_class != ?
                        """,
                        (
                            AIArtifactRetentionClass.TEMPORARY.value,
                            datetime_to_db(temporary_artifact_expiration(created)),
                            previous_id,
                            AIArtifactRetentionClass.USER_PINNED.value,
                        ),
                    )
            return saved

    def acquire_ai_conversation_send_lock(
        self,
        conversation_id: int,
        *,
        owner: str,
        stale_after_seconds: float,
        now: datetime | None = None,
    ) -> None:
        """Acquire a durable per-conversation lease before any provider call."""

        if conversation_id <= 0:
            raise ValueError("AI conversation id must be positive")
        if not owner.strip():
            raise ValueError("conversation send-lock owner is required")
        if stale_after_seconds <= 0:
            raise ValueError("conversation send-lock stale interval must be positive")
        acquired = now or utc_now()
        name = _ai_conversation_lock_name(conversation_id)
        with self._immediate_connection() as conn:
            if _get_ai_conversation(conn, conversation_id) is None:
                raise ValueError(f"AI conversation {conversation_id} does not exist")
            existing = conn.execute(
                "SELECT acquired_at FROM run_locks WHERE name = ?",
                (name,),
            ).fetchone()
            if existing is not None:
                locked_at = datetime_from_db(str(existing["acquired_at"]))
                if locked_at > acquired - timedelta(seconds=stale_after_seconds):
                    raise AIConversationBusyError(
                        "Another session is already sending to this discussion."
                    )
                conn.execute("DELETE FROM run_locks WHERE name = ?", (name,))
            timestamp = datetime_to_db(acquired)
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, owner, timestamp, timestamp),
            )

    def release_ai_conversation_send_lock(
        self,
        conversation_id: int,
        *,
        owner: str,
    ) -> None:
        if conversation_id <= 0:
            raise ValueError("AI conversation id must be positive")
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM run_locks WHERE name = ? AND owner = ?",
                (_ai_conversation_lock_name(conversation_id), owner),
            )

    def begin_ai_conversation_turn(
        self,
        *,
        conversation_id: int,
        content: str,
        expected_last_sequence: int,
        created_at: datetime | None = None,
    ) -> AIConversationMessage:
        """Append a user message only if the durable transcript has not changed."""

        if expected_last_sequence < 0:
            raise ValueError("expected conversation sequence must not be negative")
        timestamp = created_at or utc_now()
        with self._immediate_connection() as conn:
            if _get_ai_conversation(conn, conversation_id) is None:
                raise ValueError(f"AI conversation {conversation_id} does not exist")
            last = _last_ai_conversation_message_row(conn, conversation_id)
            actual_sequence = int(last["sequence_number"]) if last is not None else 0
            if actual_sequence != expected_last_sequence:
                raise AIConversationConflictError(
                    "The discussion changed in another session; reload before sending."
                )
            if last is not None and str(last["role"]) == AIConversationRole.USER.value:
                raise AIConversationConflictError(
                    "This discussion already has an unanswered user message."
                )
            message = AIConversationMessage(
                id=None,
                conversation_id=conversation_id,
                sequence_number=actual_sequence + 1,
                role=AIConversationRole.USER,
                content=content,
                created_at=timestamp,
            )
            return _insert_ai_conversation_message(conn, message)

    def complete_ai_conversation_turn(
        self,
        *,
        conversation_id: int,
        pending_user_message_id: int,
        content: str,
        provider: str,
        model_id: str,
        conversation_version: int,
        created_at: datetime | None = None,
    ) -> AIConversationMessage:
        """Append one assistant response only to the exact pending user turn."""

        timestamp = created_at or utc_now()
        with self._immediate_connection() as conn:
            conversation = _get_ai_conversation(conn, conversation_id)
            if conversation is None:
                raise ValueError(f"AI conversation {conversation_id} does not exist")
            last = _last_ai_conversation_message_row(conn, conversation_id)
            if (
                last is None
                or int(last["id"]) != pending_user_message_id
                or str(last["role"]) != AIConversationRole.USER.value
            ):
                raise AIConversationConflictError(
                    "The pending conversation turn changed before the response was saved."
                )
            candidate = AIConversation(
                id=conversation.id,
                article_id=conversation.article_id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=timestamp,
                provider=provider,
                model_id=model_id,
                conversation_version=conversation_version,
                rolling_summary_artifact_id=conversation.rolling_summary_artifact_id,
            )
            message = AIConversationMessage(
                id=None,
                conversation_id=conversation_id,
                sequence_number=int(last["sequence_number"]) + 1,
                role=AIConversationRole.ASSISTANT,
                content=content,
                created_at=timestamp,
            )
            saved = _insert_ai_conversation_message(conn, message)
            conn.execute(
                """
                UPDATE ai_conversations
                SET updated_at = ?, provider = ?, model_id = ?, conversation_version = ?
                WHERE id = ?
                """,
                (
                    datetime_to_db(candidate.updated_at),
                    candidate.provider,
                    candidate.model_id,
                    candidate.conversation_version,
                    conversation_id,
                ),
            )
            return saved

    def append_ai_conversation_message(
        self,
        *,
        conversation_id: int,
        role: AIConversationRole,
        content: str,
        created_at: datetime | None = None,
    ) -> AIConversationMessage:
        timestamp = created_at or utc_now()
        normalized_role = AIConversationRole(role)
        with self._immediate_connection() as conn:
            if _get_ai_conversation(conn, conversation_id) is None:
                raise ValueError(f"AI conversation {conversation_id} does not exist")
            row = conn.execute(
                """
                SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_sequence
                FROM ai_conversation_messages
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to allocate AI conversation sequence")
            message = AIConversationMessage(
                id=None,
                conversation_id=conversation_id,
                sequence_number=int(row["next_sequence"]),
                role=normalized_role,
                content=content,
                created_at=timestamp,
            )
            cursor = conn.execute(
                """
                INSERT INTO ai_conversation_messages (
                    conversation_id, sequence_number, role, content, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    message.conversation_id,
                    message.sequence_number,
                    message.role.value,
                    message.content,
                    datetime_to_db(message.created_at),
                ),
            )
            conn.execute(
                "UPDATE ai_conversations SET updated_at = ? WHERE id = ?",
                (datetime_to_db(message.created_at), conversation_id),
            )
            saved = _get_ai_conversation_message(conn, _lastrowid(cursor))
        if saved is None:
            raise RuntimeError("failed to load created AI conversation message")
        return saved

    def list_ai_conversation_messages(
        self,
        conversation_id: int,
    ) -> list[AIConversationMessage]:
        if conversation_id <= 0:
            raise ValueError("AI conversation id must be positive")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM ai_conversation_messages
                WHERE conversation_id = ?
                ORDER BY sequence_number ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [_ai_conversation_message_from_row(row) for row in rows]

    def get_ai_conversation_message(
        self,
        message_id: int,
    ) -> AIConversationMessage | None:
        if message_id <= 0:
            raise ValueError("AI conversation message id must be positive")
        with self._connection() as conn:
            return _get_ai_conversation_message(conn, message_id)

    def list_ai_conversation_overviews(
        self,
        article_id: int,
    ) -> list[tuple[AIConversation, int]]:
        """Load conversation headers and message counts without per-thread queries."""

        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    conversations.*,
                    COUNT(messages.id) AS message_count
                FROM ai_conversations AS conversations
                LEFT JOIN ai_conversation_messages AS messages
                    ON messages.conversation_id = conversations.id
                WHERE conversations.article_id = ?
                GROUP BY conversations.id
                ORDER BY conversations.updated_at DESC, conversations.id DESC
                """,
                (article_id,),
            ).fetchall()
        return [(_ai_conversation_from_row(row), int(row["message_count"])) for row in rows]

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

    def list_latest_saved_library_relevance_contexts(
        self,
    ) -> dict[int, LibraryRelevanceContext]:
        """Load the newest analysis context for every saved paper without N+1 reads."""

        with self._connection() as conn:
            rows = conn.execute(
                """
                WITH ranked_contexts AS (
                    SELECT
                        relevance_analyses.article_id,
                        relevance_analyses.profile_id,
                        interest_profiles.name AS profile_name,
                        relevance_analyses.relevance_score,
                        relevance_analyses.reading_priority,
                        relevance_analyses.analyzed_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY relevance_analyses.article_id
                            ORDER BY
                                relevance_analyses.analyzed_at DESC,
                                relevance_analyses.id DESC
                        ) AS context_rank
                    FROM relevance_analyses
                    JOIN interest_profiles
                        ON interest_profiles.id = relevance_analyses.profile_id
                    JOIN library_articles
                        ON library_articles.article_id = relevance_analyses.article_id
                    WHERE library_articles.saved = 1
                )
                SELECT *
                FROM ranked_contexts
                WHERE context_rank = 1
                ORDER BY article_id ASC
                """
            ).fetchall()
        return {int(row["article_id"]): _library_relevance_context_from_row(row) for row in rows}

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

    def list_saved_library_tag_assignments(
        self,
    ) -> dict[int, list[LibraryTagAssignment]]:
        """Load normalized tag relationships for all saved papers in one query."""

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
                JOIN library_articles
                    ON library_articles.article_id = assignments.article_id
                WHERE library_articles.saved = 1
                ORDER BY
                    assignments.article_id ASC,
                    assignments.origin DESC,
                    tags.display_name COLLATE NOCASE ASC,
                    tags.id ASC
                """
            ).fetchall()
        assignments_by_article: dict[int, list[LibraryTagAssignment]] = {}
        for row in rows:
            assignment = _library_tag_assignment_from_row(row)
            assignments_by_article.setdefault(assignment.article_id, []).append(assignment)
        return assignments_by_article

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

    def list_saved_library_collections_by_article(
        self,
    ) -> dict[int, list[LibraryCollection]]:
        """Load normalized collection pointers for all saved papers in one query."""

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    memberships.article_id AS membership_article_id,
                    collections.*
                FROM library_collection_memberships AS memberships
                JOIN library_collections AS collections
                    ON collections.id = memberships.collection_id
                JOIN library_articles
                    ON library_articles.article_id = memberships.article_id
                WHERE library_articles.saved = 1
                ORDER BY
                    memberships.article_id ASC,
                    collections.name COLLATE NOCASE ASC,
                    collections.id ASC
                """
            ).fetchall()
        collections_by_article: dict[int, list[LibraryCollection]] = {}
        for row in rows:
            article_id = int(row["membership_article_id"])
            collections_by_article.setdefault(article_id, []).append(
                _library_collection_from_row(row)
            )
        return collections_by_article

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

    def upsert_library_search_document(
        self,
        *,
        article_id: int,
        document_text: str,
    ) -> LibrarySearchDocument:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        text = document_text.strip()
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_search_documents (article_id, document_text, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    document_text = excluded.document_text,
                    updated_at = excluded.updated_at
                """,
                (article_id, text, now),
            )
            document = _get_library_search_document(conn, article_id)
        if document is None:
            raise RuntimeError("failed to load library search document")
        return document

    def get_library_search_document(self, article_id: int) -> LibrarySearchDocument | None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            return _get_library_search_document(conn, article_id)

    def delete_library_search_document(self, article_id: int) -> None:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM library_search_documents WHERE article_id = ?",
                (article_id,),
            )

    def prune_library_search_documents(self, saved_article_ids: Iterable[int]) -> None:
        ids = sorted({int(article_id) for article_id in saved_article_ids if int(article_id) > 0})
        with self._connection() as conn:
            if not ids:
                conn.execute("DELETE FROM library_search_documents")
                return
            placeholders = ", ".join("?" for _ in ids)
            conn.execute(
                f"""
                DELETE FROM library_search_documents
                WHERE article_id NOT IN ({placeholders})
                """,
                tuple(ids),
            )

    def search_library_document_article_ids(self, query: str) -> list[int]:
        needle = query.strip().casefold()
        if not needle:
            return []
        pattern = f"%{_escape_like(needle)}%"
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT docs.article_id
                FROM library_search_documents AS docs
                JOIN library_articles ON library_articles.article_id = docs.article_id
                WHERE library_articles.saved = 1
                    AND docs.document_text LIKE ? ESCAPE '\\'
                ORDER BY library_articles.saved_at DESC, docs.article_id ASC
                """,
                (pattern,),
            ).fetchall()
        return [int(row["article_id"]) for row in rows]

    def search_saved_library_content_article_ids(self, query: str) -> list[int]:
        """Search normalized saved-paper content in one read-only SQLite query."""

        needle = query.strip().casefold()
        if not needle:
            return []
        pattern = f"%{_escape_like(needle)}%"
        params = (pattern,) * 13
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT library_articles.article_id
                FROM library_articles
                JOIN articles ON articles.id = library_articles.article_id
                LEFT JOIN library_article_notes AS notes
                    ON notes.article_id = articles.id
                WHERE library_articles.saved = 1
                  AND (
                    lower(articles.title) LIKE ? ESCAPE '\\'
                    OR lower(articles.authors_json) LIKE ? ESCAPE '\\'
                    OR lower(articles.abstract) LIKE ? ESCAPE '\\'
                    OR lower(articles.categories_json) LIKE ? ESCAPE '\\'
                    OR lower(articles.source) LIKE ? ESCAPE '\\'
                    OR lower(articles.source_article_id) LIKE ? ESCAPE '\\'
                    OR lower(COALESCE(notes.note_text, '')) LIKE ? ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1
                        FROM library_tag_assignments AS assignments
                        JOIN library_tags AS tags ON tags.id = assignments.tag_id
                        WHERE assignments.article_id = articles.id
                          AND (
                            lower(tags.display_name) LIKE ? ESCAPE '\\'
                            OR lower(tags.normalized_name) LIKE ? ESCAPE '\\'
                          )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM library_collection_memberships AS memberships
                        JOIN library_collections AS collections
                            ON collections.id = memberships.collection_id
                        WHERE memberships.article_id = articles.id
                          AND (
                            lower(collections.name) LIKE ? ESCAPE '\\'
                            OR lower(collections.description) LIKE ? ESCAPE '\\'
                          )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM relevance_analyses
                        JOIN interest_profiles
                            ON interest_profiles.id = relevance_analyses.profile_id
                        WHERE relevance_analyses.article_id = articles.id
                          AND (
                            lower(interest_profiles.name) LIKE ? ESCAPE '\\'
                            OR lower(relevance_analyses.reading_priority) LIKE ? ESCAPE '\\'
                          )
                    )
                  )
                ORDER BY library_articles.saved_at DESC, articles.id ASC
                """,
                params,
            ).fetchall()
        return [int(row["article_id"]) for row in rows]

    def upsert_library_connection(
        self,
        *,
        article_id_a: int,
        article_id_b: int,
        relation_label: str,
        rationale: str,
        provenance: dict[str, object],
        confidence: float | None = None,
        origin: ConnectionOrigin = ConnectionOrigin.AI,
        revive: bool = False,
    ) -> LibraryConnection:
        first, second = _canonical_article_pair(article_id_a, article_id_b)
        label = relation_label.strip()
        reason = rationale.strip()
        if not label:
            raise ValueError("connection relation label is required")
        if not reason:
            raise ValueError("connection rationale is required")
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("connection confidence must be between 0 and 1")
        generated_at = datetime_to_db(utc_now())
        provenance_json = json.dumps(provenance, sort_keys=True)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_article_connections (
                    article_id_a, article_id_b, relation_label, rationale, origin,
                    provenance_json, confidence, generated_at, dismissed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(article_id_a, article_id_b) DO UPDATE SET
                    relation_label = excluded.relation_label,
                    rationale = excluded.rationale,
                    origin = excluded.origin,
                    provenance_json = excluded.provenance_json,
                    confidence = excluded.confidence,
                    generated_at = excluded.generated_at,
                    dismissed_at = CASE
                        WHEN ? THEN NULL
                        ELSE library_article_connections.dismissed_at
                    END
                """,
                (
                    first,
                    second,
                    label,
                    reason,
                    ConnectionOrigin(origin).value,
                    provenance_json,
                    confidence,
                    generated_at,
                    int(revive),
                ),
            )
            connection = _get_library_connection_by_pair(conn, first, second)
        if connection is None:
            raise RuntimeError("failed to load library connection")
        return connection

    def dismiss_library_connection(
        self,
        *,
        article_id_a: int,
        article_id_b: int,
    ) -> None:
        first, second = _canonical_article_pair(article_id_a, article_id_b)
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE library_article_connections
                SET dismissed_at = ?
                WHERE article_id_a = ? AND article_id_b = ?
                """,
                (datetime_to_db(utc_now()), first, second),
            )

    def get_library_connection_by_pair(
        self,
        article_id_a: int,
        article_id_b: int,
    ) -> LibraryConnection | None:
        first, second = _canonical_article_pair(article_id_a, article_id_b)
        with self._connection() as conn:
            return _get_library_connection_by_pair(conn, first, second)

    def list_library_connections_for_article(
        self,
        article_id: int,
        *,
        include_dismissed: bool = False,
    ) -> list[LibraryConnection]:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        where = "(article_id_a = ? OR article_id_b = ?)"
        params: list[object] = [article_id, article_id]
        if not include_dismissed:
            where += " AND dismissed_at IS NULL"
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM library_article_connections
                WHERE {where}
                ORDER BY generated_at DESC, id DESC
                """,
                tuple(params),
            ).fetchall()
        return [_library_connection_from_row(row) for row in rows]

    def list_library_connections(
        self,
        *,
        include_dismissed: bool = True,
    ) -> list[LibraryConnection]:
        where = "" if include_dismissed else "WHERE dismissed_at IS NULL"
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM library_article_connections
                {where}
                ORDER BY article_id_a ASC, article_id_b ASC
                """
            ).fetchall()
        return [_library_connection_from_row(row) for row in rows]

    def upsert_library_context_suggestion(
        self,
        *,
        run_id: int | None,
        article_id: int,
        related_article_id: int,
        collection_id: int | None,
        relation_label: str,
        rationale: str,
        provenance: dict[str, object],
        confidence: float | None = None,
        origin: LibraryContextOrigin = LibraryContextOrigin.AI,
        revive: bool = False,
    ) -> LibraryContextSuggestion:
        if run_id is not None and run_id <= 0:
            raise ValueError("run id must be positive")
        if article_id <= 0 or related_article_id <= 0:
            raise ValueError("article ids must be positive")
        if article_id == related_article_id:
            raise ValueError("context suggestion cannot link an article to itself")
        if collection_id is not None and collection_id <= 0:
            raise ValueError("collection id must be positive")
        label = relation_label.strip()
        reason = rationale.strip()
        if not label:
            raise ValueError("context relation label is required")
        if not reason:
            raise ValueError("context rationale is required")
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("context confidence must be between 0 and 1")
        created_at = datetime_to_db(utc_now())
        provenance_json = json.dumps(provenance, sort_keys=True)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO library_context_suggestions (
                    run_id, article_id, related_article_id, collection_id, relation_label,
                    rationale, origin, provenance_json, confidence, created_at, dismissed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(article_id, related_article_id, collection_key) DO UPDATE SET
                    run_id = excluded.run_id,
                    relation_label = excluded.relation_label,
                    rationale = excluded.rationale,
                    origin = excluded.origin,
                    provenance_json = excluded.provenance_json,
                    confidence = excluded.confidence,
                    created_at = excluded.created_at,
                    dismissed_at = CASE
                        WHEN ? THEN NULL
                        ELSE library_context_suggestions.dismissed_at
                    END
                """,
                (
                    run_id,
                    article_id,
                    related_article_id,
                    collection_id,
                    label,
                    reason,
                    LibraryContextOrigin(origin).value,
                    provenance_json,
                    confidence,
                    created_at,
                    int(revive),
                ),
            )
            suggestion = _get_library_context_suggestion(
                conn,
                article_id=article_id,
                related_article_id=related_article_id,
                collection_id=collection_id,
            )
        if suggestion is None:
            raise RuntimeError("failed to load library context suggestion")
        return suggestion

    def dismiss_library_context_suggestion(self, suggestion_id: int) -> None:
        if suggestion_id <= 0:
            raise ValueError("suggestion id must be positive")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE library_context_suggestions
                SET dismissed_at = ?
                WHERE id = ?
                """,
                (datetime_to_db(utc_now()), suggestion_id),
            )

    def list_library_context_suggestions_for_article(
        self,
        article_id: int,
        *,
        include_dismissed: bool = False,
    ) -> list[LibraryContextSuggestion]:
        if article_id <= 0:
            raise ValueError("article id must be positive")
        where = "article_id = ?"
        if not include_dismissed:
            where += " AND dismissed_at IS NULL"
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM library_context_suggestions
                WHERE {where}
                ORDER BY created_at DESC, id DESC
                """,
                (article_id,),
            ).fetchall()
        return [_library_context_suggestion_from_row(row) for row in rows]

    def list_library_context_suggestions(
        self,
        *,
        include_dismissed: bool = True,
    ) -> list[LibraryContextSuggestion]:
        where = "" if include_dismissed else "WHERE dismissed_at IS NULL"
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM library_context_suggestions
                {where}
                ORDER BY article_id ASC, related_article_id ASC, id ASC
                """
            ).fetchall()
        return [_library_context_suggestion_from_row(row) for row in rows]

    def save_collection_intelligence_snapshot(
        self,
        *,
        collection_id: int,
        title: str,
        summary: str,
        evidence: dict[str, object],
        provenance: dict[str, object],
        origin: LibraryContextOrigin = LibraryContextOrigin.DETERMINISTIC,
    ) -> CollectionIntelligenceSnapshot:
        if collection_id <= 0:
            raise ValueError("collection id must be positive")
        if not title.strip():
            raise ValueError("collection intelligence title is required")
        if not summary.strip():
            raise ValueError("collection intelligence summary is required")
        generated_at = datetime_to_db(utc_now())
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO collection_intelligence_snapshots (
                    collection_id, title, summary, evidence_json, origin, provenance_json,
                    generated_at, dismissed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    collection_id,
                    title.strip(),
                    summary.strip(),
                    json.dumps(evidence, sort_keys=True),
                    LibraryContextOrigin(origin).value,
                    json.dumps(provenance, sort_keys=True),
                    generated_at,
                ),
            )
            snapshot = _get_collection_intelligence_snapshot(conn, _lastrowid(cursor))
        if snapshot is None:
            raise RuntimeError("failed to load collection intelligence snapshot")
        return snapshot

    def dismiss_collection_intelligence_snapshot(self, snapshot_id: int) -> None:
        if snapshot_id <= 0:
            raise ValueError("snapshot id must be positive")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE collection_intelligence_snapshots
                SET dismissed_at = ?
                WHERE id = ?
                """,
                (datetime_to_db(utc_now()), snapshot_id),
            )

    def list_collection_intelligence_snapshots(
        self,
        collection_id: int | None = None,
        *,
        include_dismissed: bool = False,
    ) -> list[CollectionIntelligenceSnapshot]:
        params: list[object] = []
        clauses: list[str] = []
        if collection_id is not None:
            if collection_id <= 0:
                raise ValueError("collection id must be positive")
            clauses.append("collection_id = ?")
            params.append(collection_id)
        if not include_dismissed:
            clauses.append("dismissed_at IS NULL")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM collection_intelligence_snapshots
                {where}
                ORDER BY generated_at DESC, id DESC
                """,
                tuple(params),
            ).fetchall()
        return [_collection_intelligence_snapshot_from_row(row) for row in rows]

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
        now_text = datetime_to_db(utc_now())
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT
                    analyses.*,
                    CASE
                        WHEN artifacts.id IS NOT NULL
                         AND (
                            artifacts.retention_class != ?
                            OR artifacts.expires_at >= ?
                         )
                        THEN artifacts.content
                        ELSE analyses.summary
                    END AS resolved_summary
                FROM relevance_analyses AS analyses
                LEFT JOIN ai_artifacts AS artifacts
                    ON artifacts.id = analyses.summary_artifact_id
                WHERE analyses.article_id = ?
                  AND analyses.profile_id = ?
                  AND analyses.profile_fingerprint = ?
                """,
                (
                    AIArtifactRetentionClass.TEMPORARY.value,
                    now_text,
                    article_id,
                    profile_id,
                    profile_fingerprint,
                ),
            ).fetchone()
        if row is None or not str(row["resolved_summary"]).strip():
            return None
        return _analysis_from_row(row, summary_column="resolved_summary")

    def list_analysis_summary_references(
        self,
        *,
        article_ids: Iterable[int],
        profile_id: int,
        profile_fingerprint: str,
    ) -> dict[int, AnalysisSummaryReference]:
        """Batch stable summary ownership metadata for one digest snapshot."""

        ids = sorted({int(article_id) for article_id in article_ids if int(article_id) > 0})
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    analyses.id AS analysis_id,
                    analyses.article_id,
                    analyses.summary_artifact_id,
                    analyses.analyzed_at,
                    artifacts.provider,
                    artifacts.model_id,
                    artifacts.reasoning_effort,
                    artifacts.generator_version
                FROM relevance_analyses AS analyses
                LEFT JOIN ai_artifacts AS artifacts
                    ON artifacts.id = analyses.summary_artifact_id
                WHERE analyses.article_id IN ({placeholders})
                  AND analyses.profile_id = ?
                  AND analyses.profile_fingerprint = ?
                ORDER BY analyses.article_id
                """,
                (*ids, profile_id, profile_fingerprint),
            ).fetchall()
        references: dict[int, AnalysisSummaryReference] = {}
        for row in rows:
            artifact_id = row["summary_artifact_id"]
            storage = (
                AnalysisSummaryStorage.ARTIFACT
                if artifact_id is not None and row["provider"] is not None
                else AnalysisSummaryStorage.LEGACY_INLINE
            )
            references[int(row["article_id"])] = AnalysisSummaryReference(
                analysis_id=int(row["analysis_id"]),
                article_id=int(row["article_id"]),
                storage=storage,
                artifact_id=(
                    int(artifact_id) if storage == AnalysisSummaryStorage.ARTIFACT else None
                ),
                analyzed_at=datetime_from_db(str(row["analyzed_at"])),
                provider=str(row["provider"]) if row["provider"] is not None else None,
                model_id=str(row["model_id"]) if row["model_id"] is not None else None,
                reasoning_effort=(
                    str(row["reasoning_effort"]) if row["reasoning_effort"] is not None else None
                ),
                generator_version=(
                    str(row["generator_version"]) if row["generator_version"] is not None else None
                ),
            )
        return references

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
                    summary_artifact_id = NULL,
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

    def get_quantitative_calibration_for_run(
        self,
        run_id: int,
    ) -> QuantitativeRelevanceCalibration | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM quantitative_relevance_calibrations WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return _quantitative_calibration_from_row(row) if row is not None else None

    def list_quantitative_calibrations(
        self,
        *,
        profile_id: int | None = None,
        state: str | None = None,
    ) -> list[QuantitativeRelevanceCalibration]:
        clauses: list[str] = []
        params: list[object] = []
        if profile_id is not None:
            clauses.append("profile_id = ?")
            params.append(profile_id)
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM quantitative_relevance_calibrations
                {where}
                ORDER BY created_at DESC, id DESC
                """,
                tuple(params),
            ).fetchall()
        return [_quantitative_calibration_from_row(row) for row in rows]

    def has_completed_quantitative_calibration(
        self,
        *,
        article_id: int,
        profile_id: int,
    ) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM quantitative_relevance_calibrations
                WHERE article_id = ?
                    AND profile_id = ?
                    AND state = 'COMPLETED'
                LIMIT 1
                """,
                (article_id, profile_id),
            ).fetchone()
        return row is not None

    def create_quantitative_calibration_skipped(
        self,
        *,
        run_id: int,
        profile_id: int,
        profile_fingerprint: str,
    ) -> QuantitativeRelevanceCalibration:
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO quantitative_relevance_calibrations (
                    run_id, profile_id, profile_fingerprint, state, created_at
                )
                VALUES (?, ?, ?, 'SKIPPED', ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (run_id, profile_id, profile_fingerprint, now),
            )
            row = conn.execute(
                "SELECT * FROM quantitative_relevance_calibrations WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to load calibration sampling decision")
        return _quantitative_calibration_from_row(row)

    def create_quantitative_calibration_prompt(
        self,
        *,
        run_id: int,
        article_id: int,
        profile_id: int,
        profile_fingerprint: str,
        model_relevance_score: float,
    ) -> QuantitativeRelevanceCalibration:
        if model_relevance_score < 0 or model_relevance_score > 1:
            raise ValueError("model relevance score must be between 0 and 1")
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO quantitative_relevance_calibrations (
                    run_id, article_id, profile_id, profile_fingerprint,
                    model_relevance_score, state, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (
                    run_id,
                    article_id,
                    profile_id,
                    profile_fingerprint,
                    model_relevance_score,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM quantitative_relevance_calibrations WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to load calibration prompt")
        return _quantitative_calibration_from_row(row)

    def complete_quantitative_calibration(
        self,
        *,
        calibration_id: int,
        user_relevance_score: float,
    ) -> QuantitativeRelevanceCalibration:
        if user_relevance_score < 0 or user_relevance_score > 1:
            raise ValueError("user relevance score must be between 0 and 1")
        completed_at = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE quantitative_relevance_calibrations
                SET state = 'COMPLETED',
                    user_relevance_score = ?,
                    completed_at = ?
                WHERE id = ? AND state = 'PENDING'
                """,
                (user_relevance_score, completed_at, calibration_id),
            )
            row = conn.execute(
                "SELECT * FROM quantitative_relevance_calibrations WHERE id = ?",
                (calibration_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"calibration {calibration_id} does not exist")
        return _quantitative_calibration_from_row(row)

    def dismiss_quantitative_calibration(
        self,
        *,
        calibration_id: int,
    ) -> QuantitativeRelevanceCalibration:
        completed_at = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE quantitative_relevance_calibrations
                SET state = 'DISMISSED',
                    completed_at = ?
                WHERE id = ? AND state = 'PENDING'
                """,
                (completed_at, calibration_id),
            )
            row = conn.execute(
                "SELECT * FROM quantitative_relevance_calibrations WHERE id = ?",
                (calibration_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"calibration {calibration_id} does not exist")
        return _quantitative_calibration_from_row(row)

    def upsert_article_feedback(
        self,
        *,
        article_id: int,
        profile_id: int,
        profile_fingerprint: str,
        feedback_label: FeedbackLabel | None = None,
        profile_match: FeedbackAnswer | None = None,
        personal_interest: FeedbackAnswer | None = None,
        clear_profile_match: bool = False,
        clear_personal_interest: bool = False,
    ) -> ArticleFeedback:
        if clear_profile_match and (feedback_label is not None or profile_match is not None):
            raise ValueError("profile match cannot be both answered and cleared")
        if clear_personal_interest and personal_interest is not None:
            raise ValueError("personal interest cannot be both answered and cleared")
        if profile_match is None and feedback_label is not None:
            profile_match = "YES" if feedback_label == "RELEVANT" else "NO"
        if feedback_label is None and profile_match is not None:
            feedback_label = "RELEVANT" if profile_match == "YES" else "NOT_RELEVANT"
        if (
            feedback_label is None
            and profile_match is None
            and personal_interest is None
            and not clear_profile_match
            and not clear_personal_interest
        ):
            raise ValueError("at least one feedback answer is required")
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO article_feedback (
                    article_id, profile_id, profile_fingerprint, feedback_label,
                    profile_match, personal_interest, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id, profile_id, profile_fingerprint) DO UPDATE SET
                    feedback_label = CASE
                        WHEN ? THEN NULL
                        ELSE COALESCE(
                            excluded.feedback_label,
                            article_feedback.feedback_label
                        )
                    END,
                    profile_match = CASE
                        WHEN ? THEN NULL
                        ELSE COALESCE(
                            excluded.profile_match,
                            article_feedback.profile_match
                        )
                    END,
                    personal_interest = CASE
                        WHEN ? THEN NULL
                        ELSE COALESCE(
                            excluded.personal_interest,
                            article_feedback.personal_interest
                        )
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    article_id,
                    profile_id,
                    profile_fingerprint,
                    feedback_label,
                    profile_match,
                    personal_interest,
                    now,
                    now,
                    int(clear_profile_match),
                    int(clear_profile_match),
                    int(clear_personal_interest),
                ),
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

    def list_new_interest_feedback(
        self,
        *,
        profile_id: int,
        profile_fingerprint: str,
        limit: int | None = None,
    ) -> list[ArticleFeedback]:
        if limit is not None and limit <= 0:
            raise ValueError("new-interest feedback limit must be positive")
        limit_clause = "" if limit is None else "LIMIT ?"
        params: list[object] = [profile_id, profile_fingerprint]
        if limit is not None:
            params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM article_feedback
                WHERE profile_id = ?
                  AND profile_fingerprint = ?
                  AND profile_match = 'NO'
                  AND personal_interest = 'YES'
                ORDER BY updated_at DESC, id DESC
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()
        return [_feedback_from_row(row) for row in rows]

    def upsert_suggested_interest_profile(
        self,
        *,
        profile_id: int,
        profile_fingerprint: str,
        suggested_name: str,
        suggested_description: str,
        evidence_article_ids: Sequence[int],
        explanation: str,
        suggestion_key: str,
        provenance: dict[str, object],
    ) -> SuggestedInterestProfile:
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO suggested_interest_profiles (
                    profile_id, profile_fingerprint, suggested_name,
                    suggested_description, evidence_article_ids_json, explanation,
                    suggestion_key, provenance_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, profile_fingerprint, suggestion_key) DO UPDATE SET
                    suggested_name = excluded.suggested_name,
                    suggested_description = excluded.suggested_description,
                    evidence_article_ids_json = excluded.evidence_article_ids_json,
                    explanation = excluded.explanation,
                    provenance_json = excluded.provenance_json
                WHERE suggested_interest_profiles.dismissed_at IS NULL
                  AND suggested_interest_profiles.accepted_profile_id IS NULL
                """,
                (
                    profile_id,
                    profile_fingerprint,
                    suggested_name,
                    suggested_description,
                    json.dumps(list(evidence_article_ids)),
                    explanation,
                    suggestion_key,
                    json.dumps(provenance, sort_keys=True),
                    now,
                ),
            )
            suggestion = _get_suggested_interest_profile(
                conn,
                profile_id=profile_id,
                profile_fingerprint=profile_fingerprint,
                suggestion_key=suggestion_key,
            )
        if suggestion is None:
            raise RuntimeError("failed to load suggested interest profile")
        return suggestion

    def list_suggested_interest_profiles(
        self,
        *,
        profile_id: int,
        profile_fingerprint: str,
        include_dismissed: bool = False,
    ) -> list[SuggestedInterestProfile]:
        where = "profile_id = ? AND profile_fingerprint = ?"
        params: list[object] = [profile_id, profile_fingerprint]
        if not include_dismissed:
            where += " AND dismissed_at IS NULL AND accepted_profile_id IS NULL"
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM suggested_interest_profiles
                WHERE {where}
                ORDER BY created_at DESC, id DESC
                """,
                tuple(params),
            ).fetchall()
        return [_suggested_interest_profile_from_row(row) for row in rows]

    def dismiss_suggested_interest_profile(self, suggestion_id: int) -> None:
        if suggestion_id <= 0:
            raise ValueError("suggestion id must be positive")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE suggested_interest_profiles
                SET dismissed_at = ?
                WHERE id = ?
                """,
                (datetime_to_db(utc_now()), suggestion_id),
            )

    def accept_suggested_interest_profile(
        self,
        *,
        suggestion_id: int,
        accepted_profile_id: int,
    ) -> None:
        if suggestion_id <= 0:
            raise ValueError("suggestion id must be positive")
        if accepted_profile_id <= 0:
            raise ValueError("accepted profile id must be positive")
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE suggested_interest_profiles
                SET accepted_profile_id = ?
                WHERE id = ?
                """,
                (accepted_profile_id, suggestion_id),
            )

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
        selected_dates = (
            tuple(value.isoformat() for value in date_selection.selected_dates())
            if date_selection is not None
            else ()
        )
        with self._connection() as conn:
            lock = conn.execute(
                "SELECT owner FROM run_locks WHERE name = ?",
                (DIGEST_RUN_LOCK,),
            ).fetchone()
            run_owner = str(lock["owner"]) if lock is not None else None
            cursor = conn.execute(
                """
                INSERT INTO app_runs (
                    profile_id, profile_fingerprint, source_name, source_fingerprint,
                    started_at, status, run_origin, date_selection_json, run_owner,
                    requested_source_dates_json, incomplete_source_dates_json,
                    retrieval_complete
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                    run_owner,
                    json.dumps(list(selected_dates)),
                    json.dumps(list(selected_dates)),
                ),
            )
            return _lastrowid(cursor)

    def mark_app_run_running(self, run_id: int) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE app_runs
                SET status = ?, progress_stage = ?
                WHERE id = ? AND completed_at IS NULL AND cancel_requested_at IS NULL
                """,
                (APP_RUN_RUNNING, "running", run_id),
            )

    def update_app_run_progress(
        self,
        run_id: int,
        *,
        progress_stage: str,
        retrieved_count: int | None = None,
        stored_count: int | None = None,
        preselected_count: int | None = None,
        skipped_analysis_count: int | None = None,
        analyzed_count: int | None = None,
        relevant_count: int | None = None,
        progress_message: str | None = None,
    ) -> None:
        assignments = ["progress_stage = ?", "progress_message = ?"]
        params: list[object] = [progress_stage, progress_message]
        for column, value in (
            ("retrieved_count", retrieved_count),
            ("stored_count", stored_count),
            ("preselected_count", preselected_count),
            ("skipped_analysis_count", skipped_analysis_count),
            ("analyzed_count", analyzed_count),
            ("relevant_count", relevant_count),
        ):
            if value is None:
                continue
            assignments.append(f"{column} = ?")
            params.append(value)
        params.append(run_id)
        with self._connection() as conn:
            conn.execute(
                f"""
                UPDATE app_runs
                SET {", ".join(assignments)}
                WHERE id = ? AND completed_at IS NULL
                """,
                tuple(params),
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
    ) -> str:
        with self._immediate_connection() as conn:
            current = conn.execute(
                """
                SELECT status, completed_at, cancel_requested_at, cancel_reason
                FROM app_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"app run {run_id} does not exist")
            if current["completed_at"] is not None:
                return str(current["status"])
            cancellation_won = current["cancel_requested_at"] is not None
            effective_status = (
                APP_RUN_CANCELLED if cancellation_won or status == APP_RUN_CANCELLED else status
            )
            effective_error = error_message
            if effective_status == APP_RUN_CANCELLED:
                effective_error = str(current["cancel_reason"] or "Cancelled by user.")
            conn.execute(
                """
                UPDATE app_runs
                SET completed_at = ?, status = ?, retrieved_count = ?, stored_count = ?,
                    preselected_count = ?, skipped_analysis_count = ?, analyzed_count = ?,
                    relevant_count = ?, error_message = ?,
                    requested_source_dates_json = ?, covered_source_dates_json = ?,
                    empty_source_dates_json = ?, incomplete_source_dates_json = ?,
                    retrieval_complete = ?, retrieval_safety_limit = ?,
                    progress_stage = ?, progress_message = ?
                WHERE id = ? AND completed_at IS NULL
                """,
                (
                    datetime_to_db(utc_now()),
                    effective_status,
                    retrieved_count,
                    stored_count,
                    preselected_count,
                    skipped_analysis_count,
                    analyzed_count,
                    relevant_count,
                    effective_error,
                    json.dumps(list(requested_source_dates)),
                    json.dumps(list(covered_source_dates)),
                    json.dumps(list(empty_source_dates)),
                    json.dumps(list(incomplete_source_dates)),
                    int(retrieval_complete),
                    retrieval_safety_limit,
                    effective_status.lower(),
                    effective_error,
                    run_id,
                ),
            )
        return effective_status

    def request_app_run_cancellation(
        self,
        run_id: int,
        *,
        reason: str = "Cancelled by user.",
    ) -> bool:
        """Durably accept cancellation only while the run is nonterminal."""

        sanitized_reason = sanitize_error_text(reason) or "Cancelled by user."
        requested_at = datetime_to_db(utc_now())
        with self._immediate_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE app_runs
                SET cancel_requested_at = COALESCE(cancel_requested_at, ?),
                    cancel_reason = COALESCE(cancel_reason, ?),
                    progress_message = ?
                WHERE id = ?
                    AND completed_at IS NULL
                    AND status IN (?, ?, 'running')
                """,
                (
                    requested_at,
                    sanitized_reason,
                    "Cancellation requested.",
                    run_id,
                    APP_RUN_STARTING,
                    APP_RUN_RUNNING,
                ),
            )
            return cursor.rowcount > 0

    def app_run_cancellation_requested(self, run_id: int) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT cancel_requested_at FROM app_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return row is not None and row["cancel_requested_at"] is not None

    def finish_cancelled_run(self, run_id: int) -> str:
        """Terminalize cancellation without overwriting already-persisted progress."""

        now = datetime_to_db(utc_now())
        with self._immediate_connection() as conn:
            current = conn.execute(
                "SELECT status, completed_at, cancel_reason FROM app_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"app run {run_id} does not exist")
            if current["completed_at"] is not None:
                return str(current["status"])
            reason = str(current["cancel_reason"] or "Cancelled by user.")
            conn.execute(
                """
                UPDATE app_runs
                SET completed_at = ?, status = ?, error_message = ?,
                    progress_stage = ?, progress_message = ?
                WHERE id = ? AND completed_at IS NULL
                """,
                (now, APP_RUN_CANCELLED, reason, APP_RUN_CANCELLED.lower(), reason, run_id),
            )
            conn.execute(
                """
                UPDATE run_provider_processes
                SET completed_at = COALESCE(completed_at, ?), status = ?
                WHERE run_id = ? AND completed_at IS NULL
                """,
                (now, APP_RUN_CANCELLED, run_id),
            )
        return APP_RUN_CANCELLED

    def get_active_app_run(self) -> sqlite3.Row | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM app_runs
                WHERE completed_at IS NULL AND status IN (?, ?, 'running')
                ORDER BY id DESC
                LIMIT 1
                """,
                (APP_RUN_STARTING, APP_RUN_RUNNING),
            ).fetchone()
        return cast(sqlite3.Row | None, row)

    def force_cancel_after_owner_stopped(self, *, run_id: int, owner: str) -> bool:
        """Terminalize a requested cancellation after its exact owner is dead."""

        now = datetime_to_db(utc_now())
        with self._immediate_connection() as conn:
            lock = conn.execute(
                "SELECT owner FROM run_locks WHERE name = ?",
                (DIGEST_RUN_LOCK,),
            ).fetchone()
            if lock is None or str(lock["owner"]) != owner:
                return False
            cursor = conn.execute(
                """
                UPDATE app_runs
                SET completed_at = ?, status = ?, error_message = COALESCE(
                        cancel_reason, 'Cancelled by user.'
                    ),
                    progress_stage = ?, progress_message = COALESCE(
                        cancel_reason, 'Cancelled by user.'
                    )
                WHERE id = ?
                    AND completed_at IS NULL
                    AND cancel_requested_at IS NOT NULL
                    AND run_owner = ?
                    AND status IN (?, ?, 'running')
                """,
                (
                    now,
                    APP_RUN_CANCELLED,
                    APP_RUN_CANCELLED.lower(),
                    run_id,
                    owner,
                    APP_RUN_STARTING,
                    APP_RUN_RUNNING,
                ),
            )
            if cursor.rowcount == 0:
                return False
            conn.execute(
                """
                UPDATE run_provider_processes
                SET completed_at = COALESCE(completed_at, ?), status = ?
                WHERE run_id = ? AND completed_at IS NULL
                """,
                (now, APP_RUN_CANCELLED, run_id),
            )
            conn.execute(
                "DELETE FROM run_locks WHERE name = ? AND owner = ?",
                (DIGEST_RUN_LOCK, owner),
            )
            return True

    def register_provider_process(
        self,
        *,
        run_id: int,
        call_kind: str,
        pid: int,
        process_group_id: int,
        process_start_ticks: int | None,
    ) -> int:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO run_provider_processes (
                    run_id, call_kind, pid, process_group_id,
                    process_start_ticks, started_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'RUNNING')
                """,
                (
                    run_id,
                    call_kind,
                    pid,
                    process_group_id,
                    process_start_ticks,
                    datetime_to_db(utc_now()),
                ),
            )
            return _lastrowid(cursor)

    def finish_provider_process(self, process_id: int, *, status: str) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE run_provider_processes
                SET completed_at = COALESCE(completed_at, ?), status = ?
                WHERE id = ?
                """,
                (datetime_to_db(utc_now()), status, process_id),
            )

    def list_active_provider_processes(self, *, run_id: int) -> list[sqlite3.Row]:
        with self._connection() as conn:
            return list(
                conn.execute(
                    """
                    SELECT *
                    FROM run_provider_processes
                    WHERE run_id = ? AND completed_at IS NULL AND status = 'RUNNING'
                    ORDER BY id ASC
                    """,
                    (run_id,),
                ).fetchall()
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
                    retrieval_safety_limit,
                        progress_stage,
                        progress_message,
                        cancel_requested_at,
                        cancel_reason,
                        run_owner
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

    def get_app_run(self, run_id: int) -> sqlite3.Row | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM app_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return cast(sqlite3.Row | None, row)

    def mark_source_date_covered(
        self,
        *,
        source_name: str,
        source_fingerprint: str,
        source_date: date,
        run_id: int,
        run_origin: RunOrigin,
        profile_id: int | None = None,
        profile_fingerprint: str | None = None,
    ) -> None:
        del profile_id, profile_fingerprint
        covered_at = datetime_to_db(utc_now())
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO source_date_coverage (
                    source_name, source_fingerprint, source_date, status,
                    first_covered_run_id, last_covered_run_id,
                    run_origin, covered_at, updated_at
                )
                VALUES (?, ?, ?, 'COVERED', ?, ?, ?, ?, ?)
                ON CONFLICT(
                    source_name, source_fingerprint, source_date
                ) DO UPDATE SET
                    status = 'COVERED',
                    last_covered_run_id = excluded.last_covered_run_id,
                    run_origin = excluded.run_origin,
                    updated_at = excluded.updated_at
                """,
                (
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
        source_name: str,
        source_fingerprint: str,
        start_date: date,
        end_date: date,
        profile_id: int | None = None,
        profile_fingerprint: str | None = None,
    ) -> set[date]:
        del profile_id, profile_fingerprint
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT source_date
                FROM source_date_coverage
                WHERE source_name = ?
                    AND source_fingerprint = ?
                    AND status = 'COVERED'
                    AND source_date BETWEEN ? AND ?
                """,
                (
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
                    ORDER BY source_date DESC, source_name ASC, id DESC
                    """
                ).fetchall()
            )

    def record_complete_source_date(
        self,
        *,
        source_name: str,
        source_fingerprint: str,
        source_date: date,
        articles: Iterable[Article],
        run_id: int,
        run_origin: RunOrigin,
    ) -> None:
        """Atomically persist coverage and its exact locally reusable corpus."""

        self.record_complete_source_dates(
            source_name=source_name,
            source_fingerprint=source_fingerprint,
            articles_by_date={source_date: tuple(articles)},
            run_id=run_id,
            run_origin=run_origin,
        )

    def record_complete_source_dates(
        self,
        *,
        source_name: str,
        source_fingerprint: str,
        articles_by_date: Mapping[date, Iterable[Article]],
        run_id: int,
        run_origin: RunOrigin,
        requested_source_dates: Sequence[date] | None = None,
        empty_source_dates: Sequence[date] = (),
        incomplete_source_dates: Sequence[date] = (),
        retrieval_complete: bool | None = None,
        retrieval_safety_limit: int | None = None,
        retrieved_count: int | None = None,
        stored_count: int | None = None,
    ) -> None:
        """Persist one complete multi-date retrieval in a single transaction."""

        prepared: list[tuple[date, list[int]]] = []
        for source_date, articles in sorted(articles_by_date.items()):
            corpus_articles = tuple(articles)
            if any(article.id is None for article in corpus_articles):
                raise ValueError("source-date corpus articles must be stored first")
            if any(article.source != source_name for article in corpus_articles):
                raise ValueError("source-date corpus articles must match the source")
            if any(
                source_date_from_datetime(article.published_at) != source_date
                for article in corpus_articles
            ):
                raise ValueError("source-date corpus articles must match the source date")
            prepared.append(
                (source_date, sorted({cast(int, article.id) for article in corpus_articles}))
            )
        now = datetime_to_db(utc_now())
        with self._connection() as conn:
            for source_date, article_ids in prepared:
                _record_complete_source_date(
                    conn,
                    source_name,
                    source_fingerprint,
                    source_date,
                    article_ids,
                    run_id,
                    run_origin,
                    now,
                )
            if requested_source_dates is not None and retrieval_complete is not None:
                _persist_app_run_retrieval_metadata(
                    conn,
                    run_id=run_id,
                    requested_source_dates=requested_source_dates,
                    covered_source_dates=tuple(value for value, _article_ids in prepared),
                    empty_source_dates=empty_source_dates,
                    incomplete_source_dates=incomplete_source_dates,
                    retrieval_complete=retrieval_complete,
                    retrieval_safety_limit=retrieval_safety_limit,
                    retrieved_count=retrieved_count,
                    stored_count=stored_count,
                )

    def persist_app_run_retrieval_metadata(
        self,
        *,
        run_id: int,
        requested_source_dates: Sequence[date],
        covered_source_dates: Sequence[date],
        empty_source_dates: Sequence[date],
        incomplete_source_dates: Sequence[date],
        retrieval_complete: bool,
        retrieval_safety_limit: int | None,
        retrieved_count: int,
        stored_count: int,
    ) -> None:
        """Persist retrieval progress before entering cancellable downstream work."""

        with self._connection() as conn:
            _persist_app_run_retrieval_metadata(
                conn,
                run_id=run_id,
                requested_source_dates=requested_source_dates,
                covered_source_dates=covered_source_dates,
                empty_source_dates=empty_source_dates,
                incomplete_source_dates=incomplete_source_dates,
                retrieval_complete=retrieval_complete,
                retrieval_safety_limit=retrieval_safety_limit,
                retrieved_count=retrieved_count,
                stored_count=stored_count,
            )

    def load_source_date_corpus(
        self,
        *,
        source_name: str,
        source_fingerprints: Iterable[str],
        source_date: date,
    ) -> tuple[Article, ...] | None:
        """Return a complete persisted corpus, including an explicitly empty one."""

        fingerprints = tuple(dict.fromkeys(source_fingerprints))
        if not fingerprints:
            return None
        placeholders = ", ".join("?" for _ in fingerprints)
        with self._connection() as conn:
            row = conn.execute(
                f"""
                SELECT id, article_count
                FROM source_date_corpora
                WHERE source_name = ?
                    AND source_date = ?
                    AND source_fingerprint IN ({placeholders})
                ORDER BY CASE source_fingerprint
                    {" ".join(f"WHEN ? THEN {index}" for index, _ in enumerate(fingerprints))}
                    ELSE {len(fingerprints)} END
                LIMIT 1
                """,
                (
                    source_name,
                    source_date.isoformat(),
                    *fingerprints,
                    *fingerprints,
                ),
            ).fetchone()
            if row is None:
                return None
            article_rows = conn.execute(
                """
                SELECT articles.*
                FROM source_date_corpus_articles
                JOIN articles ON articles.id = source_date_corpus_articles.article_id
                WHERE source_date_corpus_articles.corpus_id = ?
                ORDER BY articles.published_at DESC, articles.id ASC
                """,
                (int(row["id"]),),
            ).fetchall()
        articles = tuple(_article_from_row(article_row) for article_row in article_rows)
        if len(articles) != int(row["article_count"]):
            raise RuntimeError("source-date corpus is incomplete")
        return articles

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

    def save_preselection_decisions(
        self,
        *,
        run_id: int,
        profile_id: int,
        profile_fingerprint: str,
        source_name: str,
        source_fingerprint: str | None,
        article_by_key: Mapping[str, Article],
        decisions: Sequence[AbstractPreselectionDecision],
    ) -> None:
        if not decisions:
            return
        now_text = datetime_to_db(utc_now())
        rows: list[tuple[object, ...]] = []
        for decision in decisions:
            article = article_by_key.get(decision.article_id)
            if article is None or article.id is None:
                continue
            rows.append(
                (
                    run_id,
                    article.id,
                    profile_id,
                    profile_fingerprint,
                    source_name,
                    source_fingerprint,
                    decision.preselection_score,
                    decision.preselection_threshold,
                    int(decision.selected),
                    decision.stage,
                    decision.decision_origin,
                    decision.preselector_version,
                    decision.reason,
                    now_text,
                )
            )
        if not rows:
            return
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT INTO preselection_decisions (
                    run_id, article_id, profile_id, profile_fingerprint,
                    source_name, source_fingerprint, preselection_score,
                    preselection_threshold, passed, stage, decision_origin,
                    preselector_version, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, article_id) DO UPDATE SET
                    profile_id = excluded.profile_id,
                    profile_fingerprint = excluded.profile_fingerprint,
                    source_name = excluded.source_name,
                    source_fingerprint = excluded.source_fingerprint,
                    preselection_score = excluded.preselection_score,
                    preselection_threshold = excluded.preselection_threshold,
                    passed = excluded.passed,
                    stage = excluded.stage,
                    decision_origin = excluded.decision_origin,
                    preselector_version = excluded.preselector_version,
                    reason = excluded.reason
                """,
                rows,
            )

    def list_preselection_decisions(self, *, run_id: int) -> list[sqlite3.Row]:
        with self._connection() as conn:
            return list(
                conn.execute(
                    """
                    SELECT
                        pd.*,
                        a.source,
                        a.source_article_id,
                        a.title
                    FROM preselection_decisions AS pd
                    JOIN articles AS a ON a.id = pd.article_id
                    WHERE pd.run_id = ?
                    ORDER BY pd.id ASC
                    """,
                    (run_id,),
                ).fetchall()
            )

    def acquire_run_lock(
        self,
        *,
        owner: str,
        stale_after_seconds: float,
        now: datetime | None = None,
        owner_state_checker: Callable[[str], RunOwnerState] = process_run_owner_state,
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
                owner_state = owner_state_checker(str(row["owner"]))
                if owner_state == RunOwnerState.ALIVE:
                    raise RunAlreadyActiveError("another digest run is already active")
                if owner_state == RunOwnerState.UNKNOWN and locked_at > stale_cutoff:
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

    def get_run_lock(self) -> RunLock | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM run_locks WHERE name = ?",
                (DIGEST_RUN_LOCK,),
            ).fetchone()
        if row is None:
            return None
        return RunLock(
            name=str(row["name"]),
            owner=str(row["owner"]),
            acquired_at=datetime_from_db(str(row["acquired_at"])),
        )

    def recover_abandoned_run(
        self,
        *,
        run_id: int,
        force_uninspectable_owner: bool = False,
        now: datetime | None = None,
        owner_state_checker: Callable[[str], RunOwnerState] = process_run_owner_state,
    ) -> AbandonedRunRecovery:
        completed_at = datetime_to_db(utc_now() if now is None else now)
        message = "Digest run was recovered after its owner process stopped before completion."
        with self._immediate_connection() as conn:
            run = conn.execute("SELECT * FROM app_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise ValueError(f"app run {run_id} does not exist")
            status_before = str(run["status"])
            if run["completed_at"] is not None or status_before not in (
                APP_RUN_STARTING,
                APP_RUN_RUNNING,
                "running",
            ):
                return AbandonedRunRecovery(
                    run_id=run_id,
                    recovered=False,
                    status_before=status_before,
                    status_after=status_before,
                    retrieved_count=int(run["retrieved_count"]),
                    stored_count=int(run["stored_count"]),
                    preselected_count=int(run["preselected_count"]),
                    skipped_analysis_count=int(run["skipped_analysis_count"]),
                    analyzed_count=int(run["analyzed_count"]),
                    relevant_count=int(run["relevant_count"]),
                    message="Digest run is already terminal.",
                )

            lock = conn.execute(
                "SELECT * FROM run_locks WHERE name = ?",
                (DIGEST_RUN_LOCK,),
            ).fetchone()
            if lock is not None:
                owner_state = owner_state_checker(str(lock["owner"]))
                if owner_state == RunOwnerState.ALIVE:
                    raise RunAlreadyActiveError("another digest run is still active")
                if owner_state == RunOwnerState.UNKNOWN and not force_uninspectable_owner:
                    raise RunLockError(
                        "digest run owner cannot be verified; use explicit recovery only "
                        "after confirming the owner process is gone"
                    )

            _mark_unfinished_runs_failed(
                conn,
                completed_at=completed_at,
                message=message,
                run_id=run_id,
            )
            conn.execute("DELETE FROM run_locks WHERE name = ?", (DIGEST_RUN_LOCK,))
            recovered = conn.execute(
                "SELECT * FROM app_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if recovered is None:
                raise RuntimeError("recovered app run disappeared")
            return AbandonedRunRecovery(
                run_id=run_id,
                recovered=True,
                status_before=status_before,
                status_after=str(recovered["status"]),
                retrieved_count=int(recovered["retrieved_count"]),
                stored_count=int(recovered["stored_count"]),
                preselected_count=int(recovered["preselected_count"]),
                skipped_analysis_count=int(recovered["skipped_analysis_count"]),
                analyzed_count=int(recovered["analyzed_count"]),
                relevant_count=int(recovered["relevant_count"]),
                message=message,
            )

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
        except BaseException:
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
        except BaseException:
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
        raise MigrationError("database schema version changed while initialization was in progress")

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


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


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


def _migration_library_search_connections(conn: sqlite3.Connection) -> None:
    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS library_search_documents (
                article_id INTEGER PRIMARY KEY,
                document_text TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS library_article_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id_a INTEGER NOT NULL,
                article_id_b INTEGER NOT NULL,
                relation_label TEXT NOT NULL,
                rationale TEXT NOT NULL,
                origin TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                confidence REAL,
                generated_at TEXT NOT NULL,
                dismissed_at TEXT,
                CHECK(article_id_a < article_id_b),
                UNIQUE(article_id_a, article_id_b),
                FOREIGN KEY(article_id_a) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(article_id_b) REFERENCES articles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_library_connections_article_a
            ON library_article_connections(article_id_a, dismissed_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_library_connections_article_b
            ON library_article_connections(article_id_b, dismissed_at)
            """,
        ),
    )


def _migration_library_context_intelligence(conn: sqlite3.Connection) -> None:
    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS library_context_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                article_id INTEGER NOT NULL,
                related_article_id INTEGER NOT NULL,
                collection_id INTEGER,
                collection_key INTEGER GENERATED ALWAYS AS (IFNULL(collection_id, 0)) STORED,
                relation_label TEXT NOT NULL,
                rationale TEXT NOT NULL,
                origin TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                confidence REAL,
                created_at TEXT NOT NULL,
                dismissed_at TEXT,
                CHECK(article_id != related_article_id),
                UNIQUE(article_id, related_article_id, collection_key),
                FOREIGN KEY(run_id) REFERENCES app_runs(id) ON DELETE SET NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(related_article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(collection_id) REFERENCES library_collections(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_library_context_suggestions_article
            ON library_context_suggestions(article_id, dismissed_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS collection_intelligence_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                origin TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                dismissed_at TEXT,
                FOREIGN KEY(collection_id) REFERENCES library_collections(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_collection_intelligence_collection
            ON collection_intelligence_snapshots(collection_id, dismissed_at, generated_at DESC)
            """,
        ),
    )


def _migration_feedback_interests(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "article_feedback"):
        columns = _table_columns(conn, "article_feedback")
        needs_rebuild = (
            "profile_match" not in columns
            or "personal_interest" not in columns
            or _feedback_label_is_not_null(conn)
        )
        if needs_rebuild:
            conn.execute("ALTER TABLE article_feedback RENAME TO article_feedback_old")
            _create_article_feedback_table_v14(conn)
            old_columns = _table_columns(conn, "article_feedback_old")
            profile_match_sql = (
                "profile_match"
                if "profile_match" in old_columns
                else """
                CASE feedback_label
                    WHEN 'RELEVANT' THEN 'YES'
                    WHEN 'NOT_RELEVANT' THEN 'NO'
                    ELSE NULL
                END
                """
            )
            personal_interest_sql = (
                "personal_interest" if "personal_interest" in old_columns else "NULL"
            )
            conn.execute(
                f"""
                INSERT INTO article_feedback (
                    id, article_id, profile_id, profile_fingerprint, feedback_label,
                    profile_match, personal_interest, created_at, updated_at
                )
                SELECT
                    id, article_id, profile_id, profile_fingerprint, feedback_label,
                    {profile_match_sql}, {personal_interest_sql}, created_at, updated_at
                FROM article_feedback_old
                """
            )
            conn.execute("DROP TABLE article_feedback_old")
    else:
        _create_article_feedback_table_v14(conn)

    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS suggested_interest_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            profile_fingerprint TEXT NOT NULL,
            suggested_name TEXT NOT NULL,
            suggested_description TEXT NOT NULL,
            evidence_article_ids_json TEXT NOT NULL,
            explanation TEXT NOT NULL,
            suggestion_key TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            dismissed_at TEXT,
            accepted_profile_id INTEGER,
            UNIQUE(profile_id, profile_fingerprint, suggestion_key),
            FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE,
            FOREIGN KEY(accepted_profile_id) REFERENCES interest_profiles(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_suggested_interest_profiles_profile
            ON suggested_interest_profiles(profile_id, profile_fingerprint, dismissed_at)
            """,
        ),
    )


def _migration_quantitative_calibration_and_progress(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "app_runs"):
        columns = _table_columns(conn, "app_runs")
        if "progress_stage" not in columns:
            conn.execute("ALTER TABLE app_runs ADD COLUMN progress_stage TEXT")
        if "progress_message" not in columns:
            conn.execute("ALTER TABLE app_runs ADD COLUMN progress_message TEXT")
    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS quantitative_relevance_calibrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL UNIQUE,
                article_id INTEGER,
                profile_id INTEGER NOT NULL,
                profile_fingerprint TEXT NOT NULL,
                model_relevance_score REAL,
                state TEXT NOT NULL,
                user_relevance_score REAL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                CHECK(state IN ('PENDING', 'COMPLETED', 'DISMISSED', 'SKIPPED')),
                CHECK(model_relevance_score IS NULL OR (
                    model_relevance_score >= 0 AND model_relevance_score <= 1
                )),
                CHECK(user_relevance_score IS NULL OR (
                    user_relevance_score >= 0 AND user_relevance_score <= 1
                )),
                FOREIGN KEY(run_id) REFERENCES app_runs(id) ON DELETE CASCADE,
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_quantitative_calibrations_profile_article
            ON quantitative_relevance_calibrations(profile_id, article_id, state)
            """,
        ),
    )


def _feedback_label_is_not_null(conn: sqlite3.Connection) -> bool:
    for row in conn.execute("PRAGMA table_info(article_feedback)").fetchall():
        if str(row["name"]) == "feedback_label":
            return bool(row["notnull"])
    return False


def _create_article_feedback_table_v14(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE article_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER NOT NULL,
        profile_id INTEGER NOT NULL,
        profile_fingerprint TEXT NOT NULL,
        feedback_label TEXT,
        profile_match TEXT,
        personal_interest TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(article_id, profile_id, profile_fingerprint),
        FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
        FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
        )
        """
    )


def _migration_preselection_decisions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preselection_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            article_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            profile_fingerprint TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_fingerprint TEXT,
            preselection_score REAL,
            preselection_threshold REAL,
            passed INTEGER NOT NULL,
            stage TEXT NOT NULL,
            decision_origin TEXT NOT NULL,
            preselector_version TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(run_id, article_id),
            FOREIGN KEY(run_id) REFERENCES app_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
            FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_preselection_decisions_run
        ON preselection_decisions(run_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_preselection_decisions_scope
        ON preselection_decisions(
            profile_id, profile_fingerprint, source_name, source_fingerprint,
            preselector_version
        )
        """
    )


def _migration_source_scoped_coverage(conn: sqlite3.Connection) -> None:
    """Remove profile identity from coverage and add reusable corpus manifests."""

    if _table_exists(conn, "source_date_coverage"):
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(source_date_coverage)").fetchall()
        }
        if "profile_id" in columns:
            conn.execute("ALTER TABLE source_date_coverage RENAME TO source_date_coverage_v16")
            _create_source_scoped_coverage_table(conn)
            conn.execute(
                """
                INSERT INTO source_date_coverage (
                    source_name, source_fingerprint, source_date, status,
                    first_covered_run_id, last_covered_run_id, run_origin,
                    covered_at, updated_at
                )
                SELECT
                    source_name,
                    source_fingerprint,
                    source_date,
                    'COVERED',
                    MIN(first_covered_run_id),
                    MAX(last_covered_run_id),
                    MAX(run_origin),
                    MIN(covered_at),
                    MAX(updated_at)
                FROM source_date_coverage_v16
                WHERE status = 'COVERED'
                GROUP BY source_name, source_fingerprint, source_date
                """
            )
            conn.execute("DROP TABLE source_date_coverage_v16")
    else:
        _create_source_scoped_coverage_table(conn)

    _backfill_complete_retrieval_coverage(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_date_corpora (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL,
            source_date TEXT NOT NULL,
            article_count INTEGER NOT NULL,
            captured_run_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_name, source_fingerprint, source_date),
            CHECK(article_count >= 0),
            FOREIGN KEY(captured_run_id) REFERENCES app_runs(id) ON DELETE RESTRICT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_date_corpus_articles (
            corpus_id INTEGER NOT NULL,
            article_id INTEGER NOT NULL,
            PRIMARY KEY(corpus_id, article_id),
            FOREIGN KEY(corpus_id) REFERENCES source_date_corpora(id) ON DELETE CASCADE,
            FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE RESTRICT
        )
        """
    )


def _migration_run_cancellation(conn: sqlite3.Connection) -> None:
    """Add durable cancellation requests and exact provider-process ownership."""

    if _table_exists(conn, "app_runs"):
        columns = _table_columns(conn, "app_runs")
        if "cancel_requested_at" not in columns:
            conn.execute("ALTER TABLE app_runs ADD COLUMN cancel_requested_at TEXT")
        if "cancel_reason" not in columns:
            conn.execute("ALTER TABLE app_runs ADD COLUMN cancel_reason TEXT")
        if "run_owner" not in columns:
            conn.execute("ALTER TABLE app_runs ADD COLUMN run_owner TEXT")
        if _table_exists(conn, "run_locks"):
            conn.execute(
                """
                UPDATE app_runs
                SET run_owner = (
                    SELECT owner FROM run_locks WHERE name = ?
                )
                WHERE run_owner IS NULL
                    AND completed_at IS NULL
                    AND status IN (?, ?, 'running')
                    AND id = (
                        SELECT id
                        FROM app_runs
                        WHERE completed_at IS NULL
                            AND status IN (?, ?, 'running')
                        ORDER BY id DESC
                        LIMIT 1
                    )
                    AND EXISTS (SELECT 1 FROM run_locks WHERE name = ?)
                """,
                (
                    DIGEST_RUN_LOCK,
                    APP_RUN_STARTING,
                    APP_RUN_RUNNING,
                    APP_RUN_STARTING,
                    APP_RUN_RUNNING,
                    DIGEST_RUN_LOCK,
                ),
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_provider_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            call_kind TEXT NOT NULL,
            pid INTEGER NOT NULL,
            process_group_id INTEGER NOT NULL,
            process_start_ticks INTEGER,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            CHECK(pid > 0),
            CHECK(process_group_id > 0),
            FOREIGN KEY(run_id) REFERENCES app_runs(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_provider_processes_active
        ON run_provider_processes(run_id, completed_at, status)
        """
    )


def _migration_library_l1a_foundation(conn: sqlite3.Connection) -> None:
    """Add normalized Library state, replaceable AI artifacts, and conversations."""

    if not _table_exists(conn, "library_articles"):
        _migration_saved_article_library(conn)
    library_columns = _table_columns(conn, "library_articles")
    if "reading_state" not in library_columns:
        conn.execute(
            """
            ALTER TABLE library_articles
            ADD COLUMN reading_state TEXT
            CHECK(reading_state IS NULL OR reading_state IN (
                'unread', 'skimmed', 'read', 'reference'
            ))
            """
        )
    if "interest_rating" not in library_columns:
        conn.execute(
            """
            ALTER TABLE library_articles
            ADD COLUMN interest_rating INTEGER
            CHECK(interest_rating IS NULL OR (
                typeof(interest_rating) = 'integer'
                AND interest_rating BETWEEN 1 AND 5
            ))
            """
        )

    _execute_schema_statements(
        conn,
        (
            """
            CREATE TABLE IF NOT EXISTS ai_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                artifact_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_id TEXT NOT NULL,
                reasoning_effort TEXT,
                generator_version TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                retention_class TEXT NOT NULL,
                expires_at TEXT,
                CHECK(length(trim(content)) > 0),
                CHECK(length(trim(provider)) > 0),
                CHECK(length(trim(model_id)) > 0),
                CHECK(length(trim(generator_version)) > 0),
                CHECK(length(trim(input_fingerprint)) > 0),
                CHECK(artifact_type IN (
                    'digest_summary', 'library_summary', 'conversation_summary'
                )),
                CHECK(retention_class IN ('TEMPORARY', 'LIBRARY', 'USER_PINNED')),
                CHECK(
                    (retention_class = 'TEMPORARY' AND expires_at IS NOT NULL)
                    OR
                    (retention_class IN ('LIBRARY', 'USER_PINNED') AND expires_at IS NULL)
                ),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_artifacts_article_type_created
            ON ai_artifacts(article_id, artifact_type, created_at DESC, id DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_artifacts_reuse
            ON ai_artifacts(
                article_id, artifact_type, input_fingerprint, created_at DESC, id DESC
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_artifacts_gc
            ON ai_artifacts(retention_class, expires_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_id TEXT NOT NULL,
                conversation_version INTEGER NOT NULL,
                rolling_summary_artifact_id INTEGER,
                CHECK(length(trim(title)) > 0),
                CHECK(length(trim(provider)) > 0),
                CHECK(length(trim(model_id)) > 0),
                CHECK(conversation_version > 0),
                FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE,
                FOREIGN KEY(rolling_summary_artifact_id)
                    REFERENCES ai_artifacts(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_conversations_article_updated
            ON ai_conversations(article_id, updated_at DESC, id DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK(sequence_number > 0),
                CHECK(role IN ('user', 'assistant')),
                CHECK(length(trim(content)) > 0),
                UNIQUE(conversation_id, sequence_number),
                FOREIGN KEY(conversation_id) REFERENCES ai_conversations(id) ON DELETE CASCADE
            )
            """,
        ),
    )


def _migration_library_l1c_summary_ownership(conn: sqlite3.Connection) -> None:
    """Link new relevance summaries to their single canonical artifact body."""

    if not _table_exists(conn, "relevance_analyses"):
        return
    if "summary_artifact_id" not in _table_columns(conn, "relevance_analyses"):
        conn.execute(
            """
            ALTER TABLE relevance_analyses
            ADD COLUMN summary_artifact_id INTEGER
            REFERENCES ai_artifacts(id) ON DELETE SET NULL
            """
        )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_relevance_analyses_summary_artifact
        ON relevance_analyses(summary_artifact_id)
        WHERE summary_artifact_id IS NOT NULL
        """
    )
    if _table_exists(conn, "ai_conversations"):
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ai_conversations_rolling_summary
            ON ai_conversations(rolling_summary_artifact_id)
            """
        )


def _create_source_scoped_coverage_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_date_coverage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL,
            source_date TEXT NOT NULL,
            status TEXT NOT NULL,
            first_covered_run_id INTEGER NOT NULL,
            last_covered_run_id INTEGER NOT NULL,
            run_origin TEXT NOT NULL,
            covered_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_name, source_fingerprint, source_date),
            FOREIGN KEY(first_covered_run_id) REFERENCES app_runs(id) ON DELETE RESTRICT,
            FOREIGN KEY(last_covered_run_id) REFERENCES app_runs(id) ON DELETE RESTRICT
        )
        """
    )


def _record_complete_source_date(
    conn: sqlite3.Connection,
    source_name: str,
    source_fingerprint: str,
    source_date: date,
    article_ids: Sequence[int],
    run_id: int,
    run_origin: RunOrigin,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO source_date_coverage (
            source_name, source_fingerprint, source_date, status,
            first_covered_run_id, last_covered_run_id,
            run_origin, covered_at, updated_at
        )
        VALUES (?, ?, ?, 'COVERED', ?, ?, ?, ?, ?)
        ON CONFLICT(source_name, source_fingerprint, source_date) DO UPDATE SET
            status = 'COVERED',
            last_covered_run_id = excluded.last_covered_run_id,
            run_origin = excluded.run_origin,
            updated_at = excluded.updated_at
        """,
        (
            source_name,
            source_fingerprint,
            source_date.isoformat(),
            run_id,
            run_id,
            run_origin.value,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO source_date_corpora (
            source_name, source_fingerprint, source_date, article_count,
            captured_run_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_name, source_fingerprint, source_date) DO UPDATE SET
            article_count = excluded.article_count,
            captured_run_id = excluded.captured_run_id,
            updated_at = excluded.updated_at
        """,
        (
            source_name,
            source_fingerprint,
            source_date.isoformat(),
            len(article_ids),
            run_id,
            now,
            now,
        ),
    )
    row = conn.execute(
        """
        SELECT id
        FROM source_date_corpora
        WHERE source_name = ? AND source_fingerprint = ? AND source_date = ?
        """,
        (source_name, source_fingerprint, source_date.isoformat()),
    ).fetchone()
    if row is None:
        raise RuntimeError("failed to load source-date corpus")
    corpus_id = int(row["id"])
    conn.execute(
        "DELETE FROM source_date_corpus_articles WHERE corpus_id = ?",
        (corpus_id,),
    )
    conn.executemany(
        """
        INSERT INTO source_date_corpus_articles (corpus_id, article_id)
        VALUES (?, ?)
        """,
        ((corpus_id, article_id) for article_id in article_ids),
    )


def _persist_app_run_retrieval_metadata(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    requested_source_dates: Sequence[date],
    covered_source_dates: Sequence[date],
    empty_source_dates: Sequence[date],
    incomplete_source_dates: Sequence[date],
    retrieval_complete: bool,
    retrieval_safety_limit: int | None,
    retrieved_count: int | None,
    stored_count: int | None,
) -> None:
    assignments = [
        "requested_source_dates_json = ?",
        "covered_source_dates_json = ?",
        "empty_source_dates_json = ?",
        "incomplete_source_dates_json = ?",
        "retrieval_complete = ?",
        "retrieval_safety_limit = ?",
    ]
    params: list[object] = [
        json.dumps([value.isoformat() for value in requested_source_dates]),
        json.dumps([value.isoformat() for value in covered_source_dates]),
        json.dumps([value.isoformat() for value in empty_source_dates]),
        json.dumps([value.isoformat() for value in incomplete_source_dates]),
        int(retrieval_complete),
        retrieval_safety_limit,
    ]
    if retrieved_count is not None:
        assignments.append("retrieved_count = ?")
        params.append(retrieved_count)
    if stored_count is not None:
        assignments.append("stored_count = ?")
        params.append(stored_count)
    params.append(run_id)
    conn.execute(
        f"""
        UPDATE app_runs
        SET {", ".join(assignments)}
        WHERE id = ? AND completed_at IS NULL
        """,
        tuple(params),
    )


def _backfill_complete_retrieval_coverage(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "app_runs"):
        return
    rows = conn.execute(
        """
        SELECT *
        FROM app_runs
        WHERE status IN (?, ?, ?, ?)
            AND source_fingerprint IS NOT NULL
        ORDER BY id ASC
        """,
        (
            APP_RUN_COMPLETED,
            APP_RUN_FAILED,
            APP_RUN_PARTIAL,
            APP_RUN_ANALYSIS_UNAVAILABLE,
        ),
    ).fetchall()
    for row in rows:
        covered = _migration_json_dates(row["covered_source_dates_json"])
        incomplete = _migration_json_dates(row["incomplete_source_dates_json"])
        for source_date in sorted(covered - incomplete):
            timestamp = str(row["completed_at"] or row["started_at"])
            conn.execute(
                """
                INSERT INTO source_date_coverage (
                    source_name, source_fingerprint, source_date, status,
                    first_covered_run_id, last_covered_run_id, run_origin,
                    covered_at, updated_at
                )
                VALUES (?, ?, ?, 'COVERED', ?, ?, ?, ?, ?)
                ON CONFLICT(source_name, source_fingerprint, source_date) DO UPDATE SET
                    status = 'COVERED',
                    last_covered_run_id = excluded.last_covered_run_id,
                    run_origin = excluded.run_origin,
                    updated_at = excluded.updated_at
                """,
                (
                    str(row["source_name"]),
                    str(row["source_fingerprint"]),
                    source_date,
                    int(row["id"]),
                    int(row["id"]),
                    str(row["run_origin"]),
                    timestamp,
                    timestamp,
                ),
            )


def _migration_json_dates(value: object) -> set[str]:
    try:
        payload = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(payload, list):
        return set()
    dates: set[str] = set()
    for item in payload:
        if not isinstance(item, str):
            continue
        try:
            dates.add(date.fromisoformat(item).isoformat())
        except ValueError:
            continue
    return dates


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
    SchemaMigration(
        12,
        "library search and connections",
        _migration_library_search_connections,
    ),
    SchemaMigration(
        13,
        "library context intelligence",
        _migration_library_context_intelligence,
    ),
    SchemaMigration(
        14,
        "feedback interests and suggested profiles",
        _migration_feedback_interests,
    ),
    SchemaMigration(
        15,
        "quantitative calibration and run progress",
        _migration_quantitative_calibration_and_progress,
    ),
    SchemaMigration(
        16,
        "preselection decision evidence",
        _migration_preselection_decisions,
    ),
    SchemaMigration(
        17,
        "source-scoped coverage and reusable corpora",
        _migration_source_scoped_coverage,
    ),
    SchemaMigration(
        18,
        "durable run cancellation and provider process ownership",
        _migration_run_cancellation,
    ),
    SchemaMigration(
        19,
        "Library L1-A stable core and AI persistence foundation",
        _migration_library_l1a_foundation,
    ),
    SchemaMigration(
        20,
        "Library L1-C canonical summary ownership",
        _migration_library_l1c_summary_ownership,
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
    message: str = "Previous digest run appears to have stopped before completion.",
    run_id: int | None = None,
) -> None:
    params: list[object] = [
        completed_at,
        APP_RUN_CANCELLED,
        APP_RUN_FAILED,
        message,
        APP_RUN_CANCELLED.lower(),
        APP_RUN_FAILED.lower(),
        message,
        APP_RUN_STARTING,
        APP_RUN_RUNNING,
        "running",
    ]
    started_clause = ""
    if started_before is not None:
        started_clause = " AND started_at <= ?"
        params.append(started_before)
    run_clause = ""
    if run_id is not None:
        run_clause = " AND id = ?"
        params.append(run_id)
    conn.execute(
        f"""
        UPDATE app_runs
        SET completed_at = ?,
            status = CASE WHEN cancel_requested_at IS NOT NULL THEN ? ELSE ? END,
            error_message = CASE
                WHEN cancel_requested_at IS NOT NULL
                    THEN COALESCE(cancel_reason, 'Cancelled by user.')
                ELSE ?
            END,
            progress_stage = CASE
                WHEN cancel_requested_at IS NOT NULL THEN ?
                ELSE ?
            END,
            progress_message = CASE
                WHEN cancel_requested_at IS NOT NULL
                    THEN COALESCE(cancel_reason, 'Cancelled by user.')
                ELSE ?
            END
        WHERE completed_at IS NULL AND status IN (?, ?, ?){started_clause}{run_clause}
        """,
        tuple(params),
    )
    conn.execute(
        """
        UPDATE run_provider_processes
        SET completed_at = COALESCE(completed_at, ?),
            status = COALESCE(
                (SELECT status FROM app_runs WHERE id = run_provider_processes.run_id),
                ?
            )
        WHERE completed_at IS NULL
            AND run_id IN (
                SELECT id
                FROM app_runs
                WHERE completed_at = ? AND status IN (?, ?)
            )
        """,
        (
            completed_at,
            APP_RUN_FAILED,
            completed_at,
            APP_RUN_FAILED,
            APP_RUN_CANCELLED,
        ),
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
        conn.execute("ALTER TABLE app_runs ADD COLUMN preselected_count INTEGER NOT NULL DEFAULT 0")
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
        str(row["name"]) for row in conn.execute("PRAGMA table_info(relevance_analyses)").fetchall()
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
            library_articles.updated_at AS library_updated_at,
            library_articles.reading_state AS library_reading_state,
            library_articles.interest_rating AS library_interest_rating
        FROM library_articles
        JOIN articles ON articles.id = library_articles.article_id
        WHERE library_articles.article_id = ? AND library_articles.saved = 1
        """,
        (article_id,),
    ).fetchone()
    return _library_entry_from_row(row) if row is not None else None


def _is_article_saved(conn: sqlite3.Connection, article_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM library_articles WHERE article_id = ? AND saved = 1",
        (article_id,),
    ).fetchone()
    return row is not None


def _get_ai_artifact(conn: sqlite3.Connection, artifact_id: int) -> AIArtifact | None:
    row = conn.execute(
        "SELECT * FROM ai_artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    return _ai_artifact_from_row(row) if row is not None else None


def _insert_ai_artifact(conn: sqlite3.Connection, artifact: AIArtifact) -> AIArtifact:
    cursor = conn.execute(
        """
        INSERT INTO ai_artifacts (
            article_id, artifact_type, content, created_at, provider, model_id,
            reasoning_effort, generator_version, input_fingerprint,
            retention_class, expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact.article_id,
            artifact.artifact_type.value,
            artifact.content,
            datetime_to_db(artifact.created_at),
            artifact.provider,
            artifact.model_id,
            artifact.reasoning_effort,
            artifact.generator_version,
            artifact.input_fingerprint,
            artifact.retention_class.value,
            datetime_to_db(artifact.expires_at) if artifact.expires_at else None,
        ),
    )
    saved = _get_ai_artifact(conn, _lastrowid(cursor))
    if saved is None:
        raise RuntimeError("failed to load created AI artifact")
    return saved


def _latest_usable_artifact_row(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    artifact_type: AIArtifactType,
    now_text: str,
) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT *
        FROM ai_artifacts
        WHERE article_id = ?
          AND artifact_type = ?
          AND (retention_class != ? OR expires_at >= ?)
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (
            article_id,
            artifact_type.value,
            AIArtifactRetentionClass.TEMPORARY.value,
            now_text,
        ),
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def _preferred_summary_artifact_id(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    now_text: str,
) -> int | None:
    for artifact_type in (
        AIArtifactType.LIBRARY_SUMMARY,
        AIArtifactType.DIGEST_SUMMARY,
    ):
        row = _latest_usable_artifact_row(
            conn,
            article_id=article_id,
            artifact_type=artifact_type,
            now_text=now_text,
        )
        if row is not None:
            return int(row["id"])
    return None


def _retain_only_preferred_summary_artifact(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    preferred_artifact_id: int | None,
    effective_at: datetime,
) -> None:
    if preferred_artifact_id is not None:
        conn.execute(
            """
            UPDATE ai_artifacts
            SET retention_class = ?, expires_at = NULL
            WHERE id = ?
              AND article_id = ?
              AND artifact_type IN (?, ?)
              AND retention_class != ?
            """,
            (
                AIArtifactRetentionClass.LIBRARY.value,
                preferred_artifact_id,
                article_id,
                AIArtifactType.DIGEST_SUMMARY.value,
                AIArtifactType.LIBRARY_SUMMARY.value,
                AIArtifactRetentionClass.USER_PINNED.value,
            ),
        )
    expires_at = datetime_to_db(temporary_artifact_expiration(effective_at))
    params: list[object] = [
        AIArtifactRetentionClass.TEMPORARY.value,
        expires_at,
        article_id,
        AIArtifactType.DIGEST_SUMMARY.value,
        AIArtifactType.LIBRARY_SUMMARY.value,
        AIArtifactRetentionClass.LIBRARY.value,
    ]
    preferred_clause = ""
    if preferred_artifact_id is not None:
        preferred_clause = "AND id != ?"
        params.append(preferred_artifact_id)
    conn.execute(
        f"""
        UPDATE ai_artifacts
        SET retention_class = ?, expires_at = ?
        WHERE article_id = ?
          AND artifact_type IN (?, ?)
          AND retention_class = ?
          {preferred_clause}
        """,
        tuple(params),
    )


def _get_compatible_ai_artifact(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    artifact_type: AIArtifactType,
    provider: str,
    model_id: str,
    generator_version: str,
    input_fingerprint: str,
    now_text: str,
) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT *
        FROM ai_artifacts
        WHERE article_id = ?
          AND artifact_type = ?
          AND provider = ?
          AND model_id = ?
          AND generator_version = ?
          AND input_fingerprint = ?
          AND (retention_class != ? OR expires_at >= ?)
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (
            article_id,
            artifact_type.value,
            provider,
            model_id,
            generator_version,
            input_fingerprint,
            AIArtifactRetentionClass.TEMPORARY.value,
            now_text,
        ),
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def _get_ai_conversation(
    conn: sqlite3.Connection,
    conversation_id: int,
) -> AIConversation | None:
    row = conn.execute(
        "SELECT * FROM ai_conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    return _ai_conversation_from_row(row) if row is not None else None


def _get_ai_conversation_message(
    conn: sqlite3.Connection,
    message_id: int,
) -> AIConversationMessage | None:
    row = conn.execute(
        "SELECT * FROM ai_conversation_messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    return _ai_conversation_message_from_row(row) if row is not None else None


def _last_ai_conversation_message_row(
    conn: sqlite3.Connection,
    conversation_id: int,
) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT *
        FROM ai_conversation_messages
        WHERE conversation_id = ?
        ORDER BY sequence_number DESC, id DESC
        LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    return cast(sqlite3.Row | None, row)


def _insert_ai_conversation_message(
    conn: sqlite3.Connection,
    message: AIConversationMessage,
) -> AIConversationMessage:
    cursor = conn.execute(
        """
        INSERT INTO ai_conversation_messages (
            conversation_id, sequence_number, role, content, created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            message.conversation_id,
            message.sequence_number,
            message.role.value,
            message.content,
            datetime_to_db(message.created_at),
        ),
    )
    conn.execute(
        "UPDATE ai_conversations SET updated_at = ? WHERE id = ?",
        (datetime_to_db(message.created_at), message.conversation_id),
    )
    saved = _get_ai_conversation_message(conn, _lastrowid(cursor))
    if saved is None:
        raise RuntimeError("failed to load created AI conversation message")
    return saved


def _ai_conversation_lock_name(conversation_id: int) -> str:
    return f"ai-conversation:{conversation_id}"


def _validate_rolling_summary_artifact(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    artifact_id: int | None,
) -> None:
    if artifact_id is None:
        return
    artifact = _get_ai_artifact(conn, artifact_id)
    if artifact is None:
        raise ValueError(f"AI artifact {artifact_id} does not exist")
    if artifact.article_id != article_id:
        raise ValueError("rolling summary artifact must belong to the conversation article")
    if artifact.artifact_type != AIArtifactType.CONVERSATION_SUMMARY:
        raise ValueError("rolling summary artifact must be a conversation summary")


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


def _get_library_search_document(
    conn: sqlite3.Connection,
    article_id: int,
) -> LibrarySearchDocument | None:
    row = conn.execute(
        "SELECT * FROM library_search_documents WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    return _library_search_document_from_row(row) if row is not None else None


def _get_library_connection_by_pair(
    conn: sqlite3.Connection,
    article_id_a: int,
    article_id_b: int,
) -> LibraryConnection | None:
    row = conn.execute(
        """
        SELECT *
        FROM library_article_connections
        WHERE article_id_a = ? AND article_id_b = ?
        """,
        (article_id_a, article_id_b),
    ).fetchone()
    return _library_connection_from_row(row) if row is not None else None


def _get_library_context_suggestion(
    conn: sqlite3.Connection,
    *,
    article_id: int,
    related_article_id: int,
    collection_id: int | None,
) -> LibraryContextSuggestion | None:
    row = conn.execute(
        """
        SELECT *
        FROM library_context_suggestions
        WHERE article_id = ?
            AND related_article_id = ?
            AND collection_key = IFNULL(?, 0)
        """,
        (article_id, related_article_id, collection_id),
    ).fetchone()
    return _library_context_suggestion_from_row(row) if row is not None else None


def _get_collection_intelligence_snapshot(
    conn: sqlite3.Connection,
    snapshot_id: int,
) -> CollectionIntelligenceSnapshot | None:
    row = conn.execute(
        "SELECT * FROM collection_intelligence_snapshots WHERE id = ?",
        (snapshot_id,),
    ).fetchone()
    return _collection_intelligence_snapshot_from_row(row) if row is not None else None


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


def _get_suggested_interest_profile(
    conn: sqlite3.Connection,
    *,
    profile_id: int,
    profile_fingerprint: str,
    suggestion_key: str,
) -> SuggestedInterestProfile | None:
    row = conn.execute(
        """
        SELECT *
        FROM suggested_interest_profiles
        WHERE profile_id = ? AND profile_fingerprint = ? AND suggestion_key = ?
        """,
        (profile_id, profile_fingerprint, suggestion_key),
    ).fetchone()
    return _suggested_interest_profile_from_row(row) if row is not None else None


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


def _canonical_article_pair(article_id_a: int, article_id_b: int) -> tuple[int, int]:
    if article_id_a <= 0 or article_id_b <= 0:
        raise ValueError("article ids must be positive")
    if article_id_a == article_id_b:
        raise ValueError("library connection cannot link an article to itself")
    if article_id_a < article_id_b:
        return article_id_a, article_id_b
    return article_id_b, article_id_a


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        reading_state=(
            ReadingState(str(row["library_reading_state"]))
            if row["library_reading_state"] is not None
            else None
        ),
        interest_rating=(
            int(row["library_interest_rating"])
            if row["library_interest_rating"] is not None
            else None
        ),
    )


def _ai_artifact_from_row(row: sqlite3.Row) -> AIArtifact:
    return AIArtifact(
        id=int(row["id"]),
        article_id=int(row["article_id"]),
        artifact_type=AIArtifactType(str(row["artifact_type"])),
        content=str(row["content"]),
        created_at=datetime_from_db(str(row["created_at"])),
        provider=str(row["provider"]),
        model_id=str(row["model_id"]),
        reasoning_effort=(
            str(row["reasoning_effort"]) if row["reasoning_effort"] is not None else None
        ),
        generator_version=str(row["generator_version"]),
        input_fingerprint=str(row["input_fingerprint"]),
        retention_class=AIArtifactRetentionClass(str(row["retention_class"])),
        expires_at=(
            datetime_from_db(str(row["expires_at"])) if row["expires_at"] is not None else None
        ),
    )


def _ai_conversation_from_row(row: sqlite3.Row) -> AIConversation:
    return AIConversation(
        id=int(row["id"]),
        article_id=int(row["article_id"]),
        title=str(row["title"]),
        created_at=datetime_from_db(str(row["created_at"])),
        updated_at=datetime_from_db(str(row["updated_at"])),
        provider=str(row["provider"]),
        model_id=str(row["model_id"]),
        conversation_version=int(row["conversation_version"]),
        rolling_summary_artifact_id=(
            int(row["rolling_summary_artifact_id"])
            if row["rolling_summary_artifact_id"] is not None
            else None
        ),
    )


def _ai_conversation_message_from_row(row: sqlite3.Row) -> AIConversationMessage:
    return AIConversationMessage(
        id=int(row["id"]),
        conversation_id=int(row["conversation_id"]),
        sequence_number=int(row["sequence_number"]),
        role=AIConversationRole(str(row["role"])),
        content=str(row["content"]),
        created_at=datetime_from_db(str(row["created_at"])),
    )


def _analysis_from_row(
    row: sqlite3.Row,
    *,
    summary_column: str = "summary",
) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=float(row["relevance_score"]),
        relevance_reason=str(row["relevance_reason"]),
        matched_topics=list(json.loads(row["matched_topics_json"])),
        summary=str(row[summary_column]),
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


def _library_search_document_from_row(row: sqlite3.Row) -> LibrarySearchDocument:
    return LibrarySearchDocument(
        article_id=int(row["article_id"]),
        document_text=str(row["document_text"]),
        updated_at=datetime_from_db(str(row["updated_at"])),
    )


def _library_connection_from_row(row: sqlite3.Row) -> LibraryConnection:
    provenance = json.loads(str(row["provenance_json"]))
    if not isinstance(provenance, dict):
        provenance = {"invalid_provenance": True}
    confidence = row["confidence"]
    dismissed_at = row["dismissed_at"]
    return LibraryConnection(
        id=int(row["id"]),
        article_id_a=int(row["article_id_a"]),
        article_id_b=int(row["article_id_b"]),
        relation_label=str(row["relation_label"]),
        rationale=str(row["rationale"]),
        origin=ConnectionOrigin(str(row["origin"])),
        provenance=cast(dict[str, object], provenance),
        confidence=float(confidence) if confidence is not None else None,
        generated_at=datetime_from_db(str(row["generated_at"])),
        dismissed_at=datetime_from_db(str(dismissed_at)) if dismissed_at is not None else None,
    )


def _library_context_suggestion_from_row(row: sqlite3.Row) -> LibraryContextSuggestion:
    provenance = json.loads(str(row["provenance_json"]))
    if not isinstance(provenance, dict):
        provenance = {"invalid_provenance": True}
    confidence = row["confidence"]
    dismissed_at = row["dismissed_at"]
    collection_id = row["collection_id"]
    run_id = row["run_id"]
    return LibraryContextSuggestion(
        id=int(row["id"]),
        run_id=int(run_id) if run_id is not None else None,
        article_id=int(row["article_id"]),
        related_article_id=int(row["related_article_id"]),
        collection_id=int(collection_id) if collection_id is not None else None,
        relation_label=str(row["relation_label"]),
        rationale=str(row["rationale"]),
        origin=LibraryContextOrigin(str(row["origin"])),
        provenance=cast(dict[str, object], provenance),
        confidence=float(confidence) if confidence is not None else None,
        created_at=datetime_from_db(str(row["created_at"])),
        dismissed_at=datetime_from_db(str(dismissed_at)) if dismissed_at is not None else None,
    )


def _collection_intelligence_snapshot_from_row(
    row: sqlite3.Row,
) -> CollectionIntelligenceSnapshot:
    evidence = json.loads(str(row["evidence_json"]))
    provenance = json.loads(str(row["provenance_json"]))
    if not isinstance(evidence, dict):
        evidence = {"invalid_evidence": True}
    if not isinstance(provenance, dict):
        provenance = {"invalid_provenance": True}
    dismissed_at = row["dismissed_at"]
    return CollectionIntelligenceSnapshot(
        id=int(row["id"]),
        collection_id=int(row["collection_id"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        evidence=cast(dict[str, object], evidence),
        origin=LibraryContextOrigin(str(row["origin"])),
        provenance=cast(dict[str, object], provenance),
        generated_at=datetime_from_db(str(row["generated_at"])),
        dismissed_at=datetime_from_db(str(dismissed_at)) if dismissed_at is not None else None,
    )


def _feedback_from_row(row: sqlite3.Row) -> ArticleFeedback:
    columns = set(row.keys())
    profile_match = row["profile_match"] if "profile_match" in columns else None
    personal_interest = row["personal_interest"] if "personal_interest" in columns else None
    feedback_label = row["feedback_label"] if "feedback_label" in columns else None
    return ArticleFeedback(
        id=int(row["id"]),
        article_id=int(row["article_id"]),
        profile_id=int(row["profile_id"]),
        profile_fingerprint=str(row["profile_fingerprint"]),
        feedback_label=(
            cast(FeedbackLabel, str(feedback_label)) if feedback_label is not None else None
        ),
        profile_match=(
            cast(FeedbackAnswer, str(profile_match)) if profile_match is not None else None
        ),
        personal_interest=(
            cast(FeedbackAnswer, str(personal_interest)) if personal_interest is not None else None
        ),
        created_at=datetime_from_db(str(row["created_at"])),
        updated_at=datetime_from_db(str(row["updated_at"])),
    )


def _quantitative_calibration_from_row(
    row: sqlite3.Row,
) -> QuantitativeRelevanceCalibration:
    article_id = row["article_id"]
    model_score = row["model_relevance_score"]
    user_score = row["user_relevance_score"]
    completed_at = row["completed_at"]
    return QuantitativeRelevanceCalibration(
        id=int(row["id"]),
        run_id=int(row["run_id"]),
        article_id=int(article_id) if article_id is not None else None,
        profile_id=int(row["profile_id"]),
        profile_fingerprint=str(row["profile_fingerprint"]),
        model_relevance_score=float(model_score) if model_score is not None else None,
        state=cast(QuantitativeCalibrationState, str(row["state"])),
        user_relevance_score=float(user_score) if user_score is not None else None,
        created_at=datetime_from_db(str(row["created_at"])),
        completed_at=(datetime_from_db(str(completed_at)) if completed_at is not None else None),
    )


def _suggested_interest_profile_from_row(row: sqlite3.Row) -> SuggestedInterestProfile:
    evidence = json.loads(str(row["evidence_article_ids_json"]))
    if not isinstance(evidence, list):
        evidence = []
    provenance = json.loads(str(row["provenance_json"]))
    if not isinstance(provenance, dict):
        provenance = {"invalid_provenance": True}
    dismissed_at = row["dismissed_at"]
    accepted_profile_id = row["accepted_profile_id"]
    return SuggestedInterestProfile(
        id=int(row["id"]),
        profile_id=int(row["profile_id"]),
        profile_fingerprint=str(row["profile_fingerprint"]),
        suggested_name=str(row["suggested_name"]),
        suggested_description=str(row["suggested_description"]),
        evidence_article_ids=tuple(int(value) for value in evidence),
        explanation=str(row["explanation"]),
        suggestion_key=str(row["suggestion_key"]),
        provenance=cast(dict[str, object], provenance),
        created_at=datetime_from_db(str(row["created_at"])),
        dismissed_at=datetime_from_db(str(dismissed_at)) if dismissed_at is not None else None,
        accepted_profile_id=(int(accepted_profile_id) if accepted_profile_id is not None else None),
    )
