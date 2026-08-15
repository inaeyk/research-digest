from __future__ import annotations

import queue
import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from research_digest.analysis.fake import FakeAnalyzer
from research_digest.db import (
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_RUNNING,
    Database,
    RunAlreadyActiveError,
)
from research_digest.models import AnalysisResult, Article, ArxivSourceConfig, InterestProfile
from research_digest.service import run_digest_for_enabled_profiles, run_digest_for_profile


class StaticSource:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        if not config.enabled:
            return []
        return list(self.articles[: config.max_results])


class BlockingSource(StaticSource):
    def __init__(
        self,
        articles: list[Article],
        *,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(articles)
        self.entered = entered
        self.release = release

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("blocking source was not released")
        return super().fetch(config, now=now)


class FailingAnalyzer:
    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        raise AssertionError("service should call analyze_many")

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        raise RuntimeError(
            "provider failed at /home/"
            + "inaeyk/private with OPENAI_API_KEY=sk-"
            + "secret123456789"
        )


def article(source_article_id: str = "2608.lifecycle01") -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title="Lifecycle paper",
        authors=["Ada Lovelace"],
        abstract="A paper about higher-dimensional gravity.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


class RunLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.db = Database(self.db_path)
        self.profile = self.db.create_interest_profile(
            name="Gravity",
            description="Higher-dimensional gravity.",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_simultaneous_service_runs_are_excluded(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        errors: queue.Queue[BaseException] = queue.Queue()

        def worker() -> None:
            try:
                run_digest_for_profile(
                    db=self.db,
                    source=BlockingSource([article()], entered=entered, release=release),
                    analyzer=FakeAnalyzer(),
                    profile_id=self.profile.id or 0,
                )
            except BaseException as exc:
                errors.put(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(entered.wait(timeout=5))

        with self.assertRaises(RunAlreadyActiveError):
            run_digest_for_enabled_profiles(
                db=Database(self.db_path),
                source=StaticSource([article("2608.lifecycle02")]),
                analyzer=FakeAnalyzer(),
            )

        release.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        if not errors.empty():
            raise errors.get()
        self.assertEqual(self.db.get_app_runs()[0]["status"], APP_RUN_COMPLETED)

    def test_stale_lock_and_running_row_recover_to_failed(self) -> None:
        stale_started = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
        late_run_started = datetime(2026, 8, 14, 2, 30, tzinfo=UTC)
        stale_now = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_runs (profile_id, source_name, started_at, status)
                VALUES (?, ?, ?, ?)
                """,
                (self.profile.id, "arxiv", late_run_started.isoformat(), APP_RUN_RUNNING),
            )
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("digest", "old-owner", stale_started.isoformat(), stale_started.isoformat()),
            )

        self.db.acquire_run_lock(
            owner="new-owner",
            stale_after_seconds=60 * 60,
            now=stale_now,
        )
        self.db.release_run_lock(owner="new-owner")

        recovered = self.db.get_app_runs()[0]
        self.assertEqual(recovered["status"], APP_RUN_FAILED)
        self.assertIn("stopped before completion", recovered["error_message"])

    def test_failed_run_releases_lock_and_retry_reuses_cache(self) -> None:
        with self.assertRaises(RuntimeError):
            run_digest_for_profile(
                db=self.db,
                source=StaticSource([article()]),
                analyzer=FailingAnalyzer(),
                profile_id=self.profile.id or 0,
            )
        failed = self.db.get_app_runs()[0]
        self.assertEqual(failed["status"], APP_RUN_FAILED)
        self.assertNotIn("/home/" + "inaeyk", failed["error_message"])
        self.assertIn("[REDACTED_API_KEY]", failed["error_message"])

        first = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
        )
        second = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile.id or 0,
        )

        self.assertEqual(first.digest.new_analysis_count, 1)
        self.assertEqual(second.digest.reused_analysis_count, 1)
        self.assertEqual(self.db.get_app_runs()[0]["status"], APP_RUN_COMPLETED)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_batch_run_releases_lock_after_profile_failure(self) -> None:
        result = run_digest_for_enabled_profiles(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FailingAnalyzer(),
        )
        self.assertEqual(result.failed_count, 1)

        retry = run_digest_for_enabled_profiles(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FakeAnalyzer(),
        )

        self.assertEqual(retry.succeeded_count, 1)
        self.assertEqual(self.db.get_app_runs()[0]["status"], APP_RUN_COMPLETED)


if __name__ == "__main__":
    unittest.main()
