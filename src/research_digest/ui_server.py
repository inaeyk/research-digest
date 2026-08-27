"""Detached, singleton Streamlit UI-server lifecycle for everyday launching."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Literal, Protocol, cast
from uuid import uuid4

from research_digest import __version__
from research_digest.errors import sanitize_error
from research_digest.run_locks import (
    linux_boot_id,
    linux_process_start_ticks,
    linux_process_state,
)

UI_APPLICATION_ID = "research-digest-ui"
UI_REGISTRATION_VERSION = 1
UI_NONCE_ENV = "RESEARCH_DIGEST_UI_NONCE"
DEFAULT_UI_PORT = 8501
UI_PORT_COUNT = 10
DEFAULT_UI_STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_UI_STOP_TIMEOUT_SECONDS = 5.0
DEFAULT_UI_LOCK_TIMEOUT_SECONDS = 40.0
UI_HEALTH_PATH = "/_stcore/health"
STREAMLIT_APP_PATH = Path(__file__).resolve().parent / "ui" / "app.py"


class UIServerError(RuntimeError):
    """Raised when the local Research Digest UI cannot be managed safely."""


class ManagedProcess(Protocol):
    pid: int

    def poll(self) -> int | None:
        """Return a process exit code, or None while the process is alive."""

    def terminate(self) -> None:
        """Request termination of a process just spawned by this caller."""

    def kill(self) -> None:
        """Kill a process just spawned by this caller."""


class ForegroundManagedProcess(ManagedProcess, Protocol):
    def wait(self) -> int:
        """Wait for the foreground process and return its exit code."""


class UIServerSpawner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str],
        log_path: Path,
    ) -> ManagedProcess:
        """Start one detached UI server."""


class ForegroundUIServerSpawner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str],
        log_path: Path,
    ) -> ForegroundManagedProcess:
        """Start one foreground UI server."""


class BrowserOpener(Protocol):
    def __call__(self, url: str) -> None:
        """Open a URL in the user's browser."""


@dataclass(frozen=True)
class UIServerRegistration:
    registration_version: int
    application: str
    application_version: str
    pid: int
    process_start_ticks: int
    boot_id: str | None
    host: str
    port: int
    url: str
    started_at: str
    nonce: str
    log_path: str
    executable: str
    app_path: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "registration_version": self.registration_version,
            "application": self.application,
            "application_version": self.application_version,
            "pid": self.pid,
            "process_start_ticks": self.process_start_ticks,
            "boot_id": self.boot_id,
            "host": self.host,
            "port": self.port,
            "url": self.url,
            "started_at": self.started_at,
            "nonce": self.nonce,
            "log_path": self.log_path,
            "executable": self.executable,
            "app_path": self.app_path,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> UIServerRegistration:
        required_strings = (
            "application",
            "application_version",
            "host",
            "url",
            "started_at",
            "nonce",
            "log_path",
            "executable",
            "app_path",
        )
        if not all(isinstance(payload.get(key), str) for key in required_strings):
            raise ValueError("UI registration contains invalid text fields")
        registration_version = payload.get("registration_version")
        pid = payload.get("pid")
        process_start_ticks = payload.get("process_start_ticks")
        port = payload.get("port")
        boot_id = payload.get("boot_id")
        if not isinstance(registration_version, int):
            raise ValueError("UI registration version is invalid")
        if not isinstance(pid, int) or pid <= 0:
            raise ValueError("UI registration PID is invalid")
        if not isinstance(process_start_ticks, int) or process_start_ticks <= 0:
            raise ValueError("UI registration process identity is invalid")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("UI registration port is invalid")
        if boot_id is not None and not isinstance(boot_id, str):
            raise ValueError("UI registration boot identity is invalid")
        return cls(
            registration_version=registration_version,
            application=str(payload["application"]),
            application_version=str(payload["application_version"]),
            pid=pid,
            process_start_ticks=process_start_ticks,
            boot_id=boot_id,
            host=str(payload["host"]),
            port=port,
            url=str(payload["url"]),
            started_at=str(payload["started_at"]),
            nonce=str(payload["nonce"]),
            log_path=str(payload["log_path"]),
            executable=str(payload["executable"]),
            app_path=str(payload["app_path"]),
        )


UIState = Literal["stopped", "running", "unreachable"]


@dataclass(frozen=True)
class UIServerStatus:
    state: UIState
    running: bool
    pid: int | None = None
    port: int | None = None
    url: str | None = None
    started_at: str | None = None
    log_path: str | None = None
    application_version: str | None = None
    stale_registration_removed: bool = False

    def to_mapping(self) -> dict[str, object]:
        return {
            "state": self.state,
            "running": self.running,
            "pid": self.pid,
            "port": self.port,
            "url": self.url,
            "started_at": self.started_at,
            "log_path": self.log_path,
            "application_version": self.application_version,
            "stale_registration_removed": self.stale_registration_removed,
        }


@dataclass(frozen=True)
class UILaunchResult:
    status: UIServerStatus
    reused: bool
    browser_opened: bool

    def to_mapping(self) -> dict[str, object]:
        return {
            **self.status.to_mapping(),
            "reused": self.reused,
            "browser_opened": self.browser_opened,
        }


@dataclass(frozen=True)
class UIStopResult:
    stopped: bool
    stale_registration_removed: bool

    def to_mapping(self) -> dict[str, object]:
        return {
            "stopped": self.stopped,
            "stale_registration_removed": self.stale_registration_removed,
        }


@dataclass
class ForegroundUIServer:
    """A foreground server handle whose registration outlives only its process."""

    registration: UIServerRegistration
    reused: bool
    _process: ForegroundManagedProcess | None
    _manager: UIServerManager

    def wait(self) -> int:
        if self._process is None:
            return 0
        try:
            exit_code = self._process.wait()
            return 0 if exit_code < 0 else exit_code
        finally:
            self._manager._forget_foreground_registration(self.registration)


class UIServerController(Protocol):
    def launch(self, *, open_browser: bool = True) -> UILaunchResult:
        """Open or start the detached UI."""

    def status(self) -> UIServerStatus:
        """Return durable UI-server status."""

    def stop(self) -> UIStopResult:
        """Stop only the exact owned UI server."""


class UIServerManager:
    """Own one exact local Streamlit process without touching digest lifecycle state."""

    def __init__(
        self,
        *,
        data_dir: Path,
        preferred_port: int = DEFAULT_UI_PORT,
        port_count: int = UI_PORT_COUNT,
        startup_timeout_seconds: float = DEFAULT_UI_STARTUP_TIMEOUT_SECONDS,
        stop_timeout_seconds: float = DEFAULT_UI_STOP_TIMEOUT_SECONDS,
        lock_timeout_seconds: float = DEFAULT_UI_LOCK_TIMEOUT_SECONDS,
        public_host: str = "localhost",
        bind_host: str = "127.0.0.1",
        app_path: Path = STREAMLIT_APP_PATH,
        executable: str = sys.executable,
        application_version: str = __version__,
        spawner: UIServerSpawner | None = None,
        foreground_spawner: ForegroundUIServerSpawner | None = None,
        browser_opener: BrowserOpener | None = None,
        port_available: Callable[[str, int], bool] | None = None,
        health_checker: Callable[[str, int, float], bool] | None = None,
        identity_checker: Callable[[UIServerRegistration], bool] | None = None,
        signal_process: Callable[[int, int], None] | None = None,
        start_ticks_reader: Callable[[int], int | None] = linux_process_start_ticks,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if preferred_port <= 0 or preferred_port > 65535:
            raise ValueError("preferred UI port must be between 1 and 65535")
        if port_count <= 0 or preferred_port + port_count - 1 > 65535:
            raise ValueError("UI port range is invalid")
        if startup_timeout_seconds <= 0:
            raise ValueError("UI startup timeout must be positive")
        if stop_timeout_seconds <= 0:
            raise ValueError("UI stop timeout must be positive")
        if lock_timeout_seconds <= 0:
            raise ValueError("UI lock timeout must be positive")
        self.data_dir = data_dir.resolve()
        self.state_dir = self.data_dir / "ui"
        self.registration_path = self.state_dir / "ui-server.json"
        self.lock_path = self.state_dir / "ui-launch.lock"
        self.log_path = self.state_dir / "ui-server.log"
        self.preferred_port = preferred_port
        self.port_count = port_count
        self.startup_timeout_seconds = startup_timeout_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self.lock_timeout_seconds = lock_timeout_seconds
        self.public_host = public_host
        self.bind_host = bind_host
        self.app_path = app_path.resolve()
        # Preserve a virtual-environment interpreter path even when it is a symlink.
        # Resolving the symlink would silently escape the environment that owns the
        # installed Research Digest and Streamlit packages.
        self.executable = str(Path(executable).expanduser().absolute())
        self.application_version = application_version
        self._spawner = spawner or _spawn_detached_streamlit
        self._foreground_spawner = foreground_spawner or _spawn_foreground_streamlit
        self._browser_opener = browser_opener or open_windows_browser
        self._port_available = port_available or _port_is_available
        self._health_checker = health_checker or _streamlit_is_healthy
        self._identity_checker = identity_checker or self._default_identity_matches
        self._signal_process = signal_process or os.kill
        self._start_ticks_reader = start_ticks_reader
        self._monotonic = monotonic
        self._sleep = sleep

    def launch(self, *, open_browser: bool = True) -> UILaunchResult:
        with self._launch_lock():
            registration, reused = self._ensure_server_locked()
            status = self._status_for_registration(registration)
        browser_opened = False
        if open_browser:
            try:
                self._browser_opener(registration.url)
            except Exception as exc:
                raise UIServerError(
                    "Research Digest is running at "
                    f"{registration.url}, but the Windows browser could not be opened: "
                    f"{sanitize_error(exc)}"
                ) from exc
            browser_opened = True
        return UILaunchResult(status=status, reused=reused, browser_opened=browser_opened)

    def start_foreground(self) -> ForegroundUIServer:
        """Start or reuse the registered UI without detaching a newly started process."""

        with self._launch_lock():
            existing, _ = self._read_registration()
            if existing is not None:
                if self._identity_checker(existing):
                    compatible = (
                        existing.application_version == self.application_version
                        and Path(existing.app_path) == self.app_path
                        and Path(existing.executable) == Path(self.executable)
                    )
                    if compatible and self._wait_for_health(
                        existing,
                        timeout_seconds=self.startup_timeout_seconds,
                    ):
                        return ForegroundUIServer(existing, True, None, self)
                    if not self._terminate_owned_process(existing):
                        raise UIServerError(
                            "The registered Research Digest UI is alive but unusable and "
                            f"could not be stopped safely; inspect {existing.log_path}."
                        )
                self._remove_registration_if_nonce(existing.nonce)

            registration, process = self._start_server_locked(self._foreground_spawner)
            return ForegroundUIServer(
                registration,
                False,
                cast(ForegroundManagedProcess, process),
                self,
            )

    def status(self) -> UIServerStatus:
        with self._launch_lock():
            registration, malformed = self._read_registration()
            if registration is None:
                return UIServerStatus(
                    state="stopped",
                    running=False,
                    log_path=str(self.log_path),
                    stale_registration_removed=malformed,
                )
            if not self._identity_checker(registration):
                self._remove_registration_if_nonce(registration.nonce)
                return UIServerStatus(
                    state="stopped",
                    running=False,
                    log_path=str(self.log_path),
                    stale_registration_removed=True,
                )
            return self._status_for_registration(registration)

    def stop(self) -> UIStopResult:
        with self._launch_lock():
            registration, malformed = self._read_registration()
            if registration is None:
                return UIStopResult(stopped=False, stale_registration_removed=malformed)
            if not self._identity_checker(registration):
                self._remove_registration_if_nonce(registration.nonce)
                return UIStopResult(stopped=False, stale_registration_removed=True)
            if not self._terminate_owned_process(registration):
                raise UIServerError(
                    "Research Digest UI did not stop within the bounded timeout; "
                    f"inspect {registration.log_path}."
                )
            self._remove_registration_if_nonce(registration.nonce)
            return UIStopResult(stopped=True, stale_registration_removed=False)

    def _ensure_server_locked(self) -> tuple[UIServerRegistration, bool]:
        existing, _ = self._read_registration()
        if existing is not None:
            if self._identity_checker(existing):
                compatible = (
                    existing.application_version == self.application_version
                    and Path(existing.app_path) == self.app_path
                    and Path(existing.executable) == Path(self.executable)
                )
                if compatible and self._wait_for_health(
                    existing,
                    timeout_seconds=self.startup_timeout_seconds,
                ):
                    return existing, True
                if not self._terminate_owned_process(existing):
                    raise UIServerError(
                        "The registered Research Digest UI is alive but unusable and could "
                        f"not be stopped safely; inspect {existing.log_path}."
                    )
            self._remove_registration_if_nonce(existing.nonce)

        registration, _ = self._start_server_locked(self._spawner)
        return registration, False

    def _start_server_locked(
        self,
        spawner: UIServerSpawner | ForegroundUIServerSpawner,
    ) -> tuple[UIServerRegistration, ManagedProcess]:
        port = self._select_available_port()
        nonce = str(uuid4())
        environment = dict(os.environ)
        environment[UI_NONCE_ENV] = nonce
        command = self._streamlit_command(port)
        process = spawner(command, environment=environment, log_path=self.log_path)
        start_ticks = self._start_ticks_reader(process.pid)
        if start_ticks is None:
            _stop_just_spawned_process(process)
            raise UIServerError(
                "Research Digest UI started without an inspectable process identity; "
                f"inspect {self.log_path}."
            )
        registration = UIServerRegistration(
            registration_version=UI_REGISTRATION_VERSION,
            application=UI_APPLICATION_ID,
            application_version=self.application_version,
            pid=process.pid,
            process_start_ticks=start_ticks,
            boot_id=linux_boot_id(),
            host=self.public_host,
            port=port,
            url=f"http://{self.public_host}:{port}",
            started_at=datetime.now(UTC).isoformat(),
            nonce=nonce,
            log_path=str(self.log_path),
            executable=self.executable,
            app_path=str(self.app_path),
        )
        self._write_registration(registration)
        deadline = self._monotonic() + self.startup_timeout_seconds
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                self._remove_registration_if_nonce(nonce)
                raise UIServerError(
                    "Research Digest UI failed during startup "
                    f"(exit code {exit_code}); inspect {self.log_path}."
                )
            if self._identity_checker(registration) and self._health_checker(
                self.bind_host,
                port,
                0.5,
            ):
                return registration, process
            if self._monotonic() >= deadline:
                _stop_just_spawned_process(process)
                self._remove_registration_if_nonce(nonce)
                raise UIServerError(
                    "Research Digest UI did not become reachable within "
                    f"{self.startup_timeout_seconds:g} seconds; inspect {self.log_path}."
                )
            self._sleep(0.1)

    def _forget_foreground_registration(
        self,
        registration: UIServerRegistration,
    ) -> None:
        with self._launch_lock():
            self._remove_registration_if_nonce(registration.nonce)

    def _status_for_registration(self, registration: UIServerRegistration) -> UIServerStatus:
        healthy = self._health_checker(self.bind_host, registration.port, 0.5)
        return UIServerStatus(
            state="running" if healthy else "unreachable",
            running=healthy,
            pid=registration.pid,
            port=registration.port,
            url=registration.url,
            started_at=registration.started_at,
            log_path=registration.log_path,
            application_version=registration.application_version,
        )

    def _wait_for_health(
        self,
        registration: UIServerRegistration,
        *,
        timeout_seconds: float,
    ) -> bool:
        deadline = self._monotonic() + timeout_seconds
        while True:
            if not self._identity_checker(registration):
                return False
            if self._health_checker(self.bind_host, registration.port, 0.5):
                return True
            if self._monotonic() >= deadline:
                return False
            self._sleep(0.1)

    def _terminate_owned_process(self, registration: UIServerRegistration) -> bool:
        if not self._identity_checker(registration):
            return True
        self._signal_process(registration.pid, signal.SIGTERM)
        if self._wait_for_exit(registration, self.stop_timeout_seconds):
            return True
        if self._identity_checker(registration):
            self._signal_process(registration.pid, signal.SIGKILL)
        return self._wait_for_exit(registration, self.stop_timeout_seconds)

    def _wait_for_exit(
        self,
        registration: UIServerRegistration,
        timeout_seconds: float,
    ) -> bool:
        deadline = self._monotonic() + timeout_seconds
        while self._identity_checker(registration):
            if self._monotonic() >= deadline:
                return False
            self._sleep(0.05)
        return True

    def _select_available_port(self) -> int:
        for port in range(self.preferred_port, self.preferred_port + self.port_count):
            if self._port_available(self.bind_host, port):
                return port
        last_port = self.preferred_port + self.port_count - 1
        raise UIServerError(
            f"No local UI port is available from {self.preferred_port} to {last_port}."
        )

    def _streamlit_command(self, port: int) -> list[str]:
        return [
            self.executable,
            "-m",
            "streamlit",
            "run",
            str(self.app_path),
            f"--server.address={self.bind_host}",
            f"--server.port={port}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ]

    def _default_identity_matches(self, registration: UIServerRegistration) -> bool:
        if registration.registration_version != UI_REGISTRATION_VERSION:
            return False
        if registration.application != UI_APPLICATION_ID:
            return False
        if registration.host != self.public_host:
            return False
        if registration.url != f"http://{registration.host}:{registration.port}":
            return False
        if registration.boot_id is not None and linux_boot_id() != registration.boot_id:
            return False
        if self._start_ticks_reader(registration.pid) != registration.process_start_ticks:
            return False
        if linux_process_state(registration.pid) == "Z":
            return False
        if _process_environment_value(registration.pid, UI_NONCE_ENV) != registration.nonce:
            return False
        command = _linux_process_command(registration.pid)
        return (
            command is not None
            and "streamlit" in command
            and "run" in command
            and registration.app_path in command
            and f"--server.port={registration.port}" in command
        )

    @contextmanager
    def _launch_lock(self) -> Iterator[None]:
        import fcntl

        self._ensure_state_dir()
        with self.lock_path.open("a+b") as lock_file:
            deadline = self._monotonic() + self.lock_timeout_seconds
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if self._monotonic() >= deadline:
                        raise UIServerError(
                            "Timed out waiting for another Research Digest launcher "
                            "invocation to finish."
                        ) from exc
                    self._sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            self.state_dir.chmod(0o700)

    def _read_registration(self) -> tuple[UIServerRegistration | None, bool]:
        if not self.registration_path.exists():
            return None, False
        try:
            payload = json.loads(self.registration_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("UI registration must be a JSON object")
            return UIServerRegistration.from_mapping(payload), False
        except (OSError, ValueError, json.JSONDecodeError):
            self._remove_registration_file()
            return None, True

    def _write_registration(self, registration: UIServerRegistration) -> None:
        self._ensure_state_dir()
        temporary = self.registration_path.with_name(
            f"{self.registration_path.name}.{registration.nonce}.tmp"
        )
        temporary.write_text(
            json.dumps(registration.to_mapping(), sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(self.registration_path)

    def _remove_registration_if_nonce(self, nonce: str) -> None:
        registration, _ = self._read_registration()
        if registration is not None and registration.nonce == nonce:
            self._remove_registration_file()

    def _remove_registration_file(self) -> None:
        with suppress(FileNotFoundError):
            self.registration_path.unlink()


def _spawn_detached_streamlit(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    log_path: Path,
) -> ManagedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle: IO[bytes] = log_path.open("ab")
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed local executable and arguments.
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
            env=dict(environment),
        )
    finally:
        log_handle.close()
    return process


def _spawn_foreground_streamlit(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    log_path: Path,
) -> ForegroundManagedProcess:
    del log_path
    return subprocess.Popen(  # noqa: S603 - fixed local executable and arguments.
        list(command),
        close_fds=True,
        env=dict(environment),
    )


def _stop_just_spawned_process(process: ManagedProcess) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    deadline = time.monotonic() + 1.0
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if process.poll() is None:
        process.kill()


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _streamlit_is_healthy(host: str, port: int, timeout_seconds: float) -> bool:
    url = f"http://{host}:{port}{UI_HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
            return bool(
                response.status == 200 and response.read(32).strip().lower() == b"ok"
            )
    except (OSError, urllib.error.URLError):
        return False


def _process_environment_value(pid: int, name: str) -> str | None:
    try:
        values = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return None
    prefix = name.encode("utf-8") + b"="
    for value in values:
        if value.startswith(prefix):
            return value[len(prefix) :].decode("utf-8", errors="strict")
    return None


def _linux_process_command(pid: int) -> tuple[str, ...] | None:
    try:
        values = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return tuple(value.decode("utf-8", errors="strict") for value in values if value)
    except (OSError, UnicodeDecodeError):
        return None


def open_windows_browser(url: str) -> None:
    """Open the exact local URL with the Windows default browser from WSL."""

    from research_digest.windows_launcher import run_windows_powershell

    run_windows_powershell(
        "$ErrorActionPreference = 'Stop'\n"
        f"Start-Process -FilePath {_powershell_quote(url)}"
    )


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
