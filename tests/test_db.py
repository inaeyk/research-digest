from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path

from research_digest.db import Database
from research_digest.models import AnalysisResult, Article, ArxivSourceConfig, InterestProfile


def sample_article(source_article_id: str = "2608.00001") -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title="Warped compactifications",
        authors=["Ada Lovelace"],
        abstract="A paper about higher-dimensional gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=f"http://arxiv.org/pdf/{source_article_id}",
    )


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_arxiv_config_defaults_and_update(self) -> None:
        config = self.db.get_arxiv_config()
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.categories, ["hep-th", "gr-qc"])

        self.db.save_arxiv_config(
            ArxivSourceConfig(
                enabled=False,
                categories=["math-ph"],
                lookback_hours=12,
                max_results=10,
            )
        )
        updated = self.db.get_arxiv_config()
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertFalse(updated.enabled)
        self.assertEqual(updated.categories, ["math-ph"])
        self.assertEqual(updated.lookback_hours, 12)
        self.assertEqual(updated.max_results, 10)

    def test_interest_crud(self) -> None:
        created = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity and black branes.",
            relevance_threshold=0.7,
            enabled=True,
        )

        self.assertIsNotNone(created.id)
        self.assertEqual(self.db.list_interest_profiles(enabled_only=True), [created])

        updated = self.db.update_interest_profile(
            InterestProfile(
                id=created.id,
                name="Gravity updated",
                description="Massive spin-2 states.",
                relevance_threshold=0.4,
                enabled=False,
            )
        )
        self.assertEqual(updated.name, "Gravity updated")
        self.assertFalse(updated.enabled)
        self.assertEqual(self.db.list_interest_profiles(enabled_only=True), [])

    def test_database_can_be_reused_from_another_thread(self) -> None:
        created = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity and black branes.",
        )
        results: queue.Queue[BaseException | list[InterestProfile]] = queue.Queue()

        def worker() -> None:
            try:
                results.put(self.db.list_interest_profiles())
            except BaseException as exc:
                results.put(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        result = results.get_nowait()
        if isinstance(result, BaseException):
            raise result
        self.assertFalse(hasattr(self.db, "_conn"))
        self.assertEqual(result, [created])

    def test_article_deduplication_and_idempotency(self) -> None:
        first, first_inserted = self.db.upsert_article(sample_article())
        second, second_inserted = self.db.upsert_article(sample_article())

        self.assertTrue(first_inserted)
        self.assertFalse(second_inserted)
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.count_articles(), 1)

    def test_analysis_round_trip(self) -> None:
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )
        article, _ = self.db.upsert_article(sample_article())
        assert article.id is not None
        assert profile.id is not None

        analysis = AnalysisResult(
            relevance_score=0.8,
            relevance_reason="Direct match.",
            matched_topics=["gravity"],
            summary="Summary.",
            why_it_matters="It matches the profile.",
            reading_priority="HIGH",
        )
        self.db.upsert_analysis(article_id=article.id, profile_id=profile.id, analysis=analysis)

        loaded = self.db.get_analysis(article.id, profile.id)
        self.assertEqual(loaded, analysis)


if __name__ == "__main__":
    unittest.main()
