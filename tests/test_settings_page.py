from __future__ import annotations

import unittest

from research_digest.doctor import DoctorCheck, DoctorReport, DoctorSeverity
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


if __name__ == "__main__":
    unittest.main()
