from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.distribution import (
    CURRENT_RUNTIME_STATE,
    PREVIOUS_RUNTIME_STATE,
    RUNTIME_OWNER_ID,
    RUNTIME_ROOT_MARKER,
    RUNTIME_STATE_SCHEMA,
    RUNTIME_VERSION_MARKER,
    DistributionError,
    activate_distribution,
)
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    WINDOWS_LOCAL_TIME_DESCRIPTION,
    ScheduleOperationResult,
    ScheduleRequest,
    ScheduleSnapshot,
    ScheduleStatus,
)
from research_digest.windows_launcher import (
    WindowsLauncherRequest,
    WindowsLauncherResult,
)


class FakeScheduler:
    def __init__(
        self,
        status: ScheduleStatus,
        *,
        restore_failure: Exception | None = None,
        snapshot_loaded: bool | None = None,
    ) -> None:
        self.schedule_status = status
        self.requests: list[ScheduleRequest] = []
        self.restored: list[ScheduleSnapshot] = []
        self.restore_failure = restore_failure
        self.snapshot_loaded = snapshot_loaded

    def install(self, request: ScheduleRequest) -> ScheduleOperationResult:
        self.requests.append(request)
        return ScheduleOperationResult(
            backend="windows_task_scheduler",
            task_name=request.task_name,
            operation="installed_or_updated",
            installed=True,
            timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
        )

    def remove(self, *, task_name: str) -> ScheduleOperationResult:
        raise AssertionError("activation never removes a schedule")

    def status(self, *, task_name: str) -> ScheduleStatus:
        self.assert_task_name = task_name
        return self.schedule_status

    def snapshot(self, *, task_name: str) -> ScheduleSnapshot:
        if not self.schedule_status.installed:
            raise AssertionError("an absent schedule is not snapshotted")
        return ScheduleSnapshot(
            backend=self.schedule_status.backend,
            task_name=task_name,
            artifact=b"exact prior scheduler artifact",
            enabled=self.schedule_status.state != "disabled",
            loaded=self.snapshot_loaded,
        )

    def restore(self, snapshot: ScheduleSnapshot) -> None:
        self.restored.append(snapshot)
        if self.restore_failure is not None:
            raise self.restore_failure


class FakeLauncher:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.requests: list[WindowsLauncherRequest] = []
        self.failure = failure

    def install(self, request: WindowsLauncherRequest) -> WindowsLauncherResult:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return WindowsLauncherResult(
            operation="installed_or_updated",
            installed=True,
            path="C:\\Users\\Researcher\\Desktop\\Research Digest.lnk",
            distro=request.distro,
            target=request.wsl_executable,
            arguments=request.windows_arguments,
        )

    def uninstall(self) -> WindowsLauncherResult:
        raise AssertionError("activation never uninstalls the launcher")


def config(root: Path) -> AppConfig:
    return AppConfig(
        db_path=root / "data" / "research_digest.sqlite3",
        data_dir=root / "data",
        config_dir=root / "config",
        analyzer_provider="openai",
        openai_api_key=None,
        openai_model="unused",
        codex_model=None,
        codex_timeout_seconds=1,
    )


def uninstalled_schedule() -> ScheduleStatus:
    return ScheduleStatus(
        backend="windows_task_scheduler",
        task_name=DEFAULT_TASK_NAME,
        installed=False,
        timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
    )


class DistributionActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.platform_dependencies = tempfile.TemporaryDirectory()
        self.addCleanup(self.platform_dependencies.cleanup)
        codex = Path(self.platform_dependencies.name) / "node" / "bin" / "codex"
        codex.parent.mkdir(parents=True)
        codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        codex.chmod(0o755)

        def resolve_test_command(name: str) -> str | None:
            return str(codex) if name == "codex" else None

        for patcher in (
            mock.patch(
                "research_digest.scheduler.resolve_windows_wsl_executable",
                return_value="C:\\Windows\\System32\\wsl.exe",
            ),
            mock.patch(
                "research_digest.windows_launcher.resolve_windows_wsl_executable",
                return_value="C:\\Windows\\System32\\wsl.exe",
            ),
            mock.patch(
                "research_digest.windows_launcher.shutil.which",
                side_effect=resolve_test_command,
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def prepare_runtime(self, root: Path) -> tuple[Path, Path]:
        runtime_root = root / "data" / "runtime"
        version_root = runtime_root / "0.5.0"
        command = version_root / "venv" / "bin" / "research-digest"
        command.parent.mkdir(parents=True)
        runtime_root.chmod(0o700)
        version_root.chmod(0o700)
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)
        owned = {"schema_version": RUNTIME_STATE_SCHEMA, "owner": RUNTIME_OWNER_ID}
        (runtime_root / RUNTIME_ROOT_MARKER).write_text(json.dumps(owned), encoding="utf-8")
        (runtime_root / RUNTIME_ROOT_MARKER).chmod(0o600)
        (version_root / RUNTIME_VERSION_MARKER).write_text(
            json.dumps({**owned, "version": "0.5.0", "wheel_sha256": "a" * 64}),
            encoding="utf-8",
        )
        (version_root / RUNTIME_VERSION_MARKER).chmod(0o600)
        return runtime_root, command

    def activate(
        self,
        root: Path,
        status: ScheduleStatus,
        *,
        snapshot_loaded: bool | None = None,
    ) -> tuple[FakeScheduler, FakeLauncher, Path]:
        runtime_root, command = self.prepare_runtime(root)
        scheduler = FakeScheduler(status, snapshot_loaded=snapshot_loaded)
        launcher = FakeLauncher()
        result = activate_distribution(
            config=config(root),
            runtime_root=runtime_root,
            version="0.5.0",
            command_executable=command,
            distro="Research Debian",
            scheduler_backend=scheduler,
            windows_launcher_backend=launcher,
            platform="linux",
        )
        self.assertEqual(result.command, str(command.resolve()))
        return scheduler, launcher, runtime_root

    def test_fresh_activation_repoints_launcher_and_creates_no_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Home With Spaces"
            root.mkdir()
            data_file = root / "data" / "library-note.txt"
            data_file.parent.mkdir()
            data_file.write_bytes(b"personal research data\x00")
            before = data_file.read_bytes()

            scheduler, launcher, runtime_root = self.activate(root, uninstalled_schedule())

            current = json.loads((runtime_root / CURRENT_RUNTIME_STATE).read_text())
            self.assertEqual(scheduler.requests, [])
            self.assertIn("/runtime/0.5.0/venv/bin/research-digest", current["command"])
            self.assertEqual(launcher.requests[0].command_executable, current["command"])
            self.assertEqual(data_file.read_bytes(), before)
            self.assertFalse((root / "data" / "research_digest.sqlite3").exists())

    def test_migration_leaves_existing_database_and_config_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "research_digest.sqlite3"
            config_path = root / "config" / "config.json"
            db_path.parent.mkdir(parents=True)
            config_path.parent.mkdir(parents=True)
            db_path.write_bytes(b"SQLite-format-human-fixture\x00\xff")
            config_path.write_bytes(b'{"config_version":5,"human_spacing":true}\n')
            before = {path: path.read_bytes() for path in (db_path, config_path)}

            self.activate(root, uninstalled_schedule())

            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)

    def test_enabled_and_disabled_schedules_preserve_state_and_time(self) -> None:
        for state, expected_enabled in (("Ready", True), ("disabled", False)):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                schedule = ScheduleStatus(
                    backend="windows_task_scheduler",
                    task_name=DEFAULT_TASK_NAME,
                    installed=True,
                    timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                    state=state,
                    time_of_day="06:45",
                    owned=True,
                    command_executable="/old/source/.venv/bin/research-digest",
                )
                scheduler, launcher, _ = self.activate(Path(tmp), schedule)

                self.assertEqual(len(scheduler.requests), 1)
                request = scheduler.requests[0]
                self.assertEqual(request.time_of_day, "06:45")
                self.assertEqual(request.enabled, expected_enabled)
                self.assertEqual(
                    request.command_executable,
                    launcher.requests[0].command_executable,
                )

    def test_schedule_snapshot_loaded_state_is_forwarded_to_replacement(self) -> None:
        for loaded in (False, True):
            with self.subTest(loaded=loaded), tempfile.TemporaryDirectory() as tmp:
                schedule = ScheduleStatus(
                    backend="launchd",
                    task_name=DEFAULT_TASK_NAME,
                    installed=True,
                    timezone="macOS local time",
                    state="enabled",
                    time_of_day="06:45",
                    owned=True,
                    command_executable="/old/source/.venv/bin/research-digest",
                )

                scheduler, _, _ = self.activate(
                    Path(tmp),
                    schedule,
                    snapshot_loaded=loaded,
                )

                self.assertIs(scheduler.requests[0].loaded, loaded)

    def test_upgrade_retains_previous_runtime_record_for_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            old_command = runtime_root / "0.4.0" / "venv" / "bin" / "research-digest"
            old_command.parent.mkdir(parents=True)
            old_command.write_text("#!/bin/sh\n", encoding="utf-8")
            old_command.chmod(0o755)
            owned = {"schema_version": RUNTIME_STATE_SCHEMA, "owner": RUNTIME_OWNER_ID}
            (runtime_root / CURRENT_RUNTIME_STATE).write_text(
                json.dumps(
                    {**owned, "version": "0.4.0", "command": str(old_command.resolve())}
                ),
                encoding="utf-8",
            )
            (runtime_root / CURRENT_RUNTIME_STATE).chmod(0o600)
            scheduler = FakeScheduler(uninstalled_schedule())
            launcher = FakeLauncher()

            result = activate_distribution(
                config=config(root),
                runtime_root=runtime_root,
                version="0.5.0",
                command_executable=command,
                distro="Research Debian",
                scheduler_backend=scheduler,
                windows_launcher_backend=launcher,
                platform="linux",
            )

            previous = json.loads((runtime_root / PREVIOUS_RUNTIME_STATE).read_text())
            self.assertEqual(previous["version"], "0.4.0")
            self.assertEqual(previous["command"], str(old_command.resolve()))
            self.assertIsNotNone(result.previous)

    def test_launcher_failure_rolls_back_schedule_and_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            old_command = "/old/source/.venv/bin/research-digest"
            owned = {"schema_version": RUNTIME_STATE_SCHEMA, "owner": RUNTIME_OWNER_ID}
            current_path = runtime_root / CURRENT_RUNTIME_STATE
            previous_path = runtime_root / PREVIOUS_RUNTIME_STATE
            current_path.write_text(
                json.dumps({**owned, "version": "0.4.0", "command": old_command}),
                encoding="utf-8",
            )
            previous_path.write_text(
                json.dumps({**owned, "version": "0.3.0", "command": "/older/command"}),
                encoding="utf-8",
            )
            current_path.chmod(0o600)
            previous_path.chmod(0o600)
            before = {path: path.read_bytes() for path in (current_path, previous_path)}
            schedule = ScheduleStatus(
                backend="windows_task_scheduler",
                task_name=DEFAULT_TASK_NAME,
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Ready",
                time_of_day="06:45",
                owned=True,
                command_executable=old_command,
            )
            scheduler = FakeScheduler(schedule)
            launcher = FakeLauncher(failure=RuntimeError("launcher write failed"))

            with self.assertRaisesRegex(RuntimeError, "launcher write failed"):
                activate_distribution(
                    config=config(root),
                    runtime_root=runtime_root,
                    version="0.5.0",
                    command_executable=command,
                    distro="Research Debian",
                    scheduler_backend=scheduler,
                    windows_launcher_backend=launcher,
                    platform="linux",
                )

            self.assertEqual(
                [request.command_executable for request in scheduler.requests],
                [str(command.resolve())],
            )
            self.assertEqual(
                [snapshot.artifact for snapshot in scheduler.restored],
                [b"exact prior scheduler artifact"],
            )
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)

    def test_state_write_failure_rolls_back_schedule_before_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            old_command = "/old/source/.venv/bin/research-digest"
            schedule = ScheduleStatus(
                backend="windows_task_scheduler",
                task_name=DEFAULT_TASK_NAME,
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="disabled",
                time_of_day="19:10",
                owned=True,
                command_executable=old_command,
            )
            scheduler = FakeScheduler(schedule)
            launcher = FakeLauncher()

            with (
                mock.patch(
                    "research_digest.distribution._atomic_json",
                    side_effect=OSError("state disk full"),
                ),
                self.assertRaisesRegex(OSError, "state disk full"),
            ):
                activate_distribution(
                    config=config(root),
                    runtime_root=runtime_root,
                    version="0.5.0",
                    command_executable=command,
                    distro="Research Debian",
                    scheduler_backend=scheduler,
                    windows_launcher_backend=launcher,
                    platform="linux",
                )

            self.assertEqual(
                [request.command_executable for request in scheduler.requests],
                [str(command.resolve())],
            )
            self.assertEqual([request.enabled for request in scheduler.requests], [False])
            self.assertEqual(
                [snapshot.artifact for snapshot in scheduler.restored],
                [b"exact prior scheduler artifact"],
            )
            self.assertEqual(launcher.requests, [])
            self.assertFalse((runtime_root / CURRENT_RUNTIME_STATE).exists())

    def test_failed_exact_schedule_restore_reports_incomplete_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            schedule = ScheduleStatus(
                backend="windows_task_scheduler",
                task_name=DEFAULT_TASK_NAME,
                installed=True,
                timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                state="Ready",
                time_of_day="06:45",
                owned=True,
                command_executable="/old/source/.venv/bin/research-digest",
            )
            scheduler = FakeScheduler(
                schedule,
                restore_failure=RuntimeError("native restore failed"),
            )

            with (
                mock.patch(
                    "research_digest.distribution._atomic_json",
                    side_effect=OSError("state disk full"),
                ),
                self.assertRaisesRegex(DistributionError, "rollback was incomplete"),
            ):
                activate_distribution(
                    config=config(root),
                    runtime_root=runtime_root,
                    version="0.5.0",
                    command_executable=command,
                    distro="Research Debian",
                    scheduler_backend=scheduler,
                    windows_launcher_backend=FakeLauncher(),
                    platform="linux",
                )

            self.assertEqual(len(scheduler.restored), 1)

    def test_unowned_schedule_blocks_before_launcher_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            scheduler = FakeScheduler(
                ScheduleStatus(
                    backend="windows_task_scheduler",
                    task_name=DEFAULT_TASK_NAME,
                    installed=True,
                    timezone=WINDOWS_LOCAL_TIME_DESCRIPTION,
                    state="Ready",
                    time_of_day="06:45",
                    owned=False,
                )
            )
            launcher = FakeLauncher()

            with self.assertRaisesRegex(DistributionError, "without verified"):
                activate_distribution(
                    config=config(root),
                    runtime_root=runtime_root,
                    version="0.5.0",
                    command_executable=command,
                    distro="Research Debian",
                    scheduler_backend=scheduler,
                    windows_launcher_backend=launcher,
                    platform="linux",
                )

            self.assertEqual(launcher.requests, [])
            self.assertFalse((runtime_root / CURRENT_RUNTIME_STATE).exists())

    def test_group_writable_runtime_root_is_rejected_before_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            runtime_root.chmod(0o770)
            launcher = FakeLauncher()

            with self.assertRaisesRegex(DistributionError, "mode 0700"):
                activate_distribution(
                    config=config(root),
                    runtime_root=runtime_root,
                    version="0.5.0",
                    command_executable=command,
                    distro="Research Debian",
                    scheduler_backend=FakeScheduler(uninstalled_schedule()),
                    windows_launcher_backend=launcher,
                    platform="linux",
                )

            self.assertEqual(launcher.requests, [])

    def test_symlinked_runtime_bin_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            bin_directory = command.parent
            command.unlink()
            bin_directory.rmdir()
            outside_bin = root / "outside-bin"
            outside_bin.mkdir()
            outside_command = outside_bin / "research-digest"
            outside_command.write_text("#!/bin/sh\n", encoding="utf-8")
            outside_command.chmod(0o755)
            bin_directory.symlink_to(outside_bin, target_is_directory=True)

            with self.assertRaisesRegex(DistributionError, "bin directory"):
                activate_distribution(
                    config=config(root),
                    runtime_root=runtime_root,
                    version="0.5.0",
                    command_executable=bin_directory / "research-digest",
                    distro="Research Debian",
                    scheduler_backend=FakeScheduler(uninstalled_schedule()),
                    windows_launcher_backend=FakeLauncher(),
                    platform="linux",
                )

    def test_installer_only_cli_surface_activates_exact_private_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root, command = self.prepare_runtime(root)
            scheduler = FakeScheduler(uninstalled_schedule())
            launcher = FakeLauncher()
            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch("research_digest.distribution.sys.platform", "linux"):
                exit_code = run_cli(
                    argv=[
                        "distribution",
                        "activate",
                        "--runtime-root",
                        str(runtime_root),
                        "--version",
                        "0.5.0",
                        "--command",
                        str(command),
                        "--distro",
                        "Research Debian",
                        "--json",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                    config=config(root),
                    scheduler_backend=scheduler,
                    windows_launcher_backend=launcher,
                )

            self.assertEqual(exit_code, 0, stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["command"], str(command.resolve()))

    def test_installer_only_cli_activation_does_not_create_or_adopt_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            config_dir = root / "fresh config"
            runtime_root, command = self.prepare_runtime(root)
            legacy_db = root / "legacy.sqlite3"
            legacy_db.write_bytes(b"human evidence, not a valid database")
            stdout = io.StringIO()
            stderr = io.StringIO()
            environment = {
                "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                "RESEARCH_DIGEST_CONFIG_DIR": str(config_dir),
                "RESEARCH_DIGEST_LEGACY_DB": str(legacy_db),
                "WSL_DISTRO_NAME": "Research Debian",
            }
            scheduler = FakeScheduler(uninstalled_schedule())
            launcher = FakeLauncher()

            with (
                mock.patch.dict("os.environ", environment, clear=True),
                mock.patch("research_digest.distribution.sys.platform", "linux"),
            ):
                exit_code = run_cli(
                    argv=[
                        "distribution",
                        "activate",
                        "--runtime-root",
                        str(runtime_root),
                        "--version",
                        "0.5.0",
                        "--command",
                        str(command),
                        "--distro",
                        "Research Debian",
                        "--json",
                    ],
                    stdout=stdout,
                    stderr=stderr,
                    config=None,
                    scheduler_backend=scheduler,
                    windows_launcher_backend=launcher,
                )

            self.assertEqual(exit_code, 0, stdout.getvalue())
            self.assertFalse(config_dir.exists())
            self.assertFalse((data_dir / "research_digest.sqlite3").exists())
            self.assertEqual(legacy_db.read_bytes(), b"human evidence, not a valid database")


if __name__ == "__main__":
    unittest.main()
