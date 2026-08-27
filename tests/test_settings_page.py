from __future__ import annotations

import inspect
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from research_digest.automation import AutomationStatus
from research_digest.backup import BackupResult
from research_digest.db import APP_RUN_COMPLETED, Database
from research_digest.doctor import DoctorCheck, DoctorReport, DoctorSeverity
from research_digest.models import DateSelection, RunOrigin
from research_digest.scheduler import (
    WINDOWS_LOCAL_TIME_DESCRIPTION,
    ScheduleOperationResult,
    ScheduleStatus,
)
from research_digest.service import HeadlessDigestRun
from research_digest.ui.pages import settings


class SettingsPageTests(unittest.TestCase):
    def test_doctor_summary_reflects_failures_warnings_and_pass(self) -> None:
        failed = DoctorReport(
            checks=(
                DoctorCheck("provider", DoctorSeverity.FAILURE, "missing"),
                DoctorCheck("network", DoctorSeverity.WARNING, "skipped"),
            )
        )
        warning = DoctorReport(
            checks=(DoctorCheck("network", DoctorSeverity.WARNING, "skipped"),)
        )
        passed = DoctorReport(checks=(DoctorCheck("python", DoctorSeverity.PASS, "ok"),))

        self.assertEqual(settings.doctor_overall_severity(failed), DoctorSeverity.FAILURE)
        self.assertEqual(settings.doctor_summary(failed), "1 failure(s), 1 warning(s)")
        self.assertEqual(settings.doctor_overall_severity(warning), DoctorSeverity.WARNING)
        self.assertEqual(settings.doctor_summary(warning), "No failures, 1 warning(s)")
        self.assertEqual(settings.doctor_overall_severity(passed), DoctorSeverity.PASS)
        self.assertEqual(settings.doctor_summary(passed), "All checks passed")

    def test_provider_health_check_uses_doctor_report(self) -> None:
        provider = DoctorCheck("provider", DoctorSeverity.PASS, "Codex analyzer is configured.")
        report = DoctorReport(
            checks=(
                DoctorCheck("sqlite", DoctorSeverity.PASS, "ok"),
                provider,
            )
        )

        self.assertEqual(settings.provider_health_check(report), provider)
        self.assertIsNone(settings.provider_health_check(DoctorReport(checks=())))

    def test_preselection_effort_summary_describes_date_native_effort(self) -> None:
        summary = settings.preselection_effort_summary()

        self.assertIn("retrieves all eligible articles", summary)
        self.assertIn("selected source dates", summary)
        self.assertIn("Cached analyses are reused", summary)
        self.assertIn("abstract-level model preselection", summary)
        self.assertNotIn("deterministic abstract preselection", summary)

    def test_run_now_uses_configured_stage1_preselector(self) -> None:
        from research_digest import worker

        source = inspect.getsource(worker.main)

        self.assertIn("use_configured_preselector=True", source)

    def test_backup_result_message_shows_backup_and_optional_export(self) -> None:
        backup = BackupResult(
            db_path=Path("/tmp/research-digest.sqlite3"),
            backup_path=Path("/tmp/backups/research_digest.sqlite3"),
            export_path=None,
            schema_version=6,
        )
        exported = BackupResult(
            db_path=backup.db_path,
            backup_path=backup.backup_path,
            export_path=Path("/tmp/backups/research_digest.export.json"),
            schema_version=6,
        )

        self.assertEqual(
            settings.backup_result_message(backup),
            "Backup created at /tmp/backups/research_digest.sqlite3.",
        )
        self.assertIn("JSON export created", settings.backup_result_message(exported))

    def test_default_backup_directory_is_next_to_active_database(self) -> None:
        self.assertEqual(
            settings.default_backup_directory(Path("/tmp/research/research_digest.sqlite3")),
            Path("/tmp/research/backups"),
        )

    def test_schedule_time_default_uses_next_then_last_run(self) -> None:
        status = ScheduleStatus(
            backend="windows_task_scheduler",
            task_name="Research Digest Test",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            next_run_time="2026-08-17T07:30:00",
            last_run_time="2026-08-16T06:15:00",
        )
        fallback = ScheduleStatus(
            backend="windows_task_scheduler",
            task_name="Research Digest Test",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            last_run_time="2026-08-16T06:15:00",
        )

        self.assertEqual(settings.schedule_time_default(status), "07:30")
        self.assertEqual(settings.schedule_time_default(fallback), "06:15")
        self.assertEqual(settings.schedule_time_default(None), "07:30")

    def test_schedule_enabled_state_distinguishes_enabled_disabled_and_unknown(self) -> None:
        ready_zero = AutomationStatus(
            ok=True,
            schedule=ScheduleStatus(
                backend="windows_task_scheduler",
                task_name="Research Digest Test",
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Ready",
                last_task_result=0,
            ),
        )
        ready_nonzero = AutomationStatus(
            ok=True,
            schedule=ScheduleStatus(
                backend="windows_task_scheduler",
                task_name="Research Digest Test",
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Ready",
                last_task_result=3221225786,
                next_run_time="2026-08-19T06:00:00",
            ),
        )
        disabled = AutomationStatus(
            ok=True,
            schedule=ScheduleStatus(
                backend="windows_task_scheduler",
                task_name="Research Digest Test",
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Disabled",
            ),
        )
        missing = AutomationStatus(
            ok=True,
            schedule=ScheduleStatus(
                backend="windows_task_scheduler",
                task_name="Research Digest Test",
                installed=False,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            ),
        )
        unknown = AutomationStatus(ok=False, schedule=None, error_message="parse failed")

        self.assertTrue(settings.schedule_enabled_state(ready_zero))
        self.assertTrue(settings.schedule_enabled_state(ready_nonzero))
        self.assertFalse(settings.schedule_enabled_state(disabled))
        self.assertFalse(settings.schedule_enabled_state(missing))
        self.assertIsNone(settings.schedule_enabled_state(unknown))

    def test_schedule_operation_message_is_user_facing(self) -> None:
        installed = ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name="Research Digest Test",
            operation="installed_or_updated",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
        )
        removed = ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name="Research Digest Test",
            operation="removed",
            installed=False,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
        )

        self.assertEqual(settings.schedule_operation_message(installed), "Schedule updated.")
        self.assertEqual(settings.schedule_operation_message(removed), "Schedule disabled.")

    def test_run_now_summary_includes_counts_and_dates(self) -> None:
        result = HeadlessDigestRun(
            profiles=(),
            pending_source_dates=(date(2026, 8, 14), date(2026, 8, 15)),
            latest_available_source_date=date(2026, 8, 15),
        )
        empty = HeadlessDigestRun(profiles=())

        self.assertIn("source dates 2026-08-14, 2026-08-15", settings.run_now_summary(result))
        self.assertIn("no uncovered source dates", settings.run_now_summary(empty))

    def test_run_now_summary_includes_run_ids_and_date_outcomes(self) -> None:
        result = SimpleNamespace(
            profiles=(
                SimpleNamespace(
                    success=True,
                    digest=SimpleNamespace(
                        digest=SimpleNamespace(
                            run_id=30,
                            run_status=APP_RUN_COMPLETED,
                            date_selection=DateSelection.date_range(
                                date(2026, 8, 14),
                                date(2026, 8, 15),
                            ),
                            retrieval_complete=True,
                            incomplete_source_dates=(),
                            analysis_complete=True,
                            retrieved_count=19,
                            covered_source_dates=(date(2026, 8, 14), date(2026, 8, 15)),
                            empty_source_dates=(date(2026, 8, 15),),
                        )
                    ),
                ),
            ),
            succeeded_count=1,
            failed_count=0,
            retrieved_count=19,
            analyzed_count=17,
            relevant_count=2,
            pending_source_dates=(date(2026, 8, 14), date(2026, 8, 15)),
        )

        summary = settings.run_now_summary(result)

        self.assertIn("runs #30", summary)
        self.assertIn("completed 1", summary)
        self.assertIn("empty 1", summary)
        self.assertIn("partial 0", summary)
        self.assertIn("failed 0", summary)

    def test_run_now_summary_reports_incomplete_completed_status_as_partial(self) -> None:
        result = SimpleNamespace(
            profiles=(
                SimpleNamespace(
                    profile_id=7,
                    success=False,
                    error_message="Retrieval failed with OPENAI_API_KEY=sk-secret123456789",
                    digest=SimpleNamespace(
                        digest=SimpleNamespace(
                            run_id=31,
                            run_status=APP_RUN_COMPLETED,
                            date_selection=DateSelection.single_date(date(2026, 8, 14)),
                            retrieval_complete=False,
                            incomplete_source_dates=(date(2026, 8, 14),),
                            analysis_complete=True,
                            retrieved_count=19,
                            requested_source_dates=(date(2026, 8, 14),),
                            covered_source_dates=(date(2026, 8, 14),),
                            empty_source_dates=(),
                        )
                    ),
                ),
            ),
            succeeded_count=0,
            failed_count=1,
            retrieved_count=19,
            analyzed_count=17,
            relevant_count=2,
            pending_source_dates=(date(2026, 8, 14),),
        )

        summary = settings.run_now_summary(result)

        self.assertIn("runs #31", summary)
        self.assertIn("completed 0", summary)
        self.assertIn("empty 0", summary)
        self.assertIn("partial 1", summary)
        self.assertIn("failed 0", summary)
        self.assertIn("profile 7", summary)
        self.assertIn("[REDACTED_API_KEY]", summary)
        self.assertNotIn("sk-secret", summary)

    def test_run_now_notice_level_reflects_profile_failures(self) -> None:
        all_failed = SimpleNamespace(succeeded_count=0, failed_count=1)
        mixed = SimpleNamespace(succeeded_count=1, failed_count=1)
        passed = SimpleNamespace(succeeded_count=1, failed_count=0)

        self.assertEqual(settings.run_now_notice_level(all_failed), "error")
        self.assertEqual(settings.run_now_notice_level(mixed), "warning")
        self.assertEqual(settings.run_now_notice_level(passed), "success")

    def test_run_now_noop_message_explains_anchor_after_latest(self) -> None:
        message = settings.run_now_noop_message(
            coverage_start_date=date(2026, 8, 17),
            latest_available_source_date=date(2026, 8, 14),
        )

        self.assertIn("No pending source dates", message)
        self.assertIn("Catch-up starts 2026-08-17", message)
        self.assertIn("Latest available source date is 2026-08-14", message)

    def test_last_scheduled_digest_outcome_prefers_scheduled_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.sqlite3")
            manual = db.create_app_run(profile_id=None, source_name="arxiv")
            db.finish_app_run(
                manual,
                status=APP_RUN_COMPLETED,
                retrieved_count=9,
                stored_count=9,
                preselected_count=9,
                skipped_analysis_count=0,
                analyzed_count=9,
                relevant_count=1,
            )
            scheduled = db.create_app_run(
                profile_id=None,
                source_name="arxiv",
                run_origin=RunOrigin.SCHEDULED,
            )
            db.finish_app_run(
                scheduled,
                status=APP_RUN_COMPLETED,
                retrieved_count=3,
                stored_count=3,
                preselected_count=3,
                skipped_analysis_count=0,
                analyzed_count=2,
                relevant_count=1,
            )

            outcome = settings.last_scheduled_digest_outcome(db)

        self.assertIn(f"run #{scheduled} completed", outcome)
        self.assertIn("retrieved 3", outcome)


if __name__ == "__main__":
    unittest.main()
