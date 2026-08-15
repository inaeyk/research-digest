"""SQLite persistence for Research Digest."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from research_digest.errors import sanitize_error_text
from research_digest.models import (
    AnalysisResult,
    Article,
    ArticleFeedback,
    ArxivSourceConfig,
    FeedbackLabel,
    InterestProfile,
    ReadingPriority,
    datetime_from_db,
    datetime_to_db,
    utc_now,
)

SOURCE_ARXIV = "arxiv"


class Database:
    """Small sqlite3 wrapper for application persistence.

    The object is safe to cache in Streamlit because it stores only the database
    path. Each public operation opens, commits or rolls back, and closes its own
    sqlite connection.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = path
        self.initialize()

    def close(self) -> None:
        """Retained for callers; operation-scoped connections close themselves."""

    def initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS interest_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    relevance_threshold REAL NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_configs (
                    source_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    categories_json TEXT NOT NULL,
                    lookback_hours INTEGER NOT NULL,
                    max_results INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

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
                );

                CREATE TABLE IF NOT EXISTS relevance_analyses (
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
                );

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
                );

                CREATE TABLE IF NOT EXISTS app_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER,
                    source_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    retrieved_count INTEGER NOT NULL DEFAULT 0,
                    stored_count INTEGER NOT NULL DEFAULT 0,
                    preselected_count INTEGER NOT NULL DEFAULT 0,
                    skipped_analysis_count INTEGER NOT NULL DEFAULT 0,
                    analyzed_count INTEGER NOT NULL DEFAULT 0,
                    relevant_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    FOREIGN KEY(profile_id) REFERENCES interest_profiles(id) ON DELETE SET NULL
                );
                """
            )
            row = conn.execute(
                "SELECT 1 FROM source_configs WHERE source_name = ?",
                (SOURCE_ARXIV,),
            ).fetchone()
            if row is None:
                _save_arxiv_config(conn, ArxivSourceConfig())
            _migrate_relevance_analysis_profile_fingerprints(conn)
            _migrate_app_run_preselection_counts(conn)
            _sanitize_existing_app_run_errors(conn)

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

    def create_app_run(self, *, profile_id: int | None, source_name: str) -> int:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO app_runs (profile_id, source_name, started_at, status)
                VALUES (?, ?, ?, ?)
                """,
                (profile_id, source_name, datetime_to_db(utc_now()), "running"),
            )
            return _lastrowid(cursor)

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
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE app_runs
                SET completed_at = ?, status = ?, retrieved_count = ?, stored_count = ?,
                    preselected_count = ?, skipped_analysis_count = ?, analyzed_count = ?,
                    relevant_count = ?, error_message = ?
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
                    run_id,
                ),
            )

    def get_app_runs(self) -> list[sqlite3.Row]:
        with self._connection() as conn:
            return list(
                conn.execute("SELECT * FROM app_runs ORDER BY id DESC").fetchall()
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


def _get_interest_profile(conn: sqlite3.Connection, profile_id: int) -> InterestProfile | None:
    row = conn.execute(
        "SELECT * FROM interest_profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()
    return _profile_from_row(row) if row is not None else None


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


def _analysis_from_row(row: sqlite3.Row) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=float(row["relevance_score"]),
        relevance_reason=str(row["relevance_reason"]),
        matched_topics=list(json.loads(row["matched_topics_json"])),
        summary=str(row["summary"]),
        why_it_matters=str(row["why_it_matters"]),
        reading_priority=cast(ReadingPriority, str(row["reading_priority"])),
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
