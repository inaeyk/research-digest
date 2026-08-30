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


def openai_config(db_path: Path) -> AppConfig:
    return AppConfig(
        db_path=db_path,
        data_dir=db_path.parent,
        config_dir=db_path.parent / "config",
        analyzer_provider="openai",
        openai_api_key="sk-test-value-that-must-not-be-scheduled",
        openai_model="gpt-test",
        codex_model=None,
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
            with mock.patch(
                "research_digest.scheduler.shutil.which",
                side_effect=lambda name: "/home/me/.nvm/versions/node/v22.22.2/bin/codex"
                if name == "codex"
                else None,
            ):
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
        self.assertEqual(
            request.environment["RESEARCH_DIGEST_CONFIG_DIR"],
            str(config(Path("runtime.sqlite3")).config_dir),
        )
        self.assertEqual(request.environment["RESEARCH_DIGEST_ANALYZER"], "codex")
        self.assertEqual(request.environment["RESEARCH_DIGEST_CODEX_MODEL"], "codex-test")
        self.assertEqual(
            request.environment["PATH"],
            "/home/me/.nvm/versions/node/v22.22.2/bin:"
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        )
        scheduled_text = request.windows_action_arguments
        self.assertIn("research-digest run", scheduled_text)
        self.assertIn("RESEARCH_DIGEST_DB=", scheduled_text)
        self.assertIn("RESEARCH_DIGEST_CONFIG_DIR=", scheduled_text)
        self.assertIn("/home/me/.nvm/versions/node/v22.22.2/bin", scheduled_text)
        self.assertNotIn("OPENAI_API_KEY", scheduled_text)
        self.assertNotIn("CODEX_API_KEY", scheduled_text)
        self.assertNotIn("auth", scheduled_text.lower())
        self.assertNotIn("sk-test-value", scheduled_text)

    def test_codex_in_nvm_like_directory_with_spaces_is_quoted_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: "/home/me/.nvm/versions/node v22/bin/codex"
            if name == "codex"
            else None,
        ):
            request = build_schedule_request(
                task_name="Research Digest Test",
                time_of_day="07:30",
                config=config(Path("/tmp/runtime.sqlite3")),
                wsl_distro="Ubuntu",
                wsl_executable="C:\\Windows\\System32\\wsl.exe",
                command_executable="/tmp/venv/bin/research-digest",
                working_directory=Path(tmp),
            )

        self.assertEqual(
            request.environment["PATH"].split(":")[0],
            "/home/me/.nvm/versions/node v22/bin",
        )
        self.assertIn(
            '"PATH=/home/me/.nvm/versions/node v22/bin:',
            request.windows_action_arguments,
        )

    def test_missing_codex_fails_schedule_install_for_codex_analyzer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_digest.scheduler.shutil.which",
            return_value=None,
        ), self.assertRaisesRegex(ScheduleError, "codex executable"):
            build_schedule_request(
                task_name="Research Digest Test",
                time_of_day="07:30",
                config=config(Path("/tmp/runtime.sqlite3")),
                wsl_distro="Ubuntu",
                wsl_executable="C:\\Windows\\System32\\wsl.exe",
                command_executable="/tmp/venv/bin/research-digest",
                working_directory=Path(tmp),
            )

    def test_openai_schedule_install_does_not_require_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_digest.scheduler.shutil.which",
            return_value=None,
        ):
            request = build_schedule_request(
                task_name="Research Digest Test",
                time_of_day="07:30",
                config=openai_config(Path("/tmp/runtime.sqlite3")),
                wsl_distro="Ubuntu",
                wsl_executable="C:\\Windows\\System32\\wsl.exe",
                command_executable="/tmp/venv/bin/research-digest",
                working_directory=Path(tmp),
            )

        self.assertEqual(request.environment["RESEARCH_DIGEST_ANALYZER"], "openai")
        self.assertNotIn("PATH", request.environment)

    def test_openai_schedule_captures_optional_codex_for_library_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: "/home/me/npm/bin/codex"
            if name == "codex"
            else None,
        ):
            request = build_schedule_request(
                task_name="Research Digest Test",
                time_of_day="07:30",
                config=openai_config(Path("/tmp/runtime.sqlite3")),
                wsl_distro="Ubuntu",
                wsl_executable="C:\\Windows\\System32\\wsl.exe",
                command_executable="/tmp/venv/bin/research-digest",
                working_directory=Path(tmp),
            )

        self.assertIn("/home/me/npm/bin", request.environment["PATH"].split(":"))

    def test_windows_install_uses_register_scheduled_task_force(self) -> None:
        runner = FakeRunner()
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)
        with mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: "/home/me/.nvm/versions/node/v22.22.2/bin/codex"
            if name == "codex"
            else None,
        ):
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
                    "time_of_day": "07:30",
                    "owned": True,
                }
            )
        )
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        status = backend.status(task_name=DEFAULT_TASK_NAME)

        self.assertTrue(status.installed)
        self.assertEqual(status.state, "Ready")
        self.assertEqual(status.last_task_result, 0)
        self.assertEqual(status.execute, "wsl.exe")
        self.assertEqual(status.time_of_day, "07:30")
        self.assertTrue(status.owned)

    def test_windows_status_accepts_large_unsigned_task_result(self) -> None:
        runner = FakeRunner(
            stdout=json.dumps(
                {
                    "installed": True,
                    "state": "Ready",
                    "last_task_result": 3221225786,
                    "last_run_time": "2026-08-18T06:00:01.0000000",
                    "next_run_time": "2026-08-19T06:00:00.0000000",
                    "execute": "wsl.exe",
                    "arguments": "-d Ubuntu --exec research-digest run",
                }
            )
        )
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        status = backend.status(task_name=DEFAULT_TASK_NAME)

        self.assertTrue(status.installed)
        self.assertEqual(status.state, "Ready")
        self.assertEqual(status.last_task_result, 3221225786)
        self.assertEqual(status.next_run_time, "2026-08-19T06:00:00.0000000")

    def test_windows_status_recovers_exact_private_command_with_spaces(self) -> None:
        arguments = (
            '-d "Research Debian" --exec env '
            '"PATH=/home/person/npm with spaces/bin:/usr/bin" '
            '"/home/person/private runtime/0.5.0/venv/bin/research-digest" run'
        )
        runner = FakeRunner(
            stdout=json.dumps(
                {
                    "installed": True,
                    "state": "Disabled",
                    "execute": "wsl.exe",
                    "arguments": arguments,
                    "time_of_day": "19:10",
                    "owned": True,
                }
            )
        )

        status = WindowsTaskSchedulerBackend(
            powershell_path="powershell.exe",
            runner=runner,
        ).status(task_name=DEFAULT_TASK_NAME)

        self.assertEqual(
            status.command_executable,
            "/home/person/private runtime/0.5.0/venv/bin/research-digest",
        )
        self.assertEqual(status.time_of_day, "19:10")
        self.assertTrue(status.owned)

    def test_windows_status_script_uses_64_bit_last_task_result(self) -> None:
        runner = FakeRunner(
            stdout=json.dumps(
                {
                    "installed": False,
                    "message": "Schedule is not installed.",
                }
            )
        )
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        backend.status(task_name=DEFAULT_TASK_NAME)

        script = runner.calls[0][-1]
        self.assertIn("[int64]$info.LastTaskResult", script)
        self.assertNotIn("[int]$info.LastTaskResult", script)

    def test_windows_install_and_remove_scripts_check_task_ownership(self) -> None:
        runner = FakeRunner(stdout=json.dumps({"removed": True}))
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)
        with mock.patch(
            "research_digest.scheduler.shutil.which",
            side_effect=lambda name: "/home/researcher/bin/codex" if name == "codex" else None,
        ):
            request = build_schedule_request(
                time_of_day="06:15",
                config=config(Path("/tmp/research-digest.sqlite3")),
                wsl_distro="Research Debian",
                wsl_executable="C:\\Windows\\System32\\wsl.exe",
                command_executable="/private runtime/venv/bin/research-digest",
            )
        backend.install(request)
        backend.remove(task_name=DEFAULT_TASK_NAME)

        install_script = runner.calls[0][-1]
        remove_script = runner.calls[1][-1]
        self.assertIn("Refusing to overwrite", install_script)
        self.assertIn("org.research-digest.windows-schedule.v1", install_script)
        self.assertIn("Export-ScheduledTask", install_script)
        self.assertIn("prior state was restored", install_script)
        self.assertIn("Refusing to remove", remove_script)
        self.assertIn("Run Research Digest once per day from WSL.", remove_script)

    def test_windows_snapshot_and_restore_preserve_exact_xml_and_disabled_state(self) -> None:
        xml = "<Task><Settings><StartWhenAvailable>true</StartWhenAvailable></Settings></Task>"
        runner = FakeRunner(
            stdout=json.dumps(
                {
                    "installed": True,
                    "owned": True,
                    "enabled": False,
                    "xml": xml,
                }
            )
        )
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        snapshot = backend.snapshot(task_name=DEFAULT_TASK_NAME)
        runner.stdout = "{}"
        backend.restore(snapshot)

        self.assertEqual(snapshot.artifact, xml.encode("utf-8"))
        restore_script = runner.calls[1][-1]
        self.assertIn(xml, restore_script)
        self.assertIn("Disable-ScheduledTask", restore_script)
        self.assertIn("Register-ScheduledTask", restore_script)

    def test_windows_snapshot_refuses_unowned_task(self) -> None:
        runner = FakeRunner(
            stdout=json.dumps({"installed": True, "owned": False})
        )
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        with self.assertRaisesRegex(ScheduleError, "without verified ownership"):
            backend.snapshot(task_name=DEFAULT_TASK_NAME)

    def test_windows_backend_sanitizes_nonzero_failure_at_cli_layer(self) -> None:
        runner = FakeRunner(returncode=1, stderr="failed with OPENAI_API_KEY=sk-secret123456789")
        backend = WindowsTaskSchedulerBackend(powershell_path="powershell.exe", runner=runner)

        with self.assertRaisesRegex(ScheduleError, "Windows Task Scheduler command failed"):
            backend.status(task_name=DEFAULT_TASK_NAME)


if __name__ == "__main__":
    unittest.main()
