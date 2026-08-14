from __future__ import annotations

import unittest
from datetime import UTC, datetime

from research_digest.models import (
    MAX_ARXIV_LOOKBACK_HOURS,
    MAX_ARXIV_RESULTS,
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    InterestProfile,
    ModelValidationError,
    normalize_whitespace,
)


class ModelTests(unittest.TestCase):
    def test_normalize_whitespace(self) -> None:
        self.assertEqual(normalize_whitespace(" a\n  b\tc "), "a b c")

    def test_article_normalizes_text_fields(self) -> None:
        article = Article(
            id=None,
            source=" arxiv ",
            source_article_id=" 2608.00001 ",
            title="Title\n with   spaces",
            authors=[" Ada  Lovelace "],
            abstract="Abstract\n text",
            categories=[" hep-th "],
            published_at=datetime(2026, 8, 14, tzinfo=UTC),
            updated_at=datetime(2026, 8, 14, tzinfo=UTC),
            abstract_url="http://arxiv.org/abs/2608.00001",
            pdf_url=None,
        )

        self.assertEqual(article.source, "arxiv")
        self.assertEqual(article.title, "Title with spaces")
        self.assertEqual(article.authors, ["Ada Lovelace"])
        self.assertEqual(article.categories, ["hep-th"])

    def test_interest_threshold_validation(self) -> None:
        with self.assertRaises(ModelValidationError):
            InterestProfile(
                id=None,
                name="Gravity",
                description="Higher-dimensional gravity",
                relevance_threshold=1.5,
            )

    def test_arxiv_source_config_upper_bounds(self) -> None:
        ArxivSourceConfig(
            categories=["hep-th"],
            lookback_hours=MAX_ARXIV_LOOKBACK_HOURS,
            max_results=MAX_ARXIV_RESULTS,
        )

        with self.assertRaises(ModelValidationError):
            ArxivSourceConfig(
                categories=["hep-th"],
                lookback_hours=MAX_ARXIV_LOOKBACK_HOURS + 1,
                max_results=MAX_ARXIV_RESULTS,
            )

        with self.assertRaises(ModelValidationError):
            ArxivSourceConfig(
                categories=["hep-th"],
                lookback_hours=MAX_ARXIV_LOOKBACK_HOURS,
                max_results=MAX_ARXIV_RESULTS + 1,
            )

    def test_analysis_payload_accepts_exact_schema(self) -> None:
        result = AnalysisResult.from_mapping(
            {
                "relevance_score": 0.9,
                "relevance_reason": "Strong conceptual match.",
                "matched_topics": ["black strings"],
                "summary": "A concise summary.",
                "why_it_matters": "It targets the profile directly.",
                "reading_priority": "HIGH",
            }
        )

        self.assertEqual(result.reading_priority, "HIGH")
        self.assertEqual(result.matched_topics, ["black strings"])

    def test_malformed_analysis_rejected(self) -> None:
        with self.assertRaises(ModelValidationError):
            AnalysisResult.from_mapping(
                {
                    "relevance_score": 0.5,
                    "relevance_reason": "Partial match.",
                    "matched_topics": [],
                    "summary": "Summary.",
                    "why_it_matters": "Reason.",
                    "reading_priority": "MEDIUM",
                    "unexpected": "not allowed",
                }
            )

        with self.assertRaises(ModelValidationError):
            AnalysisResult.from_mapping(
                {
                    "relevance_score": 1.2,
                    "relevance_reason": "Invalid score.",
                    "matched_topics": [],
                    "summary": "Summary.",
                    "why_it_matters": "Reason.",
                    "reading_priority": "HIGH",
                }
            )

        with self.assertRaises(ModelValidationError):
            AnalysisResult.from_mapping(
                {
                    "relevance_score": True,
                    "relevance_reason": "Boolean is not numeric enough.",
                    "matched_topics": [],
                    "summary": "Summary.",
                    "why_it_matters": "Reason.",
                    "reading_priority": "LOW",
                }
            )


if __name__ == "__main__":
    unittest.main()
