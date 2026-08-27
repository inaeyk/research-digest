from __future__ import annotations

import inspect
import json
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from research_digest.analysis.base import article_analysis_key
from research_digest.analysis.codex_cli import CodexAbstractPreselector
from research_digest.analysis.fake import FakeAnalyzer
from research_digest.background import (
    start_automatic_digest_worker,
    start_manual_digest_worker,
)
from research_digest.cancellation import (
    RunCancelled,
    bind_run_cancellation,
    cancellation_signal_scope,
    raise_if_cancelled,
    request_run_cancellation,
    run_owned_subprocess,
    stop_abandoned_provider_processes,
)
from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.coverage import (
    build_coverage_scope,
    source_config_semantic_fingerprint,
)
from research_digest.db import (
    APP_RUN_CANCELLED,
    APP_RUN_COMPLETED,
    CURRENT_SCHEMA_VERSION,
    Database,
)
from research_digest.history import reconstruct_digest_result
from research_digest.models import (
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.pipeline import run_digest
from research_digest.preselection import (
    AbstractPreselectionDecision,
    AbstractPreselectionResult,
)
from research_digest.run_locks import (
    RunOwnerState,
    current_process_run_owner,
    linux_process_start_ticks,
    linux_process_state,
)
from research_digest.service import run_digest_for_profile
from research_digest.sources.arxiv import ArxivDateRetrievalResult
from research_digest.ui.pages.history import history_status_label
from research_digest.ui.run_status import get_active_digest_status, render_active_digest_control

SOURCE_DATE = date(2026, 8, 20)


class DateSource:
    def __init__(self, articles: Sequence[Article], *, incomplete: bool = False) -> None:
        self.articles = tuple(articles)
        self.incomplete = incomplete
        self.calls = 0

    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        del config, now
        self.calls += 1
        return list(self.articles)

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> ArxivDateRetrievalResult:
        del config
        self.calls += 1
        requested = selection.selected_dates()
        incomplete = requested if self.incomplete else ()
        covered = () if self.incomplete else requested
        return ArxivDateRetrievalResult(
            selection=selection,
            articles=self.articles,
            requested_dates=requested,
            covered_dates=covered,
            empty_dates=tuple(value for value in covered if not self.articles),
            incomplete_dates=incomplete,
            latest_available_date=SOURCE_DATE,
            retrieved_count=len(self.articles),
            safety_limit=2000,
            safety_limit_reached=self.incomplete,
        )


class NeverFetchSource(DateSource):
    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> ArxivDateRetrievalResult:
        del config, selection
        raise AssertionError("covered source corpus must be reused without refetch")


class CancellingSource(DateSource):
    def __init__(self, db: Database) -> None:
        super().__init__(())
        self.db = db

    def fetch_date_selection(
        self,
        config: ArxivSourceConfig,
        selection: DateSelection,
    ) -> ArxivDateRetrievalResult:
        del config, selection
        active = self.db.get_active_app_run()
        assert active is not None
        self.db.request_app_run_cancellation(int(active["id"]))
        raise_if_cancelled()
        raise AssertionError("cancellation must abort retrieval")


class CancellingPreselector:
    preselection_fraction = 1.0
    preselector_version = "cancel-test-v1"

    def __init__(self, db: Database) -> None:
        self.db = db

    def preselect(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> AbstractPreselectionResult:
        del profile, articles
        active = self.db.get_active_app_run()
        assert active is not None
        self.db.request_app_run_cancellation(int(active["id"]))
        raise_if_cancelled()
        raise AssertionError("cancellation must abort Stage 1")


class CancelSecondAnalysis:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.calls = 0

    def analyze(self, *, profile: InterestProfile, article: Article) -> AnalysisResult:
        result = self.analyze_many(profile=profile, articles=(article,))
        return result[article_analysis_key(article)]

    def analyze_many(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> Mapping[str, AnalysisResult]:
        del profile
        self.calls += 1
        if self.calls == 2:
            active = self.db.get_active_app_run()
            assert active is not None
            self.db.request_app_run_cancellation(int(active["id"]))
            raise_if_cancelled()
        return {article_analysis_key(item): _analysis(item) for item in articles}


class PassAllPreselector:
    preselection_fraction = 1.0
    preselector_version = "pass-all-v1"

    def preselect(
        self,
        *,
        profile: InterestProfile,
        articles: Sequence[Article],
    ) -> AbstractPreselectionResult:
        del profile
        return AbstractPreselectionResult(
            tuple(
                AbstractPreselectionDecision(
                    article_id=article_analysis_key(article),
                    selected=True,
                    stage="test",
                    matched_terms=(),
                    reason="test",
                    preselection_score=1.0,
                    preselection_threshold=0.0,
                    preselector_version=self.preselector_version,
                )
                for article in articles
            )
        )


class CancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "digest.sqlite3"
        self.db = Database(self.db_path)
        profile = self.db.create_interest_profile(
            name="Gravity",
            description="Quantum gravity and black holes.",
            relevance_threshold=0.5,
        )
        assert profile.id is not None
        self.profile_id = profile.id
        self.config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        self.db.save_arxiv_config(self.config)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_cancellation_during_retrieval_is_uncovered_terminal_and_releases_lock(self) -> None:
        with self.assertRaises(RunCancelled):
            run_digest_for_profile(
                db=self.db,
                source=CancellingSource(self.db),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
                run_origin=RunOrigin.MANUAL,
            )

        run = self.db.get_app_runs()[0]
        self.assertEqual(run["status"], APP_RUN_CANCELLED)
        self.assertIsNotNone(run["completed_at"])
        self.assertFalse(bool(run["retrieval_complete"]))
        self.assertIsNone(self.db.get_run_lock())
        self.assertEqual(self._covered_dates(), set())

        retry = run_digest_for_profile(
            db=self.db,
            source=DateSource(()),
            analyzer=FakeAnalyzer(),
            profile_id=self.profile_id,
            date_selection=DateSelection.single_date(SOURCE_DATE),
            run_origin=RunOrigin.MANUAL,
        )
        self.assertEqual(retry.digest.run_status, APP_RUN_COMPLETED)

    def test_complete_retrieval_survives_stage1_cancellation_and_retry_reuses_corpus(self) -> None:
        article = _article("2608.20001")
        source = DateSource((article,))
        with self.assertRaises(RunCancelled):
            run_digest_for_profile(
                db=self.db,
                source=source,
                analyzer=FakeAnalyzer(),
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
                run_origin=RunOrigin.MANUAL,
                preselector=CancellingPreselector(self.db),
            )
        self.assertEqual(self._covered_dates(), {SOURCE_DATE})

        retry_analyzer = FakeAnalyzer()
        retry = run_digest_for_profile(
            db=self.db,
            source=NeverFetchSource(()),
            analyzer=retry_analyzer,
            profile_id=self.profile_id,
            date_selection=DateSelection.single_date(SOURCE_DATE),
            run_origin=RunOrigin.MANUAL,
            preselector=PassAllPreselector(),
        )
        self.assertEqual(retry.digest.retrieved_count, 1)
        self.assertEqual(retry_analyzer.calls, [article.source_article_id])

    def test_full_analysis_cancellation_preserves_completed_chunk_for_reuse(self) -> None:
        articles = (_article("2608.20002"), _article("2608.20003"))
        analyzer = CancelSecondAnalysis(self.db)
        with self.assertRaises(RunCancelled):
            run_digest(
                db=self.db,
                source=DateSource(articles),
                analyzer=analyzer,
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
                run_origin=RunOrigin.MANUAL,
                preselector=PassAllPreselector(),
                analysis_chunk_size=1,
            )

        profile = self.db.get_interest_profile(self.profile_id)
        stored = self.db.get_article_by_source_id("arxiv", articles[0].source_article_id)
        assert profile is not None and stored is not None and stored.id is not None
        from research_digest.models import profile_semantic_fingerprint

        persisted = self.db.get_analysis(
            article_id=stored.id,
            profile_id=self.profile_id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
        )
        self.assertIsNotNone(persisted)
        self.assertEqual(int(self.db.get_app_runs()[0]["analyzed_count"]), 1)

        retry_analyzer = FakeAnalyzer()
        retry = run_digest_for_profile(
            db=self.db,
            source=NeverFetchSource(()),
            analyzer=retry_analyzer,
            profile_id=self.profile_id,
            date_selection=DateSelection.single_date(SOURCE_DATE),
            preselector=PassAllPreselector(),
        )
        self.assertEqual(retry.digest.reused_analysis_count, 1)
        self.assertEqual(retry.digest.new_analysis_count, 1)

    def test_cancellation_before_synthesis_and_during_library_terminalizes(self) -> None:
        article = _article("2608.20004")

        class CancellingSynthesis:
            def build(inner_self, *, items: object, threshold: float) -> object:
                del inner_self, items, threshold
                active = self.db.get_active_app_run()
                assert active is not None
                self.db.request_app_run_cancellation(int(active["id"]))
                raise_if_cancelled()
                raise AssertionError

        with self.assertRaises(RunCancelled):
            run_digest_for_profile(
                db=self.db,
                source=DateSource((article,)),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
                preselector=PassAllPreselector(),
                synthesis_builder=CancellingSynthesis(),  # type: ignore[arg-type]
            )
        self.assertEqual(self.db.get_app_runs()[0]["status"], APP_RUN_CANCELLED)

    def test_complete_empty_retrieval_remains_covered_after_downstream_cancel(self) -> None:
        class CancellingSynthesis:
            def build(inner_self, *, items: object, threshold: float) -> object:
                del inner_self, items, threshold
                active = self.db.get_active_app_run()
                assert active is not None
                self.db.request_app_run_cancellation(int(active["id"]))
                raise_if_cancelled()
                raise AssertionError

        with self.assertRaises(RunCancelled):
            run_digest_for_profile(
                db=self.db,
                source=DateSource(()),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
                synthesis_builder=CancellingSynthesis(),  # type: ignore[arg-type]
            )
        self.assertEqual(self._covered_dates(), {SOURCE_DATE})
        self.assertEqual(
            json.loads(str(self.db.get_app_runs()[0]["empty_source_dates_json"])),
            [SOURCE_DATE.isoformat()],
        )

        def cancel_library(*args: object, **kwargs: object) -> object:
            del args, kwargs
            active = self.db.get_active_app_run()
            assert active is not None
            self.db.request_app_run_cancellation(int(active["id"]))
            raise_if_cancelled()
            raise AssertionError

        with mock.patch(
            "research_digest.service.generate_automatic_library_context_for_digest",
            side_effect=cancel_library,
        ), self.assertRaises(RunCancelled):
            run_digest_for_profile(
                db=self.db,
                source=NeverFetchSource(()),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
                library_context_generator=mock.Mock(),
                automatic_library_context_threshold=0.5,
            )
        self.assertEqual(self.db.get_app_runs()[0]["status"], APP_RUN_CANCELLED)

    def test_stage1_batching_observes_cancel_between_batches(self) -> None:
        articles = (_article("2608.20005"), _article("2608.20006"))
        run_id = self.db.create_app_run(
            profile_id=self.profile_id,
            source_name="arxiv",
        )
        self.db.mark_app_run_running(run_id)
        preselector = CodexAbstractPreselector(
            runner=mock.Mock(),
            chunk_size=1,
            preselection_fraction=1.0,
        )
        calls = 0

        def score_chunk(
            *,
            profile: InterestProfile,
            articles: Sequence[Article],
        ) -> dict[str, float]:
            nonlocal calls
            del profile
            calls += 1
            if calls == 1:
                self.db.request_app_run_cancellation(run_id)
            return {article_analysis_key(item): 1.0 for item in articles}

        with bind_run_cancellation(self.db, run_id), mock.patch.object(
            preselector,
            "_score_chunk",
            side_effect=score_chunk,
        ), self.assertRaises(RunCancelled):
            preselector.preselect(
                profile=self.db.get_interest_profile(self.profile_id),  # type: ignore[arg-type]
                articles=articles,
            )
        self.assertEqual(calls, 1)

    @unittest.skipUnless(os.name == "posix" and Path("/proc").exists(), "Linux process test")
    def test_cancel_terminates_exact_provider_tree_but_not_unrelated_process(self) -> None:
        context = multiprocessing.get_context("fork")
        worker = context.Process(target=_provider_worker, args=(str(self.db_path),))
        unrelated = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            worker.start()
            active = _wait_for_active_provider(self.db)
            result = request_run_cancellation(
                self.db,
                run_id=int(active["run_id"]),
                graceful_seconds=2.0,
                terminate_seconds=2.0,
            )
            worker.join(timeout=5.0)
            self.assertEqual(result.status, APP_RUN_CANCELLED)
            self.assertTrue(result.owner_stopped)
            self.assertFalse(worker.is_alive())
            self.assertIsNone(self.db.get_run_lock())
            self.assertIsNone(unrelated.poll())
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=2.0)
            unrelated.terminate()
            unrelated.wait(timeout=5.0)

    @unittest.skipUnless(os.name == "posix" and Path("/proc").exists(), "Linux process test")
    def test_forced_hung_worker_zombie_terminalizes_and_releases_immediately(self) -> None:
        context = multiprocessing.get_context("fork")
        worker = context.Process(target=_hung_worker, args=(str(self.db_path),))
        try:
            worker.start()
            active = _wait_for_active_run(self.db)
            result = request_run_cancellation(
                self.db,
                run_id=int(active["id"]),
                graceful_seconds=0.1,
                terminate_seconds=0.3,
            )

            self.assertEqual(result.status, APP_RUN_CANCELLED)
            self.assertTrue(result.owner_stopped)
            self.assertIsNone(self.db.get_run_lock())
            run = self.db.get_app_run(int(active["id"]))
            assert run is not None
            self.assertEqual(run["status"], APP_RUN_CANCELLED)
            self.assertIsNotNone(run["completed_at"])
            assert worker.pid is not None
            self.assertEqual(linux_process_state(worker.pid), "Z")
        finally:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=3.0)

    @unittest.skipUnless(os.name == "posix", "process-group cleanup test")
    def test_provider_spawn_registration_failure_cleans_up_exact_process(self) -> None:
        run_id = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_id)
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            with bind_run_cancellation(self.db, run_id), mock.patch(
                "research_digest.cancellation.subprocess.Popen",
                return_value=process,
            ), mock.patch.object(
                self.db,
                "register_provider_process",
                side_effect=RunCancelled(run_id),
            ), self.assertRaises(RunCancelled):
                run_owned_subprocess(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    input_text="",
                    cwd=Path(self.tmp.name),
                    env=os.environ,
                    timeout_seconds=60.0,
                )
            process.wait(timeout=3.0)
            self.assertIsNotNone(process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3.0)

    @unittest.skipUnless(os.name == "posix", "provider registration race test")
    def test_cancel_between_provider_spawn_and_registration_cannot_orphan_process(
        self,
    ) -> None:
        owner = current_process_run_owner()
        self.db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
        run_id = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_id)
        original_register = self.db.register_provider_process
        cancellation_results: list[object] = []

        def _register_after_cancel(
            *,
            run_id: int,
            call_kind: str,
            pid: int,
            process_group_id: int,
            process_start_ticks: int | None,
        ) -> int:
            thread = threading.Thread(
                target=lambda: cancellation_results.append(
                    request_run_cancellation(self.db, run_id=run_id)
                )
            )
            thread.start()
            thread.join(timeout=3.0)
            self.assertFalse(thread.is_alive())
            return original_register(
                run_id=run_id,
                call_kind=call_kind,
                pid=pid,
                process_group_id=process_group_id,
                process_start_ticks=process_start_ticks,
            )

        try:
            with bind_run_cancellation(self.db, run_id), mock.patch.object(
                self.db,
                "register_provider_process",
                side_effect=_register_after_cancel,
            ), self.assertRaises(RunCancelled):
                run_owned_subprocess(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    input_text="",
                    cwd=Path(self.tmp.name),
                    env=os.environ,
                    timeout_seconds=60.0,
                )
            self.assertEqual(len(cancellation_results), 1)
            self.assertEqual(self.db.list_active_provider_processes(run_id=run_id), [])
            with sqlite3.connect(self.db_path) as conn:
                provider = conn.execute(
                    "SELECT pid, status FROM run_provider_processes WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            assert provider is not None
            self.assertEqual(provider[1], APP_RUN_CANCELLED)
            self.assertIsNone(linux_process_start_ticks(int(provider[0])))
        finally:
            self.db.finish_cancelled_run(run_id)
            self.db.release_run_lock(owner=owner)

    def test_cancel_does_not_signal_or_release_a_new_lock_owner(self) -> None:
        owner_a = "worker-a"
        owner_b = "worker-b"
        self.db.acquire_run_lock(owner=owner_a, stale_after_seconds=60.0)
        run_a = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_a)
        self.db.release_run_lock(owner=owner_a)
        self.db.acquire_run_lock(owner=owner_b, stale_after_seconds=60.0)
        run_b = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_b)

        with mock.patch("research_digest.cancellation.os.kill") as kill:
            result = request_run_cancellation(self.db, run_id=run_a)

        kill.assert_not_called()
        self.assertEqual(result.status, APP_RUN_CANCELLED)
        lock = self.db.get_run_lock()
        assert lock is not None
        self.assertEqual(lock.owner, owner_b)
        active = self.db.get_active_app_run()
        assert active is not None
        self.assertEqual(int(active["id"]), run_b)
        self.db.finish_cancelled_run(run_b)
        self.db.release_run_lock(owner=owner_b)

    def test_stale_recovery_preserves_an_accepted_cancellation(self) -> None:
        owner_a = "dead-worker"
        owner_b = "replacement-worker"
        self.db.acquire_run_lock(owner=owner_a, stale_after_seconds=60.0)
        run_id = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_id)
        self.assertTrue(self.db.request_app_run_cancellation(run_id))

        self.db.acquire_run_lock(
            owner=owner_b,
            stale_after_seconds=0.0,
            owner_state_checker=lambda _owner: RunOwnerState.DEAD,
        )

        run = self.db.get_app_run(run_id)
        assert run is not None
        self.assertEqual(run["status"], APP_RUN_CANCELLED)
        self.assertEqual(run["error_message"], "Cancelled by user.")
        self.db.release_run_lock(owner=owner_b)

    @unittest.skipUnless(os.name == "posix" and Path("/proc").exists(), "Linux process test")
    def test_stale_recovery_stops_registered_orphan_provider(self) -> None:
        provider = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        owner = "dead-worker-owner"
        replacement = "replacement-owner"
        try:
            self.db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
            run_id = self.db.create_app_run(
                profile_id=self.profile_id,
                source_name="arxiv",
            )
            self.db.mark_app_run_running(run_id)
            self.db.register_provider_process(
                run_id=run_id,
                call_kind="orphan-test",
                pid=provider.pid,
                process_group_id=os.getpgid(provider.pid),
                process_start_ticks=linux_process_start_ticks(provider.pid),
            )
            with mock.patch(
                "research_digest.cancellation.process_run_owner_state",
                return_value=RunOwnerState.DEAD,
            ):
                stopped = stop_abandoned_provider_processes(
                    self.db,
                    stale_after_seconds=60.0,
                )
            provider.wait(timeout=3.0)
            self.assertEqual(stopped, 1)
            self.assertEqual(self.db.list_active_provider_processes(run_id=run_id), [])

            self.db.acquire_run_lock(
                owner=replacement,
                stale_after_seconds=60.0,
                owner_state_checker=lambda _owner: RunOwnerState.DEAD,
            )
            run = self.db.get_app_run(run_id)
            assert run is not None
            self.assertEqual(run["status"], "FAILED")
            self.db.release_run_lock(owner=replacement)
        finally:
            if provider.poll() is None:
                provider.kill()
                provider.wait(timeout=3.0)

    def test_persistence_failure_cannot_claim_source_coverage(self) -> None:
        with mock.patch.object(
            self.db,
            "record_complete_source_dates",
            side_effect=sqlite3.OperationalError("simulated persistence failure"),
        ), self.assertRaises(sqlite3.OperationalError):
            run_digest_for_profile(
                db=self.db,
                source=DateSource((_article("2608.29999"),)),
                analyzer=FakeAnalyzer(),
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
            )

        run = self.db.get_app_runs()[0]
        self.assertEqual(json.loads(str(run["covered_source_dates_json"])), [])
        self.assertFalse(bool(run["retrieval_complete"]))
        self.assertEqual(self._covered_dates(), set())

    def test_forced_cancellation_preserves_pre_and_post_retrieval_metadata(self) -> None:
        pre_owner = "dead-before-retrieval"
        self.db.acquire_run_lock(owner=pre_owner, stale_after_seconds=60.0)
        pre_run_id = self.db.create_app_run(
            profile_id=self.profile_id,
            source_name="arxiv",
            date_selection=DateSelection.single_date(SOURCE_DATE),
        )
        self.db.mark_app_run_running(pre_run_id)
        self.db.request_app_run_cancellation(pre_run_id)
        self.assertTrue(
            self.db.force_cancel_after_owner_stopped(
                run_id=pre_run_id,
                owner=pre_owner,
            )
        )
        pre_run = self.db.get_app_run(pre_run_id)
        assert pre_run is not None
        self.assertEqual(
            json.loads(str(pre_run["requested_source_dates_json"])),
            [SOURCE_DATE.isoformat()],
        )
        self.assertEqual(
            json.loads(str(pre_run["incomplete_source_dates_json"])),
            [SOURCE_DATE.isoformat()],
        )
        self.assertFalse(bool(pre_run["retrieval_complete"]))

        post_owner = "dead-after-retrieval"
        self.db.acquire_run_lock(owner=post_owner, stale_after_seconds=60.0)
        post_run_id = self.db.create_app_run(
            profile_id=self.profile_id,
            source_name="arxiv",
            date_selection=DateSelection.single_date(SOURCE_DATE),
        )
        self.db.mark_app_run_running(post_run_id)
        scope = build_coverage_scope(source_name="arxiv", source_config=self.config)
        self.db.record_complete_source_dates(
            source_name="arxiv",
            source_fingerprint=scope.source_fingerprint,
            articles_by_date={SOURCE_DATE: ()},
            run_id=post_run_id,
            run_origin=RunOrigin.MANUAL,
            requested_source_dates=(SOURCE_DATE,),
            empty_source_dates=(SOURCE_DATE,),
            retrieval_complete=True,
            retrieved_count=0,
            stored_count=0,
        )
        self.db.request_app_run_cancellation(post_run_id)
        self.assertTrue(
            self.db.force_cancel_after_owner_stopped(
                run_id=post_run_id,
                owner=post_owner,
            )
        )
        post_run = self.db.get_app_run(post_run_id)
        assert post_run is not None
        self.assertEqual(
            json.loads(str(post_run["covered_source_dates_json"])),
            [SOURCE_DATE.isoformat()],
        )
        self.assertEqual(
            json.loads(str(post_run["empty_source_dates_json"])),
            [SOURCE_DATE.isoformat()],
        )
        self.assertEqual(json.loads(str(post_run["incomplete_source_dates_json"])), [])
        self.assertTrue(bool(post_run["retrieval_complete"]))

    def test_completion_cancel_race_has_deterministic_precedence(self) -> None:
        completed = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(completed)
        self.db.finish_app_run(
            completed,
            status=APP_RUN_COMPLETED,
            retrieved_count=0,
            stored_count=0,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            relevant_count=0,
        )
        self.assertFalse(self.db.request_app_run_cancellation(completed))

        cancelled = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(cancelled)
        self.assertTrue(self.db.request_app_run_cancellation(cancelled))
        effective = self.db.finish_app_run(
            cancelled,
            status=APP_RUN_COMPLETED,
            retrieved_count=1,
            stored_count=1,
            preselected_count=1,
            skipped_analysis_count=0,
            analyzed_count=1,
            relevant_count=1,
        )
        self.assertEqual(effective, APP_RUN_CANCELLED)

    def test_scheduled_run_cancel_does_not_disable_schedule(self) -> None:
        run_id = self.db.create_app_run(
            profile_id=self.profile_id,
            source_name="arxiv",
            run_origin=RunOrigin.SCHEDULED,
        )
        self.db.mark_app_run_running(run_id)
        with mock.patch("research_digest.automation.remove_schedule") as disable_schedule:
            self.assertTrue(self.db.request_app_run_cancellation(run_id))
            self.db.finish_cancelled_run(run_id)
        disable_schedule.assert_not_called()
        run = self.db.get_app_run(run_id)
        assert run is not None
        self.assertEqual(run["run_origin"], RunOrigin.SCHEDULED.value)

    def test_cancelled_history_snapshot_is_never_rendered_as_a_success(self) -> None:
        profile = self.db.get_interest_profile(self.profile_id)
        assert profile is not None
        run_id = self.db.create_app_run(
            profile_id=self.profile_id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            source_name="arxiv",
            source_fingerprint=source_config_semantic_fingerprint(self.config),
            date_selection=DateSelection.single_date(SOURCE_DATE),
        )
        self.db.mark_app_run_running(run_id)
        self.db.request_app_run_cancellation(run_id)
        self.db.finish_cancelled_run(run_id)
        self.db.save_run_snapshot(run_id=run_id, snapshot_json="{}")

        self.assertIsNone(reconstruct_digest_result(self.db, run_id=run_id))

    def test_v17_upgrade_adds_cancellation_without_history_loss(self) -> None:
        owner = "pre-v18-live-worker"
        self.db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
        run_id = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_id)
        self.db.close()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE run_provider_processes")
            conn.execute("ALTER TABLE app_runs DROP COLUMN cancel_reason")
            conn.execute("ALTER TABLE app_runs DROP COLUMN cancel_requested_at")
            conn.execute("ALTER TABLE app_runs DROP COLUMN run_owner")
            conn.execute(
                "UPDATE schema_metadata SET value = '17' WHERE key = 'schema_version'"
            )
        upgraded = Database(self.db_path)
        self.db = upgraded
        self.assertEqual(upgraded.get_schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertIsNotNone(upgraded.get_app_run(run_id))
        with sqlite3.connect(self.db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(app_runs)")}
            self.assertIn("cancel_requested_at", columns)
            self.assertIn("cancel_reason", columns)
            self.assertIn("run_owner", columns)
            migrated = conn.execute(
                "SELECT run_owner FROM app_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            assert migrated is not None
            self.assertEqual(migrated[0], owner)
            self.assertIsNotNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'run_provider_processes'"
                ).fetchone()
            )

    def test_fresh_database_reattaches_and_history_labels_cancelled(self) -> None:
        owner = "uninspectable-test-owner"
        self.db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
        run_id = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_id)
        fresh = Database(self.db_path)
        try:
            active = get_active_digest_status(fresh)
            self.assertIsNotNone(active)
            assert active is not None
            self.assertEqual(active.run_id, run_id)
            fresh.request_app_run_cancellation(run_id)
            fresh.force_cancel_after_owner_stopped(run_id=run_id, owner=owner)
            entry = __import__(
                "research_digest.history",
                fromlist=["list_run_history"],
            ).list_run_history(fresh)[0]
            self.assertEqual(history_status_label(entry), "Cancelled by user")
        finally:
            fresh.close()

    def test_streamlit_reattaches_and_uses_explicit_cancel_control(self) -> None:
        owner = "uninspectable-ui-worker"
        self.db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
        run_id = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_id)

        app = AppTest.from_function(
            _active_status_app,
            default_timeout=5,
            args=(str(self.db_path),),
        ).run()
        self.assertEqual([str(value) for value in app.exception], [])
        cancel_buttons = [button for button in app.button if button.label == "Cancel digest"]
        self.assertEqual(len(cancel_buttons), 1)
        cancel_buttons[0].click().run()
        run = self.db.get_app_run(run_id)
        assert run is not None
        self.assertIsNotNone(run["cancel_requested_at"])
        self.assertTrue(
            self.db.force_cancel_after_owner_stopped(run_id=run_id, owner=owner)
        )
        self.assertIsNone(self.db.get_run_lock())

    def test_cli_and_ui_background_surfaces_share_service_boundaries(self) -> None:
        run_id = self.db.create_app_run(profile_id=self.profile_id, source_name="arxiv")
        self.db.mark_app_run_running(run_id)
        self.db.request_app_run_cancellation(run_id)
        self.db.finish_cancelled_run(run_id)
        stdout = __import__("io").StringIO()
        stderr = __import__("io").StringIO()
        config = AppConfig(
            db_path=self.db_path,
            data_dir=Path(self.tmp.name),
            config_dir=Path(self.tmp.name),
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="gpt-5-mini",
            codex_model=None,
            codex_timeout_seconds=180.0,
        )
        with mock.patch("research_digest.cli.request_run_cancellation") as cancel:
            cancel.return_value = mock.Mock(
                run_id=run_id,
                accepted=False,
                status=APP_RUN_CANCELLED,
                owner_stopped=True,
            )
            code = run_cli(
                argv=("cancel", "--run-id", str(run_id), "--json"),
                stdout=stdout,
                stderr=stderr,
                config=config,
                db=self.db,
            )
        self.assertEqual(code, 0)
        cancel.assert_called_once_with(self.db, run_id=run_id)
        self.assertEqual(json.loads(stdout.getvalue())["status"], APP_RUN_CANCELLED)

        with mock.patch("research_digest.background.subprocess.Popen") as popen:
            popen.return_value.pid = 90210
            manual = start_manual_digest_worker(
                profile_id=self.profile_id,
                date_selection=DateSelection.single_date(SOURCE_DATE),
            )
            automatic = start_automatic_digest_worker()
        self.assertEqual((manual.mode, automatic.mode), ("manual", "automatic"))
        self.assertEqual(popen.call_count, 2)
        for call in popen.call_args_list:
            self.assertTrue(call.kwargs["start_new_session"])

        ui_source = inspect.getsource(render_active_digest_control)
        self.assertIn("_render_active_status", ui_source)
        run_status_module = __import__(
            "research_digest.ui.run_status",
            fromlist=["_render_active_status"],
        )
        cancel_source = inspect.getsource(run_status_module._render_active_status)
        self.assertIn("request_run_cancellation", cancel_source)

    def _covered_dates(self) -> set[date]:
        scope = build_coverage_scope(source_name="arxiv", source_config=self.config)
        covered: set[date] = set()
        for fingerprint in scope.accepted_source_fingerprints:
            covered.update(
                self.db.list_covered_source_dates(
                    source_name=scope.source_name,
                    source_fingerprint=fingerprint,
                    start_date=SOURCE_DATE,
                    end_date=SOURCE_DATE,
                )
            )
        return covered


def _article(source_article_id: str) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=f"Gravity {source_article_id}",
        authors=["Ada Lovelace"],
        abstract="Quantum gravity and black holes.",
        categories=["hep-th"],
        published_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
        abstract_url=f"https://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def _analysis(article: Article) -> AnalysisResult:
    return AnalysisResult(
        relevance_score=0.9,
        relevance_reason=f"Relevant {article.source_article_id}.",
        matched_topics=["gravity"],
        summary=f"Summary {article.source_article_id}.",
        why_it_matters="It matters.",
        reading_priority="HIGH",
    )


def _provider_worker(db_path: str) -> None:
    db = Database(Path(db_path))
    owner = current_process_run_owner()
    db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
    run_id = db.create_app_run(profile_id=None, source_name="arxiv")
    db.mark_app_run_running(run_id)
    try:
        with cancellation_signal_scope(), bind_run_cancellation(db, run_id):
            run_owned_subprocess(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                input_text="",
                cwd=Path(db_path).parent,
                env=os.environ,
                timeout_seconds=60.0,
                call_kind="test-provider",
            )
    except RunCancelled:
        db.finish_cancelled_run(run_id)
    finally:
        db.release_run_lock(owner=owner)
        db.close()


def _hung_worker(db_path: str) -> None:
    db = Database(Path(db_path))
    owner = current_process_run_owner()
    db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
    run_id = db.create_app_run(
        profile_id=None,
        source_name="arxiv",
        date_selection=DateSelection.single_date(SOURCE_DATE),
    )
    db.mark_app_run_running(run_id)
    with cancellation_signal_scope(), bind_run_cancellation(db, run_id):
        while True:
            time.sleep(1.0)


def _wait_for_active_provider(db: Database) -> sqlite3.Row:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        active = db.get_active_app_run()
        if active is not None:
            processes = db.list_active_provider_processes(run_id=int(active["id"]))
            if processes:
                return processes[0]
        time.sleep(0.05)
    raise AssertionError("provider worker did not become active")


def _wait_for_active_run(db: Database) -> sqlite3.Row:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        active = db.get_active_app_run()
        if active is not None:
            return active
        time.sleep(0.05)
    raise AssertionError("worker did not become active")


def _active_status_app(db_path: str) -> None:
    from pathlib import Path

    from research_digest.db import Database
    from research_digest.ui.run_status import render_active_digest_control

    db = Database(Path(db_path))
    try:
        render_active_digest_control(db)
    finally:
        db.close()


if __name__ == "__main__":
    unittest.main()
