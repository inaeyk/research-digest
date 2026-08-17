from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_digest.automation import (
    install_or_update_schedule,
    read_schedule_status,
    remove_schedule,
)
from research_digest.config import AppConfig
from research_digest.scheduler import (
    WINDOWS_LOCAL_TIME_DESCRIPTION,
    ScheduleOperationResult,
    ScheduleRequest,
    ScheduleStatus,
)


class FakeSchedulerBackend:
    def __init__(self) -> None:
        self.requests: list[ScheduleRequest] = []
        self.removed: list[str] = []
        self.status_calls: list[str] = []

    def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
        self.requests.append(request)
        return ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name=request.task_name,
            operation="installed_or_updated",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            arguments=request.windows_action_arguments,
        )

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        self.removed.append(task_name)
        return ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name=task_name,
            operation="removed",
            installed=False,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
        )

    def status(self, *, task_name: str) -> ScheduleStatus:
        self.status_calls.append(task_name)
        return ScheduleStatus(
            backend="windows_task_scheduler",
            task_name=task_name,
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
            state="Ready",
        )


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


class AutomationTests(unittest.TestCase):
    def test_read_schedule_status_sanitizes_unsupported_backend(self) -> None:
        class FailingBackend:
            def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
                raise AssertionError("not used")

            def remove(self, *, task_name: str) -> ScheduleOperationResult:
                raise AssertionError("not used")

            def status(self, *, task_name: str) -> ScheduleStatus:
                raise RuntimeError("failed with OPENAI_API_KEY=sk-secret123456789")

        status = read_schedule_status(scheduler_backend=FailingBackend())

        self.assertFalse(status.ok)
        self.assertIsNone(status.schedule)
        self.assertIsNotNone(status.error_message)
        assert status.error_message is not None
        self.assertIn("[REDACTED_API_KEY]", status.error_message)
        self.assertNotIn("sk-secret", status.error_message)

    def test_install_and_remove_delegate_to_backend_without_secret_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: {
                "codex": "/home/me/.nvm/versions/node/v22/bin/codex",
                "research-digest": "/tmp/bin/research-digest",
                "wsl.exe": "/mnt/c/windows/system32/wsl.exe",
            }.get(name),
        ):
            backend = FakeSchedulerBackend()
            result = install_or_update_schedule(
                time_of_day="07:30",
                config=config(Path(tmp) / "digest.sqlite3"),
                scheduler_backend=backend,
                task_name="Research Digest Test",
                wsl_distro="Ubuntu",
            )
            removed = remove_schedule(
                scheduler_backend=backend,
                task_name="Research Digest Test",
            )

        self.assertTrue(result.installed)
        self.assertEqual(backend.requests[0].time_of_day, "07:30")
        self.assertIn("research-digest run", result.arguments or "")
        self.assertNotIn("OPENAI_API_KEY", result.arguments or "")
        self.assertEqual(removed.operation, "removed")
        self.assertEqual(backend.removed, ["Research Digest Test"])


if __name__ == "__main__":
    unittest.main()
