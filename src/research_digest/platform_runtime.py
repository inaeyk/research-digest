"""Small platform boundary for exact local process and desktop operations."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class PlatformRuntimeError(RuntimeError):
    """Raised when an OS-specific desktop/runtime operation is unavailable."""


class ExactProcessState(StrEnum):
    """Result of validating one PID plus its recorded start identity."""

    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class NativeProcessInfo:
    """Stable process facts used to reject PID reuse before signalling."""

    start_identity: int
    state: str | None
    process_group_id: int | None


class PlatformRuntime(Protocol):
    @property
    def process_platform(self) -> str:
        """Stable process-registration platform identifier."""

    @property
    def display_platform(self) -> str:
        """User-facing platform identifier."""

    def process_info(self, pid: int) -> NativeProcessInfo | None:
        """Return OS-native process identity, or None when dead/uninspectable."""

    def boot_identity(self) -> str | None:
        """Return a per-boot identity when the OS exposes one."""

    def process_command(self, pid: int) -> tuple[str, ...] | None:
        """Return a best-effort command representation for ownership validation."""

    def process_environment_value(self, pid: int, name: str) -> str | None:
        """Return a process environment value when safely inspectable."""

    def pid_exists(self, pid: int) -> bool | None:
        """Return false for dead, true for alive, or None when permission obscures it."""

    def open_url(self, url: str) -> None:
        """Open a URL with the platform default browser."""


class LinuxPlatformRuntime:
    """Linux process inspection, including the existing WSL desktop bridge."""

    process_platform = "linux"

    @property
    def display_platform(self) -> str:
        return "windows_wsl" if is_wsl() else "linux"

    def process_info(self, pid: int) -> NativeProcessInfo | None:
        start = linux_process_start_identity(pid)
        if start is None:
            return None
        return NativeProcessInfo(
            start_identity=start,
            state=linux_process_state(pid),
            process_group_id=_safe_getpgid(pid),
        )

    def boot_identity(self) -> str | None:
        return linux_boot_identity()

    def process_command(self, pid: int) -> tuple[str, ...] | None:
        try:
            values = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            return tuple(value.decode("utf-8", errors="strict") for value in values if value)
        except (OSError, UnicodeDecodeError):
            return None

    def process_environment_value(self, pid: int, name: str) -> str | None:
        try:
            values = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        except OSError:
            return None
        prefix = name.encode("utf-8") + b"="
        for value in values:
            if value.startswith(prefix):
                try:
                    return value[len(prefix) :].decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    return None
        return None

    def pid_exists(self, pid: int) -> bool | None:
        return _pid_exists(pid)

    def open_url(self, url: str) -> None:
        if not is_wsl():
            raise PlatformRuntimeError(
                "Desktop launch is supported on macOS and on Windows through WSL."
            )
        from research_digest.windows_launcher import run_windows_powershell

        run_windows_powershell(
            "$ErrorActionPreference = 'Stop'\n"
            f"Start-Process -FilePath {_powershell_quote(url)}"
        )


class _ProcBSDInfo(ctypes.Structure):
    """Darwin's public ``struct proc_bsdinfo`` from libproc.h."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_int)]


DarwinInfoReader = Callable[[int], NativeProcessInfo | None]
DarwinBootReader = Callable[[], str | None]
DarwinCommandReader = Callable[[int], tuple[str, ...] | None]
CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class DarwinPlatformRuntime:
    """Native Darwin inspection using libproc start time plus kern.boottime."""

    process_platform = "darwin"
    display_platform = "macos"

    def __init__(
        self,
        *,
        info_reader: DarwinInfoReader | None = None,
        boot_reader: DarwinBootReader | None = None,
        command_reader: DarwinCommandReader | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self._info_reader = info_reader or _darwin_process_info
        self._boot_reader = boot_reader or _darwin_boot_identity
        self._command_reader = command_reader or _darwin_process_command
        self._command_runner = command_runner or _run_command

    def process_info(self, pid: int) -> NativeProcessInfo | None:
        return self._info_reader(pid)

    def boot_identity(self) -> str | None:
        return self._boot_reader()

    def process_command(self, pid: int) -> tuple[str, ...] | None:
        return self._command_reader(pid)

    def process_environment_value(self, pid: int, name: str) -> str | None:
        del pid, name
        # macOS intentionally has no /proc environment dependency. Exact ownership
        # rests on boot identity + microsecond process start + registered command.
        return None

    def pid_exists(self, pid: int) -> bool | None:
        return _pid_exists(pid)

    def open_url(self, url: str) -> None:
        completed = self._command_runner(("/usr/bin/open", url))
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise PlatformRuntimeError(f"macOS could not open the browser: {detail}")


class GenericPlatformRuntime:
    """Fail-safe process boundary for core use on an unsupported desktop OS."""

    process_platform = "generic"
    display_platform = "unsupported"

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name

    def process_info(self, pid: int) -> NativeProcessInfo | None:
        del pid
        return None

    def boot_identity(self) -> str | None:
        return None

    def process_command(self, pid: int) -> tuple[str, ...] | None:
        del pid
        return None

    def process_environment_value(self, pid: int, name: str) -> str | None:
        del pid, name
        return None

    def pid_exists(self, pid: int) -> bool | None:
        return _pid_exists(pid)

    def open_url(self, url: str) -> None:
        del url
        raise PlatformRuntimeError(
            f"Desktop launch is not supported on platform {self.platform_name!r}."
        )


def select_platform_runtime(*, platform: str | None = None) -> PlatformRuntime:
    selected = platform or sys.platform
    if selected == "darwin":
        return DarwinPlatformRuntime()
    if selected.startswith("linux"):
        return LinuxPlatformRuntime()
    return GenericPlatformRuntime(selected)


def process_start_identity(pid: int) -> int | None:
    info = select_platform_runtime().process_info(pid)
    return None if info is None else info.start_identity


def process_state(pid: int) -> str | None:
    info = select_platform_runtime().process_info(pid)
    return None if info is None else info.state


def boot_identity() -> str | None:
    return select_platform_runtime().boot_identity()


def process_group_id(pid: int) -> int | None:
    info = select_platform_runtime().process_info(pid)
    return None if info is None else info.process_group_id


def exact_process_state(
    pid: int,
    expected_start_identity: int,
    *,
    runtime: PlatformRuntime | None = None,
) -> ExactProcessState:
    """Distinguish a live exact owner from death and inspection failure.

    A missing native identity is not evidence of process exit when the PID is
    still present or cannot be inspected.  This fail-closed distinction is
    required before releasing durable ownership or escalating a signal.
    """

    selected = runtime or select_platform_runtime()
    info = selected.process_info(pid)
    if info is None:
        return (
            ExactProcessState.DEAD
            if selected.pid_exists(pid) is False
            else ExactProcessState.UNKNOWN
        )
    if info.start_identity != expected_start_identity or info.state == "Z":
        return ExactProcessState.DEAD
    return ExactProcessState.ALIVE


def darwin_streamlit_server_command_matches(
    command: tuple[str, ...],
    *,
    app_path: str,
    bind_host: str,
    port: int,
) -> bool:
    """Corroborate the exact Streamlit argv while allowing Darwin's real Python path.

    macOS ``ps`` reports the framework executable that ultimately runs Python,
    not necessarily the virtual-environment symlink passed to ``Popen``.  The
    executable must still be Python, while every application-owned argument is
    compared exactly to the launcher command.
    """

    if not command:
        return False
    if len(command) > 1:
        return _darwin_streamlit_arguments_match(
            command,
            app_path=app_path,
            bind_host=bind_host,
            port=port,
        )

    command_text = command[0].strip()
    try:
        parsed = tuple(shlex.split(command_text))
    except ValueError:
        parsed = ()
    if _darwin_streamlit_arguments_match(
        parsed,
        app_path=app_path,
        bind_host=bind_host,
        port=port,
    ):
        return True

    # Darwin ps may render arguments containing spaces without reusable shell
    # quoting. Match the exact known suffix in that representation as a safe
    # fallback; the only flexible component remains the Python executable.
    expected_suffix = " ".join(
        _expected_streamlit_arguments(
            app_path=app_path,
            bind_host=bind_host,
            port=port,
        )
    )
    marker = f" {expected_suffix}"
    if not command_text.endswith(marker):
        return False
    return _is_python_executable(command_text[: -len(marker)].strip())


def _darwin_streamlit_arguments_match(
    arguments: tuple[str, ...],
    *,
    app_path: str,
    bind_host: str,
    port: int,
) -> bool:
    expected = _expected_streamlit_arguments(
        app_path=app_path,
        bind_host=bind_host,
        port=port,
    )
    return bool(
        len(arguments) == len(expected) + 1
        and _is_python_executable(arguments[0])
        and arguments[1:] == expected
    )


def _expected_streamlit_arguments(
    *,
    app_path: str,
    bind_host: str,
    port: int,
) -> tuple[str, ...]:
    return (
        "-m",
        "streamlit",
        "run",
        app_path,
        f"--server.address={bind_host}",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    )


def _is_python_executable(value: str) -> bool:
    name = Path(value).name.casefold()
    return re.fullmatch(r"python(?:3(?:\.\d+)*)?", name) is not None


def linux_process_start_identity(pid: int) -> int | None:
    if pid <= 0:
        return None
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = text.rsplit(") ", 1)[1].split()
        return int(fields[19])
    except (IndexError, OSError, ValueError):
        return None


def linux_process_state(pid: int) -> str | None:
    if pid <= 0:
        return None
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return text.rsplit(") ", 1)[1].split()[0]
    except (IndexError, OSError):
        return None


def linux_boot_identity() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def is_wsl() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def _darwin_process_info(pid: int) -> NativeProcessInfo | None:
    if pid <= 0 or sys.platform != "darwin":
        return None
    library_name = ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib"
    try:
        library = ctypes.CDLL(library_name, use_errno=True)
        proc_pidinfo = library.proc_pidinfo
        proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        proc_pidinfo.restype = ctypes.c_int
        info = _ProcBSDInfo()
        size = ctypes.sizeof(info)
        # PROC_PIDTBSDINFO is a stable public libproc flavor on Darwin.
        if proc_pidinfo(pid, 3, 0, ctypes.byref(info), size) != size:
            return None
    except (AttributeError, OSError):
        return None
    start = int(info.pbi_start_tvsec) * 1_000_000 + int(info.pbi_start_tvusec)
    if start <= 0:
        return None
    # SZOMB is 5 in Darwin's sys/proc.h.
    state = "Z" if int(info.pbi_status) == 5 else str(int(info.pbi_status))
    pgid = int(info.pbi_pgid) or None
    return NativeProcessInfo(start_identity=start, state=state, process_group_id=pgid)


def _darwin_boot_identity() -> str | None:
    if sys.platform != "darwin":
        return None
    library_name = ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib"
    try:
        library = ctypes.CDLL(library_name, use_errno=True)
        sysctlbyname = library.sysctlbyname
        sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        sysctlbyname.restype = ctypes.c_int
        value = _Timeval()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        result = sysctlbyname(
            b"kern.boottime",
            ctypes.byref(value),
            ctypes.byref(size),
            None,
            0,
        )
        if result != 0:
            return None
    except (AttributeError, OSError):
        return None
    return f"{int(value.tv_sec)}:{int(value.tv_usec)}"


def _darwin_process_command(pid: int) -> tuple[str, ...] | None:
    if pid <= 0:
        return None
    completed = _run_command(("/bin/ps", "-ww", "-p", str(pid), "-o", "command="))
    if completed.returncode != 0:
        return None
    command = completed.stdout.strip()
    return (command,) if command else None


def _safe_getpgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (OSError, ProcessLookupError):
        return None


def _pid_exists(pid: int) -> bool | None:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError:
        return None
    return True


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=True, text=True, check=False)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
