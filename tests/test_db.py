from __future__ import annotations

import queue
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from research_digest import db as db_module
from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_PARTIAL,
    APP_RUN_RUNNING,
    CURRENT_SCHEMA_VERSION,
    Database,
    MigrationError,
    SchemaMigration,
)
from research_digest.library import save_article_with_personal_interest, unsave_article
from research_digest.models import (
    AnalysisResult,
    Article,
    ArticleFeedback,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.preselection import AbstractPreselectionDecision


def sample_article(source_article_id: str = "2608.00001") -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title="Warped compactifications",
        authors=["Ada Lovelace"],
        abstract="A paper about higher-dimensional gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=f"http://arxiv.org/pdf/{source_article_id}",
    )


def assert_sqlite_integrity(test_case: unittest.TestCase, path: Path) -> None:
    with sqlite3.connect(path) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    test_case.assertIsNotNone(row)
    assert row is not None
    test_case.assertEqual(row[0], "ok")


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_arxiv_config_defaults_and_update(self) -> None:
        config = self.db.get_arxiv_config()
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.categories, ["gr-qc", "hep-th"])

        self.db.save_arxiv_config(
            ArxivSourceConfig(
                enabled=False,
                categories=["math-ph"],
                lookback_hours=12,
                max_results=10,
            )
        )
        updated = self.db.get_arxiv_config()
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertFalse(updated.enabled)
        self.assertEqual(updated.categories, ["math-ph"])
        self.assertEqual(updated.lookback_hours, 12)
        self.assertEqual(updated.max_results, 10)

    def test_arxiv_config_reload_preserves_category_semantic_equality(self) -> None:
        self.db.save_arxiv_config(
            ArxivSourceConfig(
                enabled=True,
                categories=[" hep-th ", "gr-qc", "hep-th"],
                lookback_hours=12,
                max_results=10,
            )
        )

        reloaded = self.db.get_arxiv_config()

        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.categories, ["gr-qc", "hep-th"])

    def test_fresh_database_records_current_schema_version(self) -> None:
        self.assertEqual(self.db.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNone(self.db.last_migration_backup_path)
        with sqlite3.connect(self.db.path) as conn:
            row = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'preselection_decisions'
                """
            ).fetchone()
        self.assertIsNotNone(row)

    def test_current_database_reopen_is_idempotent_without_backup(self) -> None:
        created = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity and black branes.",
        )
        reopened = Database(self.db.path)
        self.addCleanup(reopened.close)

        self.assertEqual(reopened.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNone(reopened.last_migration_backup_path)
        self.assertIsNone(reopened.get_last_migration_backup_path())
        self.assertEqual(reopened.list_interest_profiles(), [created])

    def test_preselection_decision_persistence_is_idempotent(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Black branes.",
            relevance_threshold=0.7,
        )
        saved, _ = self.db.upsert_article(sample_article())
        assert saved.id is not None
        assert profile.id is not None
        run_id = self.db.create_app_run(
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            source_name="arxiv",
            source_fingerprint="source-v1",
        )
        decision = AbstractPreselectionDecision(
            article_id=f"{saved.source}:{saved.source_article_id}",
            selected=True,
            stage="model_abstract",
            matched_terms=(),
            reason="fake score",
            preselection_score=0.51,
            preselection_threshold=0.49,
            preselector_version="fake_model_abstract_v1",
        )

        self.db.save_preselection_decisions(
            run_id=run_id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            source_name="arxiv",
            source_fingerprint="source-v1",
            article_by_key={decision.article_id: saved},
            decisions=(decision,),
        )
        self.db.save_preselection_decisions(
            run_id=run_id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            source_name="arxiv",
            source_fingerprint="source-v1",
            article_by_key={decision.article_id: saved},
            decisions=(decision,),
        )

        rows = self.db.list_preselection_decisions(run_id=run_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["preselection_score"]), 0.51)
        self.assertEqual(str(rows[0]["preselector_version"]), "fake_model_abstract_v1")

    def test_unknown_future_schema_version_fails_clearly(self) -> None:
        future_path = Path(self.tmpdir.name) / "future.sqlite3"
        with sqlite3.connect(future_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '999', '2026-08-14T00:00:00Z');
                """
            )

        with self.assertRaisesRegex(MigrationError, "newer than supported"):
            Database(future_path)

    def test_interest_crud(self) -> None:
        created = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity and black branes.",
            relevance_threshold=0.7,
            enabled=True,
        )

        self.assertIsNotNone(created.id)
        self.assertEqual(self.db.list_interest_profiles(enabled_only=True), [created])

        updated = self.db.update_interest_profile(
            InterestProfile(
                id=created.id,
                name="Gravity updated",
                description="Massive spin-2 states.",
                relevance_threshold=0.4,
                enabled=False,
            )
        )
        self.assertEqual(updated.name, "Gravity updated")
        self.assertFalse(updated.enabled)
        self.assertEqual(self.db.list_interest_profiles(enabled_only=True), [])

    def test_database_can_be_reused_from_another_thread(self) -> None:
        created = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity and black branes.",
        )
        results: queue.Queue[BaseException | list[InterestProfile]] = queue.Queue()

        def worker() -> None:
            try:
                results.put(self.db.list_interest_profiles())
            except BaseException as exc:
                results.put(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        result = results.get_nowait()
        if isinstance(result, BaseException):
            raise result
        self.assertFalse(hasattr(self.db, "_conn"))
        self.assertEqual(result, [created])

    def test_article_deduplication_and_idempotency(self) -> None:
        first, first_inserted = self.db.upsert_article(sample_article())
        second, second_inserted = self.db.upsert_article(sample_article())

        self.assertTrue(first_inserted)
        self.assertFalse(second_inserted)
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.count_articles(), 1)

    def test_analysis_round_trip(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        article, _ = self.db.upsert_article(sample_article())
        assert article.id is not None
        assert profile.id is not None

        analysis = AnalysisResult(
            relevance_score=0.8,
            relevance_reason="Direct match.",
            matched_topics=["gravity"],
            summary="Summary.",
            why_it_matters="It matches the profile.",
            reading_priority="HIGH",
        )
        self.db.upsert_analysis(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            analysis=analysis,
        )

        loaded = self.db.get_analysis(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
        )
        self.assertEqual(loaded, analysis)

    def test_source_date_coverage_round_trip_and_upsert(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        assert profile.id is not None
        fingerprint = profile_semantic_fingerprint(profile)
        run_id = self.db.create_app_run(
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            source_name="arxiv",
        )
        self.assertEqual(self.db.get_app_runs()[0]["profile_fingerprint"], fingerprint)

        self.db.mark_source_date_covered(
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            source_name="arxiv",
            source_fingerprint="source-a",
            source_date=date(2026, 8, 14),
            run_id=run_id,
            run_origin=RunOrigin.SCHEDULED,
        )
        self.db.mark_source_date_covered(
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            source_name="arxiv",
            source_fingerprint="source-a",
            source_date=date(2026, 8, 14),
            run_id=run_id,
            run_origin=RunOrigin.SCHEDULED,
        )

        self.assertEqual(
            self.db.list_covered_source_dates(
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
                source_name="arxiv",
                source_fingerprint="source-a",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
            ),
            {date(2026, 8, 14)},
        )
        self.assertEqual(len(self.db.list_source_date_coverage()), 1)

    def test_v16_profile_coverage_migrates_to_consolidated_source_coverage(self) -> None:
        first = self.db.create_interest_profile(name="First", description="First semantics.")
        second = self.db.create_interest_profile(name="Second", description="Second semantics.")
        assert first.id is not None
        assert second.id is not None
        source_fingerprint = "stable-source-scope"

        run_ids: list[int] = []
        for profile, source_date, status, retrieval_complete, covered, incomplete in (
            (first, date(2026, 8, 14), APP_RUN_COMPLETED, True, True, False),
            (second, date(2026, 8, 14), APP_RUN_COMPLETED, True, True, False),
            (first, date(2026, 8, 15), APP_RUN_PARTIAL, True, True, False),
            (first, date(2026, 8, 16), APP_RUN_FAILED, True, True, False),
            (first, date(2026, 8, 17), APP_RUN_FAILED, False, False, True),
        ):
            run_id = self.db.create_app_run(
                profile_id=profile.id,
                profile_fingerprint=profile_semantic_fingerprint(profile),
                source_name="arxiv",
                source_fingerprint=source_fingerprint,
                date_selection=DateSelection.single_date(source_date),
            )
            self.db.finish_app_run(
                run_id,
                status=status,
                retrieved_count=1,
                stored_count=1,
                preselected_count=1,
                skipped_analysis_count=0,
                analyzed_count=1 if status == APP_RUN_COMPLETED else 0,
                relevant_count=0,
                requested_source_dates=(source_date.isoformat(),),
                covered_source_dates=(source_date.isoformat(),) if covered else (),
                incomplete_source_dates=(source_date.isoformat(),) if incomplete else (),
                retrieval_complete=retrieval_complete,
            )
            run_ids.append(run_id)

        mixed_run_id = self.db.create_app_run(
            profile_id=first.id,
            profile_fingerprint=profile_semantic_fingerprint(first),
            source_name="arxiv",
            source_fingerprint=source_fingerprint,
            date_selection=DateSelection.date_range(
                date(2026, 8, 18),
                date(2026, 8, 19),
            ),
        )
        self.db.finish_app_run(
            mixed_run_id,
            status=APP_RUN_PARTIAL,
            retrieved_count=1,
            stored_count=1,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            relevant_count=0,
            requested_source_dates=("2026-08-18", "2026-08-19"),
            covered_source_dates=("2026-08-18",),
            incomplete_source_dates=("2026-08-19",),
            retrieval_complete=False,
        )
        run_ids.append(mixed_run_id)

        self.db.close()
        with sqlite3.connect(self.db.path) as conn:
            conn.executescript(
                """
                DROP TABLE source_date_corpus_articles;
                DROP TABLE source_date_corpora;
                DROP TABLE source_date_coverage;
                CREATE TABLE source_date_coverage (
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
                    UNIQUE(
                        profile_id, profile_fingerprint, source_name,
                        source_fingerprint, source_date
                    )
                );
                """
            )
            for profile, run_id in ((first, run_ids[0]), (second, run_ids[1])):
                conn.execute(
                    """
                    INSERT INTO source_date_coverage (
                        profile_id, profile_fingerprint, source_name, source_fingerprint,
                        source_date, status, first_covered_run_id, last_covered_run_id,
                        run_origin, covered_at, updated_at
                    ) VALUES (?, ?, 'arxiv', ?, '2026-08-14', 'COVERED', ?, ?,
                        'MANUAL', '2026-08-14T12:00:00Z', '2026-08-14T12:00:00Z')
                    """,
                    (
                        profile.id,
                        profile_semantic_fingerprint(profile),
                        source_fingerprint,
                        run_id,
                        run_id,
                    ),
                )
            conn.execute(
                "UPDATE schema_metadata SET value = '16' WHERE key = 'schema_version'"
            )

        migrated = Database(self.db.path)
        self.addCleanup(migrated.close)
        rows = migrated.list_source_date_coverage()
        with sqlite3.connect(self.db.path) as conn:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(source_date_coverage)").fetchall()
            }
            corpus_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'source_date_corpora'"
            ).fetchone()

        self.assertEqual(migrated.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNotNone(migrated.last_migration_backup_path)
        self.assertNotIn("profile_id", columns)
        self.assertNotIn("profile_fingerprint", columns)
        self.assertIsNotNone(corpus_table)
        self.assertEqual(
            {(str(row["source_date"]), int(row["last_covered_run_id"])) for row in rows},
            {
                ("2026-08-14", run_ids[1]),
                ("2026-08-15", run_ids[2]),
                ("2026-08-16", run_ids[3]),
                ("2026-08-18", run_ids[5]),
            },
        )
        self.assertEqual(len(migrated.get_app_runs()), 6)

    def test_article_feedback_round_trip_and_profile_semantic_isolation(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        article, _ = self.db.upsert_article(sample_article())
        assert article.id is not None
        assert profile.id is not None
        fingerprint = profile_semantic_fingerprint(profile)

        saved = self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            feedback_label="RELEVANT",
        )

        self.assertIsInstance(saved, ArticleFeedback)
        self.assertEqual(saved.feedback_label, "RELEVANT")
        self.assertEqual(saved.profile_match, "YES")
        self.assertIsNone(saved.personal_interest)
        self.assertEqual(
            self.db.get_article_feedback(
                article_id=article.id,
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
            ),
            saved,
        )
        self.assertEqual(
            self.db.list_article_feedback(
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
            ),
            [saved],
        )

        updated = self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            feedback_label="NOT_RELEVANT",
        )
        self.assertEqual(updated.id, saved.id)
        self.assertEqual(updated.created_at, saved.created_at)
        self.assertEqual(updated.feedback_label, "NOT_RELEVANT")
        self.assertEqual(updated.profile_match, "NO")
        self.assertIsNone(updated.personal_interest)

        interest_updated = self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            personal_interest="YES",
        )
        self.assertEqual(interest_updated.id, saved.id)
        self.assertEqual(interest_updated.profile_match, "NO")
        self.assertEqual(interest_updated.personal_interest, "YES")

        profile_updated = self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            profile_match="YES",
        )
        self.assertEqual(profile_updated.id, saved.id)
        self.assertEqual(profile_updated.profile_match, "YES")
        self.assertEqual(profile_updated.personal_interest, "YES")

        cleared_profile = self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            clear_profile_match=True,
        )
        self.assertIsNone(cleared_profile.feedback_label)
        self.assertIsNone(cleared_profile.profile_match)
        self.assertEqual(cleared_profile.personal_interest, "YES")

        cleared_interest = self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            clear_personal_interest=True,
        )
        self.assertIsNone(cleared_interest.feedback_label)
        self.assertIsNone(cleared_interest.profile_match)
        self.assertIsNone(cleared_interest.personal_interest)

    def test_save_to_library_records_personal_interest_without_profile_match(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        article, _ = self.db.upsert_article(sample_article("2608.save-interest"))
        assert article.id is not None
        assert profile.id is not None
        fingerprint = profile_semantic_fingerprint(profile)

        save_article_with_personal_interest(
            self.db,
            article_id=article.id,
            profile=profile,
            profile_fingerprint_value=fingerprint,
        )
        first = self.db.get_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
        )

        self.assertIsNotNone(first)
        assert first is not None
        self.assertIsNone(first.profile_match)
        self.assertEqual(first.personal_interest, "YES")

        self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            profile_match="NO",
            personal_interest="NO",
        )
        save_article_with_personal_interest(
            self.db,
            article_id=article.id,
            profile=profile,
            profile_fingerprint_value=fingerprint,
        )
        updated = self.db.get_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.profile_match, "NO")
        self.assertEqual(updated.personal_interest, "YES")

        unsave_article(self.db, article.id)
        after_unsave = self.db.get_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
        )
        self.assertIsNotNone(after_unsave)
        assert after_unsave is not None
        self.assertEqual(after_unsave.personal_interest, "YES")

        changed_profile = self.db.update_interest_profile(
            InterestProfile(
                id=profile.id,
                name=profile.name,
                description="Condensed matter dualities.",
                relevance_threshold=profile.relevance_threshold,
                enabled=profile.enabled,
            )
        )
        self.assertIsNone(
            self.db.get_article_feedback(
                article_id=article.id,
                profile_id=changed_profile.id or 0,
                profile_fingerprint=profile_semantic_fingerprint(changed_profile),
            )
        )

    def test_schema_13_feedback_upgrade_maps_legacy_label_to_profile_match(self) -> None:
        path = Path(self.tmpdir.name) / "schema13-feedback.sqlite3"
        now = "2026-08-14T12:00:00Z"
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE interest_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    relevance_threshold REAL NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE source_configs (
                    source_name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    categories_json TEXT NOT NULL,
                    lookback_hours INTEGER NOT NULL,
                    max_results INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE articles (
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
                CREATE TABLE article_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    profile_id INTEGER NOT NULL,
                    profile_fingerprint TEXT NOT NULL,
                    feedback_label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(article_id, profile_id, profile_fingerprint)
                );
                """
            )
            conn.execute(
                "INSERT INTO schema_metadata (key, value, updated_at) VALUES (?, ?, ?)",
                ("schema_version", "13", now),
            )
            conn.execute(
                """
                INSERT INTO interest_profiles (
                    id, name, description, relevance_threshold, enabled, created_at, updated_at
                )
                VALUES (1, 'Gravity', 'Higher-dimensional gravity.', 0.6, 1, ?, ?)
                """,
                (now, now),
            )
            conn.execute(
                """
                INSERT INTO articles (
                    id, source, source_article_id, title, authors_json, abstract,
                    categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
                )
                VALUES (1, 'arxiv', '2608.legacy-feedback', 'Legacy feedback',
                    '["Ada Lovelace"]', 'Abstract.', '["hep-th"]',
                    ?, ?, 'http://arxiv.org/abs/2608.legacy-feedback', NULL, ?)
                """,
                (now, now, now),
            )
            conn.execute(
                """
                INSERT INTO article_feedback (
                    id, article_id, profile_id, profile_fingerprint, feedback_label,
                    created_at, updated_at
                )
                VALUES (1, 1, 1, 'fingerprint', 'NOT_RELEVANT', ?, ?)
                """,
                (now, now),
            )

        migrated = Database(path)
        try:
            feedback = migrated.get_article_feedback(
                article_id=1,
                profile_id=1,
                profile_fingerprint="fingerprint",
            )
            first_version = migrated.get_schema_version()
        finally:
            migrated.close()
        reopened = Database(path)
        try:
            second_version = reopened.get_schema_version()
        finally:
            reopened.close()

        self.assertEqual(first_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(second_version, CURRENT_SCHEMA_VERSION)
        self.assertIsNotNone(feedback)
        assert feedback is not None
        self.assertEqual(feedback.feedback_label, "NOT_RELEVANT")
        self.assertEqual(feedback.profile_match, "NO")
        self.assertIsNone(feedback.personal_interest)

    def test_legacy_analysis_rows_are_retained_but_not_reused_as_current_profile(
        self,
    ) -> None:
        legacy_path = Path(self.tmpdir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript(
                """
                CREATE TABLE interest_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    relevance_threshold REAL NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE articles (
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
                CREATE TABLE relevance_analyses (
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
                );
                INSERT INTO interest_profiles (
                    id, name, description, relevance_threshold, enabled, created_at, updated_at
                )
                VALUES (
                    1, 'Gravity', 'Higher-dimensional gravity.', 0.6, 1,
                    '2026-08-14T00:00:00Z', '2026-08-14T00:00:00Z'
                );
                INSERT INTO articles (
                    id, source, source_article_id, title, authors_json, abstract,
                    categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
                )
                VALUES (
                    1, 'arxiv', '2608.00001', 'Warped compactifications',
                    '["Ada Lovelace"]', 'A paper about higher-dimensional gravity.',
                    '["hep-th"]', '2026-08-14T10:00:00Z', '2026-08-14T11:00:00Z',
                    'http://arxiv.org/abs/2608.00001', NULL, '2026-08-14T12:00:00Z'
                );
                INSERT INTO relevance_analyses (
                    id, article_id, profile_id, relevance_score, relevance_reason,
                    matched_topics_json, summary, why_it_matters, reading_priority, analyzed_at
                )
                VALUES (
                    1, 1, 1, 0.8, 'Direct match.', '["gravity"]', 'Summary.',
                    'It matches the profile.', 'HIGH', '2026-08-14T12:05:00Z'
                );
                """
            )

        migrated_db = Database(legacy_path)
        self.assertEqual(migrated_db.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNotNone(migrated_db.last_migration_backup_path)
        assert migrated_db.last_migration_backup_path is not None
        self.assertTrue(migrated_db.last_migration_backup_path.exists())
        assert_sqlite_integrity(self, migrated_db.last_migration_backup_path)
        self.assertEqual(
            migrated_db.get_last_migration_backup_path(),
            migrated_db.last_migration_backup_path,
        )
        profile = migrated_db.get_interest_profile(1)
        self.assertIsNotNone(profile)
        assert profile is not None

        loaded = migrated_db.get_analysis(
            article_id=1,
            profile_id=1,
            profile_fingerprint=profile_semantic_fingerprint(profile),
        )
        self.assertIsNone(loaded)
        with sqlite3.connect(legacy_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM relevance_analyses").fetchone()
        self.assertIsNotNone(count)
        assert count is not None
        self.assertEqual(count[0], 1)

        current_analysis = AnalysisResult(
            relevance_score=0.9,
            relevance_reason="Fresh current-profile match.",
            matched_topics=["gravity"],
            summary="Fresh summary.",
            why_it_matters="It matches the current profile.",
            reading_priority="HIGH",
        )
        migrated_db.upsert_analysis(
            article_id=1,
            profile_id=1,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            analysis=current_analysis,
        )
        self.assertEqual(
            migrated_db.get_analysis(
                article_id=1,
                profile_id=1,
                profile_fingerprint=profile_semantic_fingerprint(profile),
            ),
            current_analysis,
        )

    def test_legacy_app_runs_gain_preselection_count_columns(self) -> None:
        legacy_path = Path(self.tmpdir.name) / "legacy_runs.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript(
                """
                CREATE TABLE app_runs (
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
                    error_message TEXT
                );
                INSERT INTO app_runs (
                    id, profile_id, source_name, started_at, completed_at, status,
                    retrieved_count, stored_count, analyzed_count, relevant_count, error_message
                )
                VALUES
                    (
                        1, NULL, 'arxiv', '2026-08-14T12:00:00Z',
                        '2026-08-14T12:01:00Z', 'success', 4, 4, 3, 2, NULL
                    ),
                    (
                        2, NULL, 'arxiv', '2026-08-14T12:02:00Z',
                        NULL, 'running', 0, 0, 0, 0, NULL
                    ),
                    (
                        3, NULL, 'arxiv', '2026-08-14T12:03:00Z',
                        '2026-08-14T12:04:00Z', 'failed', 0, 0, 0, 0, 'failed'
                    ),
                    (
                        4, NULL, 'arxiv', '2026-08-14T12:05:00Z',
                        '2026-08-14T12:06:00Z', 'analysis_unavailable',
                        0, 0, 0, 0, NULL
                    );
                """
            )

        migrated_db = Database(legacy_path)
        self.assertEqual(migrated_db.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNotNone(migrated_db.last_migration_backup_path)
        assert migrated_db.last_migration_backup_path is not None
        self.assertTrue(migrated_db.last_migration_backup_path.exists())
        assert_sqlite_integrity(self, migrated_db.last_migration_backup_path)
        self.assertEqual(
            migrated_db.get_last_migration_backup_path(),
            migrated_db.last_migration_backup_path,
        )
        runs = migrated_db.get_app_runs()

        self.assertEqual(runs[-1]["preselected_count"], 0)
        self.assertEqual(runs[-1]["skipped_analysis_count"], 0)
        self.assertEqual(
            {row["id"]: row["status"] for row in runs},
            {
                1: APP_RUN_COMPLETED,
                2: APP_RUN_RUNNING,
                3: APP_RUN_FAILED,
                4: APP_RUN_ANALYSIS_UNAVAILABLE,
            },
        )
        self.assertEqual(runs[-1]["run_origin"], "LEGACY")
        self.assertIsNone(runs[-1]["profile_fingerprint"])
        self.assertIsNone(runs[-1]["date_selection_json"])
        self.assertEqual(runs[-1]["requested_source_dates_json"], "[]")
        self.assertEqual(runs[-1]["covered_source_dates_json"], "[]")
        self.assertEqual(runs[-1]["empty_source_dates_json"], "[]")
        self.assertEqual(runs[-1]["incomplete_source_dates_json"], "[]")
        self.assertEqual(runs[-1]["retrieval_complete"], 1)
        self.assertIsNone(runs[-1]["retrieval_safety_limit"])
        self.assertEqual(migrated_db.list_source_date_coverage(), [])

    def test_migration_failure_leaves_recoverable_backup_and_old_db(self) -> None:
        legacy_path = Path(self.tmpdir.name) / "failing_migration.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE interest_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    relevance_threshold REAL NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '1', '2026-08-14T00:00:00Z');
                INSERT INTO interest_profiles (
                    id, name, description, relevance_threshold, enabled, created_at, updated_at
                )
                VALUES (
                    1, 'Gravity', 'Higher-dimensional gravity.', 0.6, 1,
                    '2026-08-14T00:00:00Z', '2026-08-14T00:00:00Z'
                );
                """
            )

        def fail_migration(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE transient_migration_table (id INTEGER PRIMARY KEY)")
            raise RuntimeError("forced migration failure")

        with mock.patch.object(
            db_module,
            "MIGRATIONS",
            (SchemaMigration(2, "forced failure", fail_migration),),
        ), self.assertRaises(MigrationError) as caught:
            Database(legacy_path)

        self.assertIsNotNone(caught.exception.backup_path)
        assert caught.exception.backup_path is not None
        self.assertTrue(caught.exception.backup_path.exists())
        assert_sqlite_integrity(self, caught.exception.backup_path)
        with sqlite3.connect(legacy_path) as conn:
            row = conn.execute("SELECT name FROM interest_profiles WHERE id = 1").fetchone()
            transient = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'transient_migration_table'
                """
            ).fetchone()
        self.assertEqual(row[0], "Gravity")
        self.assertIsNone(transient)


if __name__ == "__main__":
    unittest.main()
