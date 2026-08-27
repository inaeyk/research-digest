from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast
from unittest import mock

from research_digest.db import APP_RUN_RUNNING, Database
from research_digest.models import DateSelection
from research_digest.platform_runtime import LinuxPlatformRuntime
from research_digest.ui_server import (
    UI_APPLICATION_ID,
    UI_NONCE_ENV,
    UI_REGISTRATION_VERSION,
    UIServerError,
    UIServerManager,
    UIServerRegistration,
    _spawn_detached_streamlit,
)


class FakeProcess:
    def __init__(self, runtime: FakeRuntime, pid: int, *, returncode: int | None = None) -> None:
        self.runtime = runtime
        self.pid = pid
        self.returncode = returncode

    def poll(self) -> int | None:
        if self.pid not in self.runtime.live:
            return self.returncode if self.returncode is not None else 0
        return self.returncode

    def terminate(self) -> None:
        self.runtime.live.pop(self.pid, None)

    def kill(self) -> None:
        self.runtime.live.pop(self.pid, None)

    def wait(self) -> int:
        if self.pid in self.runtime.live:
            raise AssertionError("fake foreground process is still running")
        return self.returncode if self.returncode is not None else 0


class FakeRuntime:
    def __init__(self) -> None:
        self.next_pid = 4100
        self.live: dict[int, int] = {}
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str]] = []
        self.logs: list[Path] = []
        self.browser_urls: list[str] = []
        self.signals: list[tuple[int, int]] = []
        self.unavailable_ports: set[int] = set()
        self.healthy_ports: set[int] = set()
        self.fail_next_spawn = False

    def spawn(
        self,
        command: object,
        *,
        environment: object,
        log_path: Path,
    ) -> FakeProcess:
        values = tuple(cast(list[str], command))
        env = dict(cast(dict[str, str], environment))
        pid = self.next_pid
        self.next_pid += 1
        ticks = pid * 10
        self.live[pid] = ticks
        self.commands.append(values)
        self.environments.append(env)
        self.logs.append(log_path)
        port = int(next(value.split("=", 1)[1] for value in values if "server.port=" in value))
        if self.fail_next_spawn:
            self.fail_next_spawn = False
            return FakeProcess(self, pid, returncode=7)
        self.healthy_ports.add(port)
        return FakeProcess(self, pid)

    def start_ticks(self, pid: int) -> int | None:
        return self.live.get(pid)

    def identity(self, registration: UIServerRegistration) -> bool:
        return self.live.get(registration.pid) == registration.process_start_ticks

    def port_available(self, host: str, port: int) -> bool:
        del host
        return port not in self.unavailable_ports and port not in self.healthy_ports

    def health(self, host: str, port: int, timeout: float) -> bool:
        del host, timeout
        return port in self.healthy_ports

    def signal(self, pid: int, requested_signal: int) -> None:
        self.signals.append((pid, requested_signal))
        self.live.pop(pid, None)

    def open_browser(self, url: str) -> None:
        self.browser_urls.append(url)


class UIServerManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.runtime = FakeRuntime()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def manager(self, **overrides: object) -> UIServerManager:
        values: dict[str, object] = {
            "data_dir": self.root,
            "executable": "/usr/bin/python3",
            "app_path": self.root / "installed package" / "ui" / "app.py",
            "spawner": self.runtime.spawn,
            "foreground_spawner": self.runtime.spawn,
            "browser_opener": self.runtime.open_browser,
            "port_available": self.runtime.port_available,
            "health_checker": self.runtime.health,
            "identity_checker": self.runtime.identity,
            "signal_process": self.runtime.signal,
            "start_ticks_reader": self.runtime.start_ticks,
            "sleep": lambda seconds: None,
        }
        values.update(overrides)
        return UIServerManager(**cast(Any, values))

    def test_launch_without_server_spawns_exactly_one_and_opens_actual_url(self) -> None:
        result = self.manager().launch()

        self.assertFalse(result.reused)
        self.assertTrue(result.browser_opened)
        self.assertEqual(result.status.port, 8501)
        self.assertEqual(self.runtime.browser_urls, ["http://localhost:8501"])
        self.assertEqual(len(self.runtime.commands), 1)
        command = self.runtime.commands[0]
        self.assertIn("--server.address=127.0.0.1", command)
        self.assertIn("--server.port=8501", command)
        self.assertIn("--server.headless=true", command)
        self.assertEqual(
            self.runtime.logs,
            [self.root.resolve() / "ui" / "ui-server.log"],
        )
        self.assertTrue(self.runtime.environments[0][UI_NONCE_ENV])

    def test_streamlit_spawn_preserves_virtual_environment_python_symlink(self) -> None:
        venv_bin = self.root / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        python_link = venv_bin / "python"
        python_link.symlink_to(Path(sys.executable))
        manager = self.manager(executable=str(python_link))

        manager.launch(open_browser=False)

        self.assertEqual(self.runtime.commands[0][0], str(python_link.absolute()))
        self.assertNotEqual(self.runtime.commands[0][0], str(python_link.resolve()))

    def test_existing_server_is_reused_without_duplicate_spawn(self) -> None:
        manager = self.manager()
        first = manager.launch(open_browser=False)
        second = manager.launch(open_browser=False)

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.status.pid, second.status.pid)
        self.assertEqual(len(self.runtime.commands), 1)

    def test_foreground_serve_registration_is_reused_by_detached_launcher(self) -> None:
        foreground = self.manager().start_foreground()

        launched = self.manager().launch(open_browser=False)

        self.assertFalse(foreground.reused)
        self.assertTrue(launched.reused)
        self.assertEqual(launched.status.pid, foreground.registration.pid)
        self.assertEqual(len(self.runtime.commands), 1)
        self.assertTrue(self.manager().stop().stopped)
        self.assertEqual(foreground.wait(), 0)
        self.assertFalse(self.manager().status().running)

    def test_two_simultaneous_launches_serialize_to_one_server(self) -> None:
        first_manager = self.manager()
        second_manager = self.manager()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda manager: manager.launch(open_browser=False),
                    (first_manager, second_manager),
                )
            )

        self.assertEqual(len(self.runtime.commands), 1)
        self.assertEqual({result.status.pid for result in results}, {4100})
        self.assertEqual(sum(not result.reused for result in results), 1)

    def test_launcher_serialization_wait_is_bounded(self) -> None:
        import fcntl

        manager = self.manager(
            lock_timeout_seconds=1.0,
            monotonic=iter((0.0, 0.0, 2.0)).__next__,
        )
        manager.state_dir.mkdir(parents=True)
        with manager.lock_path.open("a+b") as held_lock:
            fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(UIServerError, "Timed out waiting"):
                manager.status()

    def test_stale_pid_registration_is_discarded_and_replaced_without_signal(self) -> None:
        manager = self.manager()
        first = manager.launch(open_browser=False)
        assert first.status.pid is not None
        self.runtime.live.pop(first.status.pid)
        self.runtime.healthy_ports.clear()

        second = manager.launch(open_browser=False)

        self.assertEqual(len(self.runtime.commands), 2)
        self.assertNotEqual(first.status.pid, second.status.pid)
        self.assertEqual(self.runtime.signals, [])

    def test_pid_reuse_start_ticks_mismatch_is_not_treated_as_owned(self) -> None:
        manager = self.manager()
        first = manager.launch(open_browser=False)
        assert first.status.pid is not None
        self.runtime.live[first.status.pid] += 1
        self.runtime.healthy_ports.clear()

        second = manager.launch(open_browser=False)

        self.assertNotEqual(first.status.pid, second.status.pid)
        self.assertEqual(self.runtime.signals, [])

    def test_unrelated_default_port_is_untouched_and_fallback_is_reused(self) -> None:
        self.runtime.unavailable_ports.add(8501)
        manager = self.manager()
        first = manager.launch()
        second = manager.launch(open_browser=False)

        self.assertEqual(first.status.port, 8502)
        self.assertEqual(self.runtime.browser_urls, ["http://localhost:8502"])
        self.assertTrue(second.reused)
        self.assertEqual(len(self.runtime.commands), 1)
        self.assertEqual(self.runtime.signals, [])

    def test_failed_startup_is_actionable_and_does_not_open_browser(self) -> None:
        self.runtime.fail_next_spawn = True
        manager = self.manager()

        with self.assertRaisesRegex(UIServerError, "exit code 7.*ui-server.log"):
            manager.launch()

        self.assertEqual(self.runtime.browser_urls, [])
        self.assertFalse(manager.registration_path.exists())

    def test_startup_identity_failure_has_identity_specific_diagnostic(self) -> None:
        health = mock.Mock(return_value=True)
        manager = self.manager(
            identity_checker=lambda _registration: False,
            health_checker=health,
            startup_timeout_seconds=1.0,
            monotonic=iter((0.0, 0.0, 2.0)).__next__,
        )

        with self.assertRaisesRegex(
            UIServerError,
            "exact registered process identity could not be validated",
        ):
            manager.launch()

        health.assert_not_called()
        self.assertEqual(self.runtime.browser_urls, [])
        self.assertFalse(manager.registration_path.exists())

    def test_process_exit_after_first_poll_precedes_timeout_diagnostic(self) -> None:
        process = mock.Mock(pid=4400)
        process.poll.side_effect = (None, 9)
        manager = self.manager(
            spawner=lambda _command, *, environment, log_path: process,
            identity_checker=lambda _registration: False,
            start_ticks_reader=lambda _pid: 44_000,
            startup_timeout_seconds=1.0,
            monotonic=iter((0.0, 0.0, 2.0)).__next__,
        )

        with self.assertRaisesRegex(UIServerError, "exit code 9"):
            manager.launch()

        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        self.assertEqual(self.runtime.browser_urls, [])
        self.assertFalse(manager.registration_path.exists())

    def test_startup_health_failure_has_health_specific_diagnostic(self) -> None:
        manager = self.manager(
            health_checker=lambda _host, _port, _timeout: False,
            startup_timeout_seconds=1.0,
            monotonic=iter((0.0, 0.0, 2.0)).__next__,
        )

        with self.assertRaisesRegex(
            UIServerError,
            "identity was validated, but its health endpoint did not become ready",
        ):
            manager.launch()

        self.assertEqual(self.runtime.browser_urls, [])
        self.assertFalse(manager.registration_path.exists())

    def test_malformed_registration_is_removed_without_signalling(self) -> None:
        manager = self.manager()
        manager.state_dir.mkdir(parents=True)
        manager.registration_path.write_text("not json", encoding="utf-8")

        status = manager.status()

        self.assertFalse(status.running)
        self.assertTrue(status.stale_registration_removed)
        self.assertEqual(status.log_path, str(manager.log_path))
        self.assertEqual(self.runtime.signals, [])

    def test_ui_stop_signals_only_exact_owned_pid_and_launch_restores_ui(self) -> None:
        manager = self.manager()
        first = manager.launch(open_browser=False)
        assert first.status.pid is not None

        stopped = manager.stop()
        relaunched = manager.launch(open_browser=False)

        self.assertTrue(stopped.stopped)
        self.assertEqual(self.runtime.signals, [(first.status.pid, signal.SIGTERM)])
        self.assertNotEqual(first.status.pid, relaunched.status.pid)
        self.assertEqual(len(self.runtime.commands), 2)

    def test_ui_stop_does_not_change_active_digest_or_its_lock(self) -> None:
        db = Database(self.root / "digest.sqlite3")
        self.addCleanup(db.close)
        profile = db.create_interest_profile(name="Gravity", description="Gravity")
        db.acquire_run_lock(owner="uninspectable-test-owner", stale_after_seconds=60)
        run_id = db.create_app_run(
            profile_id=profile.id,
            source_name="arxiv",
            date_selection=DateSelection.latest_available(),
        )
        db.mark_app_run_running(run_id)
        manager = self.manager()
        manager.launch(open_browser=False)

        manager.stop()

        run = db.get_app_run(run_id)
        assert run is not None
        self.assertEqual(run["status"], APP_RUN_RUNNING)
        self.assertIsNotNone(db.get_run_lock())

    def test_launch_does_not_create_digest_runs_or_touch_digest_lock(self) -> None:
        db = Database(self.root / "digest.sqlite3")
        self.addCleanup(db.close)
        manager = self.manager()

        manager.launch(open_browser=False)

        self.assertEqual(db.get_app_runs(), [])
        self.assertIsNone(db.get_run_lock())

    def test_status_discovers_running_server_from_new_manager(self) -> None:
        first_manager = self.manager()
        launched = first_manager.launch(open_browser=False)

        fresh_manager = self.manager()
        status = fresh_manager.status()

        self.assertTrue(status.running)
        self.assertEqual(status.pid, launched.status.pid)
        self.assertEqual(status.url, launched.status.url)

    def test_owned_old_application_version_is_restarted_safely(self) -> None:
        old_manager = self.manager(application_version="0.2.0")
        old = old_manager.launch(open_browser=False)
        assert old.status.pid is not None

        current = self.manager(application_version="0.3.0").launch(open_browser=False)

        self.assertNotEqual(old.status.pid, current.status.pid)
        self.assertEqual(self.runtime.signals, [(old.status.pid, signal.SIGTERM)])

    def test_detached_spawner_returns_while_child_remains_alive(self) -> None:
        log_path = self.root / "state" / "ui.log"
        process = _spawn_detached_streamlit(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            environment=os.environ,
            log_path=log_path,
        )
        try:
            self.assertIsNone(process.poll())
            self.assertTrue(log_path.exists())
        finally:
            process.terminate()
            deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if process.poll() is None:
                process.kill()

    def test_registration_json_contains_no_environment_or_secret_values(self) -> None:
        manager = self.manager()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret"}):
            manager.launch(open_browser=False)
        payload = json.loads(manager.registration_path.read_text(encoding="utf-8"))

        self.assertNotIn("environment", payload)
        self.assertNotIn("sk-secret", json.dumps(payload))

    def test_default_identity_requires_ticks_boot_nonce_and_streamlit_command(self) -> None:
        app_path = (self.root / "package" / "ui" / "app.py").resolve()
        executable = "/usr/bin/python3"
        manager = UIServerManager(
            data_dir=self.root,
            executable=executable,
            app_path=app_path,
            start_ticks_reader=lambda pid: 991 if pid == 77 else None,
            platform_runtime=LinuxPlatformRuntime(),
        )
        registration = UIServerRegistration(
            registration_version=UI_REGISTRATION_VERSION,
            application=UI_APPLICATION_ID,
            application_version="0.3.0",
            pid=77,
            process_start_ticks=991,
            boot_id="boot-a",
            host="localhost",
            port=8501,
            url="http://localhost:8501",
            started_at="2026-08-27T12:00:00+00:00",
            nonce="nonce-a",
            log_path=str(self.root / "ui" / "ui-server.log"),
            executable=executable,
            app_path=str(app_path),
        )
        command = (
            executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.port=8501",
        )
        with (
            mock.patch("research_digest.ui_server.linux_boot_id", return_value="boot-a"),
            mock.patch("research_digest.ui_server.linux_process_state", return_value="S"),
            mock.patch(
                "research_digest.ui_server._process_environment_value",
                return_value="nonce-a",
            ),
            mock.patch("research_digest.ui_server._linux_process_command", return_value=command),
        ):
            self.assertTrue(manager._default_identity_matches(registration))

        mismatched_manager = UIServerManager(
            data_dir=self.root,
            executable=executable,
            app_path=app_path,
            start_ticks_reader=lambda pid: 992 if pid == 77 else None,
            platform_runtime=LinuxPlatformRuntime(),
        )
        self.assertFalse(mismatched_manager._default_identity_matches(registration))

    def test_default_identity_rejects_nonce_or_command_mismatch(self) -> None:
        app_path = (self.root / "package" / "ui" / "app.py").resolve()
        manager = UIServerManager(
            data_dir=self.root,
            executable="/usr/bin/python3",
            app_path=app_path,
            start_ticks_reader=lambda pid: 991,
            platform_runtime=LinuxPlatformRuntime(),
        )
        registration = UIServerRegistration(
            registration_version=UI_REGISTRATION_VERSION,
            application=UI_APPLICATION_ID,
            application_version="0.3.0",
            pid=77,
            process_start_ticks=991,
            boot_id=None,
            host="localhost",
            port=8501,
            url="http://localhost:8501",
            started_at="2026-08-27T12:00:00+00:00",
            nonce="nonce-a",
            log_path=str(self.root / "ui" / "ui-server.log"),
            executable="/usr/bin/python3",
            app_path=str(app_path),
        )
        with (
            mock.patch("research_digest.ui_server.linux_process_state", return_value="S"),
            mock.patch(
                "research_digest.ui_server._process_environment_value",
                return_value="different-nonce",
            ),
        ):
            self.assertFalse(manager._default_identity_matches(registration))
        with (
            mock.patch("research_digest.ui_server.linux_process_state", return_value="S"),
            mock.patch(
                "research_digest.ui_server._process_environment_value",
                return_value="nonce-a",
            ),
            mock.patch(
                "research_digest.ui_server._linux_process_command",
                return_value=("python", "unrelated.py"),
            ),
        ):
            self.assertFalse(manager._default_identity_matches(registration))


if __name__ == "__main__":
    unittest.main()
