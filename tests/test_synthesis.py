from __future__ import annotations

import unittest
from datetime import UTC, datetime

from research_digest.models import AnalysisOrigin, AnalysisResult, Article, DigestItem
from research_digest.synthesis import build_cross_paper_synthesis


def _item(
    *,
    source_article_id: str,
    title: str,
    score: float,
    topics: list[str],
    priority: str,
    categories: list[str],
) -> DigestItem:
    return DigestItem(
        article=Article(
            id=None,
            source="arxiv",
            source_article_id=source_article_id,
            title=title,
            authors=["Ada Lovelace"],
            abstract=f"{title} abstract.",
            categories=categories,
            published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
            abstract_url=f"http://arxiv.org/abs/{source_article_id}",
            pdf_url=None,
        ),
        analysis=AnalysisResult(
            relevance_score=score,
            relevance_reason="Reason.",
            matched_topics=topics,
            summary="Summary.",
            why_it_matters="Why.",
            reading_priority="HIGH" if priority == "HIGH" else "MEDIUM",
        ),
        analysis_origin=AnalysisOrigin.NEW_THIS_RUN,
    )


class CrossPaperSynthesisTests(unittest.TestCase):
    def test_synthesis_uses_relevant_papers_only_and_counts_recurring_topics(self) -> None:
        synthesis = build_cross_paper_synthesis(
            items=[
                _item(
                    source_article_id="2608.00001",
                    title="Black brane spectra",
                    score=0.9,
                    topics=["Black branes", "spin-2"],
                    priority="HIGH",
                    categories=["hep-th"],
                ),
                _item(
                    source_article_id="2608.00002",
                    title="Compact spin-2 modes",
                    score=0.7,
                    topics=["spin-2", "compactification"],
                    priority="MEDIUM",
                    categories=["hep-th", "gr-qc"],
                ),
                _item(
                    source_article_id="2608.00003",
                    title="Detector calibration",
                    score=0.2,
                    topics=["spin-2"],
                    priority="HIGH",
                    categories=["physics.ins-det"],
                ),
            ],
            threshold=0.6,
        )

        self.assertEqual(synthesis.analyzed_count, 3)
        self.assertEqual(synthesis.relevant_count, 2)
        self.assertEqual(synthesis.high_priority_titles, ("Black brane spectra",))
        self.assertEqual(len(synthesis.recurring_topics), 1)
        self.assertEqual(synthesis.recurring_topics[0].topic, "spin-2")
        self.assertEqual(synthesis.recurring_topics[0].paper_count, 2)
        self.assertEqual(synthesis.category_counts, (("hep-th", 2), ("gr-qc", 1)))

    def test_synthesis_has_no_signal_without_relevant_papers(self) -> None:
        synthesis = build_cross_paper_synthesis(
            items=[
                _item(
                    source_article_id="2608.00003",
                    title="Detector calibration",
                    score=0.2,
                    topics=["detectors"],
                    priority="MEDIUM",
                    categories=["physics.ins-det"],
                )
            ],
            threshold=0.6,
        )

        self.assertFalse(synthesis.has_signal)
        self.assertEqual(synthesis.relevant_count, 0)

    def test_duplicate_topics_within_one_paper_do_not_count_as_recurring(self) -> None:
        synthesis = build_cross_paper_synthesis(
            items=[
                _item(
                    source_article_id="2608.00001",
                    title="Spin-2 spectra",
                    score=0.9,
                    topics=["spin-2", "Spin-2", " spin-2 "],
                    priority="HIGH",
                    categories=["hep-th"],
                )
            ],
            threshold=0.6,
        )

        self.assertEqual(synthesis.relevant_count, 1)
        self.assertEqual(synthesis.recurring_topics, ())


if __name__ == "__main__":
    unittest.main()
