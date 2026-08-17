from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from research_digest.models import (
    MAX_ARXIV_LOOKBACK_HOURS,
    MAX_ARXIV_RESULTS,
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    DateSelectionKind,
    InterestProfile,
    ModelValidationError,
    normalize_whitespace,
    source_date_from_datetime,
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

    def test_date_selection_normalizes_explicit_dates_and_ordering(self) -> None:
        selection = DateSelection.explicit_dates(
            [
                date(2026, 8, 17),
                date(2026, 8, 15),
                date(2026, 8, 17),
            ]
        )

        self.assertEqual(selection.kind, DateSelectionKind.EXPLICIT_DATES)
        self.assertEqual(selection.dates, (date(2026, 8, 15), date(2026, 8, 17)))
        self.assertEqual(selection.selected_dates(), selection.dates)

    def test_date_selection_range_expands_inclusive_dates(self) -> None:
        selection = DateSelection.date_range(date(2026, 8, 14), date(2026, 8, 16))

        self.assertEqual(
            selection.selected_dates(),
            (date(2026, 8, 14), date(2026, 8, 15), date(2026, 8, 16)),
        )

    def test_date_selection_rejects_invalid_shapes(self) -> None:
        with self.assertRaises(ModelValidationError):
            DateSelection.explicit_dates([])
        with self.assertRaises(ModelValidationError):
            DateSelection.date_range(date(2026, 8, 17), date(2026, 8, 16))
        with self.assertRaises(ModelValidationError):
            DateSelection(DateSelectionKind.LATEST_AVAILABLE, (date(2026, 8, 17),))

    def test_date_selection_round_trip_mapping_and_fingerprint(self) -> None:
        selection = DateSelection.single_date(date(2026, 8, 17))
        loaded = DateSelection.from_mapping(selection.to_mapping())

        self.assertEqual(loaded, selection)
        self.assertEqual(loaded.canonical_key(), selection.canonical_key())
        self.assertEqual(loaded.display_label(), "2026-08-17")

    def test_date_selection_rejects_unknown_mapping_kind(self) -> None:
        with self.assertRaises(ModelValidationError):
            DateSelection.from_mapping({"kind": "UNKNOWN", "dates": []})

    def test_source_date_from_datetime_uses_utc_calendar_date(self) -> None:
        timestamp = datetime.fromisoformat("2026-08-17T01:15:00+02:00")

        self.assertEqual(source_date_from_datetime(timestamp), date(2026, 8, 16))

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
