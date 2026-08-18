from __future__ import annotations

import random
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

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
from research_digest.quantitative_calibration import (
    dismiss_quantitative_calibration,
    eligible_quantitative_calibration_candidates,
    maybe_create_quantitative_calibration_prompt,
    submit_quantitative_calibration,
)


def article(source_article_id: str, *, article_id: int, title: str) -> Article:
    return Article(
        id=article_id,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def analysis(score: float) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=score,
        relevance_reason=f"Score {score}.",
        matched_topics=["gravity"],
        summary="Summary.",
        why_it_matters="Reason.",
        reading_priority="LOW",
    )


class QuantitativeCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
            relevance_threshold=0.6,
        )
        saved_low, _ = self.db.upsert_article(
            article("2608.low", article_id=1, title="Below threshold")
        )
        saved_high, _ = self.db.upsert_article(
            article("2608.high", article_id=2, title="Above threshold")
        )
        saved_reused, _ = self.db.upsert_article(
            article("2608.reused", article_id=3, title="Reused below threshold")
        )
        self.low = saved_low
        self.high = saved_high
        self.reused = saved_reused
        self.run_id = self.db.create_app_run(
            profile_id=self.profile.id,
            source_name="arxiv",
            run_origin=RunOrigin.MANUAL,
            date_selection=DateSelection.single_date(datetime(2026, 8, 14).date()),
        )
        self.db.finish_app_run(
            self.run_id,
            status="COMPLETED",
            retrieved_count=3,
            stored_count=3,
            preselected_count=3,
            skipped_analysis_count=0,
            analyzed_count=3,
            relevant_count=1,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_false_sampling_decision_is_persisted_and_not_rerolled(self) -> None:
        digest = self._digest()

        first = maybe_create_quantitative_calibration_prompt(
            self.db,
            digest=digest,
            probability=0.20,
            rng=lambda: 0.99,
        )
        second = maybe_create_quantitative_calibration_prompt(
            self.db,
            digest=digest,
            probability=1.0,
            rng=lambda: 0.0,
        )

        self.assertIsNone(first)
        self.assertIsNone(second)
        stored = self.db.get_quantitative_calibration_for_run(self.run_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.state, "SKIPPED")

    def test_prompt_selects_eligible_below_threshold_analyzed_paper(self) -> None:
        digest = self._digest()

        prompt = maybe_create_quantitative_calibration_prompt(
            self.db,
            digest=digest,
            probability=1.0,
            rng=lambda: 0.0,
            chooser=random.Random(1),
        )

        self.assertIsNotNone(prompt)
        assert prompt is not None
        self.assertEqual(prompt.state, "PENDING")
        self.assertEqual(prompt.article_id, self.low.id)
        self.assertEqual(prompt.model_relevance_score, 0.4)
        self.assertEqual(len(self.db.list_quantitative_calibrations()), 1)

    def test_candidates_exclude_above_threshold_and_completed_article_profile_score(self) -> None:
        digest = self._digest()
        first = maybe_create_quantitative_calibration_prompt(
            self.db,
            digest=digest,
            probability=1.0,
            rng=lambda: 0.0,
            chooser=random.Random(1),
        )
        assert first is not None and first.id is not None
        submit_quantitative_calibration(
            self.db,
            calibration_id=first.id,
            user_relevance_score=0.25,
        )

        candidates = eligible_quantitative_calibration_candidates(self.db, digest=digest)

        self.assertEqual([candidate.item.article.id for candidate in candidates], [self.reused.id])

    def test_submit_and_dismiss_are_distinct_persistent_states(self) -> None:
        digest = self._digest()
        prompt = maybe_create_quantitative_calibration_prompt(
            self.db,
            digest=digest,
            probability=1.0,
            rng=lambda: 0.0,
        )
        assert prompt is not None and prompt.id is not None

        completed = submit_quantitative_calibration(
            self.db,
            calibration_id=prompt.id,
            user_relevance_score=0.33,
        )

        self.assertEqual(completed.state, "COMPLETED")
        self.assertEqual(completed.user_relevance_score, 0.33)

        second_run = self.db.create_app_run(profile_id=self.profile.id, source_name="arxiv")
        self.db.finish_app_run(
            second_run,
            status="COMPLETED",
            retrieved_count=1,
            stored_count=1,
            preselected_count=1,
            skipped_analysis_count=0,
            analyzed_count=1,
            relevant_count=0,
        )
        second_digest = self._digest(run_id=second_run, items=[self._item(self.reused, 0.3)])
        second = maybe_create_quantitative_calibration_prompt(
            self.db,
            digest=second_digest,
            probability=1.0,
            rng=lambda: 0.0,
        )
        assert second is not None and second.id is not None
        dismissed = dismiss_quantitative_calibration(self.db, calibration_id=second.id)

        self.assertEqual(dismissed.state, "DISMISSED")
        self.assertIsNone(dismissed.user_relevance_score)

    def _digest(
        self,
        *,
        run_id: int | None = None,
        items: list[DigestItem] | None = None,
    ) -> DigestResult:
        digest_items = items or [
            self._item(self.low, 0.4, origin=AnalysisOrigin.NEW_THIS_RUN),
            self._item(self.high, 0.8, origin=AnalysisOrigin.NEW_THIS_RUN),
            self._item(self.reused, 0.3, origin=AnalysisOrigin.REUSED),
        ]
        return DigestResult(
            run_id=run_id or self.run_id,
            profile=self.profile,
            source_config=ArxivSourceConfig(categories=["hep-th"]),
            retrieved_count=3,
            stored_count=3,
            preselected_count=3,
            skipped_analysis_count=0,
            analyzed_count=len(digest_items),
            new_analysis_count=sum(
                item.analysis_origin == AnalysisOrigin.NEW_THIS_RUN for item in digest_items
            ),
            reused_analysis_count=sum(
                item.analysis_origin == AnalysisOrigin.REUSED for item in digest_items
            ),
            above_threshold_count=sum(
                item.analysis.relevance_score >= self.profile.relevance_threshold
                for item in digest_items
            ),
            analysis_available=True,
            items=digest_items,
            started_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            completed_at=datetime(2026, 8, 14, 12, 1, tzinfo=UTC),
            run_origin=RunOrigin.MANUAL,
            date_selection=DateSelection.single_date(datetime(2026, 8, 14).date()),
            requested_source_dates=(datetime(2026, 8, 14).date(),),
            covered_source_dates=(datetime(2026, 8, 14).date(),),
        )

    def _item(
        self,
        source_article: Article,
        score: float,
        *,
        origin: AnalysisOrigin = AnalysisOrigin.NEW_THIS_RUN,
    ) -> DigestItem:
        return DigestItem(
            article=source_article,
            analysis=analysis(score),
            analysis_origin=origin,
        )


if __name__ == "__main__":
    unittest.main()
