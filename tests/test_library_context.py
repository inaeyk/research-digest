from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from research_digest.analysis.base import AnalyzerError
from research_digest.analysis.codex_context import _parse_context_output, build_context_prompt
from research_digest.collections import add_article_to_collection, create_collection, save_note
from research_digest.db import CURRENT_SCHEMA_VERSION, Database
from research_digest.library import save_article, unsave_article
from research_digest.library_context import (
    LibraryContextCandidate,
    LibraryContextGeneration,
    LibraryContextSuggestionDraft,
    assign_library_context_suggestions,
    build_collection_intelligence_snapshot,
    dismiss_context_suggestion,
    generate_library_context_for_item,
    list_display_context_suggestions,
    select_library_context_candidates,
)
from research_digest.models import AnalysisResult, Article, LibraryContextOrigin
from research_digest.tags import add_user_tag


def sample_article(
    source_article_id: str,
    title: str,
    *,
    abstract: str = "Abstract about black branes and compactification.",
    categories: list[str] | None = None,
    hour: int = 10,
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=abstract,
        categories=categories or ["hep-th"],
        published_at=datetime(2026, 8, 14, hour, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, hour, 30, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        relevance_score=0.8,
        relevance_reason="Relevant to black branes.",
        matched_topics=["Black branes", "compactification"],
        summary="Summary.",
        why_it_matters="Why.",
        reading_priority="HIGH",
    )


class FakeContextGenerator:
    def __init__(self, suggestions: tuple[LibraryContextSuggestionDraft, ...]) -> None:
        self.suggestions = suggestions
        self.calls = 0

    def suggest_context(
        self,
        *,
        article: Article,
        analysis: AnalysisResult,
        candidates: Sequence[LibraryContextCandidate],
        max_suggestions: int = 5,
    ) -> LibraryContextGeneration:
        self.calls += 1
        return LibraryContextGeneration(
            suggestions=self.suggestions[:max_suggestions],
            provenance={"prompt_version": "library_context_v1", "provider": "fake"},
        )


class LibraryContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "context.sqlite3")
        self.new_article, _ = self.db.upsert_article(
            sample_article("2608.ctx01", "New black brane paper", categories=["hep-th"])
        )
        self.saved_related, _ = self.db.upsert_article(
            sample_article(
                "2608.ctx02",
                "Saved black brane paper",
                categories=["hep-th", "gr-qc"],
                hour=9,
            )
        )
        self.saved_unrelated, _ = self.db.upsert_article(
            sample_article(
                "2608.ctx03",
                "Saved galaxy paper",
                abstract="Galaxy survey.",
                categories=["astro-ph.CO"],
                hour=8,
            )
        )
        assert self.new_article.id is not None
        assert self.saved_related.id is not None
        assert self.saved_unrelated.id is not None
        save_article(self.db, self.saved_related.id)
        save_article(self.db, self.saved_unrelated.id)

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_candidate_selection_is_bounded_deterministic_and_excludes_notes(self) -> None:
        assert self.saved_related.id is not None
        add_user_tag(self.db, article_id=self.saved_related.id, tag="Black branes")
        collection = create_collection(self.db, name="GL project")
        assert collection.id is not None
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.saved_related.id,
        )
        save_note(
            self.db,
            article_id=self.saved_related.id,
            note_text="private-context-token",
        )

        candidates = select_library_context_candidates(
            self.db,
            article=self.new_article,
            analysis=sample_analysis(),
            max_candidates=1,
        )

        self.assertEqual(
            [candidate.article.id for candidate in candidates],
            [self.saved_related.id],
        )
        self.assertIn("Black branes", candidates[0].evidence["shared_tags"])
        self.assertNotIn("private-context-token", candidates[0].evidence["shared_terms"])

    def test_generate_persist_dismiss_and_respect_dismissal(self) -> None:
        assert self.new_article.id is not None
        assert self.saved_related.id is not None
        add_user_tag(self.db, article_id=self.saved_related.id, tag="Black branes")
        draft = LibraryContextSuggestionDraft(
            related_candidate_id="arxiv:2608.ctx02",
            collection_id=None,
            relation_label="shared system",
            rationale="Both discuss black branes.",
            confidence=0.7,
        )
        generator = FakeContextGenerator((draft,))

        persisted = generate_library_context_for_item(
            self.db,
            run_id=None,
            article=self.new_article,
            analysis=sample_analysis(),
            generator=generator,
        )
        self.assertEqual(len(persisted), 1)
        self.assertEqual(
            len(list_display_context_suggestions(self.db, article_id=self.new_article.id)),
            1,
        )

        suggestion_id = persisted[0].id
        assert suggestion_id is not None
        dismiss_context_suggestion(self.db, suggestion_id=suggestion_id)

        self.assertEqual(
            list_display_context_suggestions(self.db, article_id=self.new_article.id),
            [],
        )
        repeated = generate_library_context_for_item(
            self.db,
            run_id=None,
            article=self.new_article,
            analysis=sample_analysis(),
            generator=generator,
        )
        self.assertEqual(repeated, [])

        regenerated = generate_library_context_for_item(
            self.db,
            run_id=None,
            article=self.new_article,
            analysis=sample_analysis(),
            generator=generator,
            regenerate=True,
        )
        self.assertEqual(len(regenerated), 1)
        self.assertIsNone(regenerated[0].dismissed_at)

    def test_assign_rejects_unknown_duplicate_self_and_wrong_collection(self) -> None:
        assert self.new_article.id is not None
        assert self.saved_related.id is not None
        candidate = LibraryContextCandidate(
            article=self.saved_related,
            score=1.0,
            evidence={},
            collections=(),
        )
        with self.assertRaisesRegex(ValueError, "unknown"):
            assign_library_context_suggestions(
                self.db,
                run_id=None,
                article_id=self.new_article.id,
                candidates=[candidate],
                suggestions=[
                    LibraryContextSuggestionDraft(
                        related_candidate_id="arxiv:missing",
                        collection_id=None,
                        relation_label="shared",
                        rationale="Grounded.",
                    )
                ],
                provenance={"provider": "fake"},
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            assign_library_context_suggestions(
                self.db,
                run_id=None,
                article_id=self.new_article.id,
                candidates=[candidate],
                suggestions=[
                    LibraryContextSuggestionDraft(
                        related_candidate_id="arxiv:2608.ctx02",
                        collection_id=None,
                        relation_label="shared",
                        rationale="Grounded.",
                    ),
                    LibraryContextSuggestionDraft(
                        related_candidate_id="arxiv:2608.ctx02",
                        collection_id=None,
                        relation_label="shared",
                        rationale="Grounded.",
                    ),
                ],
                provenance={"provider": "fake"},
            )
        with self.assertRaisesRegex(ValueError, "unknown collection"):
            assign_library_context_suggestions(
                self.db,
                run_id=None,
                article_id=self.new_article.id,
                candidates=[candidate],
                suggestions=[
                    LibraryContextSuggestionDraft(
                        related_candidate_id="arxiv:2608.ctx02",
                        collection_id=999,
                        relation_label="shared",
                        rationale="Grounded.",
                    )
                ],
                provenance={"provider": "fake"},
            )

    def test_invalid_suggestion_batch_does_not_partially_persist(self) -> None:
        assert self.new_article.id is not None
        assert self.saved_related.id is not None
        candidate = LibraryContextCandidate(
            article=self.saved_related,
            score=1.0,
            evidence={},
            collections=(),
        )

        with self.assertRaisesRegex(ValueError, "unknown"):
            assign_library_context_suggestions(
                self.db,
                run_id=None,
                article_id=self.new_article.id,
                candidates=[candidate],
                suggestions=[
                    LibraryContextSuggestionDraft(
                        related_candidate_id="arxiv:2608.ctx02",
                        collection_id=None,
                        relation_label="shared",
                        rationale="Grounded.",
                    ),
                    LibraryContextSuggestionDraft(
                        related_candidate_id="arxiv:missing",
                        collection_id=None,
                        relation_label="shared",
                        rationale="Grounded.",
                    ),
                ],
                provenance={"provider": "fake"},
            )

        self.assertEqual(
            self.db.list_library_context_suggestions_for_article(
                self.new_article.id,
                include_dismissed=True,
            ),
            [],
        )

    def test_prompt_is_bounded_untrusted_and_has_no_notes_or_secrets(self) -> None:
        candidate = LibraryContextCandidate(
            article=self.saved_related,
            score=2.0,
            evidence={"shared_terms": ("brane",)},
        )
        prompt = build_context_prompt(
            article=self.new_article,
            analysis=sample_analysis(),
            candidates=[candidate],
            max_suggestions=1,
        )

        self.assertIn("BEGIN_UNTRUSTED_LIBRARY_CONTEXT_INPUT_JSON", prompt)
        self.assertIn("No personal note text is supplied", prompt)
        self.assertNotIn("OPENAI_API_KEY", prompt)
        self.assertNotIn("sk-", prompt)

    def test_parse_context_output_validates_shape_and_confidence(self) -> None:
        parsed = _parse_context_output(
            json.dumps(
                {
                    "suggestions": [
                        {
                            "related_candidate_id": "arxiv:2608.ctx02",
                            "collection_id": None,
                            "relation_label": "shared system",
                            "rationale": "Both discuss black branes.",
                            "confidence": 0.6,
                        }
                    ]
                }
            ),
            max_suggestions=1,
        )
        self.assertEqual(parsed[0].related_candidate_id, "arxiv:2608.ctx02")
        with self.assertRaises(AnalyzerError):
            _parse_context_output(
                json.dumps(
                    {
                        "suggestions": [
                            {
                                "related_candidate_id": "arxiv:2608.ctx02",
                                "collection_id": "bad",
                                "relation_label": "shared",
                                "rationale": "x",
                                "confidence": None,
                            }
                        ]
                    }
                ),
                max_suggestions=1,
            )
        with self.assertRaises(AnalyzerError):
            _parse_context_output(
                json.dumps(
                    {
                        "suggestions": [
                            {
                                "related_candidate_id": "arxiv:2608.ctx02",
                                "collection_id": None,
                                "relation_label": "shared",
                                "rationale": "x",
                                "confidence": 1.1,
                            }
                        ]
                    }
                ),
                max_suggestions=1,
            )

    def test_collection_intelligence_snapshot_uses_stored_evidence(self) -> None:
        assert self.saved_related.id is not None
        add_user_tag(self.db, article_id=self.saved_related.id, tag="Black branes")
        collection = create_collection(self.db, name="GL project")
        assert collection.id is not None
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.saved_related.id,
        )

        snapshot = build_collection_intelligence_snapshot(self.db, collection_id=collection.id)

        self.assertEqual(snapshot.origin, LibraryContextOrigin.DETERMINISTIC)
        self.assertEqual(snapshot.collection_id, collection.id)
        self.assertIn("GL project contains 1 saved paper", snapshot.summary)
        self.assertEqual(snapshot.evidence["article_count"], 1)

    def test_collection_intelligence_ignores_unsaved_members(self) -> None:
        assert self.saved_related.id is not None
        collection = create_collection(self.db, name="GL project")
        assert collection.id is not None
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.saved_related.id,
        )

        unsave_article(self.db, self.saved_related.id)
        snapshot = build_collection_intelligence_snapshot(self.db, collection_id=collection.id)

        self.assertIn("has no saved papers", snapshot.summary)
        self.assertEqual(snapshot.evidence["article_count"], 0)
        self.assertEqual(snapshot.evidence["recent_titles"], [])

    def test_schema_12_upgrade_adds_context_tables(self) -> None:
        path = Path(self.tmpdir.name) / "schema12.sqlite3"
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
                CREATE TABLE app_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER,
                    source_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    retrieved_count INTEGER NOT NULL DEFAULT 0,
                    stored_count INTEGER NOT NULL DEFAULT 0,
                    relevant_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    preselected_count INTEGER NOT NULL DEFAULT 0,
                    skipped_analysis_count INTEGER NOT NULL DEFAULT 0,
                    analyzed_count INTEGER NOT NULL DEFAULT 0,
                    requested_source_dates_json TEXT NOT NULL DEFAULT '[]',
                    covered_source_dates_json TEXT NOT NULL DEFAULT '[]',
                    empty_source_dates_json TEXT NOT NULL DEFAULT '[]',
                    incomplete_source_dates_json TEXT NOT NULL DEFAULT '[]',
                    retrieval_complete INTEGER NOT NULL DEFAULT 1,
                    retrieval_safety_limit INTEGER,
                    run_origin TEXT NOT NULL DEFAULT 'LEGACY',
                    date_selection_json TEXT,
                    source_fingerprint TEXT,
                    profile_fingerprint TEXT
                );
                CREATE TABLE library_articles (
                    article_id INTEGER PRIMARY KEY,
                    saved INTEGER NOT NULL DEFAULT 1,
                    saved_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE library_collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE library_search_documents (
                    article_id INTEGER PRIMARY KEY,
                    document_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE library_article_connections (
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
                    UNIQUE(article_id_a, article_id_b)
                );
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '12', '2026-08-14T00:00:00Z');
                INSERT INTO source_configs (
                    source_name, enabled, categories_json, lookback_hours, max_results, updated_at
                )
                VALUES ('arxiv', 1, '["hep-th"]', 48, 50, '2026-08-14T00:00:00Z');
                INSERT INTO articles (
                    id, source, source_article_id, title, authors_json, abstract,
                    categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
                )
                VALUES (
                    1, 'arxiv', '2608.old', 'Old paper', '["Ada"]', 'abstract',
                    '["hep-th"]', '2026-08-14T00:00:00Z', '2026-08-14T00:00:00Z',
                    'http://arxiv.org/abs/2608.old', NULL, '2026-08-14T00:00:00Z'
                );
                INSERT INTO library_articles (article_id, saved, saved_at, updated_at)
                VALUES (1, 1, '2026-08-14T00:00:00Z', '2026-08-14T00:00:00Z');
                INSERT INTO library_collections (
                    id, name, normalized_name, description, created_at, updated_at
                )
                VALUES (1, 'GL project', 'gl project', '', '2026-08-14T00:00:00Z',
                    '2026-08-14T00:00:00Z');
                """
            )

        upgraded = Database(path)

        self.assertEqual(upgraded.get_schema_version(), CURRENT_SCHEMA_VERSION)
        snapshot = upgraded.save_collection_intelligence_snapshot(
            collection_id=1,
            title="Snapshot",
            summary="Summary.",
            evidence={"article_count": 1},
            provenance={"provider": "test"},
        )
        self.assertEqual(snapshot.collection_id, 1)
        upgraded.close()

    def test_backup_export_includes_context_and_collection_intelligence(self) -> None:
        assert self.new_article.id is not None
        assert self.saved_related.id is not None
        collection = create_collection(self.db, name="GL project")
        assert collection.id is not None
        self.db.upsert_library_context_suggestion(
            run_id=None,
            article_id=self.new_article.id,
            related_article_id=self.saved_related.id,
            collection_id=collection.id,
            relation_label="shared system",
            rationale="Both discuss black branes.",
            provenance={"provider": "fake"},
        )
        build_collection_intelligence_snapshot(self.db, collection_id=collection.id)

        from research_digest.backup import export_user_data

        payload = export_user_data(db_path=self.db.path)

        suggestions = cast(list[dict[str, object]], payload["library_context_suggestions"])
        snapshots = cast(list[dict[str, object]], payload["collection_intelligence_snapshots"])
        self.assertEqual(suggestions[0]["relation_label"], "shared system")
        self.assertEqual(snapshots[0]["collection_id"], collection.id)
