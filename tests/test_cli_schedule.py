from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.scheduler import (
    WINDOWS_LOCAL_TIME_DESCRIPTION,
    ScheduleOperationResult,
    SchedulerBackend,
    ScheduleRequest,
    ScheduleSnapshot,
    ScheduleStatus,
)


class FakeSchedulerBackend(SchedulerBackend):
    def __init__(self) -> None:
        self.installed_requests: list[ScheduleRequest] = []
        self.removed_tasks: list[str] = []
        self.status_tasks: list[str] = []

    def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
        self.installed_requests.append(request)
        return ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name=request.task_name,
            operation="installed_or_updated",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            execute="wsl.exe",
            arguments=request.windows_action_arguments,
        )

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        self.removed_tasks.append(task_name)
        return ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name=task_name,
            operation="not_installed",
            installed=False,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
        )

    def status(self, *, task_name: str) -> ScheduleStatus:
        self.status_tasks.append(task_name)
        return ScheduleStatus(
            backend="windows_task_scheduler",
            task_name=task_name,
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            state="Ready",
            last_task_result=0,
            next_run_time="2026-08-16T07:30:00",
        )

    def snapshot(self, *, task_name: str) -> ScheduleSnapshot:
        raise AssertionError(f"CLI schedule commands do not snapshot {task_name}")

    def restore(self, snapshot: ScheduleSnapshot) -> None:
        raise AssertionError(f"CLI schedule commands do not restore {snapshot.task_name}")


def config(db_path: Path) -> AppConfig:
    return AppConfig(
        db_path=db_path,
        data_dir=db_path.parent,
        config_dir=db_path.parent / "config",
        analyzer_provider="codex",
        openai_api_key=None,
        openai_model="gpt-test",
        codex_model=None,
        codex_timeout_seconds=12,
    )


class CLIScheduleTests(unittest.TestCase):
    def test_schedule_install_json_uses_backend_and_reports_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = FakeSchedulerBackend()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with mock.patch(
                "research_digest.scheduler.shutil.which",
                side_effect=lambda name: "/mnt/c/windows/system32/wsl.exe"
                if name == "wsl.exe"
                else "/tmp/bin/research-digest",
            ):
                exit_code = run_cli(
                    argv=[
                        "schedule",
                        "install",
                        "--time",
                        "07:30",
                        "--distro",
                        "Ubuntu",
                        "--task-name",
                        "Research Digest Test",
                        "--json",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                    config=config(Path(tmp) / "digest.sqlite3"),
                    scheduler_backend=backend,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["operation"], "installed_or_updated")
        self.assertEqual(payload["execute"], "wsl.exe")
        self.assertIn("Windows local time", payload["timezone"])
        self.assertEqual(backend.installed_requests[0].time_of_day, "07:30")

    def test_schedule_status_human_output_is_inspectable(self) -> None:
        backend = FakeSchedulerBackend()
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["schedule", "status", "--task-name", "Research Digest Test"],
            stdout=stdout,
            stderr=stderr,
            scheduler_backend=backend,
        )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Schedule status completed", output)
        self.assertIn("Backend: windows_task_scheduler", output)
        self.assertIn("Task: Research Digest Test", output)
        self.assertIn("State: Ready", output)
        self.assertIn("Next run: 2026-08-16T07:30:00", output)
        self.assertEqual(stderr.getvalue(), "")

    def test_schedule_remove_json_is_idempotent(self) -> None:
        backend = FakeSchedulerBackend()
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["schedule", "remove", "--task-name", "Research Digest Test", "--json"],
            stdout=stdout,
            stderr=stderr,
            scheduler_backend=backend,
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["operation"], "not_installed")
        self.assertFalse(payload["installed"])
        self.assertEqual(backend.removed_tasks, ["Research Digest Test"])
        self.assertEqual(stderr.getvalue(), "")

    def test_schedule_invalid_time_fails_sanitized(self) -> None:
        backend = FakeSchedulerBackend()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: "/mnt/c/windows/system32/wsl.exe"
            if name == "wsl.exe"
            else "/tmp/bin/research-digest",
        ):
            exit_code = run_cli(
                argv=["schedule", "install", "--time", "25:00", "--distro", "Ubuntu"],
                stdout=stdout,
                stderr=stderr,
                scheduler_backend=backend,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("HH:MM", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
