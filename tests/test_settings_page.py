from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from research_digest.db import APP_RUN_COMPLETED, Database
from research_digest.doctor import DoctorCheck, DoctorReport, DoctorSeverity
from research_digest.models import RunOrigin
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
