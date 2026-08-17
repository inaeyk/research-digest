from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.db import APP_RUN_COMPLETED, APP_RUN_FAILED, Database
from research_digest.doctor import DoctorSeverity, run_doctor
from research_digest.scheduler import ScheduleError, ScheduleOperationResult, ScheduleStatus


class InstalledSchedulerBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        return ScheduleStatus(
            backend="test",
            task_name=task_name,
            installed=True,
            timezone="test local time",
        )


class FailingSchedulerBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        raise ScheduleError(
            "scheduler failed at /home/"
            + "inaeyk/private with OPENAI_API_KEY=sk-secret"
        )


class LeakySchedulerStatusBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        return ScheduleStatus(
            backend="test",
            task_name=task_name,
            installed=False,
            timezone="test local time",
            message="OPENAI_API_KEY=sk-secret123456789 at /home/inaeyk/private",
        )


class StaleCodexPathSchedulerBackend:
    def install(self, request: object) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("not used")

    def status(self, *, task_name: str) -> ScheduleStatus:
        return ScheduleStatus(
            backend="test",
            task_name=task_name,
            installed=True,
            timezone="test local time",
            arguments=(
                "-d Ubuntu --exec env "
                "PATH=/old/node/bin:/usr/local/bin:/usr/bin "
                "/tmp/venv/bin/research-digest run"
            ),
        )


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.db = Database(self.db_path)
        self.config = AppConfig(
            db_path=self.db_path,
            data_dir=self.db_path.parent,
            config_dir=self.db_path.parent / "config",
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="unused",
            codex_model=None,
            codex_timeout_seconds=1,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_doctor_json_success_warning_and_failure(self) -> None:
        self.db.create_app_run(profile_id=None, source_name="arxiv")
        run_id = self.db.create_app_run(profile_id=None, source_name="arxiv")
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_COMPLETED,
            retrieved_count=1,
            stored_count=1,
            preselected_count=1,
            skipped_analysis_count=0,
            analyzed_count=1,
            relevant_count=1,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            exit_code = run_cli(
                argv=["doctor", "--json"],
                stdout=stdout,
                stderr=stderr,
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        severities = {check["name"]: check["severity"] for check in payload["checks"]}
        self.assertEqual(severities["python"], DoctorSeverity.PASS)
        self.assertEqual(severities["provider"], DoctorSeverity.PASS)
        self.assertEqual(severities["network"], DoctorSeverity.WARNING)

    def test_missing_codex_executable_is_failure(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
            )

        provider = _check(report.to_mapping(), "provider")
        self.assertEqual(provider["severity"], DoctorSeverity.FAILURE)
        self.assertEqual(report.exit_code, 1)

    def test_openai_without_api_key_is_failure_without_secret_output(self) -> None:
        config = AppConfig(
            db_path=self.db_path,
            data_dir=self.db_path.parent,
            config_dir=self.db_path.parent / "config",
            analyzer_provider="openai",
            openai_api_key=None,
            openai_model="gpt-test",
            codex_model=None,
            codex_timeout_seconds=1,
        )

        report = run_doctor(
            config=config,
            db=self.db,
            scheduler_backend=InstalledSchedulerBackend(),
        )

        payload_text = json.dumps(report.to_mapping())
        self.assertIn("OPENAI_API_KEY is not set", payload_text)
        self.assertNotIn("sk-", payload_text)
        self.assertEqual(report.exit_code, 1)

    def test_failed_last_run_is_failure(self) -> None:
        run_id = self.db.create_app_run(profile_id=None, source_name="arxiv")
        self.db.finish_app_run(
            run_id,
            status=APP_RUN_FAILED,
            retrieved_count=0,
            stored_count=0,
            preselected_count=0,
            skipped_analysis_count=0,
            analyzed_count=0,
            relevant_count=0,
            error_message="failed",
        )

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
            )

        self.assertEqual(
            _check(report.to_mapping(), "last_run")["severity"],
            DoctorSeverity.FAILURE,
        )

    def test_scheduler_error_is_sanitized_warning(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=FailingSchedulerBackend(),
            )

        scheduler = _check(report.to_mapping(), "scheduler")
        message = str(scheduler["message"])
        self.assertEqual(scheduler["severity"], DoctorSeverity.WARNING)
        self.assertNotIn("/home/" + "inaeyk", message)
        self.assertNotIn("sk-secret", message)

    def test_scheduler_status_message_is_sanitized_warning(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=LeakySchedulerStatusBackend(),
            )

        scheduler = _check(report.to_mapping(), "scheduler")
        message = str(scheduler["message"])
        self.assertEqual(scheduler["severity"], DoctorSeverity.WARNING)
        self.assertNotIn("/home/" + "inaeyk", message)
        self.assertNotIn("sk-secret", message)
        self.assertIn("[REDACTED_API_KEY]", message)

    def test_scheduler_warns_when_installed_codex_path_is_stale(self) -> None:
        with mock.patch(
            "shutil.which",
            return_value="/home/me/.nvm/versions/node/v22.22.2/bin/codex",
        ):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=StaleCodexPathSchedulerBackend(),
            )

        scheduler = _check(report.to_mapping(), "scheduler")
        message = str(scheduler["message"])
        self.assertEqual(scheduler["severity"], DoctorSeverity.WARNING)
        self.assertIn("does not include the current Codex directory", message)
        self.assertIn("/home/me/.nvm/versions/node/v22.22.2/bin", message)

    def test_network_check_runs_only_when_requested(self) -> None:
        calls: list[tuple[str, float]] = []

        def checker(url: str, timeout: float) -> None:
            calls.append((url, timeout))

        report = run_doctor(
            config=self.config,
            db=self.db,
            scheduler_backend=InstalledSchedulerBackend(),
            include_network=False,
            network_checker=checker,
        )
        self.assertEqual(calls, [])
        self.assertEqual(_check(report.to_mapping(), "network")["severity"], DoctorSeverity.WARNING)

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
                include_network=True,
                network_timeout_seconds=2.5,
                network_checker=checker,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 2.5)
        self.assertEqual(_check(report.to_mapping(), "network")["severity"], DoctorSeverity.PASS)

    def test_invalid_network_timeout_is_failure_without_network_probe(self) -> None:
        calls: list[tuple[str, float]] = []

        def checker(url: str, timeout: float) -> None:
            calls.append((url, timeout))

        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            report = run_doctor(
                config=self.config,
                db=self.db,
                scheduler_backend=InstalledSchedulerBackend(),
                include_network=True,
                network_timeout_seconds=float("inf"),
                network_checker=checker,
            )

        self.assertEqual(calls, [])
        self.assertEqual(
            _check(report.to_mapping(), "network_timeout")["severity"],
            DoctorSeverity.FAILURE,
        )
        self.assertEqual(report.exit_code, 1)

    def test_cli_doctor_does_not_create_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            config_dir = root / "config"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                        "RESEARCH_DIGEST_CONFIG_DIR": str(config_dir),
                    },
                    clear=False,
                ),
                mock.patch("shutil.which", return_value="/usr/bin/codex"),
            ):
                exit_code = run_cli(
                    argv=["doctor", "--json"],
                    stdout=stdout,
                    stderr=stderr,
                    scheduler_backend=InstalledSchedulerBackend(),
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertFalse(data_dir.exists())
            self.assertFalse(config_dir.exists())
            self.assertFalse((data_dir / "research_digest.sqlite3").exists())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(_check(payload, "config_file")["severity"], DoctorSeverity.WARNING)

    def test_cli_rejects_invalid_network_timeout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["doctor", "--network", "--network-timeout", "inf"],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")


def _check(payload: dict[str, object], name: str) -> dict[str, object]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    for check in checks:
        assert isinstance(check, dict)
        if check["name"] == name:
            return check
    raise AssertionError(f"missing check: {name}")


if __name__ == "__main__":
    unittest.main()
