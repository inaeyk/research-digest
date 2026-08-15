from __future__ import annotations

import unittest
from datetime import UTC, datetime

from research_digest.models import Article, InterestProfile
from research_digest.preselection import TermOverlapPreselector


def _article(
    *,
    title: str,
    abstract: str,
    categories: list[str] | None = None,
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id="2608.02000",
        title=title,
        authors=["Ada Lovelace"],
        abstract=abstract,
        categories=categories or ["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url="http://arxiv.org/abs/2608.02000",
        pdf_url=None,
    )


class TermOverlapPreselectorTests(unittest.TestCase):
    def test_title_or_category_match_selects_before_abstract_stage(self) -> None:
        profile = InterestProfile(
            id=1,
            name="Gravity",
            description="Black branes and higher-dimensional gravity.",
        )
        article = _article(
            title="Black brane perturbations",
            abstract="The abstract does not need to carry the matching term.",
        )

        result = TermOverlapPreselector().preselect(profile=profile, articles=[article])

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(result.decisions[0].stage, "title_category")
        self.assertIn("brane", result.decisions[0].matched_terms)

    def test_abstract_match_selects_after_title_category_miss(self) -> None:
        profile = InterestProfile(
            id=1,
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        article = _article(
            title="Spectral estimates",
            abstract="We study gravity in a compact higher-dimensional model.",
            categories=["math-ph"],
        )

        result = TermOverlapPreselector().preselect(profile=profile, articles=[article])

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.decisions[0].stage, "abstract")
        self.assertIn("gravity", result.decisions[0].matched_terms)

    def test_profile_without_useful_terms_selects_everything(self) -> None:
        profile = InterestProfile(id=1, name="The", description="And with the.")
        article = _article(
            title="Detector calibration constants",
            abstract="A procedure for measuring pixel gains.",
            categories=["physics.ins-det"],
        )

        result = TermOverlapPreselector().preselect(profile=profile, articles=[article])

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(result.decisions[0].stage, "fallback")


if __name__ == "__main__":
    unittest.main()
