from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from streamlit.testing.v1 import AppTest

from research_digest.config import save_automation_settings
from research_digest.coverage import source_config_semantic_fingerprint
from research_digest.db import APP_RUN_CANCELLED, APP_RUN_COMPLETED, Database
from research_digest.models import (
    Article,
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    RunOrigin,
    profile_semantic_fingerprint,
)


def _configure_env(root: str) -> Path:
    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    (root_path / "data").mkdir(parents=True, exist_ok=True)
    return root_path / "data" / "research_digest.sqlite3"


def _seed_app_db(root: str) -> int:
    db_path = _configure_env(root)
    db = Database(db_path)
    try:
        profile = db.create_interest_profile(
            name="Warped gravity / black holes",
            description="Higher-dimensional gravity and black holes.",
            relevance_threshold=0.6,
        )
        db.save_arxiv_config(ArxivSourceConfig(categories=["hep-th", "gr-qc"]))
        return int(profile.id or 0)
    finally:
        db.close()


def _article(source_article_id: str, title: str, category: str) -> Article:
    return Article(
        id=None,
        source="arxiv",
        source_article_id=source_article_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract=f"{title} abstract.",
        categories=[category],
        published_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 14, 12, 10, tzinfo=UTC),
        abstract_url=f"http://arxiv.org/abs/{source_article_id}",
        pdf_url=None,
    )


def _today_read_only_app(root: str, counters: dict[str, int]) -> None:
    import os
    from importlib import import_module
    from pathlib import Path

    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    import streamlit as st

    st.cache_resource.clear()
    today = import_module("research_digest.ui.pages.today")
    today_module = vars(today)
    original_start = today_module["start_manual_digest_worker"]
    original_get_context = today_module["get_library_context_generator"]

    def forbidden_start(*args: object, **kwargs: object) -> object:
        counters["worker_start"] = counters.get("worker_start", 0) + 1
        raise AssertionError("startup must not start a digest worker")

    def forbidden_context() -> tuple[object | None, str | None]:
        counters["context"] = counters.get("context", 0) + 1
        raise AssertionError("startup must not build Library context generator")

    today_module["start_manual_digest_worker"] = forbidden_start
    today_module["get_library_context_generator"] = forbidden_context
    try:
        today_module["render"]()
    finally:
        today_module["start_manual_digest_worker"] = original_start
        today_module["get_library_context_generator"] = original_get_context


def _settings_read_only_app(root: str, counters: dict[str, int]) -> None:
    import os
    from importlib import import_module
    from pathlib import Path

    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    import streamlit as st

    st.cache_resource.clear()
    settings = import_module("research_digest.ui.pages.settings")
    settings_module = vars(settings)
    original_start = settings_module["start_automatic_digest_worker"]

    def forbidden_run_now(*args: object, **kwargs: object) -> object:
        counters["run_now"] = counters.get("run_now", 0) + 1
        raise AssertionError("Settings startup must not run automatic catch-up")

    settings_module["start_automatic_digest_worker"] = forbidden_run_now
    try:
        settings_module["render"]()
    finally:
        settings_module["start_automatic_digest_worker"] = original_start


def _history_read_only_app(root: str) -> None:
    import os
    from pathlib import Path

    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    import streamlit as st

    st.cache_resource.clear()
    from research_digest.ui.pages.history import render

    render()


def _today_click_app(
    root: str,
    counters: dict[str, int],
    fail_launch: bool = False,
) -> None:
    import os
    from importlib import import_module
    from pathlib import Path
    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    import streamlit as st

    st.cache_resource.clear()
    from research_digest.background import BackgroundLaunch
    from research_digest.run_locks import linux_process_start_ticks

    today = import_module("research_digest.ui.pages.today")
    today_module = vars(today)
    original_start = today_module["start_manual_digest_worker"]
    original_get_context = today_module["get_library_context_generator"]

    def fake_get_context() -> tuple[None, None]:
        counters["context"] = counters.get("context", 0) + 1
        return None, None

    def fake_start(*args: object, **kwargs: object) -> BackgroundLaunch:
        counters["worker_start"] = counters.get("worker_start", 0) + 1
        if fail_launch:
            return BackgroundLaunch(
                pid=2_147_483_647,
                mode="manual",
                process_start_ticks=None,
            )
        return BackgroundLaunch(
            pid=os.getpid(),
            mode="manual",
            process_start_ticks=linux_process_start_ticks(os.getpid()),
        )

    today_module["get_library_context_generator"] = fake_get_context
    today_module["start_manual_digest_worker"] = fake_start
    try:
        today_module["render"]()
    finally:
        today_module["get_library_context_generator"] = original_get_context
        today_module["start_manual_digest_worker"] = original_start


def _today_external_active_race_app(root: str, counters: dict[str, int]) -> None:
    import os
    from importlib import import_module
    from pathlib import Path

    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    import streamlit as st

    from research_digest.db import Database
    from research_digest.run_locks import RunOwnerState
    from research_digest.ui.run_status import ActiveDigestStatus

    run_status = import_module("research_digest.ui.run_status")
    run_status_module = vars(run_status)
    original_get_active = run_status_module["get_active_digest_status"]

    def raced_get_active(_db: Database) -> ActiveDigestStatus | None:
        counters["active_queries"] = counters.get("active_queries", 0) + 1
        if counters["active_queries"] == 1:
            return None
        return ActiveDigestStatus(
            run_id=41,
            origin="scheduled",
            date_selection="2026-08-20",
            stage="retrieval",
            message="Retrieving source papers.",
            retrieved_count=12,
            preselected_count=0,
            analyzed_count=0,
            cancellation_requested=False,
            owner_state=RunOwnerState.ALIVE,
        )

    db = Database(root_path / "data" / "research_digest.sqlite3")
    run_status_module["get_active_digest_status"] = raced_get_active
    try:
        busy = run_status_module["render_active_digest_control"](db)
        st.button("Run digest", disabled=busy)
    finally:
        run_status_module["get_active_digest_status"] = original_get_active
        db.close()


class StreamlitStartupSideEffectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        self.profile_id = _seed_app_db(self.root)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def app_run_count(self) -> int:
        db = Database(_configure_env(self.root))
        try:
            return len(db.get_app_runs())
        finally:
            db.close()

    def assert_digest_lock_free(self) -> None:
        db = Database(_configure_env(self.root))
        owner = "startup-side-effect-test"
        try:
            db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
            db.release_run_lock(owner=owner)
        finally:
            db.close()

    def suggested_interest_count(self) -> int:
        db = Database(_configure_env(self.root))
        try:
            profile = db.get_interest_profile(self.profile_id)
            if profile is None:
                return 0
            return len(
                db.list_suggested_interest_profiles(
                    profile_id=self.profile_id,
                    profile_fingerprint=profile_semantic_fingerprint(profile),
                    include_dismissed=True,
                )
            )
        finally:
            db.close()

    def start_active_manual_run(self) -> tuple[int, str]:
        owner = "uninspectable-today-ui-worker"
        db = Database(_configure_env(self.root))
        try:
            db.acquire_run_lock(owner=owner, stale_after_seconds=60.0)
            run_id = db.create_app_run(
                profile_id=self.profile_id,
                source_name="arxiv",
                run_origin=RunOrigin.MANUAL,
                date_selection=DateSelection.single_date(date(2026, 8, 20)),
            )
            db.mark_app_run_running(run_id)
            db.update_app_run_progress(
                run_id,
                progress_stage="full_analysis",
                progress_message="Analyzing stored papers.",
                retrieved_count=100,
                preselected_count=70,
                analyzed_count=28,
            )
            return run_id, owner
        finally:
            db.close()

    def terminalize_run(self, run_id: int, owner: str, *, status: str) -> None:
        db = Database(_configure_env(self.root))
        try:
            if status == APP_RUN_CANCELLED:
                db.finish_cancelled_run(run_id)
            else:
                db.finish_app_run(
                    run_id,
                    status=status,
                    retrieved_count=100,
                    stored_count=100,
                    preselected_count=70,
                    skipped_analysis_count=0,
                    analyzed_count=28,
                    relevant_count=12,
                )
            db.release_run_lock(owner=owner)
        finally:
            db.close()

    def button(self, at: AppTest, label: str) -> Any:
        matches = [button for button in at.button if str(button.label) == label]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def plain_text(self, at: AppTest) -> str:
        texts: list[str] = []
        for collection_name in (
            "markdown",
            "text",
            "caption",
            "info",
            "warning",
            "success",
            "error",
        ):
            texts.extend(
                str(element.value) for element in getattr(at, collection_name, ())
            )
        for metric in at.metric:
            texts.extend((str(metric.label), str(metric.value)))
        return "\n".join(texts)

    def test_today_initial_load_is_read_only(self) -> None:
        before = self.app_run_count()
        counters: dict[str, int] = {}

        at = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, counters),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(self.app_run_count(), before)
        self.assertEqual(counters, {})
        self.assert_digest_lock_free()

    def test_today_refresh_rerun_is_read_only(self) -> None:
        before = self.app_run_count()
        counters: dict[str, int] = {}

        at = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, counters),
        ).run()
        at.run()
        at.run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(self.app_run_count(), before)
        self.assertEqual(counters, {})
        self.assert_digest_lock_free()

    def test_settings_initial_load_is_read_only(self) -> None:
        before = self.app_run_count()
        counters: dict[str, int] = {}

        at = AppTest.from_function(
            _settings_read_only_app,
            default_timeout=5,
            args=(self.root, counters),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(self.app_run_count(), before)
        self.assertEqual(counters, {})
        self.assert_digest_lock_free()

    def test_new_sessions_render_durable_source_coverage_on_today_and_settings(self) -> None:
        source_date = date.today()
        db = Database(_configure_env(self.root))
        try:
            profile = db.get_interest_profile(self.profile_id)
            source_config = db.get_arxiv_config()
            assert profile is not None
            assert source_config is not None
            run_id = db.create_app_run(
                profile_id=self.profile_id,
                profile_fingerprint=profile_semantic_fingerprint(profile),
                source_name="arxiv",
                source_fingerprint=source_config_semantic_fingerprint(source_config),
            )
            db.finish_app_run(
                run_id,
                status=APP_RUN_COMPLETED,
                retrieved_count=1,
                stored_count=1,
                preselected_count=1,
                skipped_analysis_count=0,
                analyzed_count=1,
                relevant_count=1,
                requested_source_dates=(source_date.isoformat(),),
                covered_source_dates=(source_date.isoformat(),),
            )
            db.mark_source_date_covered(
                source_name="arxiv",
                source_fingerprint=source_config_semantic_fingerprint(source_config),
                source_date=source_date,
                run_id=run_id,
                run_origin=RunOrigin.MANUAL,
            )
        finally:
            db.close()
        save_automation_settings(
            catch_up_missed_dates=True,
            coverage_start_date=source_date,
        )

        today = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()
        settings = AppTest.from_function(
            _settings_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()

        self.assertEqual([str(value) for value in today.exception], [])
        self.assertEqual([str(value) for value in settings.exception], [])
        self.assertTrue(any("Done" in str(element.value) for element in today.caption))
        self.assertTrue(any("Done" in str(element.value) for element in settings.caption))

        db = Database(_configure_env(self.root))
        try:
            profile = db.get_interest_profile(self.profile_id)
            assert profile is not None
            db.update_interest_profile(
                InterestProfile(
                    id=profile.id,
                    name=profile.name,
                    description=profile.description,
                    relevance_threshold=profile.relevance_threshold,
                    enabled=False,
                )
            )
        finally:
            db.close()

        settings_without_enabled_profile = AppTest.from_function(
            _settings_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()
        self.assertEqual(
            [str(value) for value in settings_without_enabled_profile.exception], []
        )
        self.assertTrue(
            any(
                "Done" in str(element.value)
                for element in settings_without_enabled_profile.caption
            )
        )

    def test_settings_initial_load_does_not_generate_suggested_interests(self) -> None:
        db = Database(_configure_env(self.root))
        try:
            profile = db.get_interest_profile(self.profile_id)
            assert profile is not None
            for index in range(3):
                article, _ = db.upsert_article(
                    _article(
                        f"2608.startup-suggestion-{index}",
                        f"Quantum code {index}",
                        "quant-ph",
                    )
                )
                assert article.id is not None
                db.upsert_article_feedback(
                    article_id=article.id,
                    profile_id=self.profile_id,
                    profile_fingerprint=profile_semantic_fingerprint(profile),
                    profile_match="NO",
                    personal_interest="YES",
                )
        finally:
            db.close()
        before = self.suggested_interest_count()

        with mock.patch(
            "research_digest.ui.pages.settings.refresh_suggested_interests",
            side_effect=AssertionError("Settings render must not refresh suggestions"),
        ):
            at = AppTest.from_function(
                _settings_read_only_app,
                default_timeout=5,
                args=(self.root, {}),
            ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(self.suggested_interest_count(), before)

    def test_legacy_history_does_not_trigger_today_run(self) -> None:
        db = Database(_configure_env(self.root))
        try:
            run_id = db.create_app_run(
                profile_id=self.profile_id,
                source_name="arxiv",
                run_origin=RunOrigin.LEGACY,
                date_selection=None,
            )
            db.finish_app_run(
                run_id,
                status=APP_RUN_COMPLETED,
                retrieved_count=1,
                stored_count=1,
                preselected_count=1,
                skipped_analysis_count=0,
                analyzed_count=1,
                relevant_count=0,
            )
        finally:
            db.close()
        before = self.app_run_count()
        counters: dict[str, int] = {}

        at = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, counters),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(self.app_run_count(), before)
        self.assertEqual(counters, {})
        self.assert_digest_lock_free()

        history = AppTest.from_function(
            _history_read_only_app,
            default_timeout=5,
            args=(self.root,),
        ).run()
        self.assertEqual([str(value) for value in history.exception], [])
        self.assertEqual(self.app_run_count(), before)
        self.assert_digest_lock_free()

    def test_today_idle_has_enabled_run_and_no_cancel_control(self) -> None:
        at = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertFalse(self.button(at, "Run digest").disabled)
        self.assertFalse(any(str(button.label) == "Cancel digest" for button in at.button))
        self.assertNotIn("Digest running", self.plain_text(at))

    def test_run_digest_launch_handoff_reattaches_without_duplicate_worker(self) -> None:
        counters: dict[str, int] = {}
        at = AppTest.from_function(
            _today_click_app,
            default_timeout=5,
            args=(self.root, counters),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(counters, {})

        self.button(at, "Run digest").click().run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(counters.get("worker_start"), 1)
        self.assertTrue(self.button(at, "Run digest").disabled)
        self.assertIn("Starting digest", self.plain_text(at))
        self.assertIn("Cancel digest will be available", self.plain_text(at))

        run_id, owner = self.start_active_manual_run()
        at.run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertTrue(self.button(at, "Run digest").disabled)
        self.assertEqual(str(self.button(at, "Cancel digest").label), "Cancel digest")
        button_labels = [str(button.label) for button in at.button]
        self.assertEqual(
            button_labels.index("Cancel digest") + 1,
            button_labels.index("Run digest"),
        )
        self.assertIn(f"Run #{run_id}", self.plain_text(at))
        self.assertIn("Manual · 2026-08-20", self.plain_text(at))
        self.assertIn("Analyzing stored papers", self.plain_text(at))
        self.assertIn("continues running independently", self.plain_text(at))
        self.assertIn("100", self.plain_text(at))
        self.assertIn("70", self.plain_text(at))
        self.assertIn("28", self.plain_text(at))

        at.run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(counters.get("worker_start"), 1)
        self.terminalize_run(run_id, owner, status=APP_RUN_CANCELLED)

    def test_today_cancel_uses_shared_service_once_and_returns_to_idle(self) -> None:
        from research_digest.cancellation import request_run_cancellation

        run_id, owner = self.start_active_manual_run()
        with mock.patch(
            "research_digest.ui.run_status.request_run_cancellation",
            wraps=request_run_cancellation,
        ) as cancel_service:
            at = AppTest.from_function(
                _today_read_only_app,
                default_timeout=5,
                args=(self.root, {}),
            ).run()
            self.button(at, "Cancel digest").click().run()

        self.assertEqual([str(value) for value in at.exception], [])
        cancel_service.assert_called_once()
        self.assertEqual(cancel_service.call_args.kwargs["run_id"], run_id)
        self.assertIn("Cancelling", self.plain_text(at))
        self.assertTrue(self.button(at, "Run digest").disabled)
        self.assertFalse(any(str(button.label) == "Cancel digest" for button in at.button))

        self.terminalize_run(run_id, owner, status=APP_RUN_CANCELLED)
        at.run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertFalse(self.button(at, "Run digest").disabled)
        self.assertFalse(any(str(button.label) == "Cancel digest" for button in at.button))
        self.assertIn(f"Digest run #{run_id} was cancelled", self.plain_text(at))

    def test_failed_detached_launch_restores_run_control_with_visible_error(self) -> None:
        counters: dict[str, int] = {}
        at = AppTest.from_function(
            _today_click_app,
            default_timeout=5,
            args=(self.root, counters, True),
        ).run()

        self.button(at, "Run digest").click().run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(counters.get("worker_start"), 1)
        self.assertFalse(self.button(at, "Run digest").disabled)
        self.assertIn("exited before registering a durable run", self.plain_text(at))
        self.assertFalse(any(str(button.label) == "Cancel digest" for button in at.button))

    def test_fragment_discovered_durable_run_promotes_outer_page_to_active(self) -> None:
        counters: dict[str, int] = {}
        at = AppTest.from_function(
            _today_external_active_race_app,
            default_timeout=5,
            args=(self.root, counters),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertGreaterEqual(counters.get("active_queries", 0), 4)
        self.assertTrue(self.button(at, "Run digest").disabled)
        self.assertEqual(str(self.button(at, "Cancel digest").label), "Cancel digest")
        self.assertIn("Run #41", self.plain_text(at))
        self.assertIn("Retrieving source papers", self.plain_text(at))

    def test_today_refresh_and_new_session_rediscover_active_run(self) -> None:
        run_id, owner = self.start_active_manual_run()
        at = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()
        at.run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(str(self.button(at, "Cancel digest").label), "Cancel digest")
        self.assertIn(f"Run #{run_id}", self.plain_text(at))

        reattached = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()
        settings = AppTest.from_function(
            _settings_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()
        self.assertEqual([str(value) for value in reattached.exception], [])
        self.assertEqual([str(value) for value in settings.exception], [])
        self.assertEqual(
            str(self.button(reattached, "Cancel digest").label),
            "Cancel digest",
        )
        self.assertEqual(str(self.button(settings, "Cancel digest").label), "Cancel digest")
        settings_button_labels = [str(button.label) for button in settings.button]
        self.assertEqual(
            settings_button_labels.index("Cancel digest") + 1,
            settings_button_labels.index("Run now"),
        )
        self.terminalize_run(run_id, owner, status=APP_RUN_CANCELLED)

    def test_today_completed_run_stops_polling_and_returns_to_idle(self) -> None:
        run_id, owner = self.start_active_manual_run()
        at = AppTest.from_function(
            _today_read_only_app,
            default_timeout=5,
            args=(self.root, {}),
        ).run()

        self.terminalize_run(run_id, owner, status=APP_RUN_COMPLETED)
        at.run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertFalse(self.button(at, "Run digest").disabled)
        self.assertFalse(any(str(button.label) == "Cancel digest" for button in at.button))


if __name__ == "__main__":
    unittest.main()
