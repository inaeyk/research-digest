from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from research_digest.ai_artifacts import (
    create_digest_summary_artifact,
    resolve_preferred_library_summary,
)
from research_digest.ai_providers import GeneratedAIText
from research_digest.collections import save_note
from research_digest.conversations import (
    create_conversation,
    list_conversation_overviews,
    list_messages,
    promote_assistant_takeaway_to_note,
    send_conversation_message,
)
from research_digest.db import APP_RUN_COMPLETED, Database
from research_digest.history import get_run_snapshot, list_run_history
from research_digest.library import (
    get_library_item,
    save_article,
    save_article_with_personal_interest,
    set_interest_rating,
    set_reading_state,
    unsave_article,
)
from research_digest.library_summaries import (
    generate_library_summary,
    library_summary_input_fingerprint,
)
from research_digest.models import (
    AIConversationRole,
    Article,
    DateSelection,
    LibrarySummarySource,
    ReadingState,
    RunOrigin,
    profile_semantic_fingerprint,
)


class _WorkflowSummaryProvider:
    provider = "workflow-fake"
    model_id = "workflow-model"
    reasoning_effort: str | None = "low"
    generator_version = "workflow-library-summary-v1"

    def __init__(self, calls: dict[str, int]) -> None:
        self.calls = calls

    def generate_summary(self, *, article: Article, context: str) -> GeneratedAIText:
        del article
        self.calls["library_summary"] += 1
        return GeneratedAIText(
            content="Explicit fake Library summary.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.generator_version,
            input_fingerprint=library_summary_input_fingerprint(context),
        )


class _WorkflowConversationProvider:
    provider = "workflow-fake"
    model_id = "workflow-model"
    reasoning_effort: str | None = "low"
    timeout_seconds = 5.0
    response_generator_version = "workflow-response-v1"
    summary_generator_version = "workflow-compression-v1"

    def __init__(self, calls: dict[str, int]) -> None:
        self.calls = calls

    def respond(self, *, article: Article, context: str) -> GeneratedAIText:
        del article
        self.calls["discussion_response"] += 1
        return GeneratedAIText(
            content="A concise fake discussion takeaway.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.response_generator_version,
            input_fingerprint=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        )

    def summarize_conversation(
        self,
        *,
        article: Article,
        context: str,
    ) -> GeneratedAIText:
        del article
        self.calls["rolling_compression"] += 1
        return GeneratedAIText(
            content="Compressed fake state.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.summary_generator_version,
            input_fingerprint=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        )


class ReleaseRepairIntegratedWorkflowTests(unittest.TestCase):
    def test_today_library_history_unsave_resave_restart_has_exact_ai_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "integrated.sqlite3"
            db = Database(path)
            profile = db.create_interest_profile(
                name="Integrated gravity",
                description="Higher-dimensional gravity.",
                relevance_threshold=0.6,
            )
            article, _ = db.upsert_article(
                Article(
                    id=None,
                    source="arxiv",
                    source_article_id="2608.release-repair",
                    title="Integrated release-repair paper",
                    authors=["Ada Researcher"],
                    abstract="A deterministic source abstract.",
                    categories=["hep-th"],
                    published_at=datetime(2026, 8, 30, tzinfo=UTC),
                    updated_at=datetime(2026, 8, 30, tzinfo=UTC),
                    abstract_url="https://arxiv.org/abs/2608.release-repair",
                    pdf_url=None,
                )
            )
            assert article.id is not None and profile.id is not None
            fingerprint = profile_semantic_fingerprint(profile)
            run_id = db.create_app_run(
                profile_id=profile.id,
                profile_fingerprint=fingerprint,
                source_name="arxiv",
                run_origin=RunOrigin.MANUAL,
                date_selection=DateSelection.single_date(datetime(2026, 8, 30).date()),
            )
            db.finish_app_run(
                run_id,
                status=APP_RUN_COMPLETED,
                retrieved_count=1,
                stored_count=1,
                preselected_count=1,
                skipped_analysis_count=0,
                analyzed_count=1,
                relevant_count=1,
                requested_source_dates=("2026-08-30",),
                covered_source_dates=("2026-08-30",),
            )
            db.save_run_snapshot(
                run_id=run_id,
                snapshot_json=json.dumps(
                    {
                        "run_id": run_id,
                        "items": [
                            {
                                "source": article.source,
                                "source_article_id": article.source_article_id,
                                "summary": "Existing digest summary.",
                            }
                        ],
                    },
                    sort_keys=True,
                ),
            )
            create_digest_summary_artifact(
                db,
                article_id=article.id,
                content="Existing digest summary.",
                provider="workflow-digest-fake",
                model_id="workflow-digest-model",
                reasoning_effort=None,
                generator_version="workflow-digest-v1",
                input_fingerprint="workflow-digest-fingerprint",
            )

            calls = {
                "library_summary": 0,
                "discussion_response": 0,
                "rolling_compression": 0,
            }
            expected_zero = dict(calls)

            # Today browsing and saving are local-only.
            self.assertIsNotNone(get_run_snapshot(db, run_id=run_id))
            save_article_with_personal_interest(
                db,
                article_id=article.id,
                profile=profile,
                profile_fingerprint_value=fingerprint,
            )
            self.assertEqual(calls, expected_zero)

            # Library browsing and human edits are local-only.
            self.assertIsNotNone(get_library_item(db, article_id=article.id))
            set_interest_rating(db, article_id=article.id, interest_rating=5)
            set_reading_state(db, article_id=article.id, reading_state=ReadingState.SKIMMED)
            save_note(db, article_id=article.id, note_text="Initial human note.")
            existing = resolve_preferred_library_summary(db, article_id=article.id)
            assert existing is not None
            self.assertEqual(existing.source, LibrarySummarySource.DIGEST_ARTIFACT)
            self.assertEqual(calls, expected_zero)

            # The first Library summary is one explicit fake-provider action.
            summary_provider = _WorkflowSummaryProvider(calls)
            generated = generate_library_summary(
                db,
                article_id=article.id,
                provider=summary_provider,
                regenerate=True,
            )
            self.assertTrue(generated.provider_called)
            self.assertEqual(calls["library_summary"], 1)

            # Creating/opening a discussion is local-only; Send is one provider call.
            conversation = create_conversation(
                db,
                article_id=article.id,
                title="Integrated discussion",
                provider="workflow-fake",
                model_id="workflow-model",
            )
            assert conversation.id is not None
            self.assertEqual(len(list_conversation_overviews(db, article_id=article.id)), 1)
            self.assertEqual(calls["discussion_response"], 0)
            conversation_provider = _WorkflowConversationProvider(calls)
            turn = send_conversation_message(
                db,
                conversation_id=conversation.id,
                content="What is the main implication?",
                provider=conversation_provider,
            )
            self.assertEqual(calls["discussion_response"], 1)
            self.assertEqual(calls["rolling_compression"], 0)
            self.assertFalse(turn.compression_provider_called)

            # Promotion, History, unsave, and resave are all local-only.
            assert turn.assistant_message.id is not None
            promote_assistant_takeaway_to_note(
                db,
                article_id=article.id,
                message_id=turn.assistant_message.id,
                approved_text="Reviewed promoted takeaway.",
            )
            self.assertEqual(len(list_run_history(db)), 1)
            unsave_article(db, article.id)
            save_article(db, article.id)
            expected_calls = {
                "library_summary": 1,
                "discussion_response": 1,
                "rolling_compression": 0,
            }
            self.assertEqual(calls, expected_calls)
            db.close()

            reopened = Database(path)
            try:
                entry = reopened.get_library_entry(article.id)
                assert entry is not None
                self.assertEqual(entry.interest_rating, 5)
                self.assertEqual(entry.reading_state, ReadingState.SKIMMED)
                note = reopened.get_library_note(article.id)
                assert note is not None
                self.assertEqual(
                    note.note_text,
                    "Initial human note.\n\nReviewed promoted takeaway.",
                )
                preferred = resolve_preferred_library_summary(reopened, article_id=article.id)
                assert preferred is not None
                self.assertEqual(preferred.source, LibrarySummarySource.LIBRARY_ARTIFACT)
                overviews = list_conversation_overviews(reopened, article_id=article.id)
                self.assertEqual(len(overviews), 1)
                assert overviews[0].conversation.id is not None
                messages = list_messages(
                    reopened,
                    conversation_id=overviews[0].conversation.id,
                )
                self.assertEqual(
                    [message.role for message in messages],
                    [AIConversationRole.USER, AIConversationRole.ASSISTANT],
                )
                self.assertIsNotNone(get_run_snapshot(reopened, run_id=run_id))
                self.assertEqual(calls, expected_calls)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
