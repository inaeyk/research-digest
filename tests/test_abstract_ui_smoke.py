from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest import mock

from streamlit.testing.v1 import AppTest

from research_digest.db import Database
from research_digest.models import (
    AnalysisOrigin,
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    DigestItem,
    DigestResult,
    RunOrigin,
)


def _article(
    source_article_id: str,
    title: str,
    abstract: str,
    hour: int,
    authors: list[str] | None = None,
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=authors or ["Ada Lovelace"],
        abstract=abstract,
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, hour, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, hour, 10, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def _analysis(score: float) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=score,
        relevance_reason=f"Score {score}.",
        matched_topics=["gravity"] if score >= 0.6 else [],
        summary=f"Generated summary for {score}.",
        why_it_matters=f"Generated reason for {score}.",
        reading_priority="HIGH" if score >= 0.6 else "LOW",
    )


# AppTest copies only each helper definition, so external annotations must stay quoted.
def _today_items_app(result: "DigestResult", db: "Database") -> None:  # noqa: UP037
    from research_digest.ui.pages.today import _render_items

    _render_items(result, db)


def _quantitative_prompt_app(
    result: "DigestResult",  # noqa: UP037
    db: "Database",  # noqa: UP037
) -> None:
    from research_digest.ui.pages.today import _render_quantitative_calibration_prompt

    _render_quantitative_calibration_prompt(db, result)


def _history_snapshot_app(
    snapshot: dict[str, object],
    db: "Database",  # noqa: UP037
) -> None:
    from research_digest.ui.pages.history import _render_snapshot

    _render_snapshot(snapshot, db)


def _date_selection_app(
    default_selection: "DateSelection",  # noqa: UP037
    source_config: "ArxivSourceConfig",  # noqa: UP037
) -> None:
    import streamlit as st

    from research_digest.ui.pages.today import _render_date_selection_control

    control = _render_date_selection_control(default_selection, source_config=source_config)
    st.write(control.selection.kind.value if control.selection is not None else "incomplete")


class AbstractUiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_env = {
            key: os.environ.get(key)
            for key in (
                "RESEARCH_DIGEST_CONFIG_DIR",
                "RESEARCH_DIGEST_DATA_DIR",
                "RESEARCH_DIGEST_LEGACY_DB",
            )
        }
        root = Path(self.tmpdir.name)
        os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root / "config")
        os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root / "data")
        os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root / "missing.sqlite3")
        self.db = Database(root / "test.sqlite3")
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
            relevance_threshold=0.6,
        )
        above, _ = self.db.upsert_article(
            _article(
                "2608.above",
                "Above threshold paper",
                "Above threshold source abstract.",
                10,
                ["Relevant Result Author"],
            )
        )
        below, _ = self.db.upsert_article(
            _article(
                "2608.below",
                "Below threshold paper",
                "Below threshold source abstract.",
                9,
                ["Below Threshold Author"],
            )
        )
        skipped, _ = self.db.upsert_article(
            _article(
                "2608.skipped",
                "Preselected-out paper",
                "Preselected-out source abstract.",
                8,
                ["Preselected Out Author"],
            )
        )
        self.result = DigestResult(
            run_id=42,
            profile=self.profile,
            source_config=ArxivSourceConfig(categories=["hep-th"]),
            retrieved_count=3,
            stored_count=3,
            preselected_count=2,
            skipped_analysis_count=1,
            analyzed_count=2,
            new_analysis_count=2,
            reused_analysis_count=0,
            above_threshold_count=1,
            analysis_available=True,
            items=[
                DigestItem(
                    article=above,
                    analysis=_analysis(0.9),
                    analysis_origin=AnalysisOrigin.NEW_THIS_RUN,
                ),
                DigestItem(
                    article=below,
                    analysis=_analysis(0.2),
                    analysis_origin=AnalysisOrigin.NEW_THIS_RUN,
                ),
            ],
            started_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
            completed_at=datetime(2026, 8, 14, 11, 1, tzinfo=UTC),
            skipped_articles=[skipped],
            run_origin=RunOrigin.MANUAL,
            date_selection=DateSelection.single_date(datetime(2026, 8, 14).date()),
            requested_source_dates=(datetime(2026, 8, 14).date(),),
            covered_source_dates=(datetime(2026, 8, 14).date(),),
        )

    def tearDown(self) -> None:
        self.db.close()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmpdir.cleanup()

    def test_today_abstract_toggles_cover_relevant_below_and_preselected_out(self) -> None:
        at = AppTest.from_function(
            _today_items_app,
            default_timeout=5,
            args=(self.result, self.db),
        ).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Relevant Result Author")
        self.assert_text_present(at, "Preselected Out Author")

        self.click_button(at, "Show abstract", occurrence=0).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Above threshold source abstract.")

        self.click_button(at, "Show abstract", occurrence=1).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Preselected-out source abstract.")

        self.set_segmented_control(at, 0, "below_threshold").run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Below Threshold Author")
        self.assert_button_present(at, "Find Library connections")
        self.click_button(at, "Show abstract", occurrence=0).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Below threshold source abstract.")

        self.set_segmented_control(at, 0, "all_analyzed").run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Relevant Result Author")
        self.assert_text_present(at, "Below Threshold Author")

    def test_today_source_date_segmented_control_preserves_safe_defaults(self) -> None:
        default = DateSelection.latest_available()
        at = AppTest.from_function(
            _date_selection_app,
            default_timeout=5,
            args=(default, self.result.source_config),
        ).run()

        self.assert_no_streamlit_exceptions(at)
        self.assertEqual(self.segmented_controls(at)[0].label, "Source dates")
        self.assertEqual(self.segmented_value(at, 0), "latest_available")
        self.assert_text_present(at, "LATEST_AVAILABLE")

        self.set_segmented_control(at, 0, "single_date").run()
        self.assert_no_streamlit_exceptions(at)
        self.assertEqual(self.segmented_value(at, 0), "single_date")
        self.assert_text_present(at, "SINGLE_DATE")

    def test_today_preselected_out_abstract_renders_when_no_items_are_analyzed(self) -> None:
        skipped = self.result.skipped_articles[0]
        result = DigestResult(
            run_id=43,
            profile=self.profile,
            source_config=ArxivSourceConfig(categories=["hep-th"]),
            retrieved_count=1,
            stored_count=1,
            preselected_count=0,
            skipped_analysis_count=1,
            analyzed_count=0,
            new_analysis_count=0,
            reused_analysis_count=0,
            above_threshold_count=0,
            analysis_available=True,
            items=[],
            started_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            completed_at=datetime(2026, 8, 14, 12, 1, tzinfo=UTC),
            skipped_articles=[skipped],
            run_origin=RunOrigin.MANUAL,
            date_selection=DateSelection.single_date(datetime(2026, 8, 14).date()),
            requested_source_dates=(datetime(2026, 8, 14).date(),),
            covered_source_dates=(datetime(2026, 8, 14).date(),),
        )

        at = AppTest.from_function(
            _today_items_app,
            default_timeout=5,
            args=(result, self.db),
        ).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Preselected Out Author")
        self.assert_text_not_containing(at, "Generated summary")
        self.assert_text_not_containing(at, "Generated reason")
        self.assert_text_not_containing(at, "Priority")

        self.click_button(at, "Show abstract", occurrence=0).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Preselected-out source abstract.")
        self.assert_text_not_containing(at, "Generated summary")
        self.assert_text_not_containing(at, "Generated reason")

    def test_history_preselected_out_snapshot_stays_minimal(self) -> None:
        snapshot = {
            "run_id": 44,
            "profile_id": self.profile.id,
            "profile_name": self.profile.name,
            "source": "arxiv",
            "items": [
                {
                    "title": "Analyzed historical paper",
                    "source": "arxiv",
                    "source_article_id": "2608.above",
                    "authors": ["Historical Author One", "Historical Author Two"],
                    "categories": ["hep-th"],
                    "published_at": "2026-08-14T10:00:00+00:00",
                    "relevance_score": 0.9,
                    "reading_priority": "HIGH",
                    "analysis_origin": "NEW_THIS_RUN",
                    "summary": "Generated analyzed summary.",
                    "why_it_matters": "Generated analyzed reason.",
                    "abstract_url": "http://arxiv.org/abs/2608.above",
                    "abstract": "Analyzed abstract.",
                }
            ],
            "skipped_articles": [
                {
                    "title": "Historical preselected-out paper",
                    "source": "arxiv",
                    "source_article_id": "2608.skipped",
                    "authors": ["Skipped History Author"],
                    "categories": ["gr-qc"],
                    "published_at": "2026-08-14T08:00:00+00:00",
                    "abstract_url": "http://arxiv.org/abs/2608.skipped",
                    "abstract": "Historical preselected-out source abstract.",
                    "summary": "Generated prose must not render.",
                    "why_it_matters": "Generated reason must not render.",
                    "reading_priority": "HIGH",
                }
            ],
        }

        at = AppTest.from_function(
            _history_snapshot_app,
            default_timeout=5,
            args=(snapshot, self.db),
        ).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Historical Author One, Historical Author Two")
        self.assert_text_present(at, "Skipped History Author")
        self.assert_text_present(at, "Generated analyzed summary.")
        self.assert_text_not_containing(at, "Generated prose must not render")
        self.assert_text_not_containing(at, "Generated reason must not render")

        self.click_button(at, "Show abstract", occurrence=1).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Historical preselected-out source abstract.")
        self.assert_text_not_containing(at, "Generated prose must not render")

    def test_older_history_snapshot_without_authors_shows_unavailable(self) -> None:
        snapshot = {
            "run_id": 45,
            "profile_id": self.profile.id,
            "source": "arxiv",
            "items": [
                {
                    "title": "Older historical paper",
                    "source": "arxiv",
                    "source_article_id": "2608.older",
                    "relevance_score": 0.8,
                    "reading_priority": "HIGH",
                    "analysis_origin": "REUSED",
                }
            ],
        }

        at = AppTest.from_function(
            _history_snapshot_app,
            default_timeout=5,
            args=(snapshot, self.db),
        ).run()

        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Authors unavailable")

    def test_today_feedback_controls_are_two_clear_unselected_questions(self) -> None:
        at = AppTest.from_function(
            _today_items_app,
            default_timeout=5,
            args=(self.result, self.db),
        ).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Help Research Digest learn")
        controls = self.segmented_controls(at)
        self.assertEqual(controls[1].label, 'Does this paper match "Gravity"?')
        self.assertEqual(
            controls[2].label,
            "Are you personally interested in this paper?",
        )
        self.assertIsNone(self.segmented_value(at, 1))
        self.assertIsNone(self.segmented_value(at, 2))

        self.set_segmented_control(at, 1, "YES").run()
        self.assert_no_streamlit_exceptions(at)
        self.set_segmented_control(at, 2, "NO").run()
        self.assert_no_streamlit_exceptions(at)

        self.assertEqual(self.segmented_value(at, 1), "YES")
        self.assertEqual(self.segmented_value(at, 2), "NO")
        feedback = self.db.get_article_feedback(
            article_id=self.result.items[0].article.id or 0,
            profile_id=self.profile.id or 0,
            profile_fingerprint=self.profile_fingerprint(),
        )
        self.assertIsNotNone(feedback)
        assert feedback is not None
        self.assertEqual(feedback.profile_match, "YES")
        self.assertEqual(feedback.personal_interest, "NO")

        self.set_segmented_control(at, 1, "UNANSWERED").run()
        self.assert_no_streamlit_exceptions(at)
        cleared = self.db.get_article_feedback(
            article_id=self.result.items[0].article.id or 0,
            profile_id=self.profile.id or 0,
            profile_fingerprint=self.profile_fingerprint(),
        )
        self.assertIsNotNone(cleared)
        assert cleared is not None
        self.assertIsNone(cleared.profile_match)
        self.assertEqual(cleared.personal_interest, "NO")

    def test_today_library_connection_generation_is_explicit_ai(self) -> None:
        generator = object()
        with (
            mock.patch(
                "research_digest.ui.pages.today.get_library_context_generator",
                return_value=(generator, None),
            ) as provider_factory,
            mock.patch(
                "research_digest.ui.pages.today.generate_library_context_for_item",
                return_value=[],
            ) as execution,
        ):
            at = AppTest.from_function(
                _today_items_app,
                default_timeout=5,
                args=(self.result, self.db),
            ).run()

            provider_factory.assert_not_called()
            execution.assert_not_called()
            self.click_button(at, "Find Library connections", occurrence=0).run()

        self.assert_no_streamlit_exceptions(at)
        provider_factory.assert_called_once_with()
        execution.assert_called_once()
        self.assertIs(execution.call_args.kwargs["generator"], generator)

    def test_quantitative_calibration_prompt_hides_model_score_until_submit(self) -> None:
        run_id = self.db.create_app_run(profile_id=self.profile.id, source_name="arxiv")
        below = self.result.items[1].article
        assert below.id is not None
        self.db.create_quantitative_calibration_prompt(
            run_id=run_id,
            article_id=below.id,
            profile_id=self.profile.id or 0,
            profile_fingerprint=self.profile_fingerprint(),
            model_relevance_score=0.2,
        )
        result = DigestResult(
            run_id=run_id,
            profile=self.profile,
            source_config=self.result.source_config,
            retrieved_count=1,
            stored_count=1,
            preselected_count=1,
            skipped_analysis_count=0,
            analyzed_count=1,
            new_analysis_count=1,
            reused_analysis_count=0,
            above_threshold_count=0,
            analysis_available=True,
            items=[self.result.items[1]],
            started_at=self.result.started_at,
            completed_at=self.result.completed_at,
            run_origin=RunOrigin.MANUAL,
        )

        at = AppTest.from_function(
            _quantitative_prompt_app,
            default_timeout=5,
            args=(result, self.db),
        ).run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Help calibrate Research Digest")
        self.assert_text_present(at, "Below Threshold Author")
        self.assert_text_absent(at, "Research Digest score")

        at.slider[0].set_value(0.35).run()
        at.button[0].click().run()
        self.assert_no_streamlit_exceptions(at)
        self.assertTrue(
            any("Research Digest score: 0.20" in text for text in self._plain_texts(at))
        )

    def assert_no_streamlit_exceptions(self, at: AppTest) -> None:
        self.assertEqual([str(value) for value in at.exception], [])

    def assert_text_present(self, at: AppTest, expected: str) -> None:
        texts = self._plain_texts(at)
        self.assertIn(expected, texts)

    def assert_text_absent(self, at: AppTest, expected: str) -> None:
        texts = self._plain_texts(at)
        self.assertNotIn(expected, texts)

    def assert_text_not_containing(self, at: AppTest, expected: str) -> None:
        haystack = "\n".join(self._plain_texts(at))
        self.assertNotIn(expected, haystack)

    def click_button(self, at: AppTest, label: str, *, occurrence: int) -> AppTest:
        self.prepare_floor_button_groups(at)
        matches = [button for button in at.button if str(button.label) == label]
        self.assertGreater(len(matches), occurrence)
        return matches[occurrence].click()

    def segmented_controls(self, at: AppTest) -> list[Any]:
        controls = list(getattr(at, "segmented_control", ()))
        if controls:
            return controls
        return list(at.get("button_group"))

    def segmented_value(self, at: AppTest, index: int) -> object | None:
        value = self.segmented_controls(at)[index].value
        if isinstance(value, list):
            return value[0] if value else None
        return cast(object | None, value)

    def set_segmented_control(self, at: AppTest, index: int, value: object) -> Any:
        controls = self.segmented_controls(at)
        if not hasattr(at, "segmented_control"):
            self.prepare_floor_button_groups(at)
            return controls[index].set_value([value])
        return controls[index].set_value(value)

    def prepare_floor_button_groups(self, at: AppTest) -> None:
        if hasattr(at, "segmented_control"):
            return
        for control in at.get("button_group"):
            value = control.value
            if isinstance(value, list):
                continue
            control.set_value([] if value is None else [value])

    def assert_button_present(self, at: AppTest, label: str) -> None:
        labels = [str(button.label) for button in at.button]
        self.assertIn(label, labels)

    def profile_fingerprint(self) -> str:
        from research_digest.models import profile_semantic_fingerprint

        return profile_semantic_fingerprint(self.profile)

    def _plain_texts(self, at: AppTest) -> list[str]:
        raw = (
            [str(element.value) for element in at.markdown]
            + [str(element.value) for element in at.text]
            + [str(element.value) for element in at.caption]
        )
        return [text.strip("*") for text in raw]


if __name__ == "__main__":
    unittest.main()
