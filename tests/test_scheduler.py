from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

from research_digest.config import AppConfig
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    ScheduleError,
    WindowsTaskSchedulerBackend,
    build_schedule_request,
    validate_time_of_day,
)


class FakeRunner:
    def __init__(self, stdout: str = "{}", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def config(db_path: Path) -> AppConfig:
    return AppConfig(
        db_path=db_path,
        data_dir=db_path.parent,
        config_dir=db_path.parent / "config",
        analyzer_provider="codex",
        openai_api_key="sk-test-value-that-must-not-be-scheduled",
        openai_model="gpt-test",
        codex_model="codex-test",
        codex_timeout_seconds=12,
    )


class SchedulerTests(unittest.TestCase):
    def test_validate_time_of_day_accepts_hh_mm(self) -> None:
        validate_time_of_day("00:00")
        validate_time_of_day("23:59")

    def test_validate_time_of_day_rejects_invalid_values(self) -> None:
        for value in ("7:30", "24:00", "12:60", "12", "12:30:00", "aa:bb"):
            with self.subTest(value=value), self.assertRaises(ScheduleError):
                validate_time_of_day(value)

    def test_build_schedule_request_resolves_paths_and_excludes_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp) / "repo"
            workdir.mkdir()
            request = build_schedule_request(
                task_name="Research Digest Test",
                time_of_day="07:30",
                config=config(Path("runtime.sqlite3")),
                wsl_distro="Ubuntu",
                wsl_executable="C:\\Windows\\System32\\wsl.exe",
                command_executable="research-digest",
                working_directory=workdir,
            )

        self.assertEqual(request.task_name, "Research Digest Test")
        self.assertEqual(request.wsl_distro, "Ubuntu")
        self.assertTrue(request.db_path.is_absolute())
        self.assertEqual(request.environment["RESEARCH_DIGEST_DB"], str(request.db_path))
        self.assertEqual(request.environment["RESEARCH_DIGEST_ANALYZER"], "codex")
        self.assertEqual(request.environment["RESEARCH_DIGEST_CODEX_MODEL"], "codex-test")
        scheduled_text = request.windows_action_arguments
        self.assertIn("research-digest run", scheduled_text)
        self.assertIn("RESEARCH_DIGEST_DB=", scheduled_text)
        self.assertNotIn("OPENAI_API_KEY", scheduled_text)
        self.assertNotIn("sk-test-value", scheduled_text)

    def test_windows_install_uses_register_scheduled_task_force(self) -> None:
        runner = FakeRunner()
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)
        request = build_schedule_request(
            task_name=DEFAULT_TASK_NAME,
            time_of_day="06:15",
            config=config(Path("/tmp/research-digest.sqlite3")),
            wsl_distro="Ubuntu",
            wsl_executable="C:\\Windows\\System32\\wsl.exe",
            command_executable="research-digest",
            working_directory=Path("/tmp/repo"),
        )

        result = backend.install(request)

        self.assertEqual(result.operation, "installed_or_updated")
        self.assertTrue(result.installed)
        self.assertEqual(result.execute, "C:\\Windows\\System32\\wsl.exe")
        self.assertIsNotNone(result.arguments)
        assert result.arguments is not None
        self.assertIn("research-digest run", result.arguments)
        script = runner.calls[0][-1]
        self.assertIn("Register-ScheduledTask", script)
        self.assertIn("-Force", script)
        self.assertIn("C:\\Windows\\System32\\wsl.exe", script)
        self.assertIn("New-ScheduledTaskTrigger -Daily -At '06:15'", script)

    def test_build_schedule_request_requires_installed_command_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: "/mnt/c/windows/system32/wsl.exe"
            if name == "wsl.exe"
            else None,
        ), self.assertRaisesRegex(ScheduleError, "research-digest command"):
            build_schedule_request(
                task_name=DEFAULT_TASK_NAME,
                time_of_day="06:15",
                config=config(Path("/tmp/research-digest.sqlite3")),
                wsl_distro="Ubuntu",
                working_directory=Path(tmp),
            )

    def test_windows_remove_is_idempotent_for_missing_task(self) -> None:
        runner = FakeRunner(stdout=json.dumps({"removed": False}))
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        result = backend.remove(task_name=DEFAULT_TASK_NAME)

        self.assertEqual(result.operation, "not_installed")
        self.assertFalse(result.installed)

    def test_windows_status_parses_task_scheduler_json(self) -> None:
        runner = FakeRunner(
            stdout=json.dumps(
                {
                    "installed": True,
                    "state": "Ready",
                    "last_task_result": 0,
                    "last_run_time": "2026-08-15T07:30:00.0000000",
                    "next_run_time": "2026-08-16T07:30:00.0000000",
                    "execute": "wsl.exe",
                    "arguments": "-d Ubuntu --exec research-digest run",
                }
            )
        )
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        status = backend.status(task_name=DEFAULT_TASK_NAME)

        self.assertTrue(status.installed)
        self.assertEqual(status.state, "Ready")
        self.assertEqual(status.last_task_result, 0)
        self.assertEqual(status.execute, "wsl.exe")

    def test_windows_backend_sanitizes_nonzero_failure_at_cli_layer(self) -> None:
        runner = FakeRunner(returncode=1, stderr="failed with OPENAI_API_KEY=sk-secret123456789")
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        with self.assertRaisesRegex(ScheduleError, "Windows Task Scheduler command failed"):
            backend.status(task_name=DEFAULT_TASK_NAME)


if __name__ == "__main__":
    unittest.main()
