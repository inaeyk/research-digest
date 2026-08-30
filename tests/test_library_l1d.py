from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research_digest.ai_artifacts import create_artifact
from research_digest.ai_providers import GeneratedAIText
from research_digest.analysis.base import AnalyzerError
from research_digest.backup import export_user_data
from research_digest.collections import save_note
from research_digest.conversations import (
    ConversationContextError,
    ConversationContextPolicy,
    ConversationError,
    append_message,
    create_conversation,
    inspect_conversation_context,
    list_conversation_overviews,
    list_messages,
    promote_assistant_takeaway_to_note,
    rename_conversation,
    retry_conversation_response,
    rolling_summary_boundary,
    send_conversation_message,
)
from research_digest.db import (
    CURRENT_SCHEMA_VERSION,
    AIConversationBusyError,
    AIConversationConflictError,
    Database,
)
from research_digest.library import save_article, unsave_article
from research_digest.models import (
    AIArtifactProvenance,
    AIArtifactRetentionClass,
    AIArtifactType,
    AIConversationRole,
    Article,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


class FakeConversationProvider:
    provider = "fake-research"
    model_id = "fake-physics-model"
    reasoning_effort: str | None = "high"
    response_generator_version = "fake-research-conversation-v1"
    summary_generator_version = "fake-conversation-summary-v1"
    timeout_seconds = 5.0

    def __init__(self) -> None:
        self.response_contexts: list[str] = []
        self.summary_contexts: list[str] = []
        self.fail_response = False
        self.fail_summary = False

    def respond(self, *, article: Article, context: str) -> GeneratedAIText:
        del article
        self.response_contexts.append(context)
        if self.fail_response:
            raise AnalyzerError("synthetic provider failure with secret=hidden")
        return GeneratedAIText(
            content=f"Assistant response {len(self.response_contexts)}.\n\nExact whitespace.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.response_generator_version,
            input_fingerprint=_fingerprint(context),
        )

    def summarize_conversation(
        self,
        *,
        article: Article,
        context: str,
    ) -> GeneratedAIText:
        del article
        self.summary_contexts.append(context)
        if self.fail_summary:
            raise AnalyzerError("synthetic compression failure")
        payload = json.loads(context)
        boundary = payload["summarized_through_sequence"]
        return GeneratedAIText(
            content=f"Research state through message {boundary}; unresolved issue retained.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.summary_generator_version,
            input_fingerprint=_fingerprint(context),
        )


class LibraryL1DTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = Database(Path(self.tempdir.name) / "l1d.sqlite3")
        article, _ = self.db.upsert_article(_article("2608.l1d"))
        assert article.id is not None
        self.article = article
        self.article_id = article.id
        save_article(self.db, self.article_id)
        self.provider = FakeConversationProvider()

    def create(self, title: str | None = None) -> int:
        conversation = create_conversation(
            self.db,
            article_id=self.article_id,
            title=title,
            provider=self.provider.provider,
            model_id=self.provider.model_id,
            created_at=NOW,
        )
        assert conversation.id is not None
        return conversation.id

    def test_creation_multiple_default_titles_rename_and_unsave_are_ai_free(self) -> None:
        first_id = self.create()
        second_id = self.create()
        renamed = rename_conversation(
            self.db,
            conversation_id=second_id,
            title="  Warped KK spectrum  ",
        )
        unsave_article(self.db, self.article_id)

        overviews = list_conversation_overviews(self.db, article_id=self.article_id)
        by_id = {overview.conversation.id: overview for overview in overviews}
        self.assertEqual(by_id[first_id].conversation.title, "Discussion 1")
        self.assertEqual(renamed.title, "Warped KK spectrum")
        self.assertEqual(by_id[second_id].conversation.title, "Warped KK spectrum")
        self.assertEqual(self.provider.response_contexts, [])
        self.assertEqual(self.provider.summary_contexts, [])

    def test_full_transcript_round_trips_whitespace_and_sequence(self) -> None:
        conversation_id = self.create("Transcript")
        contents = ["\n user exact \n", " assistant exact\n\n", "second user"]
        roles = [
            AIConversationRole.USER,
            AIConversationRole.ASSISTANT,
            AIConversationRole.USER,
        ]
        for index, (role, content) in enumerate(zip(roles, contents, strict=True)):
            append_message(
                self.db,
                conversation_id=conversation_id,
                role=role,
                content=content,
                created_at=NOW + timedelta(seconds=index),
            )
        stored = list_messages(self.db, conversation_id=conversation_id)
        self.assertEqual([message.sequence_number for message in stored], [1, 2, 3])
        self.assertEqual([message.content for message in stored], contents)
        self.assertEqual([message.role for message in stored], roles)

    def test_optimistic_sequence_and_durable_lock_reject_concurrent_send(self) -> None:
        conversation_id = self.create()
        first = self.db.begin_ai_conversation_turn(
            conversation_id=conversation_id,
            content="first",
            expected_last_sequence=0,
            created_at=NOW,
        )
        self.assertEqual(first.sequence_number, 1)
        with self.assertRaises(AIConversationConflictError):
            self.db.begin_ai_conversation_turn(
                conversation_id=conversation_id,
                content="racing second",
                expected_last_sequence=0,
                created_at=NOW,
            )

        other_id = self.create("Other")
        self.db.acquire_ai_conversation_send_lock(
            other_id,
            owner="session-a",
            stale_after_seconds=900,
            now=NOW,
        )
        with self.assertRaises(AIConversationBusyError):
            self.db.acquire_ai_conversation_send_lock(
                other_id,
                owner="session-b",
                stale_after_seconds=900,
                now=NOW + timedelta(seconds=1),
            )
        self.db.release_ai_conversation_send_lock(other_id, owner="session-a")

    def test_explicit_send_calls_once_and_persists_one_assistant(self) -> None:
        conversation_id = self.create()
        result = send_conversation_message(
            self.db,
            conversation_id=conversation_id,
            content="How does the instability arise?",
            provider=self.provider,
            now=NOW,
        )
        messages = list_messages(self.db, conversation_id=conversation_id)
        self.assertEqual(len(self.provider.response_contexts), 1)
        self.assertEqual(self.provider.summary_contexts, [])
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(messages[-1].content, result.assistant_message.content)
        with self.assertRaises(ConversationError):
            retry_conversation_response(
                self.db,
                conversation_id=conversation_id,
                provider=self.provider,
            )
        self.assertEqual(len(self.provider.response_contexts), 1)

    def test_send_lease_covers_two_provider_timeouts_without_hidden_retry_window(
        self,
    ) -> None:
        conversation_id = self.create()
        self.provider.timeout_seconds = 600.0
        with patch.object(
            self.db,
            "acquire_ai_conversation_send_lock",
            wraps=self.db.acquire_ai_conversation_send_lock,
        ) as acquire:
            send_conversation_message(
                self.db,
                conversation_id=conversation_id,
                content="Bound the provider window",
                provider=self.provider,
                now=NOW,
            )
        self.assertEqual(acquire.call_args.kwargs["stale_after_seconds"], 1260.0)

    def test_provider_failure_leaves_one_clear_pending_turn_then_explicit_retry(self) -> None:
        conversation_id = self.create()
        self.provider.fail_response = True
        with self.assertRaises(AnalyzerError):
            send_conversation_message(
                self.db,
                conversation_id=conversation_id,
                content="Pending physics question",
                provider=self.provider,
                now=NOW,
            )
        pending = list_messages(self.db, conversation_id=conversation_id)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].role, AIConversationRole.USER)

        self.provider.fail_response = False
        retry_conversation_response(
            self.db,
            conversation_id=conversation_id,
            provider=self.provider,
            now=NOW + timedelta(seconds=1),
        )
        stored = list_messages(self.db, conversation_id=conversation_id)
        self.assertEqual([message.sequence_number for message in stored], [1, 2])
        self.assertEqual(len(self.provider.response_contexts), 2)

    def test_context_hierarchy_bounds_and_excludes_unrelated_state(self) -> None:
        conversation_id = self.create()
        other_id = self.create("Other conversation")
        append_message(
            self.db,
            conversation_id=other_id,
            role=AIConversationRole.USER,
            content="SECRET OTHER CONVERSATION",
        )
        save_note(
            self.db,
            article_id=self.article_id,
            note_text="Human note context " + ("n" * 200),
        )
        create_artifact(
            self.db,
            article_id=self.article_id,
            artifact_type=AIArtifactType.LIBRARY_SUMMARY,
            content="Preferred derived summary",
            provider="fixture",
            model_id="fixture",
            reasoning_effort=None,
            generator_version="fixture-v1",
            input_fingerprint="fixture",
            retention_class=AIArtifactRetentionClass.LIBRARY,
        )
        policy = ConversationContextPolicy(
            max_context_bytes=1400,
            max_title_bytes=80,
            max_abstract_bytes=300,
            max_note_bytes=80,
            max_preferred_summary_bytes=60,
            max_rolling_summary_bytes=200,
            max_live_conversation_bytes=400,
            max_current_user_message_bytes=200,
            max_assistant_message_bytes=300,
            max_compression_source_bytes=1000,
        )
        send_conversation_message(
            self.db,
            conversation_id=conversation_id,
            content="Current high-priority question",
            provider=self.provider,
            policy=policy,
        )
        payload = json.loads(self.provider.response_contexts[-1])
        self.assertIn("authoritative_paper_source", payload)
        self.assertIn("user_authored_context", payload)
        self.assertIn("derived_ai_context", payload)
        self.assertIn("live_conversation", payload)
        self.assertIn("Stored abstract", payload["authoritative_paper_source"]["abstract"])
        self.assertIn("Human note", payload["user_authored_context"]["my_notes"])
        self.assertEqual(
            payload["derived_ai_context"]["preferred_ai_summary"],
            "Preferred derived summary",
        )
        self.assertEqual(
            payload["live_conversation"][-1]["content"], "Current high-priority question"
        )
        self.assertNotIn("SECRET OTHER CONVERSATION", self.provider.response_contexts[-1])
        self.assertNotIn(self.article.abstract_url, self.provider.response_contexts[-1])
        self.assertNotIn(
            self.article.pdf_url or "PDF-URL-MISSING", self.provider.response_contexts[-1]
        )
        self.assertNotIn("history", self.provider.response_contexts[-1].casefold())
        self.assertLessEqual(
            len(self.provider.response_contexts[-1].encode("utf-8")),
            policy.max_context_bytes,
        )

    def test_overlong_current_message_is_rejected_before_persistence_or_provider(self) -> None:
        conversation_id = self.create()
        policy = ConversationContextPolicy(max_current_user_message_bytes=8)
        with self.assertRaises(ConversationContextError):
            send_conversation_message(
                self.db,
                conversation_id=conversation_id,
                content="é" * 5,
                provider=self.provider,
                policy=policy,
            )
        self.assertEqual(list_messages(self.db, conversation_id=conversation_id), [])
        self.assertEqual(self.provider.response_contexts, [])

    def test_compression_trigger_is_byte_driven_not_a_fixed_message_count(self) -> None:
        tiny_id = self.create("Many tiny turns")
        for _turn in range(10):
            append_message(
                self.db,
                conversation_id=tiny_id,
                role=AIConversationRole.USER,
                content="q",
            )
            append_message(
                self.db,
                conversation_id=tiny_id,
                role=AIConversationRole.ASSISTANT,
                content="a",
            )
        send_conversation_message(
            self.db,
            conversation_id=tiny_id,
            content="still bounded",
            provider=self.provider,
        )
        self.assertEqual(self.provider.summary_contexts, [])

        large_id = self.create("Few large turns")
        for _turn in range(2):
            append_message(
                self.db,
                conversation_id=large_id,
                role=AIConversationRole.USER,
                content="q" * 12_000,
            )
            append_message(
                self.db,
                conversation_id=large_id,
                role=AIConversationRole.ASSISTANT,
                content="a" * 12_000,
            )
        send_conversation_message(
            self.db,
            conversation_id=large_id,
            content="trigger by bytes",
            provider=self.provider,
        )
        self.assertEqual(len(self.provider.summary_contexts), 1)

    def test_threshold_compresses_once_keeps_full_transcript_and_exact_boundary(self) -> None:
        conversation_id = self.create()
        for turn in range(3):
            append_message(
                self.db,
                conversation_id=conversation_id,
                role=AIConversationRole.USER,
                content=f"Question {turn}: " + ("q" * 110),
            )
            append_message(
                self.db,
                conversation_id=conversation_id,
                role=AIConversationRole.ASSISTANT,
                content=f"Answer {turn}: " + ("a" * 110),
            )
        before = list_messages(self.db, conversation_id=conversation_id)
        policy = _compression_policy()
        result = send_conversation_message(
            self.db,
            conversation_id=conversation_id,
            content="Current question after long context",
            provider=self.provider,
            policy=policy,
            now=NOW,
        )

        after = list_messages(self.db, conversation_id=conversation_id)
        conversation = self.db.get_ai_conversation(conversation_id)
        assert conversation is not None and conversation.rolling_summary_artifact_id is not None
        artifact = self.db.get_ai_artifact(conversation.rolling_summary_artifact_id)
        assert artifact is not None
        boundary = rolling_summary_boundary(conversation_id=conversation_id, artifact=artifact)
        self.assertTrue(result.compression_provider_called)
        self.assertEqual(len(self.provider.summary_contexts), 1)
        self.assertEqual(len(self.provider.response_contexts), 1)
        self.assertGreater(boundary, 0)
        self.assertEqual(after[: len(before)], before)
        self.assertEqual(len(after), len(before) + 2)
        self.assertEqual(result.context.composition.summarized_through_sequence, boundary)
        response_payload = json.loads(self.provider.response_contexts[-1])
        recent_sequences = [row["sequence_number"] for row in response_payload["live_conversation"]]
        self.assertTrue(all(sequence > boundary for sequence in recent_sequences))

    def test_failed_compression_keeps_transcript_and_does_not_advance_pointer(self) -> None:
        conversation_id = self.create()
        for _turn in range(3):
            append_message(
                self.db,
                conversation_id=conversation_id,
                role=AIConversationRole.USER,
                content="question " + ("q" * 120),
            )
            append_message(
                self.db,
                conversation_id=conversation_id,
                role=AIConversationRole.ASSISTANT,
                content="answer " + ("a" * 120),
            )
        self.provider.fail_summary = True
        with self.assertRaises(AnalyzerError):
            send_conversation_message(
                self.db,
                conversation_id=conversation_id,
                content="pending after compression failure",
                provider=self.provider,
                policy=_compression_policy(),
            )
        conversation = self.db.get_ai_conversation(conversation_id)
        assert conversation is not None
        self.assertIsNone(conversation.rolling_summary_artifact_id)
        messages = list_messages(self.db, conversation_id=conversation_id)
        self.assertEqual(len(messages), 7)
        self.assertEqual(messages[-1].role, AIConversationRole.USER)
        self.assertEqual(
            self.db.list_ai_artifacts(
                self.article_id,
                artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
            ),
            [],
        )

    def test_atomic_summary_replacement_demotes_old_only_after_success_and_gc_protects_live(
        self,
    ) -> None:
        conversation_id = self.create()
        append_message(
            self.db,
            conversation_id=conversation_id,
            role=AIConversationRole.USER,
            content="old question",
        )
        append_message(
            self.db,
            conversation_id=conversation_id,
            role=AIConversationRole.ASSISTANT,
            content="old answer",
        )
        old = self.db.replace_ai_conversation_rolling_summary(
            conversation_id=conversation_id,
            content="old rolling state",
            provenance=AIArtifactProvenance(
                provider="fixture",
                model_id="fixture",
                reasoning_effort=None,
                generator_version="fixture-summary-v1",
                input_fingerprint=(
                    f"conversation-summary-boundary-v1:conversation={conversation_id}:"
                    f"through=2:sha256={'0' * 64}"
                ),
            ),
            summarized_through_sequence=2,
            created_at=NOW,
        )
        assert old.id is not None
        with (
            patch(
                "research_digest.db._insert_ai_artifact",
                side_effect=sqlite3.Error("disk"),
            ),
            self.assertRaises(sqlite3.Error),
        ):
            self.db.replace_ai_conversation_rolling_summary(
                conversation_id=conversation_id,
                content="new rolling state",
                provenance=AIArtifactProvenance(
                    provider="fixture",
                    model_id="fixture",
                    reasoning_effort=None,
                    generator_version="fixture-summary-v2",
                    input_fingerprint=(
                        f"conversation-summary-boundary-v1:conversation={conversation_id}:"
                        f"through=2:sha256={'1' * 64}"
                    ),
                ),
                summarized_through_sequence=2,
                created_at=NOW + timedelta(seconds=1),
            )
        unchanged = self.db.get_ai_conversation(conversation_id)
        assert unchanged is not None
        self.assertEqual(unchanged.rolling_summary_artifact_id, old.id)
        self.assertEqual(self.db.get_ai_artifact(old.id).retention_class, "LIBRARY")  # type: ignore[union-attr]

        new = self.db.replace_ai_conversation_rolling_summary(
            conversation_id=conversation_id,
            content="new rolling state",
            provenance=AIArtifactProvenance(
                provider="fixture",
                model_id="fixture",
                reasoning_effort=None,
                generator_version="fixture-summary-v2",
                input_fingerprint=(
                    f"conversation-summary-boundary-v1:conversation={conversation_id}:"
                    f"through=2:sha256={'2' * 64}"
                ),
            ),
            summarized_through_sequence=2,
            created_at=NOW + timedelta(seconds=2),
        )
        assert new.id is not None
        self.assertEqual(self.db.get_ai_artifact(old.id).retention_class, "TEMPORARY")  # type: ignore[union-attr]
        self.db.set_ai_artifact_retention(
            old.id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            effective_at=NOW - timedelta(days=100),
        )
        self.db.set_ai_artifact_retention(
            new.id,
            retention_class=AIArtifactRetentionClass.TEMPORARY,
            effective_at=NOW - timedelta(days=100),
        )
        self.assertEqual(self.db.collect_expired_ai_artifacts(now=NOW), 1)
        self.assertIsNotNone(self.db.get_ai_artifact(new.id))

    def test_rolling_summary_boundary_argument_must_match_structured_provenance(
        self,
    ) -> None:
        conversation_id = self.create()
        for role, content in (
            (AIConversationRole.USER, "question one"),
            (AIConversationRole.ASSISTANT, "answer one"),
            (AIConversationRole.USER, "question two"),
            (AIConversationRole.ASSISTANT, "answer two"),
        ):
            append_message(
                self.db,
                conversation_id=conversation_id,
                role=role,
                content=content,
            )
        before = self.db.list_ai_artifacts(
            self.article_id,
            artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.db.replace_ai_conversation_rolling_summary(
                conversation_id=conversation_id,
                content="Only the first turn is represented.",
                provenance=AIArtifactProvenance(
                    provider="fixture",
                    model_id="fixture",
                    reasoning_effort=None,
                    generator_version="fixture-summary-v1",
                    input_fingerprint=(
                        f"conversation-summary-boundary-v1:conversation={conversation_id}:"
                        f"through=4:sha256={'0' * 64}"
                    ),
                ),
                summarized_through_sequence=2,
                created_at=NOW,
            )
        conversation = self.db.get_ai_conversation(conversation_id)
        assert conversation is not None
        self.assertIsNone(conversation.rolling_summary_artifact_id)
        self.assertEqual(
            self.db.list_ai_artifacts(
                self.article_id,
                artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
            ),
            before,
        )

    def test_explicit_note_promotion_is_zero_ai_and_does_not_mutate_transcript(self) -> None:
        conversation_id = self.create()
        assistant = append_message(
            self.db,
            conversation_id=conversation_id,
            role=AIConversationRole.ASSISTANT,
            content="AI response source remains in the transcript.",
        )
        assert assistant.id is not None
        save_note(self.db, article_id=self.article_id, note_text="Existing human note.")
        before = list_messages(self.db, conversation_id=conversation_id)
        promoted = promote_assistant_takeaway_to_note(
            self.db,
            article_id=self.article_id,
            message_id=assistant.id,
            approved_text="Human-approved edited takeaway.",
        )
        self.assertEqual(
            promoted.note_text,
            "Existing human note.\n\nHuman-approved edited takeaway.",
        )
        self.assertEqual(list_messages(self.db, conversation_id=conversation_id), before)
        self.assertEqual(self.provider.response_contexts, [])
        self.assertEqual(self.provider.summary_contexts, [])

    def test_reads_inspection_refresh_equivalent_and_export_are_zero_ai(self) -> None:
        conversation_id = self.create("Persistent")
        append_message(
            self.db,
            conversation_id=conversation_id,
            role=AIConversationRole.USER,
            content="Stored question",
        )
        first = list_messages(self.db, conversation_id=conversation_id)
        second = list_messages(self.db, conversation_id=conversation_id)
        overviews = list_conversation_overviews(self.db, article_id=self.article_id)
        context = inspect_conversation_context(self.db, conversation_id=conversation_id)
        payload = export_user_data(db_path=self.db.path)
        self.assertEqual(first, second)
        self.assertEqual(overviews[0].message_count, 1)
        self.assertEqual(context.composition.recent_message_count, 1)
        self.assertEqual(payload["schema_version"], 20)
        self.assertEqual(len(payload["ai_conversations"]), 1)  # type: ignore[arg-type]
        self.assertEqual(len(payload["ai_conversation_messages"]), 1)  # type: ignore[arg-type]
        self.assertEqual(self.provider.response_contexts, [])
        self.assertEqual(self.provider.summary_contexts, [])

    def test_schema20_and_normalized_pointer_storage_remain_frozen(self) -> None:
        self.assertEqual(CURRENT_SCHEMA_VERSION, 20)
        with sqlite3.connect(self.db.path) as conn:
            conversation_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(ai_conversations)")
            }
            message_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(ai_conversation_messages)")
            }
        forbidden = {"abstract", "authors", "paper_title", "summary", "note"}
        self.assertTrue(forbidden.isdisjoint(conversation_columns))
        self.assertTrue(forbidden.isdisjoint(message_columns))
        self.assertIn("rolling_summary_artifact_id", conversation_columns)


def _article(source_id: str) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_id,
        title="Black Strings and p-Branes are Unstable",
        authors=["R. Gregory", "R. Laflamme"],
        abstract="Stored abstract: a long-wavelength black-string instability is identified.",
        categories=["hep-th", "gr-qc"],
        published_at=datetime(1993, 1, 1, tzinfo=UTC),
        updated_at=datetime(1993, 1, 1, tzinfo=UTC),
        abstract_url="https://arxiv.org/abs/2608.l1d",
        pdf_url="https://arxiv.org/pdf/2608.l1d",
    )


def _compression_policy() -> ConversationContextPolicy:
    return ConversationContextPolicy(
        max_context_bytes=1200,
        max_title_bytes=100,
        max_abstract_bytes=250,
        max_note_bytes=80,
        max_preferred_summary_bytes=80,
        max_rolling_summary_bytes=180,
        max_live_conversation_bytes=520,
        max_current_user_message_bytes=180,
        max_assistant_message_bytes=300,
        max_compression_source_bytes=1600,
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    unittest.main()
