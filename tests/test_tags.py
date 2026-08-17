from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from research_digest.db import CURRENT_SCHEMA_VERSION, Database
from research_digest.models import AnalysisResult, Article, TagOrigin, profile_semantic_fingerprint
from research_digest.tags import (
    AI_TAG_PROMPT_VERSION,
    AITagGeneration,
    AITagSuggestion,
    TagValidationError,
    add_user_tag,
    assign_ai_tags,
    generate_ai_tags_for_saved_article,
    list_article_tags,
    normalize_tag_name,
    remove_ai_tag,
    remove_user_tag,
)


def sample_article(source_article_id: str = "2608.tag01") -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title="Warped compactifications and brane spectra",
        authors=["Ada Lovelace"],
        abstract="A study of Kaluza-Klein spectra in higher-dimensional gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        relevance_score=0.9,
        relevance_reason="Strong match.",
        matched_topics=["Kaluza-Klein spectra"],
        summary="Summary.",
        why_it_matters="Relevant to compactification physics.",
        reading_priority="HIGH",
    )


class FakeTagGenerator:
    def __init__(self, tags: list[str]) -> None:
        self.tags = tags
        self.calls = 0

    def suggest_tags(self, **kwargs: object) -> AITagGeneration:
        self.calls += 1
        return AITagGeneration(
            suggestions=tuple(AITagSuggestion(tag=value) for value in self.tags),
            provenance={"prompt_version": AI_TAG_PROMPT_VERSION, "provider": "fake"},
        )


class FailingTagGenerator:
    def suggest_tags(self, **kwargs: object) -> AITagGeneration:
        raise RuntimeError("provider failed")


class TagServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "tags.sqlite3")
        self.article, _ = self.db.upsert_article(sample_article())
        assert self.article.id is not None
        self.db.save_library_article(self.article.id)

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_normalization_case_whitespace_and_leading_hash(self) -> None:
        normalized = normalize_tag_name("  #AdS/CFT   duality  ")

        self.assertEqual(normalized.normalized_name, "ads/cft duality")
        self.assertEqual(normalized.display_name, "AdS/CFT duality")
        with self.assertRaises(TagValidationError):
            normalize_tag_name(" #  ")
        with self.assertRaises(TagValidationError):
            normalize_tag_name("x" * 81)

    def test_user_tag_crud_and_duplicate_normalization(self) -> None:
        assert self.article.id is not None
        first = add_user_tag(self.db, article_id=self.article.id, tag="AdS/CFT")
        second = add_user_tag(self.db, article_id=self.article.id, tag=" ads/cft ")

        tags = list_article_tags(self.db, article_id=self.article.id)

        self.assertEqual(first.id, second.id)
        self.assertEqual([tag.tag.display_name for tag in tags.user_tags], ["AdS/CFT"])
        self.assertEqual(tags.user_tags[0].origin, TagOrigin.USER)
        self.assertEqual(tags.ai_tags, ())

        remove_user_tag(self.db, article_id=self.article.id, tag="ADS/CFT")
        self.assertEqual(list_article_tags(self.db, article_id=self.article.id).user_tags, ())

    def test_ai_assignment_provenance_and_user_isolation(self) -> None:
        assert self.article.id is not None
        add_user_tag(self.db, article_id=self.article.id, tag="black branes")
        ai_assignments = assign_ai_tags(
            self.db,
            article_id=self.article.id,
            tags=["Black Branes", "KK spectra", "KK spectra"],
            provenance={"prompt_version": AI_TAG_PROMPT_VERSION, "provider": "fake"},
        )

        tags = list_article_tags(self.db, article_id=self.article.id)

        self.assertEqual(len(ai_assignments), 2)
        self.assertEqual([tag.tag.normalized_name for tag in tags.user_tags], ["black branes"])
        self.assertEqual(
            [tag.tag.normalized_name for tag in tags.ai_tags],
            ["black branes", "kk spectra"],
        )
        self.assertIsNotNone(tags.ai_tags[0].ai_provenance)

        remove_ai_tag(self.db, article_id=self.article.id, tag="BLACK BRANES")
        after = list_article_tags(self.db, article_id=self.article.id)
        self.assertEqual([tag.tag.normalized_name for tag in after.user_tags], ["black branes"])
        self.assertEqual([tag.tag.normalized_name for tag in after.ai_tags], ["kk spectra"])
        suppressions = self.db.list_ai_library_tag_suppressions(self.article.id)
        self.assertEqual([item.tag.normalized_name for item in suppressions], ["black branes"])

    def test_suppression_survives_generation_and_user_tag_survives_regeneration(self) -> None:
        assert self.article.id is not None
        add_user_tag(self.db, article_id=self.article.id, tag="Black Branes")
        assign_ai_tags(
            self.db,
            article_id=self.article.id,
            tags=["Black Branes"],
            provenance={"prompt_version": AI_TAG_PROMPT_VERSION, "provider": "fake"},
        )
        remove_ai_tag(self.db, article_id=self.article.id, tag="Black Branes")
        generator = FakeTagGenerator(["Black Branes", "KK spectra"])

        assignments = generate_ai_tags_for_saved_article(
            self.db,
            article_id=self.article.id,
            generator=generator,
            regenerate=True,
        )
        tags = list_article_tags(self.db, article_id=self.article.id)

        self.assertEqual(generator.calls, 1)
        self.assertEqual([tag.tag.normalized_name for tag in assignments], ["kk spectra"])
        self.assertEqual([tag.tag.normalized_name for tag in tags.user_tags], ["black branes"])
        self.assertEqual([tag.tag.normalized_name for tag in tags.ai_tags], ["kk spectra"])

    def test_failed_regeneration_preserves_existing_ai_tags_and_suppressions(self) -> None:
        assert self.article.id is not None
        assign_ai_tags(
            self.db,
            article_id=self.article.id,
            tags=["KK spectra"],
            provenance={"prompt_version": AI_TAG_PROMPT_VERSION, "provider": "fake"},
        )
        remove_ai_tag(self.db, article_id=self.article.id, tag="Black Branes")

        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            generate_ai_tags_for_saved_article(
                self.db,
                article_id=self.article.id,
                generator=FailingTagGenerator(),
                regenerate=True,
                clear_suppressions=True,
            )

        tags = list_article_tags(self.db, article_id=self.article.id)
        suppressions = self.db.list_ai_library_tag_suppressions(self.article.id)
        self.assertEqual([tag.tag.normalized_name for tag in tags.ai_tags], ["kk spectra"])
        self.assertEqual([item.tag.normalized_name for item in suppressions], ["black branes"])

    def test_listing_tags_does_not_call_generator_or_mutate(self) -> None:
        assert self.article.id is not None
        generator = FakeTagGenerator(["KK spectra"])
        before = list_article_tags(self.db, article_id=self.article.id)

        after = list_article_tags(self.db, article_id=self.article.id)

        self.assertEqual(before, after)
        self.assertEqual(generator.calls, 0)

    def test_ai_generation_requires_saved_article_and_includes_relevance_context(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        assert profile.id is not None
        assert self.article.id is not None
        self.db.upsert_analysis(
            article_id=self.article.id,
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            analysis=sample_analysis(),
        )
        unsaved, _ = self.db.upsert_article(sample_article("2608.unsaved"))
        assert unsaved.id is not None
        generator = FakeTagGenerator(["KK spectra"])

        assignments = generate_ai_tags_for_saved_article(
            self.db,
            article_id=self.article.id,
            generator=generator,
        )

        self.assertIsNotNone(assignments[0].ai_provenance)
        assert assignments[0].ai_provenance is not None
        self.assertEqual(assignments[0].ai_provenance["relevance_context_included"], True)
        with self.assertRaisesRegex(ValueError, "saved Library articles"):
            generate_ai_tags_for_saved_article(self.db, article_id=unsaved.id, generator=generator)

    def test_schema_9_upgrade_adds_empty_tag_tables(self) -> None:
        path = Path(self.tmpdir.name) / "schema9.sqlite3"
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
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '9', '2026-08-14T00:00:00Z');
                INSERT INTO source_configs (
                    source_name, enabled, categories_json, lookback_hours, max_results, updated_at
                )
                VALUES ('arxiv', 1, '["gr-qc", "hep-th"]', 48, 50, '2026-08-14T00:00:00Z');
                INSERT INTO articles (
                    id, source, source_article_id, title, authors_json, abstract,
                    categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
                )
                VALUES (
                    1, 'arxiv', '2608.upgrade-tag', 'Upgrade tag paper',
                    '["Ada Lovelace"]', 'Upgrade abstract.', '["hep-th"]',
                    '2026-08-14T10:00:00Z', '2026-08-14T11:00:00Z',
                    'http://arxiv.org/abs/2608.upgrade-tag', NULL,
                    '2026-08-14T12:00:00Z'
                );
                INSERT INTO library_articles (article_id, saved, saved_at, updated_at)
                VALUES (1, 1, '2026-08-14T12:00:00Z', '2026-08-14T12:00:00Z');
                """
            )

        migrated = Database(path)
        self.addCleanup(migrated.close)

        self.assertEqual(migrated.get_schema_version(), CURRENT_SCHEMA_VERSION)
        add_user_tag(migrated, article_id=1, tag="Upgrade tag")
        self.assertEqual(
            list_article_tags(migrated, article_id=1).user_tags[0].tag.display_name,
            "Upgrade tag",
        )


if __name__ == "__main__":
    unittest.main()
