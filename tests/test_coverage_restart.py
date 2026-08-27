from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path
from typing import cast
from unittest import mock

from streamlit.testing.v1 import AppTest

from research_digest.config import load_config, save_automation_settings
from research_digest.coverage import (
    build_automatic_coverage_plan,
    build_coverage_scope,
    build_date_coverage_statuses,
    source_config_semantic_fingerprint,
)
from research_digest.db import (
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_PARTIAL,
    SOURCE_ARXIV,
    Database,
)
from research_digest.models import (
    ArxivSourceConfig,
    DateSelection,
    InterestProfile,
    RunOrigin,
    profile_semantic_fingerprint,
)

SOURCE_DATE = date(2026, 8, 14)


class StaticLatestDateResolver:
    def __init__(self, latest_date: date) -> None:
        self.latest_date = latest_date

    def resolve_latest_available_date(self, config: ArxivSourceConfig) -> date | None:
        return self.latest_date if config.enabled else None


def _isolated_env(root: Path) -> dict[str, str]:
    return {
        "RESEARCH_DIGEST_DATA_DIR": str(root / "data"),
        "RESEARCH_DIGEST_CONFIG_DIR": str(root / "config"),
        "RESEARCH_DIGEST_LEGACY_DB": str(root / "missing.sqlite3"),
    }


def _create_profile(db: Database) -> InterestProfile:
    return db.create_interest_profile(
        name="Restart fixture",
        description="Stable deterministic fixture semantics.",
        relevance_threshold=0.7,
    )


def _create_terminal_run(
    db: Database,
    *,
    profile: InterestProfile,
    source_config: ArxivSourceConfig,
    source_date: date,
    status: str,
    covered: bool,
    incomplete: bool = False,
    retrieval_complete: bool | None = None,
) -> int:
    scope = build_coverage_scope(
        profile=profile,
        source_name=SOURCE_ARXIV,
        source_config=source_config,
    )
    run_id = db.create_app_run(
        profile_id=profile.id,
        profile_fingerprint=profile_semantic_fingerprint(profile),
        source_name=scope.source_name,
        source_fingerprint=scope.source_fingerprint,
        date_selection=DateSelection.single_date(source_date),
    )
    db.finish_app_run(
        run_id,
        status=status,
        retrieved_count=1,
        stored_count=1,
        preselected_count=1,
        skipped_analysis_count=0,
        analyzed_count=1 if status == APP_RUN_COMPLETED else 0,
        relevant_count=1 if status == APP_RUN_COMPLETED else 0,
        requested_source_dates=(source_date.isoformat(),),
        covered_source_dates=(source_date.isoformat(),) if covered else (),
        incomplete_source_dates=(source_date.isoformat(),) if incomplete else (),
        retrieval_complete=not incomplete if retrieval_complete is None else retrieval_complete,
    )
    return run_id


def _mark_covered(
    db: Database,
    *,
    profile: InterestProfile,
    source_config: ArxivSourceConfig,
    source_date: date = SOURCE_DATE,
) -> int:
    run_id = _create_terminal_run(
        db,
        profile=profile,
        source_config=source_config,
        source_date=source_date,
        status=APP_RUN_COMPLETED,
        covered=True,
    )
    scope = build_coverage_scope(
        profile=profile,
        source_name=SOURCE_ARXIV,
        source_config=source_config,
    )
    db.mark_source_date_covered(
        source_name=scope.source_name,
        source_fingerprint=scope.source_fingerprint,
        source_date=source_date,
        run_id=run_id,
        run_origin=RunOrigin.MANUAL,
    )
    return run_id


def _status(
    db: Database,
    *,
    profile: InterestProfile,
    source_config: ArxivSourceConfig,
    source_date: date = SOURCE_DATE,
    selected_dates: tuple[date, ...] = (),
) -> str:
    return build_date_coverage_statuses(
        db=db,
        profile=profile,
        source_name=SOURCE_ARXIV,
        source_config=source_config,
        start_date=source_date,
        end_date=source_date,
        selected_dates=selected_dates,
    )[0].status


def _streamlit_durable_status_app(db_path: str, source_date_iso: str) -> None:
    from datetime import date

    import streamlit as st

    from research_digest.coverage import build_date_coverage_statuses
    from research_digest.db import SOURCE_ARXIV, Database

    initial_session_empty = len(st.session_state) == 0
    db = Database(db_path)
    profile = db.list_interest_profiles(enabled_only=True)[0]
    source_config = db.get_arxiv_config()
    assert source_config is not None
    source_date = date.fromisoformat(source_date_iso)
    status = build_date_coverage_statuses(
        db=db,
        profile=profile,
        source_name=SOURCE_ARXIV,
        source_config=source_config,
        start_date=source_date,
        end_date=source_date,
    )[0]
    st.caption(f"initial_session_empty={initial_session_empty}")
    st.caption(f"durable_status={status.status}")


class CoverageRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "research_digest.sqlite3"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_same_process_reload_keeps_completed_status_and_selection_is_overlay(self) -> None:
        db = Database(self.db_path)
        profile = _create_profile(db)
        source_config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        _mark_covered(db, profile=profile, source_config=source_config)

        first = _status(db, profile=profile, source_config=source_config)
        second_status = build_date_coverage_statuses(
            db=db,
            profile=profile,
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            start_date=SOURCE_DATE,
            end_date=SOURCE_DATE,
            selected_dates=(SOURCE_DATE,),
        )[0]

        self.assertEqual(first, "completed")
        self.assertEqual(second_status.status, "completed")
        self.assertTrue(second_status.selected)

    def test_new_database_and_config_objects_preserve_fingerprints_and_coverage(self) -> None:
        with mock.patch.dict(os.environ, _isolated_env(self.root), clear=True):
            first_config = load_config()
            first_db = Database(first_config.db_path)
            profile = _create_profile(first_db)
            source_config = ArxivSourceConfig(
                categories=[" hep-th ", "gr-qc", "hep-th"]
            )
            first_db.save_arxiv_config(source_config)
            _mark_covered(first_db, profile=profile, source_config=source_config)
            first_scope = build_coverage_scope(
                profile=profile,
                source_name=SOURCE_ARXIV,
                source_config=source_config,
            )
            save_automation_settings(
                catch_up_missed_dates=True,
                coverage_start_date=SOURCE_DATE,
            )
            first_db.close()

            second_config = load_config()
            second_db = Database(second_config.db_path)
            reloaded_profile = second_db.list_interest_profiles(enabled_only=True)[0]
            reloaded_source = cast(ArxivSourceConfig, second_db.get_arxiv_config())
            second_scope = build_coverage_scope(
                profile=reloaded_profile,
                source_name=SOURCE_ARXIV,
                source_config=reloaded_source,
            )

            self.assertEqual(first_config.db_path, second_config.db_path)
            self.assertEqual(second_config.automatic_coverage_start_date, SOURCE_DATE)
            self.assertEqual(reloaded_source.categories, ["gr-qc", "hep-th"])
            self.assertEqual(
                profile_semantic_fingerprint(profile),
                profile_semantic_fingerprint(reloaded_profile),
            )
            self.assertEqual(first_scope.source_fingerprint, second_scope.source_fingerprint)
            self.assertEqual(
                _status(
                    second_db,
                    profile=reloaded_profile,
                    source_config=reloaded_source,
                ),
                "completed",
            )

    def test_category_reorder_survives_restart_but_set_change_creates_new_scope(self) -> None:
        first_db = Database(self.db_path)
        profile = _create_profile(first_db)
        original = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        _mark_covered(first_db, profile=profile, source_config=original)
        first_db.close()

        second_db = Database(self.db_path)
        reloaded_profile = cast(
            InterestProfile,
            second_db.get_interest_profile(cast(int, profile.id)),
        )
        reordered = ArxivSourceConfig(categories=["gr-qc", " hep-th ", "gr-qc"])
        changed = ArxivSourceConfig(categories=["astro-ph.CO", "gr-qc"])
        resolver = StaticLatestDateResolver(SOURCE_DATE)

        same_plan = build_automatic_coverage_plan(
            db=second_db,
            profiles=(reloaded_profile,),
            source_name=SOURCE_ARXIV,
            source_config=reordered,
            latest_resolver=resolver,
            coverage_start_date=SOURCE_DATE,
            catch_up_missed_dates=True,
        )
        changed_plan = build_automatic_coverage_plan(
            db=second_db,
            profiles=(reloaded_profile,),
            source_name=SOURCE_ARXIV,
            source_config=changed,
            latest_resolver=resolver,
            coverage_start_date=SOURCE_DATE,
            catch_up_missed_dates=True,
        )

        self.assertEqual(
            source_config_semantic_fingerprint(original),
            source_config_semantic_fingerprint(reordered),
        )
        self.assertEqual(
            _status(second_db, profile=reloaded_profile, source_config=reordered),
            "completed",
        )
        self.assertEqual(same_plan.pending_dates, ())
        self.assertNotEqual(
            source_config_semantic_fingerprint(original),
            source_config_semantic_fingerprint(changed),
        )
        self.assertEqual(changed_plan.pending_dates, (SOURCE_DATE,))

    def test_profile_reload_and_semantic_edit_preserve_source_scope(self) -> None:
        first_db = Database(self.db_path)
        profile = _create_profile(first_db)
        source_config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        _mark_covered(first_db, profile=profile, source_config=source_config)
        original_fingerprint = profile_semantic_fingerprint(profile)
        first_db.close()

        second_db = Database(self.db_path)
        unchanged = cast(InterestProfile, second_db.get_interest_profile(cast(int, profile.id)))
        self.assertEqual(profile_semantic_fingerprint(unchanged), original_fingerprint)
        self.assertEqual(
            _status(second_db, profile=unchanged, source_config=source_config),
            "completed",
        )

        changed = second_db.update_interest_profile(
            InterestProfile(
                id=unchanged.id,
                name=unchanged.name,
                description="A genuine change in fixture digest semantics.",
                relevance_threshold=unchanged.relevance_threshold,
                enabled=unchanged.enabled,
            )
        )
        changed_plan = build_automatic_coverage_plan(
            db=second_db,
            profiles=(changed,),
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            latest_resolver=StaticLatestDateResolver(SOURCE_DATE),
            coverage_start_date=SOURCE_DATE,
            catch_up_missed_dates=True,
        )

        self.assertNotEqual(profile_semantic_fingerprint(changed), original_fingerprint)
        self.assertEqual(changed_plan.pending_dates, ())
        self.assertEqual(
            _status(second_db, profile=changed, source_config=source_config),
            "completed",
        )

    def test_empty_streamlit_session_renders_durable_completed_status(self) -> None:
        db = Database(self.db_path)
        profile = _create_profile(db)
        source_config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        db.save_arxiv_config(source_config)
        _mark_covered(db, profile=profile, source_config=source_config)
        db.close()

        at = AppTest.from_function(
            _streamlit_durable_status_app,
            default_timeout=5,
            args=(str(self.db_path), SOURCE_DATE.isoformat()),
        ).run()

        self.assertEqual([str(value) for value in at.exception], [])
        captions = [str(element.value) for element in at.caption]
        self.assertIn("initial_session_empty=True", captions)
        self.assertIn("durable_status=completed", captions)

    def test_app_run_fallback_uses_retrieval_metadata_not_analysis_status(self) -> None:
        db = Database(self.db_path)
        profile = _create_profile(db)
        source_config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        completed_date = SOURCE_DATE
        analysis_failed_date = date(2026, 8, 15)
        network_failed_date = date(2026, 8, 16)
        partial_date = date(2026, 8, 17)
        mixed_covered_date = date(2026, 8, 18)
        mixed_incomplete_date = date(2026, 8, 19)
        _create_terminal_run(
            db,
            profile=profile,
            source_config=source_config,
            source_date=completed_date,
            status=APP_RUN_COMPLETED,
            covered=True,
        )
        _create_terminal_run(
            db,
            profile=profile,
            source_config=source_config,
            source_date=analysis_failed_date,
            status=APP_RUN_FAILED,
            covered=True,
        )
        _create_terminal_run(
            db,
            profile=profile,
            source_config=source_config,
            source_date=network_failed_date,
            status=APP_RUN_FAILED,
            covered=False,
            retrieval_complete=False,
        )
        _create_terminal_run(
            db,
            profile=profile,
            source_config=source_config,
            source_date=partial_date,
            status=APP_RUN_PARTIAL,
            covered=True,
            incomplete=True,
        )
        scope = build_coverage_scope(
            source_name=SOURCE_ARXIV,
            source_config=source_config,
        )
        mixed_run_id = db.create_app_run(
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            source_name=scope.source_name,
            source_fingerprint=scope.source_fingerprint,
            date_selection=DateSelection.date_range(
                mixed_covered_date,
                mixed_incomplete_date,
            ),
        )
        db.finish_app_run(
            mixed_run_id,
            status=APP_RUN_PARTIAL,
            retrieved_count=1,
            stored_count=1,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            relevant_count=0,
            requested_source_dates=(
                mixed_covered_date.isoformat(),
                mixed_incomplete_date.isoformat(),
            ),
            covered_source_dates=(mixed_covered_date.isoformat(),),
            incomplete_source_dates=(mixed_incomplete_date.isoformat(),),
            retrieval_complete=False,
        )

        statuses = {
            item.source_date: item.status
            for item in build_date_coverage_statuses(
                db=db,
                profile=profile,
                source_name=SOURCE_ARXIV,
                source_config=source_config,
                start_date=completed_date,
                end_date=mixed_incomplete_date,
            )
        }
        plan = build_automatic_coverage_plan(
            db=db,
            profiles=(profile,),
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            latest_resolver=StaticLatestDateResolver(mixed_incomplete_date),
            coverage_start_date=completed_date,
            catch_up_missed_dates=True,
        )

        self.assertEqual(db.list_source_date_coverage(), [])
        self.assertEqual(statuses[completed_date], "completed")
        self.assertEqual(statuses[analysis_failed_date], "completed")
        self.assertEqual(statuses[network_failed_date], "failed")
        self.assertEqual(statuses[partial_date], "partial")
        self.assertEqual(statuses[mixed_covered_date], "completed")
        self.assertEqual(statuses[mixed_incomplete_date], "partial")
        self.assertEqual(
            plan.pending_dates,
            (network_failed_date, partial_date, mixed_incomplete_date),
        )

    def test_success_after_failure_is_completed_after_restart_and_history_is_preserved(
        self,
    ) -> None:
        first_db = Database(self.db_path)
        profile = _create_profile(first_db)
        source_config = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
        failed_run = _create_terminal_run(
            first_db,
            profile=profile,
            source_config=source_config,
            source_date=SOURCE_DATE,
            status=APP_RUN_FAILED,
            covered=False,
        )
        completed_run = _create_terminal_run(
            first_db,
            profile=profile,
            source_config=source_config,
            source_date=SOURCE_DATE,
            status=APP_RUN_COMPLETED,
            covered=True,
        )
        first_db.close()

        second_db = Database(self.db_path)
        reloaded = cast(InterestProfile, second_db.get_interest_profile(cast(int, profile.id)))
        rows = second_db.get_app_runs()
        status = build_date_coverage_statuses(
            db=second_db,
            profile=reloaded,
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            start_date=SOURCE_DATE,
            end_date=SOURCE_DATE,
        )[0]

        self.assertEqual(status.status, "completed")
        self.assertEqual(status.run_id, completed_run)
        self.assertEqual([int(row["id"]) for row in rows], [completed_run, failed_run])
        self.assertEqual([str(row["status"]) for row in rows], [APP_RUN_COMPLETED, APP_RUN_FAILED])

    def test_fresh_process_pending_planner_excludes_durable_completed_date(self) -> None:
        env = os.environ.copy()
        env.update(_isolated_env(self.root))
        repo_root = Path(__file__).resolve().parents[1]
        write_script = textwrap.dedent(
            f"""
            from datetime import date
            from research_digest.config import load_config
            from research_digest.coverage import build_coverage_scope
            from research_digest.db import APP_RUN_COMPLETED, SOURCE_ARXIV, Database
            from research_digest.models import (
                ArxivSourceConfig,
                DateSelection,
                RunOrigin,
                profile_semantic_fingerprint,
            )

            config = load_config()
            db = Database(config.db_path)
            profile = db.create_interest_profile(
                name="Process fixture",
                description="Stable separate-process semantics.",
                relevance_threshold=0.7,
            )
            source = ArxivSourceConfig(categories=["hep-th", "gr-qc"])
            db.save_arxiv_config(source)
            scope = build_coverage_scope(
                profile=profile,
                source_name=SOURCE_ARXIV,
                source_config=source,
            )
            source_date = date.fromisoformat("{SOURCE_DATE.isoformat()}")
            run_id = db.create_app_run(
                profile_id=profile.id,
                profile_fingerprint=profile_semantic_fingerprint(profile),
                source_name=scope.source_name,
                source_fingerprint=scope.source_fingerprint,
                date_selection=DateSelection.single_date(source_date),
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
                source_name=scope.source_name,
                source_fingerprint=scope.source_fingerprint,
                source_date=source_date,
                run_id=run_id,
                run_origin=RunOrigin.MANUAL,
            )
            print(profile_semantic_fingerprint(profile) + ":" + scope.source_fingerprint)
            """
        )
        read_script = textwrap.dedent(
            f"""
            import json
            from datetime import date
            from research_digest.config import load_config
            from research_digest.coverage import (
                build_automatic_coverage_plan,
                build_coverage_scope,
                build_date_coverage_statuses,
            )
            from research_digest.db import SOURCE_ARXIV, Database
            from research_digest.models import profile_semantic_fingerprint

            class Resolver:
                def resolve_latest_available_date(self, source_config):
                    return date.fromisoformat("{SOURCE_DATE.isoformat()}")

            config = load_config()
            db = Database(config.db_path)
            profile = db.list_interest_profiles(enabled_only=True)[0]
            source = db.get_arxiv_config()
            assert source is not None
            source_date = date.fromisoformat("{SOURCE_DATE.isoformat()}")
            scope = build_coverage_scope(
                profile=profile,
                source_name=SOURCE_ARXIV,
                source_config=source,
            )
            status = build_date_coverage_statuses(
                db=db,
                profile=profile,
                source_name=SOURCE_ARXIV,
                source_config=source,
                start_date=source_date,
                end_date=source_date,
            )[0]
            plan = build_automatic_coverage_plan(
                db=db,
                profiles=(profile,),
                source_name=SOURCE_ARXIV,
                source_config=source,
                latest_resolver=Resolver(),
                coverage_start_date=source_date,
                catch_up_missed_dates=True,
            )
            print(json.dumps({{
                "fingerprints": (
                    profile_semantic_fingerprint(profile)
                    + ":"
                    + scope.source_fingerprint
                ),
                "status": status.status,
                "pending": [value.isoformat() for value in plan.pending_dates],
                "coverage_rows": len(db.list_source_date_coverage()),
                "app_runs": len(db.get_app_runs()),
            }}, sort_keys=True))
            """
        )

        written = subprocess.run(
            [sys.executable, "-c", write_script],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        read = subprocess.run(
            [sys.executable, "-c", read_script],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(read.stdout)

        self.assertEqual(payload["fingerprints"], written.stdout.strip())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["pending"], [])
        self.assertEqual(payload["coverage_rows"], 1)
        self.assertEqual(payload["app_runs"], 1)

    def test_today_and_automation_use_the_same_authoritative_status_builder(self) -> None:
        from importlib import import_module

        today = vars(import_module("research_digest.ui.pages.today"))
        settings = vars(import_module("research_digest.ui.pages.settings"))

        self.assertIs(
            today["build_date_coverage_statuses"],
            settings["build_date_coverage_statuses"],
        )


if __name__ == "__main__":
    unittest.main()
