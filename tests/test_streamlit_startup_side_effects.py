from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from research_digest.db import APP_RUN_COMPLETED, Database
from research_digest.models import (
    Article,
    ArxivSourceConfig,
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
    original_source = today_module["ArxivSource"]
    original_run = today_module["run_digest_for_profile"]
    original_get_analyzer = today_module["get_analyzer"]
    original_get_context = today_module["get_library_context_generator"]

    class ForbiddenSource:
        def resolve_latest_available_date(self, config: object) -> object:
            counters["source_fetch"] = counters.get("source_fetch", 0) + 1
            raise AssertionError("startup must not resolve latest arXiv date")

        def fetch(self, *args: object, **kwargs: object) -> list[object]:
            counters["source_fetch"] = counters.get("source_fetch", 0) + 1
            raise AssertionError("startup must not fetch arXiv")

        def fetch_date_selection(self, *args: object, **kwargs: object) -> object:
            counters["source_fetch"] = counters.get("source_fetch", 0) + 1
            raise AssertionError("startup must not fetch arXiv date selections")

    def forbidden_run(*args: object, **kwargs: object) -> object:
        counters["run_service"] = counters.get("run_service", 0) + 1
        raise AssertionError("startup must not run a digest")

    def forbidden_analyzer() -> tuple[object | None, str | None]:
        counters["analyzer"] = counters.get("analyzer", 0) + 1
        raise AssertionError("startup must not build the analyzer")

    def forbidden_context() -> tuple[object | None, str | None]:
        counters["context"] = counters.get("context", 0) + 1
        raise AssertionError("startup must not build Library context generator")

    today_module["ArxivSource"] = ForbiddenSource
    today_module["run_digest_for_profile"] = forbidden_run
    today_module["get_analyzer"] = forbidden_analyzer
    today_module["get_library_context_generator"] = forbidden_context
    try:
        today_module["render"]()
    finally:
        today_module["ArxivSource"] = original_source
        today_module["run_digest_for_profile"] = original_run
        today_module["get_analyzer"] = original_get_analyzer
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
    original_source = settings_module["ArxivSource"]
    original_run_now = settings_module["run_automatic_digest_now"]

    class ForbiddenSource:
        def resolve_latest_available_date(self, config: object) -> object:
            counters["source_fetch"] = counters.get("source_fetch", 0) + 1
            raise AssertionError("Settings startup must not resolve latest arXiv date")

    def forbidden_run_now(*args: object, **kwargs: object) -> object:
        counters["run_now"] = counters.get("run_now", 0) + 1
        raise AssertionError("Settings startup must not run automatic catch-up")

    settings_module["ArxivSource"] = ForbiddenSource
    settings_module["run_automatic_digest_now"] = forbidden_run_now
    try:
        settings_module["render"]()
    finally:
        settings_module["ArxivSource"] = original_source
        settings_module["run_automatic_digest_now"] = original_run_now


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


def _today_click_app(root: str, counters: dict[str, int]) -> None:
    import os
    from datetime import UTC, date, datetime
    from importlib import import_module
    from pathlib import Path
    from types import SimpleNamespace
    from typing import cast

    from research_digest.db import Database
    from research_digest.models import DateSelection, DigestResult, RunOrigin

    root_path = Path(root)
    os.environ["RESEARCH_DIGEST_CONFIG_DIR"] = str(root_path / "config")
    os.environ["RESEARCH_DIGEST_DATA_DIR"] = str(root_path / "data")
    os.environ["RESEARCH_DIGEST_LEGACY_DB"] = str(root_path / "missing.sqlite3")
    import streamlit as st

    st.cache_resource.clear()
    today = import_module("research_digest.ui.pages.today")
    today_module = vars(today)
    original_run = today_module["run_digest_for_profile"]
    original_get_analyzer = today_module["get_analyzer"]
    original_get_context = today_module["get_library_context_generator"]
    original_source = today_module["ArxivSource"]

    class ExplicitSource:
        pass

    def fake_get_analyzer() -> tuple[object, None]:
        counters["analyzer"] = counters.get("analyzer", 0) + 1
        return object(), None

    def fake_get_context() -> tuple[None, None]:
        counters["context"] = counters.get("context", 0) + 1
        return None, None

    def fake_run_digest_for_profile(*args: object, **kwargs: object) -> SimpleNamespace:
        counters["run_service"] = counters.get("run_service", 0) + 1
        db = cast(Database, kwargs["db"])
        profile_id = cast(int, kwargs["profile_id"])
        profile = db.get_interest_profile(profile_id)
        source_config = db.get_arxiv_config()
        if profile is None or source_config is None:
            raise AssertionError("test profile/source config missing")
        result = DigestResult(
            run_id=100 + counters["run_service"],
            profile=profile,
            source_config=source_config,
            retrieved_count=0,
            stored_count=0,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            new_analysis_count=0,
            reused_analysis_count=0,
            above_threshold_count=0,
            analysis_available=True,
            items=[],
            started_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
            completed_at=datetime(2026, 8, 18, 12, 1, tzinfo=UTC),
            run_origin=RunOrigin.MANUAL,
            date_selection=DateSelection.latest_available(),
            requested_source_dates=(date(2026, 8, 14),),
            covered_source_dates=(date(2026, 8, 14),),
        )
        return SimpleNamespace(digest=result)

    today_module["ArxivSource"] = ExplicitSource
    today_module["get_analyzer"] = fake_get_analyzer
    today_module["get_library_context_generator"] = fake_get_context
    today_module["run_digest_for_profile"] = fake_run_digest_for_profile
    try:
        today_module["render"]()
    finally:
        today_module["ArxivSource"] = original_source
        today_module["get_analyzer"] = original_get_analyzer
        today_module["get_library_context_generator"] = original_get_context
        today_module["run_digest_for_profile"] = original_run


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

    def test_run_digest_button_invokes_service_once_and_rerun_does_not_duplicate(self) -> None:
        counters: dict[str, int] = {}
        at = AppTest.from_function(
            _today_click_app,
            default_timeout=5,
            args=(self.root, counters),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(counters, {})

        at.button[0].click().run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(counters.get("run_service"), 1)
        self.assertEqual(counters.get("analyzer"), 1)

        at.run()
        self.assertEqual([str(value) for value in at.exception], [])
        self.assertEqual(counters.get("run_service"), 1)


if __name__ == "__main__":
    unittest.main()
