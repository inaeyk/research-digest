from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

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
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
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


def _today_items_app(result: DigestResult, db: Database) -> None:
    from research_digest.ui.pages.today import _render_items

    _render_items(result, db)


class AbstractUiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
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
            )
        )
        below, _ = self.db.upsert_article(
            _article(
                "2608.below",
                "Below threshold paper",
                "Below threshold source abstract.",
                9,
            )
        )
        skipped, _ = self.db.upsert_article(
            _article(
                "2608.skipped",
                "Preselected-out paper",
                "Preselected-out source abstract.",
                8,
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
        self.tmpdir.cleanup()

    def test_today_abstract_toggles_cover_relevant_below_and_preselected_out(self) -> None:
        at = AppTest.from_function(
            _today_items_app,
            default_timeout=5,
            args=(self.result, self.db),
        ).run()
        self.assert_no_streamlit_exceptions(at)

        at.button[0].click().run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Above threshold source abstract.")
        self.assert_text_absent(at, "Generated summary for 0.9.")

        at.button[1].click().run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Preselected-out source abstract.")

        at.segmented_control[0].set_value("below_threshold").run()
        self.assert_no_streamlit_exceptions(at)
        at.button[0].click().run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Below threshold source abstract.")

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

        at.button[0].click().run()
        self.assert_no_streamlit_exceptions(at)
        self.assert_text_present(at, "Preselected-out source abstract.")

    def assert_no_streamlit_exceptions(self, at: AppTest) -> None:
        self.assertEqual([str(value) for value in at.exception], [])

    def assert_text_present(self, at: AppTest, expected: str) -> None:
        texts = self._plain_texts(at)
        self.assertIn(expected, texts)

    def assert_text_absent(self, at: AppTest, expected: str) -> None:
        texts = self._plain_texts(at)
        self.assertNotIn(expected, texts)

    def _plain_texts(self, at: AppTest) -> list[str]:
        return [str(element.value) for element in at.text] + [
            str(element.value) for element in at.caption
        ]


if __name__ == "__main__":
    unittest.main()
