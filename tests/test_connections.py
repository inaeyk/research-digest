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
from research_digest.analysis.codex_connections import (
    _parse_connection_output,
    build_connection_prompt,
)
from research_digest.collections import add_article_to_collection, create_collection, save_note
from research_digest.connections import (
    ConnectionCandidate,
    LibraryConnectionGeneration,
    LibraryConnectionSuggestion,
    article_candidate_id,
    assign_connection_suggestions,
    dismiss_connection,
    generate_connections_for_saved_article,
    list_related_connections,
    select_connection_candidates,
)
from research_digest.db import CURRENT_SCHEMA_VERSION, Database
from research_digest.library import list_library_items, save_article, unsave_article
from research_digest.library_search import (
    rebuild_library_search_index,
    search_saved_library_article_ids,
)
from research_digest.models import AnalysisResult, Article, profile_semantic_fingerprint
from research_digest.tags import add_user_tag, assign_ai_tags


def sample_article(
    source_article_id: str,
    title: str,
    *,
    abstract: str = "Abstract about black branes and Kaluza Klein spectra.",
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


class FakeConnectionGenerator:
    def __init__(self, suggestions: tuple[LibraryConnectionSuggestion, ...]) -> None:
        self.suggestions = suggestions
        self.calls = 0

    def suggest_connections(
        self,
        *,
        target: Article,
        candidates: Sequence[ConnectionCandidate],
        relevance_context: object | None,
        max_suggestions: int = 5,
    ) -> LibraryConnectionGeneration:
        self.calls += 1
        return LibraryConnectionGeneration(
            suggestions=self.suggestions[:max_suggestions],
            provenance={"prompt_version": "library_connections_v1", "provider": "fake"},
        )


class ConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "connections.sqlite3")
        self.target, _ = self.db.upsert_article(
            sample_article(
                "2608.conn01",
                "Black brane instability",
                abstract="Gregory Laflamme instability for black branes.",
                categories=["hep-th", "gr-qc"],
                hour=12,
            )
        )
        self.related, _ = self.db.upsert_article(
            sample_article(
                "2608.conn02",
                "Kaluza Klein black string",
                abstract="Kaluza Klein compactification and black brane spectra.",
                categories=["gr-qc"],
                hour=11,
            )
        )
        self.unrelated, _ = self.db.upsert_article(
            sample_article(
                "2608.conn03",
                "Cosmic dust survey",
                abstract="Dust maps for observational cosmology.",
                categories=["astro-ph.CO"],
                hour=9,
            )
        )
        for article in (self.target, self.related, self.unrelated):
            assert article.id is not None
            save_article(self.db, article.id)

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_search_index_covers_article_tags_collections_abstract_and_notes(self) -> None:
        assert self.target.id is not None
        assert self.related.id is not None
        add_user_tag(self.db, article_id=self.target.id, tag="Black branes")
        assign_ai_tags(
            self.db,
            article_id=self.related.id,
            tags=["KK spectra"],
            provenance={"prompt_version": "library_ai_tags_v1", "provider": "fake"},
        )
        collection = create_collection(self.db, name="GL project", description="Instability work")
        assert collection.id is not None
        add_article_to_collection(self.db, collection_id=collection.id, article_id=self.target.id)
        save_note(self.db, article_id=self.related.id, note_text="Read for warped tower.")

        rebuild_library_search_index(self.db)

        self.assertEqual(
            search_saved_library_article_ids(self.db, query="GL project"),
            [self.target.id],
        )
        self.assertEqual(
            search_saved_library_article_ids(self.db, query="warped tower"),
            [self.related.id],
        )
        self.assertEqual(
            [item.article.source_article_id for item in list_library_items(
                self.db,
                query="KK spectra",
                sort_by="title",
            )],
            ["2608.conn02"],
        )

    def test_candidate_selection_is_bounded_deterministic_and_excludes_self(self) -> None:
        assert self.target.id is not None
        assert self.related.id is not None
        assert self.unrelated.id is not None
        add_user_tag(self.db, article_id=self.target.id, tag="Black branes")
        add_user_tag(self.db, article_id=self.related.id, tag="Black branes")
        collection = create_collection(self.db, name="GL project")
        assert collection.id is not None
        add_article_to_collection(self.db, collection_id=collection.id, article_id=self.target.id)
        add_article_to_collection(self.db, collection_id=collection.id, article_id=self.related.id)

        candidates = select_connection_candidates(
            self.db,
            article_id=self.target.id,
            max_candidates=1,
        )

        self.assertEqual([candidate.article.id for candidate in candidates], [self.related.id])
        self.assertIn("Black branes", candidates[0].evidence["shared_tags"])
        self.assertNotIn(self.target.id, [candidate.article.id for candidate in candidates])

    def test_connection_upsert_dedupes_unordered_pair_and_dismisses(self) -> None:
        assert self.target.id is not None
        assert self.related.id is not None
        connection = self.db.upsert_library_connection(
            article_id_a=self.target.id,
            article_id_b=self.related.id,
            relation_label="shared method",
            rationale="Both discuss black brane spectra.",
            provenance={"provider": "fake"},
            confidence=0.7,
        )
        again = self.db.upsert_library_connection(
            article_id_a=self.related.id,
            article_id_b=self.target.id,
            relation_label="same system",
            rationale="Both concern black branes.",
            provenance={"provider": "fake"},
        )

        self.assertEqual(connection.id, again.id)
        self.assertEqual(again.article_id_a, min(self.target.id, self.related.id))
        self.assertEqual(len(list_related_connections(self.db, article_id=self.target.id)), 1)

        dismiss_connection(self.db, article_id=self.target.id, related_article_id=self.related.id)

        self.assertEqual(list_related_connections(self.db, article_id=self.target.id), [])
        dismissed = self.db.get_library_connection_by_pair(self.target.id, self.related.id)
        self.assertIsNotNone(dismissed)
        assert dismissed is not None
        self.assertIsNotNone(dismissed.dismissed_at)

    def test_unsaved_related_article_is_not_displayed_but_connection_is_preserved(self) -> None:
        assert self.target.id is not None
        assert self.related.id is not None
        self.db.upsert_library_connection(
            article_id_a=self.target.id,
            article_id_b=self.related.id,
            relation_label="shared method",
            rationale="Both discuss black branes.",
            provenance={"provider": "fake"},
        )

        unsave_article(self.db, self.related.id)

        self.assertEqual(list_related_connections(self.db, article_id=self.target.id), [])
        self.assertIsNotNone(
            self.db.get_library_connection_by_pair(self.target.id, self.related.id)
        )

        save_article(self.db, self.related.id)

        self.assertEqual(len(list_related_connections(self.db, article_id=self.target.id)), 1)

    def test_personal_note_text_is_not_sent_as_connection_candidate_evidence(self) -> None:
        assert self.target.id is not None
        assert self.related.id is not None
        save_note(self.db, article_id=self.target.id, note_text="private-secret-method")
        save_note(self.db, article_id=self.related.id, note_text="private-secret-method")

        candidates = select_connection_candidates(
            self.db,
            article_id=self.target.id,
            max_candidates=5,
        )

        for candidate in candidates:
            self.assertNotIn("private-secret-method", candidate.evidence["shared_terms"])

    def test_generation_respects_dismissal_and_regenerate_revives(self) -> None:
        assert self.target.id is not None
        assert self.related.id is not None
        add_user_tag(self.db, article_id=self.target.id, tag="Black branes")
        add_user_tag(self.db, article_id=self.related.id, tag="Black branes")
        suggestion = LibraryConnectionSuggestion(
            candidate_id=article_candidate_id(self.related),
            relation_label="shared system",
            rationale="Both discuss black branes.",
            confidence=0.8,
        )
        generator = FakeConnectionGenerator((suggestion,))

        first = generate_connections_for_saved_article(
            self.db,
            article_id=self.target.id,
            generator=generator,
        )
        self.assertEqual(len(first), 1)
        dismiss_connection(self.db, article_id=self.target.id, related_article_id=self.related.id)

        second = generate_connections_for_saved_article(
            self.db,
            article_id=self.target.id,
            generator=generator,
        )
        self.assertEqual(second, [])

        revived = generate_connections_for_saved_article(
            self.db,
            article_id=self.target.id,
            generator=generator,
            regenerate=True,
        )
        self.assertEqual(len(revived), 1)
        self.assertIsNone(revived[0].dismissed_at)

    def test_assign_suggestions_rejects_unknown_and_duplicate_candidates(self) -> None:
        assert self.target.id is not None
        candidate = ConnectionCandidate(article=self.related, score=1.0, evidence={})
        with self.assertRaisesRegex(ValueError, "unknown"):
            assign_connection_suggestions(
                self.db,
                article_id=self.target.id,
                candidates=[candidate],
                suggestions=[
                    LibraryConnectionSuggestion(
                        candidate_id="arxiv:missing",
                        relation_label="shared method",
                        rationale="Grounded.",
                    )
                ],
                provenance={"provider": "fake"},
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            assign_connection_suggestions(
                self.db,
                article_id=self.target.id,
                candidates=[candidate],
                suggestions=[
                    LibraryConnectionSuggestion(
                        candidate_id=article_candidate_id(self.related),
                        relation_label="shared method",
                        rationale="Grounded.",
                    ),
                    LibraryConnectionSuggestion(
                        candidate_id=article_candidate_id(self.related),
                        relation_label="shared method",
                        rationale="Grounded.",
                    ),
                ],
                provenance={"provider": "fake"},
            )

    def test_invalid_connection_batch_does_not_partially_persist(self) -> None:
        assert self.target.id is not None
        candidate = ConnectionCandidate(article=self.related, score=1.0, evidence={})
        valid = LibraryConnectionSuggestion(
            candidate_id=article_candidate_id(self.related),
            relation_label="shared method",
            rationale="Grounded.",
        )
        duplicate = LibraryConnectionSuggestion(
            candidate_id=article_candidate_id(self.related),
            relation_label="same system",
            rationale="Also grounded.",
        )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            assign_connection_suggestions(
                self.db,
                article_id=self.target.id,
                candidates=[candidate],
                suggestions=[valid, duplicate],
                provenance={"provider": "fake"},
            )

        self.assertEqual(self.db.list_library_connections(), [])

    def test_unknown_after_valid_connection_does_not_partially_persist(self) -> None:
        assert self.target.id is not None
        candidate = ConnectionCandidate(article=self.related, score=1.0, evidence={})

        with self.assertRaisesRegex(ValueError, "unknown"):
            assign_connection_suggestions(
                self.db,
                article_id=self.target.id,
                candidates=[candidate],
                suggestions=[
                    LibraryConnectionSuggestion(
                        candidate_id=article_candidate_id(self.related),
                        relation_label="shared method",
                        rationale="Grounded.",
                    ),
                    LibraryConnectionSuggestion(
                        candidate_id="arxiv:missing",
                        relation_label="same system",
                        rationale="Not grounded.",
                    ),
                ],
                provenance={"provider": "fake"},
            )

        self.assertEqual(self.db.list_library_connections(), [])

    def test_prompt_is_bounded_and_labels_untrusted_data(self) -> None:
        candidate = ConnectionCandidate(
            article=self.related,
            score=3.0,
            evidence={"shared_categories": ("gr-qc",)},
        )
        prompt = build_connection_prompt(
            target=self.target,
            candidates=[candidate],
            relevance_context=None,
            max_suggestions=1,
        )

        self.assertIn("BEGIN_UNTRUSTED_LIBRARY_CONNECTION_INPUT_JSON", prompt)
        self.assertIn(article_candidate_id(self.related), prompt)
        self.assertNotIn("OPENAI_API_KEY", prompt)
        self.assertNotIn("sk-", prompt)

    def test_parse_connection_output_rejects_malformed_confidence_and_too_many(self) -> None:
        parsed = _parse_connection_output(
            json.dumps(
                {
                    "connections": [
                        {
                            "candidate_id": "arxiv:2608.conn02",
                            "relation_label": "shared method",
                            "rationale": "Both discuss spectra.",
                            "confidence": 0.6,
                        }
                    ]
                }
            ),
            max_suggestions=1,
        )
        self.assertEqual(parsed[0].candidate_id, "arxiv:2608.conn02")
        with self.assertRaises(AnalyzerError):
            _parse_connection_output(
                json.dumps(
                    {
                        "connections": [
                            {
                                "candidate_id": "arxiv:1",
                                "relation_label": "shared",
                                "rationale": "x",
                                "confidence": 1.2,
                            }
                        ]
                    }
                ),
                max_suggestions=1,
            )
        with self.assertRaises(AnalyzerError):
            _parse_connection_output(
                json.dumps(
                    {
                        "connections": [
                            {
                                "candidate_id": "arxiv:1",
                                "relation_label": "shared",
                                "rationale": "x",
                                "confidence": None,
                            },
                            {
                                "candidate_id": "arxiv:2",
                                "relation_label": "shared",
                                "rationale": "x",
                                "confidence": None,
                            },
                        ]
                    }
                ),
                max_suggestions=1,
            )

    def test_schema_11_upgrade_adds_search_and_connections(self) -> None:
        path = Path(self.tmpdir.name) / "schema11.sqlite3"
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
                    updated_at TEXT NOT NULL
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
                CREATE TABLE library_article_notes (
                    article_id INTEGER PRIMARY KEY,
                    note_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
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
                CREATE TABLE library_collection_memberships (
                    collection_id INTEGER NOT NULL,
                    article_id INTEGER NOT NULL,
                    added_at TEXT NOT NULL,
                    UNIQUE(collection_id, article_id)
                );
                INSERT INTO schema_metadata (key, value, updated_at)
                VALUES ('schema_version', '11', '2026-08-14T00:00:00Z');
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
                """
            )

        upgraded = Database(path)

        self.assertEqual(upgraded.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNotNone(upgraded.get_library_entry(1))
        upgraded.upsert_library_search_document(article_id=1, document_text="old paper")
        self.assertEqual(upgraded.search_library_document_article_ids("old"), [1])
        upgraded.close()

    def test_backup_export_includes_connection_state(self) -> None:
        assert self.target.id is not None
        assert self.related.id is not None
        self.db.upsert_library_connection(
            article_id_a=self.target.id,
            article_id_b=self.related.id,
            relation_label="shared system",
            rationale="Both discuss black branes.",
            provenance={"provider": "fake"},
            confidence=0.5,
        )

        from research_digest.backup import export_user_data

        payload = export_user_data(db_path=self.db.path)

        connections = cast(list[dict[str, object]], payload["library_article_connections"])
        self.assertIsInstance(connections, list)
        self.assertEqual(len(connections), 1)
        connection = connections[0]
        article_a = cast(dict[str, object], connection["article_a"])
        article_b = cast(dict[str, object], connection["article_b"])
        self.assertEqual(connection["relation_label"], "shared system")
        self.assertEqual(article_a["source_article_id"], "2608.conn01")
        self.assertEqual(article_b["source_article_id"], "2608.conn02")


class ConnectionAnalysisCacheBoundaryTests(unittest.TestCase):
    def test_connection_generation_does_not_touch_analysis_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "cache.sqlite3")
            article, _ = db.upsert_article(sample_article("2608.cache1", "Cache target"))
            related, _ = db.upsert_article(sample_article("2608.cache2", "Cache related"))
            assert article.id is not None
            assert related.id is not None
            save_article(db, article.id)
            save_article(db, related.id)
            add_user_tag(db, article_id=article.id, tag="Cache")
            add_user_tag(db, article_id=related.id, tag="Cache")
            profile = db.create_interest_profile(name="Profile", description="Physics.")
            assert profile.id is not None
            fingerprint = profile_semantic_fingerprint(profile)
            db.upsert_analysis(
                article_id=article.id,
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
                analysis=AnalysisResult(
                    relevance_score=0.7,
                    relevance_reason="Reason.",
                    matched_topics=["cache"],
                    summary="Summary.",
                    why_it_matters="Useful.",
                    reading_priority="HIGH",
                ),
            )
            before = db.get_analysis(
                article_id=article.id,
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
            )

            generate_connections_for_saved_article(
                db,
                article_id=article.id,
                generator=FakeConnectionGenerator(
                    (
                        LibraryConnectionSuggestion(
                            candidate_id=article_candidate_id(related),
                            relation_label="shared tag",
                            rationale="Both use the Cache tag.",
                        ),
                    )
                ),
            )

            after = db.get_analysis(
                article_id=article.id,
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
            )
            self.assertEqual(before, after)
            db.close()
