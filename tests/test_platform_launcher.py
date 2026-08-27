from __future__ import annotations

import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.launcher import LauncherPlatformError, install_launcher, uninstall_launcher
from research_digest.macos_launcher import (
    MACOS_LAUNCHER_ID,
    MacLauncherRequest,
    MacLauncherResult,
)
from research_digest.windows_launcher import (
    WindowsLauncherRequest,
    WindowsLauncherResult,
)


class FakeMacBackend:
    def __init__(self) -> None:
        self.requests: list[MacLauncherRequest] = []
        self.uninstall_calls = 0

    def install(self, request: MacLauncherRequest) -> MacLauncherResult:
        self.requests.append(request)
        return MacLauncherResult(
            operation="installed_or_updated",
            installed=True,
            path=str(request.bundle_path),
            target=request.command_executable,
        )

    def uninstall(self, *, bundle_path: Path | None = None) -> MacLauncherResult:
        self.uninstall_calls += 1
        return MacLauncherResult(
            operation="removed",
            installed=False,
            path=str(bundle_path or Path("/Users/me/Applications/Research Digest.app")),
        )


class FakeWindowsBackend:
    def __init__(self) -> None:
        self.requests: list[WindowsLauncherRequest] = []
        self.uninstall_calls = 0

    def install(self, request: WindowsLauncherRequest) -> WindowsLauncherResult:
        self.requests.append(request)
        return WindowsLauncherResult(
            operation="installed_or_updated",
            installed=True,
            path="C:\\Users\\Me\\Desktop\\Research Digest.lnk",
            distro=request.distro,
            target=request.wsl_executable,
            arguments=request.windows_arguments,
        )

    def uninstall(self) -> WindowsLauncherResult:
        self.uninstall_calls += 1
        return WindowsLauncherResult(
            operation="removed",
            installed=False,
            path="C:\\Users\\Me\\Desktop\\Research Digest.lnk",
        )


class PlatformLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.root = root
        self.config = AppConfig(
            db_path=root / "data" / "digest.sqlite3",
            data_dir=root / "data",
            config_dir=root / "config",
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="unused",
            codex_model=None,
            codex_timeout_seconds=5,
            automatic_coverage_start_date=date(2026, 8, 27),
        )
        self.command = root / "venv" / "bin" / "research-digest"
        self.codex = root / "node" / "bin" / "codex"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_darwin_dispatches_to_mac_bundle_backend(self) -> None:
        backend = FakeMacBackend()
        with (
            mock.patch(
                "research_digest.macos_launcher.resolve_research_digest_command",
                return_value=str(self.command),
            ),
            mock.patch(
                "research_digest.macos_launcher.resolve_codex_executable",
                return_value=str(self.codex),
            ),
        ):
            result = install_launcher(
                config=self.config,
                macos_backend=backend,
                platform="darwin",
            )

        self.assertIsInstance(result, MacLauncherResult)
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(backend.requests[0].command_executable, str(self.command))

    def test_windows_dispatch_remains_the_existing_wsl_backend(self) -> None:
        backend = FakeWindowsBackend()
        with (
            mock.patch(
                "research_digest.windows_launcher.resolve_windows_wsl_executable",
                return_value="C:\\Windows\\System32\\wsl.exe",
            ),
            mock.patch(
                "research_digest.windows_launcher.resolve_research_digest_command",
                return_value=str(self.command),
            ),
        ):
            result = install_launcher(
                config=self.config,
                distro="Research Debian",
                windows_backend=backend,
                platform="linux",
            )

        self.assertIsInstance(result, WindowsLauncherResult)
        self.assertEqual(backend.requests[0].distro, "Research Debian")
        self.assertIn("wsl.exe", backend.requests[0].wsl_executable.lower())

    def test_unsupported_platform_fails_without_touching_backends(self) -> None:
        mac = FakeMacBackend()
        windows = FakeWindowsBackend()
        with self.assertRaisesRegex(LauncherPlatformError, "macOS"):
            install_launcher(
                config=self.config,
                windows_backend=windows,
                macos_backend=mac,
                platform="freebsd14",
            )
        self.assertEqual(mac.requests, [])
        self.assertEqual(windows.requests, [])

    def test_macos_cli_install_and_uninstall_use_shared_platform_dispatch(self) -> None:
        backend = FakeMacBackend()
        with (
            mock.patch("research_digest.launcher.sys.platform", "darwin"),
            mock.patch(
                "research_digest.macos_launcher.resolve_research_digest_command",
                return_value=str(self.command),
            ),
            mock.patch(
                "research_digest.macos_launcher.resolve_codex_executable",
                return_value=str(self.codex),
            ),
        ):
            install_stdout = io.StringIO()
            install_exit = run_cli(
                argv=["install-launcher", "--json"],
                stdout=install_stdout,
                stderr=io.StringIO(),
                config=self.config,
                macos_launcher_backend=backend,
            )
            uninstall_stdout = io.StringIO()
            uninstall_exit = run_cli(
                argv=["uninstall-launcher", "--json"],
                stdout=uninstall_stdout,
                stderr=io.StringIO(),
                macos_launcher_backend=backend,
            )

        self.assertEqual((install_exit, uninstall_exit), (0, 0))
        self.assertEqual(json.loads(install_stdout.getvalue())["platform"], "macos")
        self.assertEqual(json.loads(uninstall_stdout.getvalue())["operation"], "removed")
        self.assertEqual(backend.uninstall_calls, 1)

    def test_mac_launcher_marker_is_accepted_by_canonical_launch_cli(self) -> None:
        controller = mock.Mock()
        controller.launch.return_value.to_mapping.return_value = {}
        with mock.patch("research_digest.cli._write_ui_launch_result"):
            exit_code = run_cli(
                argv=["launch", "--launcher-id", MACOS_LAUNCHER_ID, "--no-browser"],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                ui_server_manager=controller,
            )
        self.assertEqual(exit_code, 0)
        controller.launch.assert_called_once_with(open_browser=False)

    def test_platform_uninstall_dispatches_without_scientific_state(self) -> None:
        backend = FakeMacBackend()
        result = uninstall_launcher(macos_backend=backend, platform="darwin")
        self.assertEqual(result.operation, "removed")
        self.assertEqual(backend.uninstall_calls, 1)


if __name__ == "__main__":
    unittest.main()
