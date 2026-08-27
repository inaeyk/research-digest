from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from research_digest.cli import run_cli
from research_digest.config import AppConfig
from research_digest.db import Database
from research_digest.models import DateSelection
from research_digest.ui.run_status import get_active_digest_status
from research_digest.ui_server import (
    UILaunchResult,
    UIServerStatus,
    UIStopResult,
)
from research_digest.windows_launcher import (
    WINDOWS_LAUNCHER_ID,
    WindowsLauncherRequest,
    WindowsLauncherResult,
)


class FakeUIController:
    def __init__(self) -> None:
        self.launch_calls: list[bool] = []
        self.status_calls = 0
        self.stop_calls = 0
        self.launch_error: Exception | None = None
        self.ui_status = UIServerStatus(
            state="running",
            running=True,
            pid=5123,
            port=8502,
            url="http://localhost:8502",
            started_at="2026-08-27T12:00:00+00:00",
            log_path="/data/ui/ui-server.log",
            application_version="0.3.0",
        )

    def launch(self, *, open_browser: bool = True) -> UILaunchResult:
        self.launch_calls.append(open_browser)
        if self.launch_error is not None:
            raise self.launch_error
        return UILaunchResult(
            status=self.ui_status,
            reused=len(self.launch_calls) > 1,
            browser_opened=open_browser,
        )

    def status(self) -> UIServerStatus:
        self.status_calls += 1
        return self.ui_status

    def stop(self) -> UIStopResult:
        self.stop_calls += 1
        return UIStopResult(stopped=True, stale_registration_removed=False)


class FakeWindowsLauncherController:
    def __init__(self) -> None:
        self.install_requests: list[WindowsLauncherRequest] = []
        self.uninstall_calls = 0

    def install(self, request: WindowsLauncherRequest) -> WindowsLauncherResult:
        self.install_requests.append(request)
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


class LauncherCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.config = AppConfig(
            db_path=root / "data" / "digest.sqlite3",
            data_dir=root / "data",
            config_dir=root / "config",
            analyzer_provider="codex",
            openai_api_key=None,
            openai_model="unused",
            codex_model=None,
            codex_timeout_seconds=1,
            automatic_coverage_start_date=date(2026, 8, 27),
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_launch_uses_only_ui_controller_and_emits_actual_endpoint(self) -> None:
        controller = FakeUIController()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch("research_digest.cli.load_config", side_effect=AssertionError("config")),
            mock.patch(
                "research_digest.cli.build_configured_analyzer",
                side_effect=AssertionError("analyzer"),
            ),
            mock.patch.object(
                __import__("research_digest.cli", fromlist=["ARXIV_SOURCE_DEFINITION"]),
                "ARXIV_SOURCE_DEFINITION",
                side_effect=AssertionError("source"),
            ),
        ):
            exit_code = run_cli(
                argv=["launch", "--json"],
                stdout=stdout,
                stderr=stderr,
                ui_server_manager=controller,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["url"], "http://localhost:8502")
        self.assertTrue(payload["browser_opened"])
        self.assertEqual(controller.launch_calls, [True])

    def test_launch_no_browser_and_shortcut_marker_are_accepted(self) -> None:
        controller = FakeUIController()
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=[
                "launch",
                "--no-browser",
                "--launcher-id",
                WINDOWS_LAUNCHER_ID,
                "--json",
            ],
            stdout=stdout,
            stderr=stderr,
            ui_server_manager=controller,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(controller.launch_calls, [False])
        self.assertFalse(json.loads(stdout.getvalue())["browser_opened"])

    def test_launch_failure_is_actionable_and_not_false_success(self) -> None:
        controller = FakeUIController()
        controller.launch_error = RuntimeError("startup exited; inspect /data/ui/ui-server.log")
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            argv=["launch"],
            stdout=stdout,
            stderr=stderr,
            ui_server_manager=controller,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("startup exited", stderr.getvalue())
        self.assertIn("ui-server.log", stderr.getvalue())

    def test_ui_status_json_and_ui_stop_use_separate_controller_methods(self) -> None:
        controller = FakeUIController()
        status_stdout = io.StringIO()
        stop_stdout = io.StringIO()

        status_exit = run_cli(
            argv=["ui-status", "--json"],
            stdout=status_stdout,
            stderr=io.StringIO(),
            ui_server_manager=controller,
        )
        stop_exit = run_cli(
            argv=["ui-stop", "--json"],
            stdout=stop_stdout,
            stderr=io.StringIO(),
            ui_server_manager=controller,
        )

        self.assertEqual((status_exit, stop_exit), (0, 0))
        self.assertEqual(controller.status_calls, 1)
        self.assertEqual(controller.stop_calls, 1)
        self.assertTrue(json.loads(status_stdout.getvalue())["running"])
        self.assertTrue(json.loads(stop_stdout.getvalue())["stopped"])

    def test_stopped_ui_status_retains_actionable_log_path(self) -> None:
        controller = FakeUIController()
        controller.ui_status = UIServerStatus(
            state="stopped",
            running=False,
            log_path="/data/ui/ui-server.log",
        )
        stdout = io.StringIO()

        exit_code = run_cli(
            argv=["ui-status", "--json"],
            stdout=stdout,
            stderr=io.StringIO(),
            ui_server_manager=controller,
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["running"])
        self.assertEqual(payload["log_path"], "/data/ui/ui-server.log")

    def test_launch_preserves_active_digest_for_reattached_ui(self) -> None:
        self.config.data_dir.mkdir(parents=True)
        db = Database(self.config.db_path)
        self.addCleanup(db.close)
        profile = db.create_interest_profile(name="Gravity", description="Gravity")
        db.acquire_run_lock(owner="uninspectable-launcher-test", stale_after_seconds=60)
        run_id = db.create_app_run(
            profile_id=profile.id,
            source_name="arxiv",
            date_selection=DateSelection.latest_available(),
        )
        db.mark_app_run_running(run_id)
        controller = FakeUIController()

        exit_code = run_cli(
            argv=["launch", "--no-browser"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            ui_server_manager=controller,
        )

        active = get_active_digest_status(db)
        self.assertEqual(exit_code, 0)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.run_id, run_id)
        self.assertIsNotNone(db.get_run_lock())

    def test_install_launcher_discovers_distro_and_is_idempotent_at_shared_boundary(self) -> None:
        controller = FakeWindowsLauncherController()
        with (
            mock.patch(
                "research_digest.windows_launcher.resolve_windows_wsl_executable",
                return_value="C:\\Windows\\System32\\wsl.exe",
            ),
            mock.patch(
                "research_digest.windows_launcher.resolve_research_digest_command",
                return_value="/home/me/app/.venv/bin/research-digest",
            ),
            mock.patch.dict(os.environ, {"WSL_DISTRO_NAME": "Research Debian"}),
        ):
            outputs = []
            for _ in range(2):
                stdout = io.StringIO()
                exit_code = run_cli(
                    argv=["install-launcher", "--json"],
                    stdout=stdout,
                    stderr=io.StringIO(),
                    config=self.config,
                    windows_launcher_backend=controller,
                )
                self.assertEqual(exit_code, 0)
                outputs.append(json.loads(stdout.getvalue()))

        self.assertEqual(len(controller.install_requests), 2)
        self.assertEqual(controller.install_requests[0], controller.install_requests[1])
        self.assertEqual(outputs[0]["distro"], "Research Debian")
        self.assertNotIn("OPENAI_API_KEY", outputs[0]["arguments"])

    def test_uninstall_launcher_uses_same_owned_backend(self) -> None:
        controller = FakeWindowsLauncherController()
        stdout = io.StringIO()

        exit_code = run_cli(
            argv=["uninstall-launcher", "--json"],
            stdout=stdout,
            stderr=io.StringIO(),
            windows_launcher_backend=controller,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(controller.uninstall_calls, 1)
        self.assertEqual(json.loads(stdout.getvalue())["operation"], "removed")

    def test_existing_serve_remains_the_foreground_manual_boundary(self) -> None:
        launched: list[tuple[str, ...]] = []
        with (
            mock.patch("research_digest.cli._select_available_port", return_value=18501),
            mock.patch(
                "research_digest.cli.subprocess.Popen",
                side_effect=AssertionError("serve must not detach"),
            ),
        ):
            exit_code = run_cli(
                argv=["serve", "--port", "18501"],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                process_launcher=lambda command: launched.append(tuple(command)),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(launched), 1)


if __name__ == "__main__":
    unittest.main()
