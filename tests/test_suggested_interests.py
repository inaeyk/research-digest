from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from research_digest.db import Database
from research_digest.models import Article, profile_semantic_fingerprint
from research_digest.suggested_interests import (
    create_profile_from_suggestion,
    dismiss_suggested_interest,
    refresh_suggested_interests,
)


def _article(
    source_article_id: str,
    title: str,
    *,
    category: str,
    hour: int,
) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract.",
        categories=[category],
        published_at=datetime(2026, 8, 14, hour, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, hour, 10, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class SuggestedInterestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "suggested.sqlite3")
        self.profile = self.db.create_interest_profile(
            name="Warped gravity / black holes",
            description="Warped compactifications and black holes.",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_fewer_than_minimum_evidence_produces_no_suggestion(self) -> None:
        self._mark_new_interest("2608.sug01", "Quantum code one", category="quant-ph")
        self._mark_new_interest("2608.sug02", "Quantum code two", category="quant-ph")

        self.assertEqual(refresh_suggested_interests(self.db, profile=self.profile), [])

    def test_coherent_evidence_produces_candidate_without_modifying_profile(self) -> None:
        original = self.profile
        self._mark_new_interest("2608.sug01", "Quantum code one", category="quant-ph")
        self._mark_new_interest("2608.sug02", "Quantum code two", category="quant-ph")
        self._mark_new_interest("2608.sug03", "Quantum code three", category="quant-ph")

        suggestions = refresh_suggested_interests(self.db, profile=self.profile)

        self.assertEqual(len(suggestions), 1)
        self.assertIn("quant-ph", suggestions[0].suggested_name)
        self.assertEqual(len(suggestions[0].evidence_article_ids), 3)
        self.assertEqual(self.db.get_interest_profile(original.id or 0), original)

    def test_heterogeneous_examples_do_not_force_candidate(self) -> None:
        self._mark_new_interest("2608.sug01", "Quantum code one", category="quant-ph")
        self._mark_new_interest("2608.sug02", "Galaxy survey", category="astro-ph.CO")
        self._mark_new_interest("2608.sug03", "Number theory", category="math.NT")

        self.assertEqual(refresh_suggested_interests(self.db, profile=self.profile), [])

    def test_dismissal_prevents_repeated_theme_suggestion_when_evidence_changes(self) -> None:
        for index in range(3):
            self._mark_new_interest(
                f"2608.sug{index}",
                f"Quantum code {index}",
                category="quant-ph",
            )
        suggestion = refresh_suggested_interests(self.db, profile=self.profile)[0]
        assert suggestion.id is not None

        dismiss_suggested_interest(self.db, suggestion_id=suggestion.id)

        self.assertEqual(refresh_suggested_interests(self.db, profile=self.profile), [])
        self._mark_new_interest("2608.sug_extra", "Quantum code extra", category="quant-ph")
        self.assertEqual(refresh_suggested_interests(self.db, profile=self.profile), [])
        self.assertEqual(
            len(
                self.db.list_suggested_interest_profiles(
                    profile_id=self.profile.id or 0,
                    profile_fingerprint=profile_semantic_fingerprint(self.profile),
                    include_dismissed=True,
                )
            ),
            1,
        )

    def test_candidate_construction_uses_bounded_feedback_scan(self) -> None:
        for index in range(3):
            self._mark_new_interest(
                f"2608.sug{index}",
                f"Quantum code {index}",
                category="quant-ph",
            )

        with mock.patch.object(
            self.db,
            "list_new_interest_feedback",
            wraps=self.db.list_new_interest_feedback,
        ) as feedback_reader:
            refresh_suggested_interests(self.db, profile=self.profile, max_evidence=7)

        feedback_reader.assert_called_once_with(
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            limit=7,
        )

    def test_create_profile_requires_explicit_approval_and_allows_edits(self) -> None:
        for index in range(3):
            self._mark_new_interest(
                f"2608.sug{index}",
                f"Quantum code {index}",
                category="quant-ph",
            )
        suggestion = refresh_suggested_interests(self.db, profile=self.profile)[0]
        assert suggestion.id is not None

        created = create_profile_from_suggestion(
            self.db,
            suggestion_id=suggestion.id,
            name="Quantum error correction",
            description="Quantum codes and error-correction methods.",
        )

        self.assertEqual(created.name, "Quantum error correction")
        self.assertEqual(
            created.description,
            "Quantum codes and error-correction methods.",
        )
        self.assertEqual(refresh_suggested_interests(self.db, profile=self.profile), [])

    def _mark_new_interest(
        self,
        source_article_id: str,
        title: str,
        *,
        category: str,
    ) -> None:
        article, _ = self.db.upsert_article(
            _article(
                source_article_id,
                title,
                category=category,
                hour=int(source_article_id[-1]) if source_article_id[-1].isdigit() else 9,
            )
        )
        assert article.id is not None
        assert self.profile.id is not None
        self.db.upsert_article_feedback(
            article_id=article.id,
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            profile_match="NO",
            personal_interest="YES",
        )


if __name__ == "__main__":
    unittest.main()
