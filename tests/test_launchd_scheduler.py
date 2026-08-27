from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from unittest import mock

from research_digest.config import AppConfig
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    LAUNCHD_BACKEND_NAME,
    LAUNCHD_DEFAULT_LABEL,
    LAUNCHD_OWNER_ID,
    LaunchdSchedulerBackend,
    ScheduleError,
    ScheduleRequest,
    WindowsTaskSchedulerBackend,
    build_schedule_request,
    select_scheduler_backend,
)


class FakeLaunchctl:
    def __init__(
        self,
        *,
        print_returncode: int = 0,
        fail_operation: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.print_returncode = print_returncode
        self.fail_operation = fail_operation

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        values = tuple(command)
        self.calls.append(values)
        if self.fail_operation is not None and self.fail_operation in values:
            returncode = 1
        else:
            returncode = self.print_returncode if "print" in values else 0
        return subprocess.CompletedProcess(values, returncode, "", "not loaded")


class StatefulLaunchctl:
    def __init__(
        self,
        *,
        loaded: bool,
        fail_next_bootstrap: bool = False,
        fail_enable: bool = False,
        fail_bootout: bool = False,
    ) -> None:
        self.loaded = loaded
        self.fail_next_bootstrap = fail_next_bootstrap
        self.fail_enable = fail_enable
        self.fail_bootout = fail_bootout
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        values = tuple(command)
        self.calls.append(values)
        operation = values[1]
        if operation == "print":
            returncode = 0 if self.loaded else 113
        elif operation == "bootout":
            if self.fail_bootout:
                returncode = 1
            else:
                self.loaded = False
                returncode = 0
        elif operation == "bootstrap":
            if self.fail_next_bootstrap:
                self.fail_next_bootstrap = False
                returncode = 1
            else:
                self.loaded = True
                returncode = 0
        elif operation == "enable" and self.fail_enable:
            returncode = 1
        else:
            returncode = 0
        return subprocess.CompletedProcess(values, returncode, "", "simulated failure")


def _config(root: Path) -> AppConfig:
    return AppConfig(
        db_path=root / "data" / "digest.sqlite3",
        data_dir=root / "data",
        config_dir=root / "config",
        analyzer_provider="codex",
        openai_api_key="sk-secret-not-for-launchd",
        openai_model="gpt-test",
        codex_model="codex-test",
        codex_timeout_seconds=17,
        automatic_coverage_start_date=date(2026, 8, 27),
    )


class LaunchdSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.agent = (
            self.root
            / "Library"
            / "LaunchAgents"
            / f"{LAUNCHD_DEFAULT_LABEL}.plist"
        )
        self.command = self.root / "venv with spaces" / "bin" / "research-digest"
        self.codex = self.root / "npm with spaces" / "bin" / "codex"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def request(self) -> ScheduleRequest:
        with mock.patch(
            "research_digest.scheduler.resolve_codex_executable",
            return_value=str(self.codex),
        ):
            return build_schedule_request(
                task_name=DEFAULT_TASK_NAME,
                time_of_day="07:35",
                config=_config(self.root),
                command_executable=str(self.command),
                working_directory=self.root / "data",
                platform=LAUNCHD_BACKEND_NAME,
                launch_agent_path=self.agent,
            )

    def test_launchd_plist_generation_is_owned_exact_and_secret_free(self) -> None:
        runner = FakeLaunchctl()
        backend = LaunchdSchedulerBackend(home=self.root, runner=runner, uid=501)

        result = backend.install(self.request())

        with self.agent.open("rb") as handle:
            plist = plistlib.load(handle)
        self.assertEqual(plist["Label"], LAUNCHD_DEFAULT_LABEL)
        self.assertEqual(plist["ResearchDigestOwner"], LAUNCHD_OWNER_ID)
        self.assertEqual(plist["ProgramArguments"], [str(self.command), "run"])
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 7, "Minute": 35})
        self.assertFalse(plist["RunAtLoad"])
        environment = plist["EnvironmentVariables"]
        self.assertEqual(environment["RESEARCH_DIGEST_DB"], str(_config(self.root).db_path))
        self.assertIn(str(self.codex.parent), environment["PATH"])
        self.assertIn(str(self.command.parent), environment["PATH"])
        serialized = self.agent.read_text(encoding="utf-8")
        self.assertNotIn("sk-secret", serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)
        self.assertEqual(result.backend, "launchd")
        self.assertIn(("/bin/launchctl", "bootstrap", "gui/501", str(self.agent)), runner.calls)

    def test_install_update_and_status_are_idempotent(self) -> None:
        runner = FakeLaunchctl()
        backend = LaunchdSchedulerBackend(home=self.root, runner=runner, uid=502)
        request = self.request()

        backend.install(request)
        first = self.agent.read_bytes()
        backend.install(request)
        status = backend.status(task_name=DEFAULT_TASK_NAME)

        self.assertEqual(first, self.agent.read_bytes())
        self.assertTrue(status.installed)
        self.assertEqual(status.state, "enabled")
        self.assertEqual(status.execute, str(self.command))
        self.assertEqual(status.environment, request.environment)

    def test_unrelated_launch_agent_is_untouched_by_install_and_remove(self) -> None:
        self.agent.parent.mkdir(parents=True)
        with self.agent.open("wb") as handle:
            plistlib.dump({"Label": LAUNCHD_DEFAULT_LABEL}, handle)
        original = self.agent.read_bytes()
        backend = LaunchdSchedulerBackend(home=self.root, runner=FakeLaunchctl())

        with self.assertRaisesRegex(ScheduleError, "Refusing to overwrite"):
            backend.install(self.request())
        with self.assertRaisesRegex(ScheduleError, "Refusing to remove"):
            backend.remove(task_name=DEFAULT_TASK_NAME)

        self.assertEqual(self.agent.read_bytes(), original)

    def test_remove_unloads_and_removes_only_owned_agent(self) -> None:
        runner = FakeLaunchctl()
        backend = LaunchdSchedulerBackend(home=self.root, runner=runner, uid=503)
        backend.install(self.request())
        unrelated = self.agent.parent / "com.example.other.plist"
        unrelated.write_text("other", encoding="utf-8")

        removed = backend.remove(task_name=DEFAULT_TASK_NAME)
        absent = backend.remove(task_name=DEFAULT_TASK_NAME)

        self.assertEqual(removed.operation, "removed")
        self.assertEqual(absent.operation, "not_installed")
        self.assertFalse(self.agent.exists())
        self.assertTrue(unrelated.exists())
        self.assertIn(
            ("/bin/launchctl", "bootout", "gui/503", str(self.agent)),
            runner.calls,
        )

    def test_status_reports_installed_but_not_loaded_without_mutation(self) -> None:
        install_runner = FakeLaunchctl()
        LaunchdSchedulerBackend(home=self.root, runner=install_runner).install(self.request())
        before = self.agent.read_bytes()
        backend = LaunchdSchedulerBackend(
            home=self.root,
            runner=FakeLaunchctl(print_returncode=113),
        )

        status = backend.status(task_name=DEFAULT_TASK_NAME)

        self.assertTrue(status.installed)
        self.assertEqual(status.state, "disabled")
        self.assertEqual(self.agent.read_bytes(), before)

    def test_failed_bootstrap_does_not_leave_false_installed_artifact(self) -> None:
        backend = LaunchdSchedulerBackend(
            home=self.root,
            runner=FakeLaunchctl(fail_operation="bootstrap"),
        )
        with self.assertRaisesRegex(ScheduleError, "launchd command failed"):
            backend.install(self.request())
        self.assertFalse(self.agent.exists())

    def test_failed_update_restores_previously_loaded_agent(self) -> None:
        LaunchdSchedulerBackend(
            home=self.root,
            runner=StatefulLaunchctl(loaded=False),
            uid=504,
        ).install(self.request())
        previous = self.agent.read_bytes()
        runner = StatefulLaunchctl(loaded=True, fail_next_bootstrap=True)
        backend = LaunchdSchedulerBackend(home=self.root, runner=runner, uid=504)

        with self.assertRaisesRegex(ScheduleError, "launchd command failed"):
            backend.install(self.request())

        self.assertEqual(self.agent.read_bytes(), previous)
        self.assertTrue(runner.loaded)
        operations = [call[1] for call in runner.calls]
        self.assertEqual(operations.count("bootout"), 1)
        self.assertEqual(operations.count("bootstrap"), 2)

    def test_failed_update_preserves_previously_unloaded_state(self) -> None:
        LaunchdSchedulerBackend(
            home=self.root,
            runner=StatefulLaunchctl(loaded=False),
            uid=505,
        ).install(self.request())
        previous = self.agent.read_bytes()
        runner = StatefulLaunchctl(loaded=False, fail_next_bootstrap=True)
        backend = LaunchdSchedulerBackend(home=self.root, runner=runner, uid=505)

        with self.assertRaisesRegex(ScheduleError, "launchd command failed"):
            backend.install(self.request())

        self.assertEqual(self.agent.read_bytes(), previous)
        self.assertFalse(runner.loaded)
        operations = [call[1] for call in runner.calls]
        self.assertNotIn("bootout", operations)
        self.assertEqual(operations.count("bootstrap"), 1)

    def test_failed_enable_keeps_truthful_new_artifact_when_bootout_fails(self) -> None:
        runner = StatefulLaunchctl(
            loaded=False,
            fail_enable=True,
            fail_bootout=True,
        )
        backend = LaunchdSchedulerBackend(home=self.root, runner=runner, uid=507)

        with self.assertRaisesRegex(ScheduleError, "matching owned plist was retained"):
            backend.install(self.request())

        self.assertTrue(runner.loaded)
        self.assertTrue(self.agent.exists())
        with self.agent.open("rb") as handle:
            plist = plistlib.load(handle)
        self.assertEqual(plist["ResearchDigestOwner"], LAUNCHD_OWNER_ID)

    def test_plist_write_failure_does_not_unload_existing_agent(self) -> None:
        LaunchdSchedulerBackend(
            home=self.root,
            runner=StatefulLaunchctl(loaded=False),
            uid=506,
        ).install(self.request())
        previous = self.agent.read_bytes()
        runner = StatefulLaunchctl(loaded=True)
        backend = LaunchdSchedulerBackend(home=self.root, runner=runner, uid=506)

        with mock.patch(
            "research_digest.scheduler.plistlib.dump",
            side_effect=OSError("disk full"),
        ), self.assertRaisesRegex(OSError, "disk full"):
            backend.install(self.request())

        self.assertEqual(self.agent.read_bytes(), previous)
        self.assertTrue(runner.loaded)
        self.assertNotIn("bootout", [call[1] for call in runner.calls])

    def test_launchd_path_executes_codex_env_shebang_without_shell_init(self) -> None:
        node = self.root / "Homebrew Runtime" / "bin" / "node"
        node.parent.mkdir(parents=True)
        node.write_text(
            "#!/bin/sh\nprintf 'launchd-node:%s\\n' \"$1\"\n",
            encoding="utf-8",
        )
        node.chmod(0o755)
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text("#!/usr/bin/env node\n", encoding="utf-8")
        self.codex.chmod(0o755)

        def find_runtime(name: str) -> str | None:
            return str(node) if name == "node" else None

        with mock.patch(
            "research_digest.executable_environment.shutil.which",
            side_effect=find_runtime,
        ):
            request = self.request()

        completed = subprocess.run(  # noqa: S603 - exact owned test executable.
            [str(self.codex), "--version"],
            env={"PATH": request.environment["PATH"]},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"launchd-node:{self.codex}", completed.stdout)
        self.assertIn(str(node.parent), request.environment["PATH"].split(os.pathsep))

    def test_platform_dispatch_selects_darwin_and_preserves_windows(self) -> None:
        with (
            mock.patch("research_digest.scheduler.sys.platform", "darwin"),
            mock.patch("research_digest.scheduler.Path.exists", return_value=True),
        ):
            self.assertIsInstance(select_scheduler_backend(), LaunchdSchedulerBackend)
        with (
            mock.patch("research_digest.scheduler.sys.platform", "linux"),
            mock.patch("research_digest.scheduler.is_wsl", return_value=True),
            mock.patch(
                "research_digest.scheduler.shutil.which",
                return_value="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            ),
        ):
            self.assertIsInstance(select_scheduler_backend(), WindowsTaskSchedulerBackend)

    def test_unsupported_platform_fails_only_platform_schedule_selection(self) -> None:
        with (
            mock.patch("research_digest.scheduler.sys.platform", "freebsd14"),
            mock.patch("research_digest.scheduler.is_wsl", return_value=False),
            self.assertRaisesRegex(ScheduleError, "Windows/WSL or macOS"),
        ):
            select_scheduler_backend()


if __name__ == "__main__":
    unittest.main()
