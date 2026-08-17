from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from research_digest.collections import (
    CollectionValidationError,
    add_article_to_collection,
    create_collection,
    delete_collection,
    filter_library_items_by_collection,
    filter_library_items_by_tag,
    get_note,
    list_article_collections,
    normalize_collection_name,
    remove_article_from_collection,
    rename_collection,
    save_note,
)
from research_digest.db import APP_RUN_COMPLETED, CURRENT_SCHEMA_VERSION, Database
from research_digest.library import list_library_items, save_article, unsave_article
from research_digest.models import AnalysisResult, Article, profile_semantic_fingerprint
from research_digest.tags import add_user_tag, assign_ai_tags


def sample_article(source_article_id: str, title: str) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract about compactification.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        relevance_score=0.8,
        relevance_reason="Match.",
        matched_topics=["compactification"],
        summary="Summary.",
        why_it_matters="Relevant.",
        reading_priority="HIGH",
    )


class CollectionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "collections.sqlite3")
        self.first, _ = self.db.upsert_article(sample_article("2608.col01", "First paper"))
        self.second, _ = self.db.upsert_article(sample_article("2608.col02", "Second paper"))
        assert self.first.id is not None
        assert self.second.id is not None
        save_article(self.db, self.first.id)
        save_article(self.db, self.second.id)

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_note_save_update_empty_clear_and_resave_survival(self) -> None:
        assert self.first.id is not None
        saved = save_note(self.db, article_id=self.first.id, note_text=" Read soon. ")
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.note_text, "Read soon.")

        updated = save_note(self.db, article_id=self.first.id, note_text="Updated note")
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.created_at, saved.created_at)
        self.assertEqual(updated.note_text, "Updated note")

        unsave_article(self.db, self.first.id)
        save_article(self.db, self.first.id)
        preserved = get_note(self.db, article_id=self.first.id)
        self.assertIsNotNone(preserved)
        assert preserved is not None
        self.assertEqual(preserved.note_text, "Updated note")

        cleared = save_note(self.db, article_id=self.first.id, note_text="   ")
        self.assertIsNone(cleared)
        self.assertIsNone(get_note(self.db, article_id=self.first.id))

    def test_collection_crud_duplicate_normalization_and_membership(self) -> None:
        assert self.first.id is not None
        assert self.second.id is not None
        normalized = normalize_collection_name("  GL   project ")
        self.assertEqual(normalized.normalized_name, "gl project")
        self.assertEqual(normalized.display_name, "GL project")
        with self.assertRaises(CollectionValidationError):
            normalize_collection_name(" ")

        collection = create_collection(self.db, name="GL project", description="Gregory-Laflamme")
        duplicate = create_collection(self.db, name=" gl project ", description="Updated")
        self.assertEqual(collection.id, duplicate.id)
        self.assertEqual(duplicate.description, "Updated")
        assert collection.id is not None

        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.first.id,
        )
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.first.id,
        )
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.second.id,
        )
        self.assertEqual(len(self.db.list_library_collection_memberships(collection.id)), 2)
        self.assertEqual(
            [item.name for item in list_article_collections(self.db, article_id=self.first.id)],
            ["GL project"],
        )

        renamed = rename_collection(
            self.db,
            collection_id=collection.id,
            name="Warped KK",
            description="Renamed",
        )
        self.assertEqual(renamed.id, collection.id)
        self.assertEqual(renamed.name, "Warped KK")
        self.assertEqual(len(self.db.list_library_collection_memberships(collection.id)), 2)

        remove_article_from_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.second.id,
        )
        remove_article_from_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.second.id,
        )
        self.assertEqual(len(self.db.list_library_collection_memberships(collection.id)), 1)

    def test_multi_collection_filtering_and_tag_filtering(self) -> None:
        assert self.first.id is not None
        assert self.second.id is not None
        gl = create_collection(self.db, name="GL project")
        kk = create_collection(self.db, name="KK project")
        assert gl.id is not None
        assert kk.id is not None
        add_article_to_collection(self.db, collection_id=gl.id, article_id=self.first.id)
        add_article_to_collection(self.db, collection_id=kk.id, article_id=self.first.id)
        add_article_to_collection(self.db, collection_id=kk.id, article_id=self.second.id)
        add_user_tag(self.db, article_id=self.first.id, tag="Black branes")
        assign_ai_tags(
            self.db,
            article_id=self.second.id,
            tags=["KK spectra"],
            provenance={"prompt_version": "library_ai_tags_v1", "provider": "fake"},
        )
        items = list_library_items(self.db, sort_by="title")

        self.assertEqual(
            [item.article.source_article_id for item in filter_library_items_by_collection(
                self.db,
                items,
                collection_id=gl.id,
            )],
            ["2608.col01"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                sort_by="title",
                collection_id=kk.id,
            )],
            ["2608.col01", "2608.col02"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in filter_library_items_by_tag(
                self.db,
                items,
                normalized_tag_name="black branes",
            )],
            ["2608.col01"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                sort_by="title",
                normalized_tag_name="kk spectra",
            )],
            ["2608.col02"],
        )

    def test_collection_deletion_preserves_article_scientific_state(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        assert self.first.id is not None
        assert profile.id is not None
        fingerprint = profile_semantic_fingerprint(profile)
        self.db.upsert_analysis(
            article_id=self.first.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            analysis=sample_analysis(),
        )
        self.db.upsert_article_feedback(
            article_id=self.first.id,
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
            feedback_label="RELEVANT",
        )
        run_id = self.db.create_app_run(profile_id=profile.id, source_name="arxiv")
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
        save_note(self.db, article_id=self.first.id, note_text="Important")
        add_user_tag(self.db, article_id=self.first.id, tag="Black branes")
        collection = create_collection(self.db, name="Delete me")
        assert collection.id is not None
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.first.id,
        )

        delete_collection(self.db, collection_id=collection.id)

        self.assertIsNotNone(self.db.get_article(self.first.id))
        self.assertTrue(self.db.get_library_entry(self.first.id))
        note = get_note(self.db, article_id=self.first.id)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.note_text, "Important")
        self.assertEqual(
            self.db.list_library_tag_assignments(self.first.id)[0].tag.display_name,
            "Black branes",
        )
        self.assertIsNotNone(
            self.db.get_analysis(
                article_id=self.first.id,
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
            )
        )
        self.assertIsNotNone(self.db.get_run_snapshot(run_id=run_id))
        self.assertEqual(self.db.list_library_collection_memberships(), [])

    def test_schema_10_upgrade_adds_notes_and_collections(self) -> None:
        path = Path(self.tmpdir.name) / "schema10.sqlite3"
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
                CREATE TABLE library_articles (
                    article_id INTEGER PRIMARY KEY,
                    saved INTEGER NOT NULL DEFAULT 1,
                    saved_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(article_id) REFERENCES articles(id) ON DELETE CASCADE
                );
                CREATE TABLE library_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE library_tag_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    origin TEXT NOT NULL,
                    ai_provenance_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(article_id, tag_id, origin)
                );
                CREATE TABLE library_ai_tag_suppressions (
                    article_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    suppressed_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    UNIQUE(article_id, tag_id)
                );
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '10', '2026-08-14T00:00:00Z');
                INSERT INTO source_configs (
                    source_name, enabled, categories_json, lookback_hours, max_results, updated_at
                )
                VALUES ('arxiv', 1, '["gr-qc", "hep-th"]', 48, 50, '2026-08-14T00:00:00Z');
                INSERT INTO articles (
                    id, source, source_article_id, title, authors_json, abstract,
                    categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
                )
                VALUES (
                    1, 'arxiv', '2608.upgrade-c', 'Upgrade C paper',
                    '["Ada Lovelace"]', 'Upgrade abstract.', '["hep-th"]',
                    '2026-08-14T10:00:00Z', '2026-08-14T11:00:00Z',
                    'http://arxiv.org/abs/2608.upgrade-c', NULL,
                    '2026-08-14T12:00:00Z'
                );
                INSERT INTO library_articles (article_id, saved, saved_at, updated_at)
                VALUES (1, 1, '2026-08-14T12:00:00Z', '2026-08-14T12:00:00Z');
                """
            )

        migrated = Database(path)
        self.addCleanup(migrated.close)

        self.assertEqual(migrated.get_schema_version(), CURRENT_SCHEMA_VERSION)
        save_note(migrated, article_id=1, note_text="Upgrade note")
        collection = create_collection(migrated, name="Upgrade collection")
        assert collection.id is not None
        add_article_to_collection(migrated, collection_id=collection.id, article_id=1)
        note = get_note(migrated, article_id=1)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.note_text, "Upgrade note")
        self.assertEqual(len(migrated.list_library_collection_memberships()), 1)


if __name__ == "__main__":
    unittest.main()
