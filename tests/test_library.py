from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from research_digest.db import APP_RUN_COMPLETED, CURRENT_SCHEMA_VERSION, Database
from research_digest.library import (
    filter_library_items,
    is_article_saved,
    is_source_article_saved,
    list_library_items,
    save_article,
    save_article_by_source_identity,
    sort_library_items,
    unsave_article,
    unsave_article_by_source_identity,
)
from research_digest.models import (
    AnalysisResult,
    Article,
    profile_semantic_fingerprint,
)
from research_digest.ui.abstracts import ArticleIdentity
from research_digest.ui.library_controls import library_button_key, library_button_label


def sample_article(
    source_article_id: str = "2608.lib01",
    title: str = "Library paper",
    *,
    hour: int = 10,
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace", "Grace Hopper"],
        abstract=f"{title} abstract about warped compactifications.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, hour, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, hour, 10, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=f"http://arxiv.org/pdf/{source_article_id}",
    )


def sample_analysis(score: float = 0.8) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=score,
        relevance_reason="Direct scientific match.",
        matched_topics=["gravity"],
        summary="Generated summary.",
        why_it_matters="Generated reason.",
        reading_priority="HIGH" if score >= 0.7 else "LOW",
    )


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "library.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_save_is_idempotent_and_article_centric(self) -> None:
        first, inserted = self.db.upsert_article(sample_article())
        second, second_inserted = self.db.upsert_article(sample_article())
        assert first.id is not None

        first_save = save_article(self.db, first.id)
        repeated_save = save_article(self.db, first.id)

        self.assertTrue(inserted)
        self.assertFalse(second_inserted)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first_save.article.id, repeated_save.article.id)
        self.assertEqual(first_save.saved_at, repeated_save.saved_at)
        self.assertTrue(is_article_saved(self.db, first.id))
        self.assertEqual(len(self.db.list_saved_library_entries()), 1)

    def test_unsave_and_resave_preserve_underlying_scientific_records(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        article, _ = self.db.upsert_article(sample_article())
        assert article.id is not None
        assert profile.id is not None
        fingerprint = profile_semantic_fingerprint(profile)
        self.db.upsert_analysis(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            analysis=sample_analysis(),
        )
        self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            feedback_label="RELEVANT",
        )
        run_id = self.db.create_app_run(
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            source_name="arxiv",
        )
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_COMPLETED,
            retrieved_count=1,
            stored_count=1,
            preselected_count=1,
            skipped_analysis_count=0,
            analyzed_count=1,
            relevant_count=1,
        )
        self.db.save_run_snapshot(run_id=run_id, snapshot_json='{"run_id": 1}')

        save_article(self.db, article.id)
        unsave_article(self.db, article.id)

        self.assertFalse(is_article_saved(self.db, article.id))
        self.assertIsNotNone(self.db.get_article(article.id))
        self.assertEqual(
            self.db.get_analysis(
                article_id=article.id,
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
            ),
            sample_analysis(),
        )
        self.assertIsNotNone(
            self.db.get_article_feedback(
                article_id=article.id,
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
            )
        )
        self.assertEqual(len(self.db.get_app_runs()), 1)
        self.assertIsNotNone(self.db.get_run_snapshot(run_id=run_id))

        resaved = save_article(self.db, article.id)
        self.assertEqual(resaved.article.id, article.id)
        self.assertTrue(is_article_saved(self.db, article.id))

    def test_save_by_source_identity_supports_history_and_preselected_cards(self) -> None:
        article, _ = self.db.upsert_article(sample_article("2608.histlib", "History paper"))

        entry = save_article_by_source_identity(
            self.db,
            source="arxiv",
            source_article_id="2608.histlib",
        )

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.article.id, article.id)
        self.assertTrue(
            is_source_article_saved(
                self.db,
                source="arxiv",
                source_article_id="2608.histlib",
            )
        )
        self.assertTrue(
            unsave_article_by_source_identity(
                self.db,
                source="arxiv",
                source_article_id="2608.histlib",
            )
        )
        self.assertFalse(is_article_saved(self.db, article.id))

    def test_library_listing_filtering_sorting_and_relevance_context(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        assert profile.id is not None
        high, _ = self.db.upsert_article(
            sample_article("2608.libhigh", "Warped library", hour=12)
        )
        low, _ = self.db.upsert_article(
            sample_article("2608.liblow", "Kaluza library", hour=10)
        )
        assert high.id is not None
        assert low.id is not None
        self.db.upsert_analysis(
            article_id=high.id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            analysis=sample_analysis(0.9),
        )
        save_article(self.db, low.id)
        save_article(self.db, high.id)

        items = list_library_items(self.db, sort_by="title")

        self.assertEqual(
            [item.article.title for item in items],
            ["Kaluza library", "Warped library"],
        )
        filtered = filter_library_items(items, query="Warped library")
        self.assertEqual([item.article.source_article_id for item in filtered], ["2608.libhigh"])
        self.assertIsNotNone(filtered[0].relevance_context)
        assert filtered[0].relevance_context is not None
        self.assertEqual(filtered[0].relevance_context.profile_name, "Gravity")
        self.assertEqual(
            [
                item.article.source_article_id
                for item in sort_library_items(items, sort_by="published_newest")
            ],
            ["2608.libhigh", "2608.liblow"],
        )

    def test_library_button_helpers_are_stable_and_state_specific(self) -> None:
        identity = ArticleIdentity(source="arxiv", source_article_id="2608.lib01")

        self.assertEqual(library_button_label(False), "Save to Library")
        self.assertEqual(library_button_label(True), "Remove from Library")
        self.assertEqual(
            library_button_key(identity, context="today:1"),
            library_button_key(identity, context="today:1"),
        )
        self.assertNotEqual(
            library_button_key(identity, context="today:1"),
            library_button_key(identity, context="history:1"),
        )

    def test_schema_8_upgrade_adds_empty_library_table(self) -> None:
        path = Path(self.tmpdir.name) / "schema8.sqlite3"
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
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
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '8', '2026-08-14T00:00:00Z');
                INSERT INTO source_configs (
                    source_name, enabled, categories_json, lookback_hours, max_results, updated_at
                )
                VALUES ('arxiv', 1, '["gr-qc", "hep-th"]', 48, 50, '2026-08-14T00:00:00Z');
                INSERT INTO articles (
                    id, source, source_article_id, title, authors_json, abstract,
                    categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
                )
                VALUES (
                    1, 'arxiv', '2608.upgrade', 'Upgrade paper', '["Ada Lovelace"]',
                    'Upgrade abstract.', '["hep-th"]', '2026-08-14T10:00:00Z',
                    '2026-08-14T11:00:00Z', 'http://arxiv.org/abs/2608.upgrade',
                    NULL, '2026-08-14T12:00:00Z'
                );
                """
            )

        migrated = Database(path)
        self.addCleanup(migrated.close)

        self.assertEqual(migrated.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertEqual(migrated.list_saved_library_entries(), [])
        save_article(migrated, 1)
        self.assertTrue(is_article_saved(migrated, 1))


if __name__ == "__main__":
    unittest.main()
