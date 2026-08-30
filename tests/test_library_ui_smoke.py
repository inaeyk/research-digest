from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from streamlit.testing.v1 import AppTest

from research_digest.ai_artifacts import create_artifact
from research_digest.ai_providers import GeneratedAIText
from research_digest.collections import (
    add_article_to_collection,
    create_collection,
    save_note,
)
from research_digest.conversations import (
    append_message,
    create_conversation,
    list_conversation_overviews,
    list_messages,
)
from research_digest.db import Database
from research_digest.library import (
    save_article,
    set_interest_rating,
    set_reading_state,
)
from research_digest.library_summaries import library_summary_input_fingerprint
from research_digest.models import (
    AIArtifactRetentionClass,
    AIArtifactType,
    AIConversationRole,
    AnalysisResult,
    Article,
    ReadingState,
    TagOrigin,
)
from research_digest.tags import add_user_tag


def _article(
    source_article_id: str = "2608.library-smoke",
    *,
    title: str = "Library smoke paper",
    published_at: datetime | None = None,
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=[
            "Ada Lovelace",
            "Grace Hopper",
            "Emmy Noether",
            "Sofia Kovalevskaya",
            "Maryam Mirzakhani",
            "Katherine Johnson",
            "Chien-Shiung Wu",
        ],
        abstract=f"Stored source abstract for {title}.",
        categories=["hep-th", "gr-qc"],
        published_at=published_at or datetime(2026, 8, 14, 16, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 16, 10, tzinfo=UTC),
        abstract_url=f"https://arxiv.org/abs/{source_article_id}",
        pdf_url=f"https://arxiv.org/pdf/{source_article_id}",
    )


def _library_app(config_dir: str, data_dir: str) -> None:
    import os

    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = config_dir
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = data_dir

    import streamlit as st

    st.cache_resource.clear()
    from research_digest.ui.pages.library import render

    render()


class _CountingLibrarySummaryProvider:
    provider = "app-test-summary"
    model_id = "app-test-model"
    reasoning_effort: str | None = "low"
    generator_version = "app-test-summary-v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def generate_summary(
        self,
        *,
        article: Article,
        context: str,
    ) -> GeneratedAIText:
        del article
        self.calls += 1
        if self.fail:
            raise RuntimeError("private /home/researcher sk-secret-summary-token")
        return GeneratedAIText(
            content=f"Explicit generated summary {self.calls}.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.generator_version,
            input_fingerprint=library_summary_input_fingerprint(context),
        )


class _CountingConversationProvider:
    provider = "app-test-conversation"
    model_id = "app-test-research-model"
    reasoning_effort: str | None = "high"
    response_generator_version = "app-test-conversation-v1"
    summary_generator_version = "app-test-conversation-summary-v1"
    timeout_seconds = 5.0

    def __init__(self, *, fail: bool = False) -> None:
        self.response_calls = 0
        self.summary_calls = 0
        self.fail = fail

    def respond(self, *, article: Article, context: str) -> GeneratedAIText:
        del article
        self.response_calls += 1
        if self.fail:
            raise RuntimeError("private /home/researcher sk-secret-conversation-token")
        return GeneratedAIText(
            content=f"Persisted research answer {self.response_calls}.",
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
        self.summary_calls += 1
        return GeneratedAIText(
            content="Bounded rolling research state.",
            provider=self.provider,
            model_id=self.model_id,
            reasoning_effort=self.reasoning_effort,
            generator_version=self.summary_generator_version,
            input_fingerprint=hashlib.sha256(context.encode("utf-8")).hexdigest(),
        )


class LibraryUiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.config_dir = self.root / "config"
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True)
        self.db = Database(self.data_dir / "research_digest.sqlite3")
        article, _ = self.db.upsert_article(_article())
        assert article.id is not None
        self.article_id = article.id
        save_article(self.db, self.article_id)
        save_note(
            self.db,
            article_id=self.article_id,
            note_text="Human note remains authoritative and separate.",
        )
        self.primary_collection = create_collection(self.db, name="Core papers")
        self.secondary_collection = create_collection(self.db, name="Follow-up")
        assert self.primary_collection.id is not None
        add_article_to_collection(
            self.db,
            collection_id=self.primary_collection.id,
            article_id=self.article_id,
        )
        add_user_tag(self.db, article_id=self.article_id, tag="gravity")
        self.db.upsert_library_tag_assignment(
            article_id=self.article_id,
            normalized_name="foundational",
            display_name="Foundational",
            origin=TagOrigin.AI,
            ai_provenance={"provider": "fixture", "generator_version": "fixture-v1"},
        )
        create_artifact(
            self.db,
            article_id=self.article_id,
            artifact_type=AIArtifactType.LIBRARY_SUMMARY,
            content="Stored preferred AI summary for display only.",
            provider="fixture-provider",
            model_id="fixture-model",
            reasoning_effort="low",
            generator_version="fixture-summary-v1",
            input_fingerprint="sha256:fixture-summary",
            retention_class=AIArtifactRetentionClass.LIBRARY,
            created_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        )
        conversation = create_conversation(
            self.db,
            article_id=self.article_id,
            title="Stored discussion",
            provider="fixture-provider",
            model_id="fixture-model",
        )
        assert conversation.id is not None
        append_message(
            self.db,
            conversation_id=conversation.id,
            role=AIConversationRole.USER,
            content="What is the instability mechanism?",
        )
        append_message(
            self.db,
            conversation_id=conversation.id,
            role=AIConversationRole.ASSISTANT,
            content="The stored answer remains local and read-only.",
        )
        second, _ = self.db.upsert_article(
            _article(
                "2608.library-second",
                title="Second saved paper",
                published_at=datetime(1993, 1, 1, tzinfo=UTC),
            )
        )
        assert second.id is not None
        self.second_article_id = second.id
        save_article(self.db, second.id)
        set_interest_rating(self.db, article_id=second.id, interest_rating=2)
        set_reading_state(
            self.db,
            article_id=second.id,
            reading_state=ReadingState.READ,
        )
        add_user_tag(self.db, article_id=second.id, tag="comparison")

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_dense_list_shows_scan_fields_without_expanding_paper_content(self) -> None:
        at = self.run_app()

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual([str(value.value) for value in at.title], ["Library"])
        self.assert_button_present(at, "Library smoke paper")
        self.assert_button_present(at, "Second saved paper")
        self.assert_text_present(at, "Ada Lovelace, Grace Hopper")
        self.assert_text_present(at, "+2 more · 2026")
        self.assert_text_present(at, "Interest: Unrated")
        self.assert_text_present(at, "Reading: Not set")
        self.assert_text_present(at, "Collections: Core papers")
        self.assert_text_present(at, "Tags: gravity · Foundational (AI)")
        self.assert_text_present(at, "My note: Human note remains authoritative")
        self.assert_text_absent(at, "Stored source abstract for Library smoke paper.")
        self.assert_text_absent(at, "Stored preferred AI summary for display only.")

    def test_detail_hierarchy_summary_discussion_links_and_long_authors(self) -> None:
        at = self.run_app()
        self.click_button(at, "Library smoke paper").run()

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual([str(value.value) for value in at.title], ["Library smoke paper"])
        self.assertEqual(
            [str(value.value) for value in at.subheader],
            [
                "My Library state",
                "Abstract",
                "My Notes",
                "AI Summary",
                "AI Discussions",
                "Bibliography and links",
                "Research Atlas",
            ],
        )
        self.assert_text_present(at, "Human note remains authoritative and separate.")
        self.assert_text_present(at, "Stored source abstract for Library smoke paper.")
        self.assert_text_present(at, "Stored preferred AI summary for display only.")
        self.assert_text_present(at, "Library summary · 2026-08-20")
        self.assert_button_present(at, "Stored discussion")
        self.assert_text_present(at, "2 messages · updated")
        self.assert_text_present(at, "Published Aug 14, 2026")
        self.assert_text_present(at, "arXiv:2608.library-smoke")
        self.assertEqual(
            {str(button.label) for button in at.get("link_button")},
            {"Source page", "PDF"},
        )
        self.assertIn("Show all authors", [str(status.label) for status in at.status])
        self.assert_button_present(at, "Regenerate summary")
        self.assert_button_absent(at, "New discussion")
        self.assert_button_present(at, "Create discussion")
        self.click_button(at, "Stored discussion").run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "What is the instability mechanism?")
        self.assert_text_present(at, "The stored answer remains local and read-only.")
        self.text_area(at, "Message")

    def test_detail_without_summary_or_discussion_is_explicit(self) -> None:
        with mock.patch(
            "research_digest.ui.pages.library.get_library_summary_provider",
            side_effect=AssertionError("rendering a missing summary invoked AI"),
        ) as provider_factory:
            at = self.run_app()
            self.click_button(at, "Second saved paper").run()

        provider_factory.assert_not_called()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "No AI summary generated.")
        self.assert_text_present(at, "No discussions yet.")
        self.assert_button_present(at, "Generate Library summary")
        self.assert_button_absent(at, "Ask AI")
        self.assert_button_present(at, "Create discussion")

    def test_digest_fallback_discloses_first_library_summary_generation(self) -> None:
        create_artifact(
            self.db,
            article_id=self.second_article_id,
            artifact_type=AIArtifactType.DIGEST_SUMMARY,
            content="Existing digest summary remains reusable display prose.",
            provider="digest-fixture",
            model_id="digest-model",
            reasoning_effort=None,
            generator_version="digest-summary-v1",
            input_fingerprint="sha256:digest-fixture",
            retention_class=AIArtifactRetentionClass.LIBRARY,
        )
        with mock.patch(
            "research_digest.ui.pages.library.get_library_summary_provider",
            side_effect=AssertionError("displaying a digest fallback invoked AI"),
        ) as provider_factory:
            at = self.run_app()
            self.click_button(at, "Second saved paper").run()

        provider_factory.assert_not_called()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Existing digest summary remains reusable display prose.")
        self.assert_button_present(at, "Generate Library summary")
        self.assert_button_absent(at, "Regenerate summary")

        provider = _CountingLibrarySummaryProvider()
        with mock.patch(
            "research_digest.ui.pages.library.get_library_summary_provider",
            return_value=(provider, None),
        ):
            self.click_button(at, "Generate Library summary").run()

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual(provider.calls, 1)
        self.assert_text_present(at, "Explicit generated summary 1.")
        self.assert_button_present(at, "Regenerate summary")
        artifacts = self.db.list_ai_artifacts(self.second_article_id)
        self.assertEqual(
            {artifact.artifact_type for artifact in artifacts},
            {AIArtifactType.DIGEST_SUMMARY, AIArtifactType.LIBRARY_SUMMARY},
        )

    def test_grandfathered_digest_fallback_uses_generate_library_wording(self) -> None:
        profile = self.db.create_interest_profile(
            name="Legacy summary fixture",
            description="Preserve grandfathered summary display.",
            relevance_threshold=0.5,
        )
        assert profile.id is not None
        self.db.upsert_analysis(
            article_id=self.second_article_id,
            profile_id=profile.id,
            profile_fingerprint="legacy-summary-profile-fingerprint",
            analysis=AnalysisResult(
                relevance_score=0.8,
                relevance_reason="Legacy relevance reason.",
                matched_topics=["legacy"],
                summary="Grandfathered inline digest summary.",
                why_it_matters="Legacy why-it-matters.",
                reading_priority="HIGH",
            ),
        )
        with mock.patch(
            "research_digest.ui.pages.library.get_library_summary_provider",
            side_effect=AssertionError("displaying a legacy digest summary invoked AI"),
        ) as provider_factory:
            at = self.run_app()
            self.click_button(at, "Second saved paper").run()

        provider_factory.assert_not_called()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Grandfathered inline digest summary.")
        self.assert_button_present(at, "Generate Library summary")
        self.assert_button_absent(at, "Regenerate summary")

    def test_explicit_generate_calls_once_and_refresh_does_not_repeat(self) -> None:
        provider = _CountingLibrarySummaryProvider()
        with mock.patch(
            "research_digest.ui.pages.library.get_library_summary_provider",
            return_value=(provider, None),
        ) as provider_factory:
            at = self.run_app()
            self.click_button(at, "Second saved paper").run()
            self.click_button(at, "Generate Library summary").run()

            self.assert_no_streamlit_exceptions(at)
            self.assertEqual(provider.calls, 1)
            self.assert_text_present(at, "Explicit generated summary 1.")
            self.assert_button_present(at, "Regenerate summary")
            at.run()
            self.assertEqual(provider.calls, 1)

        provider_factory.assert_called_once()
        artifacts = self.db.list_ai_artifacts(self.second_article_id)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].content, "Explicit generated summary 1.")
        self.assertIsNone(self.db.get_library_note(self.second_article_id))

    def test_provider_failure_is_sanitized_and_preserves_no_summary_state(self) -> None:
        provider = _CountingLibrarySummaryProvider(fail=True)
        with mock.patch(
            "research_digest.ui.pages.library.get_library_summary_provider",
            return_value=(provider, None),
        ):
            at = self.run_app()
            self.click_button(at, "Second saved paper").run()
            self.click_button(at, "Generate Library summary").run()

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual(provider.calls, 1)
        errors = [str(element.value) for element in at.error]
        self.assertTrue(any("Summary generation failed" in value for value in errors))
        self.assertFalse(any("/home/" in value or "sk-secret" in value for value in errors))
        self.assertEqual(self.db.list_ai_artifacts(self.second_article_id), [])

    def test_detail_edits_persist_without_crossing_note_or_provenance_boundaries(self) -> None:
        at = self.run_app()
        self.click_button(at, "Library smoke paper").run()

        self.selectbox(at, "Interest").select(4).run()
        self.selectbox(at, "Reading state").select(ReadingState.UNREAD).run()
        self.multiselect(at, "Collections").select(self.secondary_collection).run()
        self.multiselect(at, "User tags").select("comparison").run()
        self.text_area(at, "Note").set_value("Edited human note only.")
        self.click_button(at, "Save note").run()

        self.assert_no_streamlit_exceptions(at)
        entry = self.db.get_library_entry(self.article_id)
        assert entry is not None
        self.assertEqual(entry.interest_rating, 4)
        self.assertEqual(entry.reading_state, ReadingState.UNREAD)
        self.assertEqual(
            {
                collection.name
                for collection in self.db.list_library_collections_for_article(self.article_id)
            },
            {"Core papers", "Follow-up"},
        )
        assignments = self.db.list_library_tag_assignments(self.article_id)
        self.assertEqual(
            {(assignment.tag.display_name, assignment.origin.value) for assignment in assignments},
            {
                ("comparison", "USER"),
                ("gravity", "USER"),
                ("Foundational", "AI"),
            },
        )
        note = self.db.get_library_note(self.article_id)
        assert note is not None
        self.assertEqual(note.note_text, "Edited human note only.")
        self.assert_text_present(at, "Stored preferred AI summary for display only.")

    def test_filter_state_survives_detail_navigation(self) -> None:
        set_interest_rating(self.db, article_id=self.article_id, interest_rating=4)
        set_reading_state(
            self.db,
            article_id=self.article_id,
            reading_state=ReadingState.UNREAD,
        )
        at = self.run_app()
        self.text_input(at, "Search").set_value("Library smoke")
        self.selectbox(at, "Interest").select("at_least_4")
        self.selectbox(at, "Reading").select("unread")
        self.selectbox(at, "Collection").select(self.primary_collection)
        gravity_tag = next(
            tag for tag in self.db.list_library_tags() if tag.normalized_name == "gravity"
        )
        self.selectbox(at, "Tag").select(gravity_tag)
        self.selectbox(at, "Sort").select("interest_desc")
        self.click_button(at, "Apply").run()

        self.assert_button_present(at, "Library smoke paper")
        self.assert_button_absent(at, "Second saved paper")
        self.click_button(at, "Library smoke paper").run()
        self.click_button(at, "Back to Library").run()

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual(self.text_input(at, "Search").value, "Library smoke")
        self.assertEqual(self.selectbox(at, "Interest").value, "at_least_4")
        self.assertEqual(self.selectbox(at, "Reading").value, "unread")
        self.assertEqual(self.selectbox(at, "Sort").value, "interest_desc")
        self.assert_button_present(at, "Library smoke paper")
        self.assert_button_absent(at, "Second saved paper")

    def test_all_l1b_render_navigation_and_edit_paths_are_zero_ai(self) -> None:
        forbidden = AssertionError("Library L1-B must not reach an AI execution boundary")
        with (
            mock.patch(
                "research_digest.ui.common.get_analyzer",
                side_effect=forbidden,
            ) as analyzer,
            mock.patch(
                "research_digest.ui.common.get_ai_tag_generator",
                side_effect=forbidden,
            ) as tag_generator,
            mock.patch(
                "research_digest.ui.common.get_connection_generator",
                side_effect=forbidden,
            ) as connection_generator,
            mock.patch(
                "research_digest.ui.common.get_library_context_generator",
                side_effect=forbidden,
            ) as context_generator,
            mock.patch(
                "research_digest.analysis.providers.build_configured_analyzer",
                side_effect=forbidden,
            ) as analyzer_factory,
            mock.patch(
                "research_digest.tags.generate_ai_tags_for_saved_article",
                side_effect=forbidden,
            ) as tag_execution,
            mock.patch(
                "research_digest.connections.generate_connections_for_saved_article",
                side_effect=forbidden,
            ) as connection_execution,
            mock.patch(
                "research_digest.library_context.generate_library_context_for_item",
                side_effect=forbidden,
            ) as context_execution,
            mock.patch(
                "research_digest.ui.pages.library.get_library_summary_provider",
                side_effect=forbidden,
            ) as summary_provider,
            mock.patch(
                "research_digest.ui.pages.library.get_research_conversation_provider",
                side_effect=forbidden,
            ) as conversation_provider,
        ):
            at = self.run_app()
            self.text_input(at, "Search").set_value("Library")
            self.selectbox(at, "Sort").select("published_newest")
            self.click_button(at, "Apply").run()
            self.click_button(at, "Library smoke paper").run()
            self.selectbox(at, "Interest").select(3).run()
            self.selectbox(at, "Reading state").select(ReadingState.SKIMMED).run()
            self.multiselect(at, "Collections").select(self.secondary_collection).run()
            self.multiselect(at, "User tags").select("comparison").run()
            self.text_area(at, "Note").set_value("AI-free note edit.")
            self.click_button(at, "Save note").run()
            self.click_button(at, "Stored discussion").run()

        self.assert_no_streamlit_exceptions(at)
        for boundary in (
            analyzer,
            tag_generator,
            connection_generator,
            context_generator,
            analyzer_factory,
            tag_execution,
            connection_execution,
            context_execution,
            summary_provider,
            conversation_provider,
        ):
            boundary.assert_not_called()

    def test_new_discussion_is_zero_ai_and_send_is_exactly_one_call(self) -> None:
        provider = _CountingConversationProvider()
        with mock.patch(
            "research_digest.ui.pages.library.get_research_conversation_provider",
            return_value=(provider, None),
        ) as provider_factory:
            at = self.run_app()
            self.click_button(at, "Second saved paper").run()
            self.text_input(at, "Title (optional)").set_value("Scalar subsector")
            self.click_button(at, "Create discussion").run()

            self.assertEqual(provider.response_calls, 0)
            self.assertEqual(provider.summary_calls, 0)
            self.text_area(at, "Message").set_value("How does the scalar mode enter?")
            self.click_button(at, "Send").run()

            self.assert_no_streamlit_exceptions(at)
            self.assertEqual(provider.response_calls, 1)
            self.assertEqual(provider.summary_calls, 0)
            self.assert_text_present(at, "How does the scalar mode enter?")
            self.assert_text_present(at, "Persisted research answer 1.")
            at.run()
            self.assertEqual(provider.response_calls, 1)

        provider_factory.assert_called_once()
        overviews = list_conversation_overviews(self.db, article_id=self.second_article_id)
        self.assertEqual(len(overviews), 1)
        self.assertEqual(overviews[0].conversation.title, "Scalar subsector")
        assert overviews[0].conversation.id is not None
        self.assertEqual(
            [
                message.role
                for message in list_messages(
                    self.db,
                    conversation_id=overviews[0].conversation.id,
                )
            ],
            [AIConversationRole.USER, AIConversationRole.ASSISTANT],
        )

    def test_takeaway_requires_editable_confirmation_and_spends_no_new_ai(self) -> None:
        provider = _CountingConversationProvider()
        with mock.patch(
            "research_digest.ui.pages.library.get_research_conversation_provider",
            return_value=(provider, None),
        ):
            at = self.run_app()
            self.click_button(at, "Library smoke paper").run()
            self.click_button(at, "Stored discussion").run()
            self.click_button(at, "Add takeaway to My Notes").run()

            note_before = self.db.get_library_note(self.article_id)
            assert note_before is not None
            self.assertEqual(
                note_before.note_text,
                "Human note remains authoritative and separate.",
            )
            self.text_area(at, "Review takeaway before adding").set_value(
                "Human-approved instability takeaway."
            )
            self.click_button(at, "Add to My Notes").run()

        self.assert_no_streamlit_exceptions(at)
        note_after = self.db.get_library_note(self.article_id)
        assert note_after is not None
        self.assertEqual(
            note_after.note_text,
            "Human note remains authoritative and separate.\n\n"
            "Human-approved instability takeaway.",
        )
        self.assertEqual(provider.response_calls, 0)
        self.assertEqual(provider.summary_calls, 0)
        conversation = list_conversation_overviews(self.db, article_id=self.article_id)[0]
        assert conversation.conversation.id is not None
        transcript = list_messages(
            self.db,
            conversation_id=conversation.conversation.id,
        )
        self.assertEqual(transcript[-1].content, "The stored answer remains local and read-only.")

    def test_conversation_failure_is_sanitized_and_explicit_retry_succeeds(self) -> None:
        provider = _CountingConversationProvider(fail=True)
        with mock.patch(
            "research_digest.ui.pages.library.get_research_conversation_provider",
            return_value=(provider, None),
        ):
            at = self.run_app()
            self.click_button(at, "Library smoke paper").run()
            self.click_button(at, "Stored discussion").run()
            self.text_area(at, "Message").set_value("A question that initially fails")
            self.click_button(at, "Send").run()

            self.assertEqual(provider.response_calls, 1)
            errors = [str(element.value) for element in at.error]
            self.assertTrue(any("Discussion response failed" in value for value in errors))
            self.assertFalse(any("/home/" in value or "sk-secret" in value for value in errors))
            at.run()
            self.assert_button_present(at, "Retry response")
            provider.fail = False
            self.click_button(at, "Retry response").run()

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual(provider.response_calls, 2)
        self.assert_text_present(at, "Persisted research answer 2.")

    def run_app(self) -> AppTest:
        return AppTest.from_function(
            _library_app,
            default_timeout=5,
            args=(str(self.config_dir), str(self.data_dir)),
        ).run()

    def assert_no_streamlit_exceptions(self, at: AppTest) -> None:
        self.assertEqual([str(value) for value in at.exception], [])

    def assert_text_present(self, at: AppTest, expected: str) -> None:
        self.assertTrue(any(expected in text for text in self._plain_texts(at)), expected)

    def assert_text_absent(self, at: AppTest, expected: str) -> None:
        self.assertFalse(any(expected in text for text in self._plain_texts(at)), expected)

    def assert_button_present(self, at: AppTest, label: str) -> None:
        self.assertTrue(any(str(button.label) == label for button in at.button), label)

    def assert_button_absent(self, at: AppTest, label: str) -> None:
        self.assertFalse(any(str(button.label) == label for button in at.button), label)

    def click_button(self, at: AppTest, label: str) -> Any:
        matches = [button for button in at.button if str(button.label) == label]
        self.assertGreater(len(matches), 0, label)
        return matches[0].click()

    def selectbox(self, at: AppTest, label: str) -> Any:
        matches = [element for element in at.selectbox if str(element.label) == label]
        self.assertEqual(len(matches), 1, label)
        return matches[0]

    def multiselect(self, at: AppTest, label: str) -> Any:
        matches = [element for element in at.multiselect if str(element.label) == label]
        self.assertEqual(len(matches), 1, label)
        return matches[0]

    def text_input(self, at: AppTest, label: str) -> Any:
        matches = [element for element in at.text_input if str(element.label) == label]
        self.assertEqual(len(matches), 1, label)
        return matches[0]

    def text_area(self, at: AppTest, label: str) -> Any:
        matches = [element for element in at.text_area if str(element.label) == label]
        self.assertEqual(len(matches), 1, label)
        return matches[0]

    def _plain_texts(self, at: AppTest) -> list[str]:
        return (
            [str(element.value) for element in at.title]
            + [str(element.value) for element in at.header]
            + [str(element.value) for element in at.subheader]
            + [str(element.value) for element in at.markdown]
            + [str(element.value) for element in at.text]
            + [str(element.value) for element in at.caption]
        )


if __name__ == "__main__":
    unittest.main()
