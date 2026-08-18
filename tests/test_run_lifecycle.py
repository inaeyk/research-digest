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
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_RUNNING,
    Database,
    RunAlreadyActiveError,
    RunLockError,
)
from research_digest.models import (
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    InterestProfile,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.preselection import AbstractPreselectionDecision, AbstractPreselectionResult
from research_digest.run_locks import RunOwnerState
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


class InterruptingBatchAnalyzer:
    def __init__(self) -> None:
        self.calls = 0
        self.fake = FakeAnalyzer()

    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        raise AssertionError("service should call analyze_many")

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        self.calls += 1
        if self.calls > 1:
            raise KeyboardInterrupt
        return self.fake.analyze_many(profile=profile, articles=articles)


class AllPreselector:
    preselection_fraction = 0.50
    preselector_version = "test_all_v1"

    def preselect(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> AbstractPreselectionResult:
        return AbstractPreselectionResult(
            tuple(
                AbstractPreselectionDecision(
                    article_id=f"{article.source}:{article.source_article_id}",
                    selected=True,
                    stage="test",
                    matched_terms=(),
                    reason="test selects all",
                    preselection_score=1.0,
                    preselection_threshold=(
                        profile.relevance_threshold * self.preselection_fraction
                    ),
                    preselector_version=self.preselector_version,
                )
                for article in articles
            )
        )


class InterruptingSource(StaticSource):
    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        raise KeyboardInterrupt


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
            run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                UPDATE app_runs
                SET progress_stage = 'analysis',
                    progress_message = 'Full analysis 1 / 3.'
                WHERE id = ?
                """,
                (run_id,),
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
        self.assertEqual(recovered["progress_stage"], APP_RUN_FAILED.lower())
        self.assertIn("stopped before completion", recovered["progress_message"])
        self.assertIn("stopped before completion", recovered["error_message"])

    def test_active_process_owner_blocks_overlap(self) -> None:
        started = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
        now = datetime(2026, 8, 14, 1, 1, tzinfo=UTC)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_runs (profile_id, source_name, started_at, status)
                VALUES (?, ?, ?, ?)
                """,
                (self.profile.id, "arxiv", started.isoformat(), APP_RUN_RUNNING),
            )
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("digest", "process-owner", started.isoformat(), started.isoformat()),
            )

        with self.assertRaises(RunAlreadyActiveError):
            self.db.acquire_run_lock(
                owner="new-owner",
                stale_after_seconds=60 * 60 * 6,
                now=now,
                owner_state_checker=lambda _owner: RunOwnerState.ALIVE,
            )
        self.assertEqual(self.db.get_app_runs()[0]["status"], APP_RUN_RUNNING)

    def test_dead_process_owner_is_recovered_without_waiting_for_age_stale(self) -> None:
        started = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
        now = datetime(2026, 8, 14, 1, 1, tzinfo=UTC)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_runs (
                    profile_id, source_name, started_at, status, retrieved_count,
                    stored_count, preselected_count, skipped_analysis_count, analyzed_count
                )
                VALUES (?, ?, ?, ?, 198, 58, 177, 21, 70)
                """,
                (self.profile.id, "arxiv", started.isoformat(), APP_RUN_RUNNING),
            )
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("digest", "process-owner", started.isoformat(), started.isoformat()),
            )

        self.db.acquire_run_lock(
            owner="new-owner",
            stale_after_seconds=60 * 60 * 6,
            now=now,
            owner_state_checker=lambda _owner: RunOwnerState.DEAD,
        )
        self.db.release_run_lock(owner="new-owner")

        recovered = self.db.get_app_runs()[0]
        self.assertEqual(recovered["status"], APP_RUN_FAILED)
        self.assertEqual(recovered["retrieved_count"], 198)
        self.assertEqual(recovered["preselected_count"], 177)
        self.assertEqual(recovered["analyzed_count"], 70)
        self.assertIn("stopped before completion", recovered["error_message"])

    def test_uninspectable_owner_requires_explicit_force_recovery(self) -> None:
        started = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_runs (profile_id, source_name, started_at, status)
                VALUES (?, ?, ?, ?)
                """,
                (self.profile.id, "arxiv", started.isoformat(), APP_RUN_RUNNING),
            )
            run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("digest", "pid:legacy-uuid", started.isoformat(), started.isoformat()),
            )

        with self.assertRaises(RunLockError):
            self.db.recover_abandoned_run(run_id=run_id)

        result = self.db.recover_abandoned_run(
            run_id=run_id,
            force_uninspectable_owner=True,
        )

        self.assertTrue(result.recovered)
        self.assertEqual(result.status_before, APP_RUN_RUNNING)
        self.assertEqual(result.status_after, APP_RUN_FAILED)
        self.assertIsNone(self.db.get_run_lock())

    def test_interrupted_scheduled_run_recovery_preserves_history(self) -> None:
        started = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_runs (
                    profile_id, source_name, started_at, status, run_origin,
                    retrieved_count, preselected_count, analyzed_count
                )
                VALUES (?, ?, ?, ?, ?, 198, 177, 70)
                """,
                (
                    self.profile.id,
                    "arxiv",
                    started.isoformat(),
                    APP_RUN_RUNNING,
                    RunOrigin.SCHEDULED.value,
                ),
            )
            run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("digest", "dead-owner", started.isoformat(), started.isoformat()),
            )

        result = self.db.recover_abandoned_run(
            run_id=run_id,
            owner_state_checker=lambda _owner: RunOwnerState.DEAD,
        )

        self.assertTrue(result.recovered)
        row = self.db.get_app_runs()[0]
        self.assertEqual(row["id"], run_id)
        self.assertEqual(row["status"], APP_RUN_FAILED)
        self.assertEqual(row["run_origin"], RunOrigin.SCHEDULED.value)
        self.assertEqual(row["retrieved_count"], 198)
        self.assertEqual(row["preselected_count"], 177)
        self.assertEqual(row["analyzed_count"], 70)

    def test_recovery_permits_new_run_and_reuses_valid_analyses(self) -> None:
        saved_article = self.db.upsert_articles([article()])[0][0]
        assert saved_article.id is not None
        assert self.profile.id is not None
        self.db.upsert_analysis(
            article_id=saved_article.id,
            profile_id=self.profile.id,
            profile_fingerprint=profile_semantic_fingerprint(self.profile),
            analysis=FakeAnalyzer().analyze(profile=self.profile, article=saved_article),
        )
        started = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO app_runs (
                    profile_id, source_name, started_at, status, retrieved_count,
                    preselected_count, analyzed_count
                )
                VALUES (?, ?, ?, ?, 1, 1, 1)
                """,
                (self.profile.id, "arxiv", started.isoformat(), APP_RUN_RUNNING),
            )
            run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """
                INSERT INTO run_locks (name, owner, acquired_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("digest", "dead-owner", started.isoformat(), started.isoformat()),
            )

        self.db.recover_abandoned_run(
            run_id=run_id,
            owner_state_checker=lambda _owner: RunOwnerState.DEAD,
        )
        analyzer = FakeAnalyzer()
        retry = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=analyzer,
            profile_id=self.profile.id,
        )

        self.assertEqual(retry.digest.reused_analysis_count, 1)
        self.assertEqual(retry.digest.new_analysis_count, 0)
        self.assertEqual(analyzer.calls, [])
        runs = self.db.get_app_runs()
        self.assertEqual(runs[0]["status"], APP_RUN_COMPLETED)
        self.assertEqual(runs[1]["status"], APP_RUN_FAILED)

    def test_keyboard_interrupt_marks_run_failed_and_releases_lock(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            run_digest_for_profile(
                db=self.db,
                source=InterruptingSource([]),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile.id or 0,
            )

        row = self.db.get_app_runs()[0]
        self.assertEqual(row["status"], APP_RUN_FAILED)
        self.assertIn("interrupted", row["error_message"].lower())
        self.assertIsNone(self.db.get_run_lock())

    def test_keyboard_interrupt_preserves_durable_analysis_progress_counts(self) -> None:
        articles = [article(f"2608.interrupt{i}") for i in range(6)]

        with self.assertRaises(KeyboardInterrupt):
            run_digest_for_profile(
                db=self.db,
                source=StaticSource(articles),
                analyzer=InterruptingBatchAnalyzer(),
                profile_id=self.profile.id or 0,
                preselector=AllPreselector(),
            )

        row = self.db.get_app_runs()[0]
        self.assertEqual(row["status"], APP_RUN_FAILED)
        self.assertEqual(row["retrieved_count"], 6)
        self.assertEqual(row["preselected_count"], 6)
        self.assertEqual(row["analyzed_count"], 5)
        self.assertIn("interrupted", row["error_message"].lower())
        self.assertIsNone(self.db.get_run_lock())

    def test_analysis_unavailable_run_releases_lock_and_retry_reuses_cache(self) -> None:
        unavailable = run_digest_for_profile(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FailingAnalyzer(),
            profile_id=self.profile.id or 0,
        )
        failed = self.db.get_app_runs()[0]
        self.assertEqual(unavailable.digest.run_status, APP_RUN_ANALYSIS_UNAVAILABLE)
        self.assertEqual(failed["status"], APP_RUN_ANALYSIS_UNAVAILABLE)
        self.assertNotIn("/home/" + "inaeyk", failed["error_message"])
        self.assertIn("Analysis unavailable", failed["error_message"])

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

    def test_batch_run_releases_lock_after_profile_analysis_unavailable(self) -> None:
        result = run_digest_for_enabled_profiles(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FailingAnalyzer(),
        )
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.analysis_incomplete_count, 1)

        retry = run_digest_for_enabled_profiles(
            db=self.db,
            source=StaticSource([article()]),
            analyzer=FakeAnalyzer(),
        )

        self.assertEqual(retry.succeeded_count, 1)
        self.assertEqual(self.db.get_app_runs()[0]["status"], APP_RUN_COMPLETED)


if __name__ == "__main__":
    unittest.main()
