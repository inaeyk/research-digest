from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

import research_digest.db as db_module
from research_digest.ai_artifacts import (
    collect_expired_artifacts,
    create_artifact,
    create_digest_summary_artifact,
    resolve_preferred_library_summary,
    set_artifact_retention,
)
from research_digest.backup import export_user_data
from research_digest.collections import (
    add_article_to_collection,
    create_collection,
    get_note,
    remove_article_from_collection,
    save_note,
)
from research_digest.conversations import (
    append_message,
    create_conversation,
    list_conversations,
    list_messages,
    set_rolling_summary,
)
from research_digest.db import CURRENT_SCHEMA_VERSION, Database
from research_digest.library import (
    list_library_items,
    save_article,
    set_interest_rating,
    set_reading_state,
    unsave_article,
)
from research_digest.models import (
    AIArtifactRetentionClass,
    AIArtifactType,
    AIConversationRole,
    AnalysisResult,
    Article,
    LibraryEntry,
    LibrarySummarySource,
    ModelValidationError,
    ReadingState,
)
from research_digest.retention import DEFAULT_TEMPORARY_AI_ARTIFACT_RETENTION
from research_digest.tags import add_user_tag, remove_user_tag

FIXED_NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def sample_article(source_article_id: str = "2608.l1a01") -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=f"Stable Library foundation {source_article_id}",
        authors=["Ada Researcher", "Ben Scientist"],
        abstract="Canonical abstract stored once on the Article row.",
        categories=["hep-th"],
        published_at=FIXED_NOW - timedelta(days=2),
        updated_at=FIXED_NOW - timedelta(days=1),
        abstract_url=f"https://arxiv.org/abs/{source_article_id}",
        pdf_url=f"https://arxiv.org/pdf/{source_article_id}",
    )


def create_persisted_article(db: Database, source_article_id: str = "2608.l1a01") -> Article:
    article, _inserted = db.upsert_article(sample_article(source_article_id))
    assert article.id is not None
    return article


class _ArtifactKwargs(TypedDict):
    artifact_type: AIArtifactType
    content: str
    provider: str
    model_id: str
    reasoning_effort: str | None
    generator_version: str
    input_fingerprint: str


def artifact_kwargs(*, content: str = "Retained generated summary.") -> _ArtifactKwargs:
    return {
        "artifact_type": AIArtifactType.DIGEST_SUMMARY,
        "content": content,
        "provider": "fake-provider",
        "model_id": "fake-model",
        "reasoning_effort": "medium",
        "generator_version": "digest-summary-v1",
        "input_fingerprint": "sha256:input-fixture",
    }


class LibraryCoreFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = Database(Path(self.tempdir.name) / "library-foundation.sqlite3")
        self.article = create_persisted_article(self.db)
        article_id = self.article.id
        assert article_id is not None
        self.article_id = article_id

    def test_interest_rating_domain_and_nullable_default(self) -> None:
        entry = save_article(self.db, self.article_id)
        self.assertIsNone(entry.interest_rating)
        self.assertIsNone(entry.reading_state)

        for rating in range(1, 6):
            entry = set_interest_rating(
                self.db,
                article_id=self.article_id,
                interest_rating=rating,
            )
            self.assertEqual(entry.interest_rating, rating)

        cleared = set_interest_rating(
            self.db,
            article_id=self.article_id,
            interest_rating=None,
        )
        self.assertIsNone(cleared.interest_rating)
        for invalid in (0, 6, 2.5, "3", True):
            with self.assertRaises(ValueError):
                set_interest_rating(
                    self.db,
                    article_id=self.article_id,
                    interest_rating=invalid,  # type: ignore[arg-type]
                )

        with self.assertRaises(ModelValidationError):
            LibraryEntry(
                article=self.article,
                saved_at=FIXED_NOW,
                updated_at=FIXED_NOW,
                reading_state=None,
                interest_rating=2.5,  # type: ignore[arg-type]
            )

    def test_database_constraints_reject_out_of_range_interest_rating(self) -> None:
        save_article(self.db, self.article_id)
        with sqlite3.connect(self.db.path) as conn:
            for invalid in (0, 6, 2.5):
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "UPDATE library_articles SET interest_rating = ? WHERE article_id = ?",
                        (invalid, self.article_id),
                    )

    def test_reading_state_domain_is_small_and_nullable(self) -> None:
        save_article(self.db, self.article_id)
        for state in ReadingState:
            entry = set_reading_state(
                self.db,
                article_id=self.article_id,
                reading_state=state,
            )
            self.assertEqual(entry.reading_state, state)
        cleared = set_reading_state(
            self.db,
            article_id=self.article_id,
            reading_state=None,
        )
        self.assertIsNone(cleared.reading_state)
        with self.assertRaises(ValueError):
            self.db.set_library_reading_state(self.article_id, "queued")  # type: ignore[arg-type]

    def test_one_canonical_article_and_pointer_only_relationship_rows(self) -> None:
        repeated, inserted = self.db.upsert_article(sample_article(self.article.source_article_id))
        self.assertFalse(inserted)
        self.assertEqual(repeated.id, self.article_id)
        save_article(self.db, self.article_id)
        collection = create_collection(self.db, name="Foundation project")
        assert collection.id is not None
        add_article_to_collection(
            self.db,
            collection_id=collection.id,
            article_id=self.article_id,
        )
        add_user_tag(self.db, article_id=self.article_id, tag="Stable identity")
        create_artifact(
            self.db,
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.LIBRARY,
            created_at=FIXED_NOW,
            **artifact_kwargs(),
        )
        create_conversation(
            self.db,
            article_id=self.article_id,
            title="Identity discussion",
            provider="fake-provider",
            model_id="fake-model",
        )

        forbidden = {
            "title",
            "authors",
            "authors_json",
            "abstract",
            "published_at",
            "source_article_id",
            "categories",
            "categories_json",
        }
        relationship_tables = (
            "library_articles",
            "library_article_notes",
            "library_collection_memberships",
            "library_tag_assignments",
            "ai_artifacts",
            "ai_conversations",
            "ai_conversation_messages",
        )
        with sqlite3.connect(self.db.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 1)
            for table in relationship_tables:
                columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
                table_forbidden = forbidden - ({"title"} if table == "ai_conversations" else set())
                self.assertFalse(table_forbidden.intersection(columns), (table, columns))

    def test_all_foundation_user_operations_are_ai_free(self) -> None:
        fail = AssertionError("persistence foundation invoked an AI execution boundary")
        with (
            patch(
                "research_digest.analysis.providers.build_configured_analyzer",
                side_effect=fail,
            ) as analyzer_factory,
            patch(
                "research_digest.analysis.openai.OpenAIAnalyzer.analyze_many",
                side_effect=fail,
            ) as openai_analyze,
            patch(
                "research_digest.analysis.codex_cli.CodexCLIAnalyzer.analyze_many",
                side_effect=fail,
            ) as codex_analyze,
            patch(
                "research_digest.tags.generate_ai_tags_for_saved_article",
                side_effect=fail,
            ) as ai_tag_generation,
        ):
            temporary = create_artifact(
                self.db,
                article_id=self.article_id,
                retention_class=AIArtifactRetentionClass.TEMPORARY,
                **artifact_kwargs(),
            )
            save_article(self.db, self.article_id)
            list_library_items(self.db)
            set_interest_rating(self.db, article_id=self.article_id, interest_rating=3)
            set_reading_state(
                self.db,
                article_id=self.article_id,
                reading_state=ReadingState.SKIMMED,
            )
            save_note(self.db, article_id=self.article_id, note_text="Human-authored note.")
            collection = create_collection(self.db, name="AI-free collection")
            assert collection.id is not None
            add_article_to_collection(
                self.db,
                collection_id=collection.id,
                article_id=self.article_id,
            )
            remove_article_from_collection(
                self.db,
                collection_id=collection.id,
                article_id=self.article_id,
            )
            add_user_tag(self.db, article_id=self.article_id, tag="Human tag")
            remove_user_tag(self.db, article_id=self.article_id, tag="Human tag")
            artifact = create_artifact(
                self.db,
                article_id=self.article_id,
                retention_class=AIArtifactRetentionClass.LIBRARY,
                created_at=FIXED_NOW,
                **artifact_kwargs(),
            )
            assert artifact.id is not None
            set_artifact_retention(
                self.db,
                artifact_id=artifact.id,
                retention_class=AIArtifactRetentionClass.USER_PINNED,
            )
            collect_expired_artifacts(self.db, now=FIXED_NOW + timedelta(days=200))
            conversation = create_conversation(
                self.db,
                article_id=self.article_id,
                title="Persistence only",
                provider="fake-provider",
                model_id="fake-model",
            )
            assert conversation.id is not None
            append_message(
                self.db,
                conversation_id=conversation.id,
                role=AIConversationRole.USER,
                content="No model call should occur.",
            )
            unsave_article(self.db, self.article_id)
            assert temporary.id is not None
            demoted = self.db.get_ai_artifact(temporary.id)
            assert demoted is not None
            self.assertEqual(
                demoted.retention_class,
                AIArtifactRetentionClass.TEMPORARY,
            )

        analyzer_factory.assert_not_called()
        openai_analyze.assert_not_called()
        codex_analyze.assert_not_called()
        ai_tag_generation.assert_not_called()


class AIArtifactFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = Database(Path(self.tempdir.name) / "artifacts.sqlite3")
        self.article = create_persisted_article(self.db, "2608.artifact")
        article_id = self.article.id
        assert article_id is not None
        self.article_id = article_id

    def test_temporary_artifact_provenance_and_default_expiration_round_trip(self) -> None:
        artifact = create_artifact(
            self.db,
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            **artifact_kwargs(),
        )
        self.assertEqual(artifact.retention_class, AIArtifactRetentionClass.TEMPORARY)
        self.assertEqual(
            artifact.expires_at,
            FIXED_NOW + DEFAULT_TEMPORARY_AI_ARTIFACT_RETENTION,
        )
        self.assertEqual(artifact.provider, "fake-provider")
        self.assertEqual(artifact.model_id, "fake-model")
        self.assertEqual(artifact.reasoning_effort, "medium")
        self.assertEqual(artifact.generator_version, "digest-summary-v1")
        self.assertEqual(artifact.input_fingerprint, "sha256:input-fixture")

    def test_save_promotes_and_unsave_demotes_same_artifact_without_copy(self) -> None:
        artifact = create_artifact(
            self.db,
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            **artifact_kwargs(content="One immutable content body."),
        )
        assert artifact.id is not None
        save_article(self.db, self.article_id)
        promoted = self.db.get_ai_artifact(artifact.id)
        assert promoted is not None
        self.assertEqual(promoted.id, artifact.id)
        self.assertEqual(promoted.content, artifact.content)
        self.assertEqual(promoted.retention_class, AIArtifactRetentionClass.LIBRARY)
        self.assertIsNone(promoted.expires_at)

        unsaved_at = FIXED_NOW + timedelta(days=10)
        with patch("research_digest.db.utc_now", return_value=unsaved_at):
            unsave_article(self.db, self.article_id)
        demoted = self.db.get_ai_artifact(artifact.id)
        assert demoted is not None
        self.assertEqual(demoted.id, artifact.id)
        self.assertEqual(demoted.content, artifact.content)
        self.assertEqual(demoted.retention_class, AIArtifactRetentionClass.TEMPORARY)
        self.assertEqual(
            demoted.expires_at,
            unsaved_at + DEFAULT_TEMPORARY_AI_ARTIFACT_RETENTION,
        )

    def test_save_does_not_resurrect_an_expired_temporary_artifact(self) -> None:
        artifact = self.db.create_ai_artifact(
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(days=1),
            **artifact_kwargs(content="Expired prose must remain disposable."),
        )
        assert artifact.id is not None
        save_at = FIXED_NOW + timedelta(days=2)
        with patch("research_digest.db.utc_now", return_value=save_at):
            save_article(self.db, self.article_id)
        unchanged = self.db.get_ai_artifact(artifact.id)
        assert unchanged is not None
        self.assertEqual(
            unchanged.retention_class,
            AIArtifactRetentionClass.TEMPORARY,
        )
        self.assertEqual(unchanged.expires_at, FIXED_NOW + timedelta(days=1))
        self.assertIsNone(
            resolve_preferred_library_summary(
                self.db,
                article_id=self.article_id,
                now=save_at,
            )
        )

    def test_artifact_and_resolved_summary_preserve_markdown_whitespace(self) -> None:
        content = "\n  ```python\n  print('indent is data')\n  ```\n\n"
        artifact = create_artifact(
            self.db,
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            **artifact_kwargs(content=content),
        )
        assert artifact.id is not None
        self.assertEqual(artifact.content, content)
        loaded = self.db.get_ai_artifact(artifact.id)
        assert loaded is not None
        self.assertEqual(loaded.content, content)
        resolved = resolve_preferred_library_summary(
            self.db,
            article_id=self.article_id,
            now=FIXED_NOW,
        )
        assert resolved is not None
        self.assertEqual(resolved.content, content)

    def test_user_pinned_artifact_never_expires_or_demotes(self) -> None:
        artifact = create_artifact(
            self.db,
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.USER_PINNED,
            created_at=FIXED_NOW,
            **artifact_kwargs(),
        )
        assert artifact.id is not None
        save_article(self.db, self.article_id)
        unsave_article(self.db, self.article_id)
        retained = self.db.get_ai_artifact(artifact.id)
        assert retained is not None
        self.assertEqual(retained.retention_class, AIArtifactRetentionClass.USER_PINNED)
        self.assertIsNone(retained.expires_at)
        self.assertEqual(
            collect_expired_artifacts(self.db, now=FIXED_NOW + timedelta(days=1000)),
            0,
        )

    def test_gc_deletes_only_expired_unreferenced_temporary_artifacts(self) -> None:
        expired = self.db.create_ai_artifact(
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(days=1),
            **artifact_kwargs(content="Expired and unreferenced."),
        )
        future = self.db.create_ai_artifact(
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(days=20),
            **artifact_kwargs(content="Still usable."),
        )
        assert expired.id is not None and future.id is not None
        deleted = collect_expired_artifacts(self.db, now=FIXED_NOW + timedelta(days=10))
        self.assertEqual(deleted, 1)
        self.assertIsNone(self.db.get_ai_artifact(expired.id))
        self.assertIsNotNone(self.db.get_ai_artifact(future.id))

    def test_gc_reclaims_nonretained_saved_artifact_but_protects_conversation_ref(self) -> None:
        save_article(self.db, self.article_id)
        saved_temporary = self.db.create_ai_artifact(
            article_id=self.article_id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(days=1),
            **artifact_kwargs(content="Saved article safety predicate."),
        )
        other = create_persisted_article(self.db, "2608.conversation-summary")
        assert other.id is not None
        rolling = self.db.create_ai_artifact(
            article_id=other.id,
            artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
            content="Rolling summary remains a durable reference.",
            provider="fake-provider",
            model_id="fake-model",
            reasoning_effort=None,
            generator_version="conversation-summary-v1",
            input_fingerprint="sha256:conversation",
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(days=1),
        )
        assert saved_temporary.id is not None and rolling.id is not None
        conversation = self.db.create_ai_conversation(
            article_id=other.id,
            title="Durable transcript",
            provider="fake-provider",
            model_id="fake-model",
            rolling_summary_artifact_id=rolling.id,
        )
        self.assertIsNotNone(conversation.id)
        self.assertEqual(
            collect_expired_artifacts(self.db, now=FIXED_NOW + timedelta(days=10)),
            1,
        )
        self.assertIsNone(self.db.get_ai_artifact(saved_temporary.id))
        self.assertIsNotNone(self.db.get_ai_artifact(rolling.id))

    def test_preferred_summary_resolution_reuses_without_generation_or_copy(self) -> None:
        profile = self.db.create_interest_profile(name="Profile", description="Fixture")
        assert profile.id is not None
        self.db.upsert_analysis(
            article_id=self.article_id,
            profile_id=profile.id,
            profile_fingerprint="profile-fingerprint",
            analysis=AnalysisResult(
                relevance_score=0.8,
                relevance_reason="Relevant.",
                matched_topics=["foundation"],
                summary="Existing authoritative digest summary.",
                why_it_matters="Useful.",
                reading_priority="HIGH",
            ),
        )
        legacy = resolve_preferred_library_summary(
            self.db,
            article_id=self.article_id,
            now=FIXED_NOW,
        )
        assert legacy is not None
        self.assertEqual(legacy.source, LibrarySummarySource.LEGACY_DIGEST_ANALYSIS)
        self.assertEqual(legacy.content, "Existing authoritative digest summary.")
        self.assertIsNone(legacy.artifact_id)

        digest = create_digest_summary_artifact(
            self.db,
            article_id=self.article_id,
            content="Artifact-backed digest summary.",
            provider="fake-provider",
            model_id="fake-model",
            reasoning_effort="low",
            generator_version="digest-summary-v2",
            input_fingerprint="sha256:digest-v2",
            created_at=FIXED_NOW,
        )
        resolved_digest = resolve_preferred_library_summary(
            self.db,
            article_id=self.article_id,
            now=FIXED_NOW,
        )
        assert resolved_digest is not None
        self.assertEqual(resolved_digest.source, LibrarySummarySource.DIGEST_ARTIFACT)
        self.assertEqual(resolved_digest.artifact_id, digest.id)

        save_article(self.db, self.article_id)
        library_summary = create_artifact(
            self.db,
            article_id=self.article_id,
            artifact_type=AIArtifactType.LIBRARY_SUMMARY,
            content="Explicit Library summary.",
            provider="other-provider",
            model_id="other-model",
            reasoning_effort="high",
            generator_version="library-summary-v1",
            input_fingerprint="sha256:library-v1",
            retention_class=AIArtifactRetentionClass.LIBRARY,
            created_at=FIXED_NOW - timedelta(days=1),
        )
        preferred = resolve_preferred_library_summary(
            self.db,
            article_id=self.article_id,
            now=FIXED_NOW,
        )
        assert preferred is not None
        self.assertEqual(preferred.source, LibrarySummarySource.LIBRARY_ARTIFACT)
        self.assertEqual(preferred.artifact_id, library_summary.id)
        self.assertEqual(len(self.db.list_ai_artifacts(self.article_id)), 2)

    def test_no_summary_and_save_creates_no_artifact(self) -> None:
        self.assertIsNone(
            resolve_preferred_library_summary(self.db, article_id=self.article_id)
        )
        save_article(self.db, self.article_id)
        self.assertEqual(self.db.list_ai_artifacts(self.article_id), [])


class AIConversationFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = Database(Path(self.tempdir.name) / "conversations.sqlite3")
        self.article = create_persisted_article(self.db, "2608.conversation")
        article_id = self.article.id
        assert article_id is not None
        self.article_id = article_id
        save_article(self.db, self.article_id)
        save_note(self.db, article_id=self.article_id, note_text="Human note remains separate.")

    def test_multiple_conversations_provenance_and_null_summary_pointer(self) -> None:
        first = create_conversation(
            self.db,
            article_id=self.article_id,
            title="First discussion",
            provider="provider-a",
            model_id="model-a",
            conversation_version=2,
            created_at=FIXED_NOW,
        )
        second = create_conversation(
            self.db,
            article_id=self.article_id,
            title="Second discussion",
            provider="provider-b",
            model_id="model-b",
            created_at=FIXED_NOW + timedelta(minutes=1),
        )
        conversations = list_conversations(self.db, article_id=self.article_id)
        self.assertEqual({item.id for item in conversations}, {first.id, second.id})
        self.assertEqual(first.provider, "provider-a")
        self.assertEqual(first.model_id, "model-a")
        self.assertEqual(first.conversation_version, 2)
        self.assertIsNone(first.rolling_summary_artifact_id)

    def test_message_order_full_text_unsave_survival_and_note_separation(self) -> None:
        conversation = create_conversation(
            self.db,
            article_id=self.article_id,
            title="Transcript",
            provider="fake-provider",
            model_id="fake-model",
            created_at=FIXED_NOW,
        )
        assert conversation.id is not None
        user_text = "\n  User Markdown\n\n- exact first message\n"
        assistant_text = "  Assistant Markdown\n\n1. exact response\n\n"
        append_message(
            self.db,
            conversation_id=conversation.id,
            role=AIConversationRole.USER,
            content=user_text,
            created_at=FIXED_NOW,
        )
        append_message(
            self.db,
            conversation_id=conversation.id,
            role=AIConversationRole.ASSISTANT,
            content=assistant_text,
            created_at=FIXED_NOW + timedelta(seconds=1),
        )
        unsave_article(self.db, self.article_id)
        messages = list_messages(self.db, conversation_id=conversation.id)
        self.assertEqual([message.sequence_number for message in messages], [1, 2])
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual([message.content for message in messages], [user_text, assistant_text])
        self.assertEqual(len(list_conversations(self.db, article_id=self.article_id)), 1)
        note = get_note(self.db, article_id=self.article_id)
        assert note is not None
        self.assertEqual(note.note_text, "Human note remains separate.")

    def test_rolling_summary_pointer_requires_same_article_and_type(self) -> None:
        conversation = create_conversation(
            self.db,
            article_id=self.article_id,
            title="Compressible later",
            provider="fake-provider",
            model_id="fake-model",
        )
        assert conversation.id is not None
        summary = create_artifact(
            self.db,
            article_id=self.article_id,
            artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
            content="Rolling context only; transcript remains complete.",
            provider="fake-provider",
            model_id="fake-model",
            reasoning_effort="medium",
            generator_version="conversation-summary-v1",
            input_fingerprint="sha256:rolling",
            retention_class=AIArtifactRetentionClass.LIBRARY,
        )
        assert summary.id is not None
        updated = set_rolling_summary(
            self.db,
            conversation_id=conversation.id,
            artifact_id=summary.id,
        )
        self.assertEqual(updated.rolling_summary_artifact_id, summary.id)
        self.assertEqual(list_messages(self.db, conversation_id=conversation.id), [])


class Schema19MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "realistic-v041.sqlite3"
        _create_realistic_schema_18_database(self.path)

    def test_realistic_v041_migration_preserves_all_stable_data_and_creates_backup(self) -> None:
        fail = AssertionError("migration invoked an AI execution boundary")
        with (
            patch(
                "research_digest.analysis.providers.build_configured_analyzer",
                side_effect=fail,
            ) as analyzer_factory,
            patch(
                "research_digest.analysis.openai.OpenAIAnalyzer.analyze_many",
                side_effect=fail,
            ) as openai_analyze,
            patch(
                "research_digest.analysis.codex_cli.CodexCLIAnalyzer.analyze_many",
                side_effect=fail,
            ) as codex_analyze,
        ):
            migrated = Database(self.path)
        analyzer_factory.assert_not_called()
        openai_analyze.assert_not_called()
        codex_analyze.assert_not_called()
        self.assertEqual(CURRENT_SCHEMA_VERSION, 20)
        self.assertEqual(migrated.get_schema_version(), 20)
        self.assertIsNotNone(migrated.last_migration_backup_path)
        assert migrated.last_migration_backup_path is not None
        self.assertTrue(migrated.last_migration_backup_path.exists())
        self.assertIn("backup-v18-to-v20", migrated.last_migration_backup_path.name)
        with sqlite3.connect(migrated.last_migration_backup_path) as backup:
            version = backup.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
            self.assertEqual(version, ("18",))
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 1)

        entry = migrated.get_library_entry(1)
        assert entry is not None
        self.assertIsNone(entry.interest_rating)
        self.assertIsNone(entry.reading_state)
        note = migrated.get_library_note(1)
        assert note is not None
        self.assertEqual(note.note_text, "Exact v0.4.1 human note.\n\nPreserve Markdown.")
        self.assertEqual(
            migrated.list_library_tag_assignments(1)[0].ai_provenance,
            {"provider": "legacy-fake", "prompt_version": "library_ai_tags_v1"},
        )
        self.assertEqual(len(migrated.list_library_collection_memberships()), 1)
        snapshot = migrated.get_run_snapshot(run_id=1)
        assert snapshot is not None
        self.assertEqual(
            str(snapshot["snapshot_json"]),
            json.dumps(
                {
                    "run_id": 1,
                    "items": [{"summary": "Exact historical generated prose."}],
                },
                sort_keys=True,
            ),
        )
        feedback = migrated.get_article_feedback(
            article_id=1,
            profile_id=1,
            profile_fingerprint="profile-fingerprint",
        )
        assert feedback is not None
        self.assertEqual(feedback.personal_interest, "YES")
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM source_date_coverage").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM source_date_corpora").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM relevance_analyses").fetchone()[0],
                1,
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_conversations").fetchone()[0], 0)

    def test_migration_is_restart_safe_and_backup_export_includes_l1a_data(self) -> None:
        migrated = Database(self.path)
        first_backup = migrated.last_migration_backup_path
        reopened = Database(self.path)
        self.assertEqual(reopened.get_schema_version(), 20)
        self.assertIsNone(reopened.last_migration_backup_path)
        self.assertEqual(reopened.get_last_migration_backup_path(), first_backup)
        entry = set_interest_rating(reopened, article_id=1, interest_rating=4)
        self.assertEqual(entry.interest_rating, 4)
        artifact = create_artifact(
            reopened,
            article_id=1,
            artifact_type=AIArtifactType.LIBRARY_SUMMARY,
            content="Exported Library summary.",
            provider="fake-provider",
            model_id="fake-model",
            reasoning_effort=None,
            generator_version="library-summary-v1",
            input_fingerprint="sha256:export",
            retention_class=AIArtifactRetentionClass.LIBRARY,
        )
        conversation = create_conversation(
            reopened,
            article_id=1,
            title="Exported conversation",
            provider="fake-provider",
            model_id="fake-model",
        )
        assert conversation.id is not None
        message = append_message(
            reopened,
            conversation_id=conversation.id,
            role=AIConversationRole.USER,
            content="Export this complete transcript.",
        )
        payload = export_user_data(db_path=self.path)
        self.assertEqual(payload["schema_version"], 20)
        self.assertEqual(payload["library_articles"][0]["interest_rating"], 4)  # type: ignore[index]
        self.assertEqual(payload["ai_artifacts"][0]["id"], artifact.id)  # type: ignore[index]
        self.assertEqual(payload["ai_conversations"][0]["id"], conversation.id)  # type: ignore[index]
        self.assertEqual(payload["ai_conversation_messages"][0]["id"], message.id)  # type: ignore[index]


def _create_realistic_schema_18_database(path: Path) -> None:
    timestamp = "2026-08-29T12:00:00Z"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        for migration in db_module.MIGRATIONS:
            if migration.version >= 19:
                break
            migration.apply(conn)
        conn.execute(
            "INSERT INTO schema_metadata (key, value, updated_at) VALUES (?, ?, ?)",
            ("schema_version", "18", timestamp),
        )
        conn.execute(
            """
            INSERT INTO interest_profiles (
                id, name, description, relevance_threshold, enabled, created_at, updated_at
            ) VALUES (1, 'Fixture profile', 'Migration fixture', 0.6, 1, ?, ?)
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO source_configs (
                source_name, enabled, categories_json, lookback_hours, max_results, updated_at
            ) VALUES ('arxiv', 1, '["hep-th"]', 48, 50, ?)
            """,
            (timestamp,),
        )
        conn.execute(
            """
            INSERT INTO articles (
                id, source, source_article_id, title, authors_json, abstract,
                categories_json, published_at, updated_at, abstract_url, pdf_url, created_at
            ) VALUES (
                1, 'arxiv', '2608.v041', 'Exact v0.4.1 article', '["Ada Researcher"]',
                'Exact canonical abstract.', '["hep-th"]', ?, ?,
                'https://arxiv.org/abs/2608.v041', NULL, ?
            )
            """,
            (timestamp, timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO app_runs (
                id, profile_id, source_name, started_at, completed_at, status,
                retrieved_count, stored_count, preselected_count, skipped_analysis_count,
                analyzed_count, relevant_count, run_origin, requested_source_dates_json,
                covered_source_dates_json, empty_source_dates_json,
                incomplete_source_dates_json, retrieval_complete, source_fingerprint,
                profile_fingerprint
            ) VALUES (
                1, 1, 'arxiv', ?, ?, 'COMPLETED', 1, 1, 1, 0, 1, 1, 'MANUAL',
                '["2026-08-29"]', '["2026-08-29"]', '[]', '[]', 1,
                'source-fingerprint', 'profile-fingerprint'
            )
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO relevance_analyses (
                id, article_id, profile_id, profile_fingerprint, relevance_score,
                relevance_reason, matched_topics_json, summary, why_it_matters,
                reading_priority, analyzed_at
            ) VALUES (
                1, 1, 1, 'profile-fingerprint', 0.9, 'Exact relevance reason.',
                '["foundation"]', 'Exact digest summary.', 'Exact why-it-matters.',
                'HIGH', ?
            )
            """,
            (timestamp,),
        )
        conn.execute(
            """
            INSERT INTO article_feedback (
                id, article_id, profile_id, profile_fingerprint, feedback_label,
                profile_match, personal_interest, created_at, updated_at
            ) VALUES (
                1, 1, 1, 'profile-fingerprint', 'RELEVANT', 'YES', 'YES', ?, ?
            )
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO library_articles (article_id, saved, saved_at, updated_at)
            VALUES (1, 1, ?, ?)
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO library_tags (
                id, normalized_name, display_name, created_at, updated_at
            ) VALUES (1, 'ai tag', 'AI tag', ?, ?)
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO library_tag_assignments (
                id, article_id, tag_id, origin, ai_provenance_json, created_at, updated_at
            ) VALUES (1, 1, 1, 'AI', ?, ?, ?)
            """,
            (
                json.dumps(
                    {"provider": "legacy-fake", "prompt_version": "library_ai_tags_v1"},
                    sort_keys=True,
                ),
                timestamp,
                timestamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO library_article_notes (article_id, note_text, created_at, updated_at)
            VALUES (1, ?, ?, ?)
            """,
            ("Exact v0.4.1 human note.\n\nPreserve Markdown.", timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO library_collections (
                id, name, normalized_name, description, created_at, updated_at
            ) VALUES (1, 'Fixture collection', 'fixture collection', 'Exact description.', ?, ?)
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO library_collection_memberships (collection_id, article_id, added_at)
            VALUES (1, 1, ?)
            """,
            (timestamp,),
        )
        conn.execute(
            "INSERT INTO run_snapshots (run_id, snapshot_json, created_at) VALUES (1, ?, ?)",
            (
                json.dumps(
                    {
                        "run_id": 1,
                        "items": [{"summary": "Exact historical generated prose."}],
                    },
                    sort_keys=True,
                ),
                timestamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO source_date_coverage (
                id, source_name, source_fingerprint, source_date, status,
                first_covered_run_id, last_covered_run_id, run_origin, covered_at, updated_at
            ) VALUES (
                1, 'arxiv', 'source-fingerprint', '2026-08-29', 'COVERED',
                1, 1, 'MANUAL', ?, ?
            )
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO source_date_corpora (
                id, source_name, source_fingerprint, source_date, article_count,
                captured_run_id, created_at, updated_at
            ) VALUES (
                1, 'arxiv', 'source-fingerprint', '2026-08-29', 1, 1, ?, ?
            )
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            "INSERT INTO source_date_corpus_articles (corpus_id, article_id) VALUES (1, 1)"
        )
        conn.execute(
            """
            INSERT INTO preselection_decisions (
                id, run_id, article_id, profile_id, profile_fingerprint, source_name,
                source_fingerprint, preselection_score, preselection_threshold, passed,
                stage, decision_origin, preselector_version, reason, created_at
            ) VALUES (
                1, 1, 1, 1, 'profile-fingerprint', 'arxiv', 'source-fingerprint',
                0.95, 0.6, 1, 'model_abstract', 'NEW_THIS_RUN',
                'fake_model_abstract_v1', 'Exact preselection prose.', ?
            )
            """,
            (timestamp,),
        )


if __name__ == "__main__":
    unittest.main()
