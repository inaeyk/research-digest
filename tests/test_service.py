from __future__ import annotations

import tempfile
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from research_digest.analysis.base import article_analysis_key
from research_digest.analysis.fake import FakeAnalyzer
from research_digest.db import Database
from research_digest.models import AnalysisResult, Article, ArxivSourceConfig, InterestProfile
from research_digest.pipeline import DigestPipelineError
from research_digest.service import run_digest_for_enabled_profiles, run_digest_for_profile


class StaticSource:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles[: config.max_results])


class SelectiveFailAnalyzer:
    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        raise AssertionError("service should call analyze_many through the pipeline")

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        if profile.name == "Failing profile":
            raise RuntimeError(
                "provider failed at /home/"
                + "inaeyk/private with OPENAI_API_KEY=sk-"
                + "secret123456789"
            )
        return {
            article_analysis_key(article): AnalysisResult(
                relevance_score=0.9,
                relevance_reason="Strong match.",
                matched_topics=["gravity"],
                summary="Summary.",
                why_it_matters="Reason.",
                reading_priority="HIGH",
            )
            for article in articles
        }


def article(source_article_id: str = "2608.10001") -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title="Warped compactifications and massive spin-2 spectra",
        authors=["Ada Lovelace"],
        abstract="A study of higher-dimensional gravity and Kaluza-Klein spectra.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_headless_run_processes_all_enabled_profiles(self) -> None:
        first = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity and spin-2 states.",
        )
        second = self.db.create_interest_profile(
            name="Branes",
            description="Black branes and compactification physics.",
        )
        self.db.create_interest_profile(
            name="Disabled",
            description="This disabled profile should not run.",
            enabled=False,
        )
        analyzer = FakeAnalyzer()

        result = run_digest_for_enabled_profiles(
            db=self.db,
            source=StaticSource([article("2608.10001"), article("2608.10002")]),
            analyzer=analyzer,
        )

        self.assertEqual(result.succeeded_count, 2)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual([run.profile_id for run in result.profiles], [second.id, first.id])
        self.assertEqual(result.retrieved_count, 4)
        self.assertEqual(result.analyzed_count, 4)
        self.assertEqual(len(self.db.get_app_runs()), 2)

    def test_single_profile_service_returns_calibration_and_synthesis(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity and spin-2 states.",
        )
        result = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FakeAnalyzer(
                {
                    "2608.10001": {
                        "relevance_score": 0.9,
                        "relevance_reason": "Direct match.",
                        "matched_topics": ["gravity"],
                        "summary": "Summary.",
                        "why_it_matters": "Reason.",
                        "reading_priority": "HIGH",
                    }
                }
            ),
            profile_id=profile.id or 0,
        )

        self.assertEqual(result.digest.relevant_count, 1)
        self.assertEqual(result.calibration.feedback_count, 0)
        self.assertEqual(result.synthesis.relevant_count, 1)
        self.assertEqual(
            result.synthesis.high_priority_titles,
            ("Warped compactifications and massive spin-2 spectra",),
        )

    def test_headless_run_sanitizes_profile_failure_and_continues(self) -> None:
        failing = self.db.create_interest_profile(
            name="Failing profile",
            description="Higher-dimensional gravity.",
        )
        succeeding = self.db.create_interest_profile(
            name="Succeeding profile",
            description="Higher-dimensional gravity.",
        )

        result = run_digest_for_enabled_profiles(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=SelectiveFailAnalyzer(),
        )

        self.assertEqual(result.succeeded_count, 1)
        self.assertEqual(result.failed_count, 1)
        failure = result.profiles[0]
        self.assertEqual(failure.profile_id, failing.id)
        self.assertFalse(failure.success)
        self.assertIsNotNone(failure.error_message)
        assert failure.error_message is not None
        self.assertNotIn("/home/" + "inaeyk", failure.error_message)
        self.assertNotIn("sk-secret", failure.error_message)
        self.assertIn("Analysis unavailable", failure.error_message)
        self.assertEqual(result.profiles[1].profile_id, succeeding.id)

    def test_headless_run_requires_enabled_profile(self) -> None:
        with self.assertRaisesRegex(DigestPipelineError, "interest profile"):
            run_digest_for_enabled_profiles(
                db=self.db,
                source=StaticSource([article()]),
                analyzer=FakeAnalyzer(),
            )


if __name__ == "__main__":
    unittest.main()
