from __future__ import annotations

import unittest
from datetime import UTC, datetime

from research_digest.calibration import build_calibration_summary
from research_digest.models import (
    AnalysisOrigin,
    AnalysisResult,
    Article,
    ArticleFeedback,
    DigestItem,
)


def _article(article_id: int, source_article_id: str) -> Article:
    return Article(
        id=article_id,
        source="arxiv",
        source_article_id=source_article_id,
        title=f"Paper {source_article_id}",
        authors=["Ada Lovelace"],
        abstract="A paper about gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def _item(article_id: int, source_article_id: str, score: float) -> DigestItem:
    return DigestItem(
        article=_article(article_id, source_article_id),
        analysis=AnalysisResult(
            relevance_score=score,
            relevance_reason=f"Score {score}.",
            matched_topics=["gravity"] if score >= 0.6 else [],
            summary="Summary.",
            why_it_matters="Reason.",
            reading_priority="HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.6 else "LOW",
        ),
        analysis_origin=AnalysisOrigin.NEW_THIS_RUN,
    )


def _feedback(article_id: int, label: str) -> ArticleFeedback:
    return ArticleFeedback(
        id=article_id,
        article_id=article_id,
        profile_id=1,
        profile_fingerprint="fingerprint",
        feedback_label="RELEVANT" if label == "RELEVANT" else "NOT_RELEVANT",
        created_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
    )


class CalibrationTests(unittest.TestCase):
    def test_build_calibration_summary_counts_threshold_outcomes(self) -> None:
        items = [
            _item(1, "2608.00001", 0.9),
            _item(2, "2608.00002", 0.8),
            _item(3, "2608.00003", 0.4),
            _item(4, "2608.00004", 0.2),
        ]
        feedback = {
            1: _feedback(1, "RELEVANT"),
            2: _feedback(2, "NOT_RELEVANT"),
            3: _feedback(3, "RELEVANT"),
            4: _feedback(4, "NOT_RELEVANT"),
        }

        summary = build_calibration_summary(
            items=items,
            feedback_by_article_id=feedback,
            threshold=0.6,
        )

        self.assertEqual(summary.feedback_count, 4)
        self.assertEqual(summary.predicted_relevant_count, 2)
        self.assertEqual(summary.actual_relevant_count, 2)
        self.assertEqual(summary.true_positive_count, 1)
        self.assertEqual(summary.false_positive_count, 1)
        self.assertEqual(summary.false_negative_count, 1)
        self.assertEqual(summary.true_negative_count, 1)
        self.assertEqual(summary.precision, 0.5)
        self.assertEqual(summary.recall, 0.5)

    def test_precision_and_recall_are_absent_when_denominator_is_zero(self) -> None:
        summary = build_calibration_summary(
            items=[_item(1, "2608.00001", 0.2)],
            feedback_by_article_id={1: _feedback(1, "NOT_RELEVANT")},
            threshold=0.6,
        )

        self.assertIsNone(summary.precision)
        self.assertIsNone(summary.recall)


if __name__ == "__main__":
    unittest.main()
