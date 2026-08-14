from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from research_digest.analysis.fake import FakeAnalyzer
from research_digest.db import Database
from research_digest.models import (
    AnalysisOrigin,
    Article,
    ArxivSourceConfig,
    ModelValidationError,
    above_threshold_digest_items,
    below_threshold_digest_items,
)
from research_digest.pipeline import run_digest


class StaticSource:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles[: config.max_results])


class FailingAnalyzer:
    def analyze(self, *, profile: object, article: object) -> object:
        raise AssertionError("pipeline should call analyze_many")

    def analyze_many(self, *, profile: object, articles: object) -> object:
        api_key = "sk-" + "secret123456789"
        raise RuntimeError(
            "provider failed at /home/"
            + "inaeyk/private with OPENAI_API_KEY="
            + api_key
            + " Bearer "
            + "token.secret.value"
        )


def article(source_article_id: str, title: str, published_hour: int) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract about gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, published_hour, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, published_hour, 10, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description=(
                "Higher-dimensional gravity, black strings, black branes, "
                "and spin-2 states."
            ),
            relevance_threshold=0.6,
        )
        self.articles = [
            article("2608.00001", "Warped spin-2 compactifications", 10),
            article("2608.00002", "Black strings", 9),
            article("2608.00003", "Unrelated detector calibration", 8),
        ]
        self.analysis_payloads = {
            "2608.00001": {
                "relevance_score": 0.95,
                "relevance_reason": "Direct spin-2 compactification match.",
                "matched_topics": ["spin-2", "compactifications"],
                "summary": "Summary one.",
                "why_it_matters": "It targets the requested spectrum.",
                "reading_priority": "HIGH",
            },
            "2608.00002": {
                "relevance_score": 0.7,
                "relevance_reason": "Black-string match.",
                "matched_topics": ["black strings"],
                "summary": "Summary two.",
                "why_it_matters": "It concerns Gregory-Laflamme-adjacent systems.",
                "reading_priority": "MEDIUM",
            },
            "2608.00003": {
                "relevance_score": 0.2,
                "relevance_reason": "No real scientific connection.",
                "matched_topics": [],
                "summary": "Summary three.",
                "why_it_matters": "It does not matter for the profile.",
                "reading_priority": "LOW",
            },
        }

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_fake_analyzer_and_pipeline_ranking_filtering(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)

        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(result.retrieved_count, 3)
        self.assertEqual(result.stored_count, 3)
        self.assertEqual(result.analyzed_count, 3)
        self.assertEqual(result.new_analysis_count, 3)
        self.assertEqual(result.reused_analysis_count, 0)
        self.assertEqual(result.new_analysis_count + result.reused_analysis_count, 3)
        self.assertEqual(result.above_threshold_count, 2)
        self.assertEqual(result.relevant_count, 2)
        self.assertEqual(
            [item.article.source_article_id for item in result.items],
            ["2608.00001", "2608.00002", "2608.00003"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in above_threshold_digest_items(result)],
            ["2608.00001", "2608.00002"],
        )
        self.assertEqual(
            [item.article.source_article_id for item in below_threshold_digest_items(result)],
            ["2608.00003"],
        )
        self.assertEqual(
            {item.article.source_article_id: item.analysis_origin for item in result.items},
            {
                "2608.00001": AnalysisOrigin.NEW_THIS_RUN,
                "2608.00002": AnalysisOrigin.NEW_THIS_RUN,
                "2608.00003": AnalysisOrigin.NEW_THIS_RUN,
            },
        )
        self.assertEqual(analyzer.calls, ["2608.00001", "2608.00002", "2608.00003"])

        second = run_digest(
            db=self.db,
            source=StaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
            now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        )
        self.assertEqual(second.stored_count, 0)
        self.assertEqual(second.analyzed_count, 3)
        self.assertEqual(second.new_analysis_count, 0)
        self.assertEqual(second.reused_analysis_count, 3)
        self.assertEqual(second.new_analysis_count + second.reused_analysis_count, 3)
        self.assertEqual(second.above_threshold_count, 2)
        self.assertEqual(self.db.count_articles(), 3)
        self.assertEqual(analyzer.calls, ["2608.00001", "2608.00002", "2608.00003"])
        self.assertEqual(
            {item.article.source_article_id: item.analysis_origin for item in second.items},
            {
                "2608.00001": AnalysisOrigin.REUSED,
                "2608.00002": AnalysisOrigin.REUSED,
                "2608.00003": AnalysisOrigin.REUSED,
            },
        )

    def test_pipeline_counts_mixed_new_and_reused_analyses(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)
        run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )
        analyzer.calls.clear()

        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )

        self.assertEqual(result.retrieved_count, 3)
        self.assertEqual(result.analyzed_count, 3)
        self.assertEqual(result.new_analysis_count, 2)
        self.assertEqual(result.reused_analysis_count, 1)
        self.assertEqual(result.new_analysis_count + result.reused_analysis_count, 3)
        self.assertEqual(analyzer.calls, ["2608.00002", "2608.00003"])
        self.assertEqual(
            {item.article.source_article_id: item.analysis_origin for item in result.items},
            {
                "2608.00001": AnalysisOrigin.REUSED,
                "2608.00002": AnalysisOrigin.NEW_THIS_RUN,
                "2608.00003": AnalysisOrigin.NEW_THIS_RUN,
            },
        )

    def test_pipeline_without_analyzer_remains_usable(self) -> None:
        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=None,
            profile_id=self.profile.id,
        )

        self.assertFalse(result.analysis_available)
        self.assertEqual(result.retrieved_count, 1)
        self.assertEqual(result.analyzed_count, 0)
        self.assertEqual(result.new_analysis_count, 0)
        self.assertEqual(result.reused_analysis_count, 0)
        self.assertEqual(result.above_threshold_count, 0)
        self.assertEqual(result.relevant_count, 0)
        self.assertEqual(self.db.count_articles(), 1)

    def test_pipeline_without_analyzer_reuses_existing_analyses(self) -> None:
        analyzer = FakeAnalyzer(self.analysis_payloads)
        run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )
        analyzer.calls.clear()

        result = run_digest(
            db=self.db,
            source=StaticSource(self.articles[:1]),
            analyzer=None,
            profile_id=self.profile.id,
        )

        self.assertFalse(result.analysis_available)
        self.assertEqual(result.analyzed_count, 1)
        self.assertEqual(result.new_analysis_count, 0)
        self.assertEqual(result.reused_analysis_count, 1)
        self.assertEqual(result.new_analysis_count + result.reused_analysis_count, 1)
        self.assertEqual(result.items[0].analysis_origin, AnalysisOrigin.REUSED)
        self.assertEqual(analyzer.calls, [])

    def test_threshold_boundary_is_relevant(self) -> None:
        boundary = article("2608.00004", "Boundary score paper", 7)
        analyzer = FakeAnalyzer(
            {
                "2608.00004": {
                    "relevance_score": 0.6,
                    "relevance_reason": "Exactly at the configured threshold.",
                    "matched_topics": ["gravity"],
                    "summary": "Boundary summary.",
                    "why_it_matters": "It verifies threshold inclusivity.",
                    "reading_priority": "MEDIUM",
                }
            }
        )

        result = run_digest(
            db=self.db,
            source=StaticSource([boundary]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )

        self.assertEqual(result.above_threshold_count, 1)
        self.assertEqual(
            [item.article.source_article_id for item in above_threshold_digest_items(result)],
            ["2608.00004"],
        )
        self.assertEqual(below_threshold_digest_items(result), [])

    def test_malformed_analysis_rejected_and_run_marked_failed(self) -> None:
        analyzer = FakeAnalyzer(
            {
                "2608.00001": {
                    "relevance_score": 1.5,
                    "relevance_reason": "Invalid score.",
                    "matched_topics": [],
                    "summary": "Summary.",
                    "why_it_matters": "Reason.",
                    "reading_priority": "HIGH",
                }
            }
        )

        with self.assertRaises(ModelValidationError):
            run_digest(
                db=self.db,
                source=StaticSource(self.articles[:1]),
                analyzer=analyzer,
                profile_id=self.profile.id,
            )

        runs = self.db.get_app_runs()
        self.assertEqual(runs[0]["status"], "failed")
        self.assertIn("relevance_score", runs[0]["error_message"])

    def test_pipeline_persists_sanitized_error_message(self) -> None:
        with self.assertRaises(RuntimeError):
            run_digest(
                db=self.db,
                source=StaticSource(self.articles[:1]),
                analyzer=FailingAnalyzer(),
                profile_id=self.profile.id,
            )

        runs = self.db.get_app_runs()
        error_message = runs[0]["error_message"]
        self.assertNotIn("/home/" + "inaeyk", error_message)
        self.assertNotIn("sk-secret", error_message)
        self.assertNotIn("token.secret.value", error_message)
        self.assertIn("[HOME]", error_message)
        self.assertIn("[REDACTED_API_KEY]", error_message)
        self.assertIn("Bearer [REDACTED]", error_message)


if __name__ == "__main__":
    unittest.main()
