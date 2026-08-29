from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest import mock

from research_digest import background, cancellation
from research_digest.platform_runtime import (
    DarwinPlatformRuntime,
    ExactProcessState,
    LinuxPlatformRuntime,
    NativeProcessInfo,
    PlatformRuntimeError,
    select_platform_runtime,
)
from research_digest.platform_runtime import is_wsl as platform_is_wsl
from research_digest.run_locks import (
    ProcessOwnershipUnavailable,
    ProcessRunOwner,
    RunOwnerState,
    current_process_run_owner,
    process_run_owner_state,
)
from research_digest.ui.run_status import PendingDigestLaunch, _pending_process_state
from research_digest.ui_server import (
    UI_APPLICATION_ID,
    UI_REGISTRATION_VERSION,
    UIServerManager,
    UIServerRegistration,
)
from research_digest.windows_launcher import (
    WINDOWS_LAUNCHER_DEFAULT_PATH,
    WINDOWS_POWERSHELL_RELATIVE_PATH,
    resolve_windows_powershell,
    run_windows_powershell,
)


class FakeDarwinRuntime(DarwinPlatformRuntime):
    def __init__(self) -> None:
        self.info: dict[int, NativeProcessInfo] = {}
        self.commands: dict[int, tuple[str, ...]] = {}
        self.existence: dict[int, bool | None] = {}
        self.opened: list[tuple[str, ...]] = []
        super().__init__(
            info_reader=lambda pid: self.info.get(pid),
            boot_reader=lambda: "darwin-boot-123",
            command_reader=lambda pid: self.commands.get(pid),
            command_runner=self._run,
        )

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        values = tuple(command)
        self.opened.append(values)
        return subprocess.CompletedProcess(values, 0, "", "")

    def pid_exists(self, pid: int) -> bool | None:
        if pid in self.info:
            return True
        return self.existence.get(pid, False)


def _darwin_streamlit_command(
    executable: Path | str,
    app: Path | str,
    *,
    port: int = 8501,
    bind_host: str = "127.0.0.1",
) -> tuple[str, ...]:
    return (
        f"{executable} -m streamlit run {app} "
        f"--server.address={bind_host} --server.port={port} "
        "--server.headless=true --browser.gatherUsageStats=false",
    )


class DarwinPlatformRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "requires native Darwin libproc")
    def test_native_darwin_identity_inspects_current_process(self) -> None:
        runtime = DarwinPlatformRuntime()
        info = runtime.process_info(os.getpid())
        self.assertIsNotNone(info)
        assert info is not None
        self.assertGreater(info.start_identity, 0)
        self.assertEqual(info.process_group_id, os.getpgid(os.getpid()))
        self.assertIsNotNone(runtime.boot_identity())
        self.assertIsNotNone(runtime.process_command(os.getpid()))

    def test_darwin_process_identity_accepts_exact_owner_and_rejects_pid_reuse(self) -> None:
        runtime = FakeDarwinRuntime()
        runtime.info[77] = NativeProcessInfo(1_725_000_123_456_789, "2", 77)
        owner = ProcessRunOwner(
            pid=77,
            host="mac-a",
            start_ticks=1_725_000_123_456_789,
            nonce="run-nonce",
            boot_id="darwin-boot-123",
            platform="darwin",
        ).to_owner_string()

        self.assertEqual(
            process_run_owner_state(owner, current_host="mac-a", runtime=runtime),
            RunOwnerState.ALIVE,
        )
        runtime.info[77] = NativeProcessInfo(1_725_000_999_000_000, "2", 77)
        self.assertEqual(
            process_run_owner_state(owner, current_host="mac-a", runtime=runtime),
            RunOwnerState.DEAD,
        )

    def test_uninspectable_live_darwin_owner_is_unknown_not_dead(self) -> None:
        runtime = FakeDarwinRuntime()
        runtime.existence[78] = None
        owner = ProcessRunOwner(
            pid=78,
            host="mac-a",
            start_ticks=123,
            nonce="run-nonce",
            boot_id="darwin-boot-123",
            platform="darwin",
        ).to_owner_string()
        self.assertEqual(
            process_run_owner_state(owner, current_host="mac-a", runtime=runtime),
            RunOwnerState.UNKNOWN,
        )

    def test_darwin_run_refuses_uninspectable_self_owner(self) -> None:
        runtime = FakeDarwinRuntime()
        runtime.existence[os.getpid()] = True
        with self.assertRaisesRegex(ProcessOwnershipUnavailable, "will not acquire"):
            current_process_run_owner(runtime=runtime)

    def test_missing_current_boot_identity_keeps_recorded_owner_unknown(self) -> None:
        runtime = DarwinPlatformRuntime(
            info_reader=lambda _pid: NativeProcessInfo(123, "2", 77),
            boot_reader=lambda: None,
            command_reader=lambda _pid: ("worker",),
        )
        owner = ProcessRunOwner(
            pid=77,
            host="mac-a",
            start_ticks=123,
            nonce="run-nonce",
            boot_id="recorded-boot",
            platform="darwin",
        ).to_owner_string()

        self.assertEqual(
            process_run_owner_state(owner, current_host="mac-a", runtime=runtime),
            RunOwnerState.UNKNOWN,
        )

    def test_darwin_framework_python_matches_exact_registered_streamlit_server(self) -> None:
        runtime = FakeDarwinRuntime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "package with spaces" / "ui" / "app.py"
            executable = Path("/Users/me/project/.venv/bin/python")
            framework_python = Path(
                "/Library/Frameworks/Python.framework/Versions/3.12/"
                "Resources/Python.app/Contents/MacOS/Python"
            )
            runtime.info[88] = NativeProcessInfo(900_001, "2", 88)
            runtime.commands[88] = _darwin_streamlit_command(framework_python, app)
            manager = UIServerManager(
                data_dir=root,
                app_path=app,
                executable=str(executable),
                platform_runtime=runtime,
            )
            registration = UIServerRegistration(
                registration_version=UI_REGISTRATION_VERSION,
                application=UI_APPLICATION_ID,
                application_version="0.3.0",
                pid=88,
                process_start_ticks=900_001,
                boot_id="darwin-boot-123",
                host="localhost",
                port=8501,
                url="http://localhost:8501",
                started_at="2026-08-27T12:00:00+00:00",
                nonce="nonce",
                log_path=str(root / "ui.log"),
                executable=str(executable),
                app_path=str(app),
                platform="darwin",
                process_group_id=88,
            )

            self.assertTrue(manager._default_identity_matches(registration))

            runtime.commands[88] = _darwin_streamlit_command(
                framework_python,
                root / "other" / "app.py",
            )
            self.assertFalse(manager._default_identity_matches(registration))
            runtime.commands[88] = _darwin_streamlit_command(
                framework_python,
                app,
                port=8502,
            )
            self.assertFalse(manager._default_identity_matches(registration))
            runtime.commands[88] = (
                f"{framework_python} streamlit run {app} "
                "--server.address=127.0.0.1 --server.port=8501 "
                "--server.headless=true --browser.gatherUsageStats=false",
            )
            self.assertFalse(manager._default_identity_matches(registration))

            runtime.commands[88] = _darwin_streamlit_command(framework_python, app)
            runtime.info[88] = NativeProcessInfo(900_002, "2", 88)
            self.assertFalse(manager._default_identity_matches(registration))
            runtime.info[88] = NativeProcessInfo(900_001, "2", 88)
            self.assertFalse(
                manager._default_identity_matches(
                    replace(registration, boot_id="different-boot")
                )
            )
            runtime.info[88] = NativeProcessInfo(900_001, "2", 999)
            self.assertFalse(manager._default_identity_matches(registration))
            runtime.info[88] = NativeProcessInfo(900_001, "2", 88)
            runtime.commands[88] = _darwin_streamlit_command(
                "/tmp/python-malicious",
                app,
            )
            self.assertFalse(manager._default_identity_matches(registration))
            runtime.commands[88] = ("python unrelated.py --server.port=8501",)
            self.assertFalse(manager._default_identity_matches(registration))

    def test_darwin_ui_stop_signals_only_exact_owned_server(self) -> None:
        runtime = FakeDarwinRuntime()
        signals: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "ui" / "app.py"
            executable = root / "venv" / "bin" / "python"
            runtime.info[99] = NativeProcessInfo(700_001, "2", 99)
            runtime.commands[99] = _darwin_streamlit_command(executable, app)

            def signal_exact(pid: int, requested_signal: int) -> None:
                signals.append((pid, requested_signal))
                runtime.info.pop(pid, None)
                runtime.commands.pop(pid, None)

            manager = UIServerManager(
                data_dir=root,
                app_path=app,
                executable=str(executable),
                platform_runtime=runtime,
                signal_process=signal_exact,
            )
            registration = UIServerRegistration(
                registration_version=UI_REGISTRATION_VERSION,
                application=UI_APPLICATION_ID,
                application_version="0.3.0",
                pid=99,
                process_start_ticks=700_001,
                boot_id="darwin-boot-123",
                host="localhost",
                port=8501,
                url="http://localhost:8501",
                started_at="2026-08-27T12:00:00+00:00",
                nonce="nonce",
                log_path=str(root / "ui.log"),
                executable=str(executable),
                app_path=str(app),
                platform="darwin",
                process_group_id=99,
            )
            manager._write_registration(registration)

            result = manager.stop()

            self.assertTrue(result.stopped)
            self.assertEqual(signals, [(99, signal.SIGTERM)])

            runtime.info[99] = NativeProcessInfo(700_002, "2", 99)
            runtime.commands[99] = ("python unrelated.py",)
            manager._write_registration(registration)
            stale = manager.stop()
            self.assertFalse(stale.stopped)
            self.assertEqual(signals, [(99, signal.SIGTERM)])

    def test_uninspectable_darwin_ui_owner_is_not_replaced_or_signalled(self) -> None:
        runtime = FakeDarwinRuntime()
        runtime.existence[101] = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = UIServerManager(data_dir=root, platform_runtime=runtime)
            registration = UIServerRegistration(
                registration_version=UI_REGISTRATION_VERSION,
                application=UI_APPLICATION_ID,
                application_version="0.3.0",
                pid=101,
                process_start_ticks=44,
                boot_id="darwin-boot-123",
                host="localhost",
                port=8501,
                url="http://localhost:8501",
                started_at="2026-08-27T12:00:00+00:00",
                nonce="nonce",
                log_path=str(root / "ui.log"),
                executable=manager.executable,
                app_path=str(manager.app_path),
                platform="darwin",
            )
            manager._write_registration(registration)
            with self.assertRaisesRegex(Exception, "cannot be inspected"):
                manager.status()
            self.assertTrue(manager.registration_path.exists())

    def test_darwin_ui_command_inspection_failure_is_unknown_not_stale(self) -> None:
        runtime = FakeDarwinRuntime()
        runtime.info[102] = NativeProcessInfo(45, "2", 102)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = UIServerManager(data_dir=root, platform_runtime=runtime)
            registration = UIServerRegistration(
                registration_version=UI_REGISTRATION_VERSION,
                application=UI_APPLICATION_ID,
                application_version="0.3.0",
                pid=102,
                process_start_ticks=45,
                boot_id="darwin-boot-123",
                host="localhost",
                port=8501,
                url="http://localhost:8501",
                started_at="2026-08-27T12:00:00+00:00",
                nonce="nonce",
                log_path=str(root / "ui.log"),
                executable=manager.executable,
                app_path=str(manager.app_path),
                platform="darwin",
            )
            manager._write_registration(registration)

            with self.assertRaisesRegex(Exception, "cannot be inspected"):
                manager.status()

            self.assertTrue(manager.registration_path.exists())

    def test_darwin_ui_stop_does_not_escalate_or_forget_after_inspection_loss(
        self,
    ) -> None:
        runtime = FakeDarwinRuntime()
        signals: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "ui" / "app.py"
            executable = root / "venv" / "bin" / "python"
            command = _darwin_streamlit_command(executable, app)[0]
            runtime.info[103] = NativeProcessInfo(46, "2", 103)
            runtime.commands[103] = (command,)

            def signal_then_hide_command(pid: int, requested_signal: int) -> None:
                signals.append((pid, requested_signal))
                runtime.commands.pop(pid, None)

            manager = UIServerManager(
                data_dir=root,
                app_path=app,
                executable=str(executable),
                platform_runtime=runtime,
                signal_process=signal_then_hide_command,
                stop_timeout_seconds=0.001,
                sleep=lambda _seconds: None,
            )
            registration = UIServerRegistration(
                registration_version=UI_REGISTRATION_VERSION,
                application=UI_APPLICATION_ID,
                application_version="0.3.0",
                pid=103,
                process_start_ticks=46,
                boot_id="darwin-boot-123",
                host="localhost",
                port=8501,
                url="http://localhost:8501",
                started_at="2026-08-27T12:00:00+00:00",
                nonce="nonce",
                log_path=str(root / "ui.log"),
                executable=str(executable),
                app_path=str(app),
                platform="darwin",
                process_group_id=103,
            )
            manager._write_registration(registration)

            with self.assertRaisesRegex(Exception, "did not stop"):
                manager.stop()

            self.assertEqual(signals, [(103, signal.SIGTERM)])
            self.assertTrue(manager.registration_path.exists())

    def test_darwin_ui_stop_revalidates_before_first_signal(self) -> None:
        runtime = FakeDarwinRuntime()
        signals: list[tuple[int, int]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "ui" / "app.py"
            executable = root / "venv" / "bin" / "python"
            command = _darwin_streamlit_command(executable, app)
            runtime.info[104] = NativeProcessInfo(47, "2", 104)
            runtime.commands[104] = command
            manager = UIServerManager(
                data_dir=root,
                app_path=app,
                executable=str(executable),
                platform_runtime=runtime,
                signal_process=lambda pid, sig: signals.append((pid, sig)),
            )
            registration = UIServerRegistration(
                registration_version=UI_REGISTRATION_VERSION,
                application=UI_APPLICATION_ID,
                application_version="0.3.0",
                pid=104,
                process_start_ticks=47,
                boot_id="darwin-boot-123",
                host="localhost",
                port=8501,
                url="http://localhost:8501",
                started_at="2026-08-27T12:00:00+00:00",
                nonce="nonce",
                log_path=str(root / "ui.log"),
                executable=str(executable),
                app_path=str(app),
                platform="darwin",
                process_group_id=104,
            )
            manager._write_registration(registration)
            with mock.patch.object(
                runtime,
                "process_command",
                side_effect=[command, None],
            ), self.assertRaisesRegex(Exception, "did not stop"):
                manager.stop()

            self.assertEqual(signals, [])
            self.assertTrue(manager.registration_path.exists())

    def test_darwin_default_browser_uses_native_open_after_caller_health_boundary(self) -> None:
        runtime = FakeDarwinRuntime()
        runtime.open_url("http://localhost:8507")
        self.assertEqual(runtime.opened, [("/usr/bin/open", "http://localhost:8507")])

    def test_linux_wsl_browser_bridge_preserves_windows_behavior(self) -> None:
        runtime = LinuxPlatformRuntime()
        with (
            mock.patch("research_digest.platform_runtime.is_wsl", return_value=True),
            mock.patch(
                "research_digest.windows_launcher.run_windows_powershell"
            ) as powershell,
        ):
            runtime.open_url("http://localhost:8507/path?value=one'two")

        powershell.assert_called_once_with(
            "$ErrorActionPreference = 'Stop'\n"
            "Start-Process -FilePath 'http://localhost:8507/path?value=one''two'"
        )

    def test_wsl_browser_bridge_resolves_windows_powershell_without_host_path(
        self,
    ) -> None:
        runtime = LinuxPlatformRuntime()
        commands: list[tuple[str, ...]] = []

        def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            values = tuple(command)
            commands.append(values)
            return subprocess.CompletedProcess(values, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normal_bin = root / "normal WSL path"
            normal_bin.mkdir()
            normal_powershell = normal_bin / "powershell.exe"
            normal_powershell.write_text("normal path bridge", encoding="utf-8")
            normal_powershell.chmod(0o755)

            windows_root = root / "mounted Windows drive"
            mounted_powershell = windows_root / WINDOWS_POWERSHELL_RELATIVE_PATH
            mounted_powershell.parent.mkdir(parents=True)
            mounted_powershell.write_text("mounted bridge", encoding="utf-8")
            mounted_powershell.chmod(0o755)
            encoded_mount = str(windows_root).replace(" ", r"\040")
            mounts = root / "mounts"
            mounts.write_text(
                f"Z:\\134 {encoded_mount} 9p rw,aname=drvfs;path=Z:\\134 0 0\n",
                encoding="utf-8",
            )

            with (
                mock.patch.dict(os.environ, {"PATH": str(normal_bin)}, clear=True),
                mock.patch(
                    "research_digest.windows_launcher.WSL_MOUNTS_PATH",
                    mounts,
                ),
                mock.patch(
                    "research_digest.windows_launcher.is_wsl",
                    return_value=True,
                ),
            ):
                self.assertEqual(resolve_windows_powershell(), str(normal_powershell))

            compact_path = "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
            with (
                mock.patch.dict(os.environ, {"PATH": compact_path}, clear=True),
                mock.patch("research_digest.platform_runtime.is_wsl", return_value=True),
                mock.patch(
                    "research_digest.windows_launcher.is_wsl",
                    return_value=True,
                ),
                mock.patch(
                    "research_digest.windows_launcher.WSL_MOUNTS_PATH",
                    mounts,
                ),
                mock.patch(
                    "research_digest.windows_launcher._run_command",
                    side_effect=run,
                ),
            ):
                runtime.open_url("http://localhost:8509")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0], str(mounted_powershell))
        self.assertIn("Start-Process -FilePath 'http://localhost:8509'", commands[0][-1])

    def test_wsl_browser_bridge_missing_from_path_and_mounts_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mounts = Path(tmp) / "mounts"
            mounts.write_text("none / ext4 rw 0 0\n", encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {"PATH": "/usr/local/bin:/usr/bin:/bin"},
                    clear=True,
                ),
                mock.patch("research_digest.platform_runtime.is_wsl", return_value=True),
                mock.patch(
                    "research_digest.windows_launcher.is_wsl",
                    return_value=True,
                ),
                mock.patch(
                    "research_digest.windows_launcher.WSL_MOUNTS_PATH",
                    mounts,
                ),
                self.assertRaisesRegex(
                    PlatformRuntimeError,
                    "WSL interop is enabled.*Windows system drive is mounted",
                ),
            ):
                LinuxPlatformRuntime().open_url("http://localhost:8509")

    def test_wsl_browser_bridge_spawn_failure_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            windows_root = root / "mounted Windows drive"
            mounted_powershell = windows_root / WINDOWS_POWERSHELL_RELATIVE_PATH
            mounted_powershell.parent.mkdir(parents=True)
            mounted_powershell.write_text("not an executable format", encoding="utf-8")
            mounted_powershell.chmod(0o755)
            encoded_mount = str(windows_root).replace(" ", r"\040")
            mounts = root / "mounts"
            mounts.write_text(
                f"Z:\\134 {encoded_mount} 9p rw,aname=drvfs;path=Z:\\134 0 0\n",
                encoding="utf-8",
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {"PATH": "/usr/local/bin:/usr/bin:/bin"},
                    clear=True,
                ),
                mock.patch("research_digest.platform_runtime.is_wsl", return_value=True),
                mock.patch(
                    "research_digest.windows_launcher.is_wsl",
                    return_value=True,
                ),
                mock.patch(
                    "research_digest.windows_launcher.WSL_MOUNTS_PATH",
                    mounts,
                ),
                self.assertRaisesRegex(
                    PlatformRuntimeError,
                    "could not be started through WSL.*WSL interop is enabled",
                ),
            ):
                LinuxPlatformRuntime().open_url("http://localhost:8509")

    @unittest.skipUnless(
        os.environ.get("RESEARCH_DIGEST_RUN_WINDOWS_NATIVE_TESTS") == "1"
        and platform_is_wsl(),
        "requires explicitly enabled native Windows PowerShell boundary",
    )
    def test_native_windows_powershell_bridge_runs_from_compact_path(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"PATH": WINDOWS_LAUNCHER_DEFAULT_PATH},
            clear=False,
        ):
            resolved = resolve_windows_powershell()
            completed = run_windows_powershell(
                "Write-Output research-digest-compact-path-bridge"
            )

        self.assertTrue(Path(resolved).is_absolute())
        self.assertEqual(completed.stdout.strip(), "research-digest-compact-path-bridge")

    def test_non_wsl_linux_desktop_launch_fails_clearly(self) -> None:
        with (
            mock.patch("research_digest.platform_runtime.is_wsl", return_value=False),
            self.assertRaisesRegex(PlatformRuntimeError, "Windows through WSL"),
        ):
            LinuxPlatformRuntime().open_url("http://localhost:8501")

    def test_darwin_open_failure_is_actionable(self) -> None:
        runtime = DarwinPlatformRuntime(
            info_reader=lambda _pid: None,
            boot_reader=lambda: None,
            command_reader=lambda _pid: None,
            command_runner=lambda command: subprocess.CompletedProcess(
                command,
                1,
                "",
                "LaunchServices unavailable",
            ),
        )
        with self.assertRaisesRegex(PlatformRuntimeError, "LaunchServices unavailable"):
            runtime.open_url("http://localhost:8501")

    def test_darwin_has_no_proc_environment_or_architecture_path_dependency(self) -> None:
        runtime = FakeDarwinRuntime()
        self.assertIsNone(runtime.process_environment_value(55, "SECRET"))
        self.assertEqual(select_platform_runtime(platform="darwin").process_platform, "darwin")

    def test_unsupported_runtime_keeps_core_inspection_fail_safe(self) -> None:
        runtime = select_platform_runtime(platform="freebsd14")
        self.assertEqual(runtime.process_platform, "generic")
        self.assertIsNone(runtime.process_info(os.getpid()))
        with self.assertRaisesRegex(PlatformRuntimeError, "not supported"):
            runtime.open_url("http://localhost:8501")

    def test_pending_worker_inspection_failure_remains_unknown(self) -> None:
        launch = PendingDigestLaunch(pid=125, mode="manual", process_start_ticks=458)
        with mock.patch(
            "research_digest.ui.run_status.exact_process_state",
            return_value=ExactProcessState.UNKNOWN,
        ):
            self.assertEqual(_pending_process_state(launch), RunOwnerState.UNKNOWN)

    def test_live_worker_without_exact_identity_is_stopped_before_handoff(self) -> None:
        process = mock.Mock(pid=126)
        process.poll.return_value = None
        process.wait.return_value = 0
        with (
            mock.patch("research_digest.background.subprocess.Popen", return_value=process),
            mock.patch(
                "research_digest.background._wait_for_process_identity",
                return_value=None,
            ),
            self.assertRaisesRegex(background.BackgroundLaunchError, "worker was stopped"),
        ):
            background.start_automatic_digest_worker()

        process.terminate.assert_called_once_with()

    def test_provider_group_termination_signals_only_exact_registered_owner(self) -> None:
        row = {
            "pid": 123,
            "process_group_id": 123,
            "process_start_ticks": 456,
        }
        with (
            mock.patch.object(
                cancellation,
                "exact_process_state",
                return_value=ExactProcessState.ALIVE,
            ),
            mock.patch("research_digest.cancellation.os.getpgid", return_value=123),
            mock.patch.object(cancellation, "_wait_for_process_exit", return_value=True),
            mock.patch.object(cancellation, "_signal_process_group") as signal_group,
        ):
            stopped = cancellation._terminate_registered_process(
                cast(sqlite3.Row, row),
                graceful_seconds=0.1,
            )
        self.assertTrue(stopped)
        signal_group.assert_called_once_with(123, signal.SIGTERM)

        with (
            mock.patch.object(
                cancellation,
                "exact_process_state",
                return_value=ExactProcessState.DEAD,
            ),
            mock.patch.object(cancellation, "_signal_process_group") as unrelated_signal,
        ):
            self.assertTrue(
                cancellation._terminate_registered_process(
                    cast(sqlite3.Row, row),
                    graceful_seconds=0.1,
                )
            )
        unrelated_signal.assert_not_called()

    def test_provider_group_does_not_escalate_after_identity_becomes_unknown(self) -> None:
        row = {
            "pid": 124,
            "process_group_id": 124,
            "process_start_ticks": 457,
        }
        with (
            mock.patch.object(
                cancellation,
                "exact_process_state",
                side_effect=(ExactProcessState.ALIVE, ExactProcessState.UNKNOWN),
            ),
            mock.patch("research_digest.cancellation.os.getpgid", return_value=124),
            mock.patch.object(cancellation, "_wait_for_process_exit", return_value=False),
            mock.patch.object(cancellation, "_signal_process_group") as signal_group,
        ):
            stopped = cancellation._terminate_registered_process(
                cast(sqlite3.Row, row),
                graceful_seconds=0.1,
            )

        self.assertFalse(stopped)
        signal_group.assert_called_once_with(124, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
