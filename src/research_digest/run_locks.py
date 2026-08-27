"""Process-aware run-lock owner helpers."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from research_digest.platform_runtime import (
    PlatformRuntime,
    linux_boot_identity,
    linux_process_start_identity,
    select_platform_runtime,
)
from research_digest.platform_runtime import (
    linux_process_state as _linux_process_state,
)


class RunOwnerState(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


class ProcessOwnershipUnavailable(RuntimeError):
    """Raised when this process cannot establish exact durable ownership."""


@dataclass(frozen=True)
class ProcessRunOwner:
    pid: int
    host: str
    start_ticks: int | None
    nonce: str
    boot_id: str | None = None
    platform: str | None = None

    def to_owner_string(self) -> str:
        return json.dumps(
            {
                "kind": "process",
                "version": 1,
                "pid": self.pid,
                "host": self.host,
                "start_ticks": self.start_ticks,
                "nonce": self.nonce,
                "boot_id": self.boot_id,
                "platform": self.platform,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


StartTicksReader = Callable[[int], int | None]


def current_process_run_owner(*, runtime: PlatformRuntime | None = None) -> str:
    active_runtime = runtime or select_platform_runtime()
    process_info = active_runtime.process_info(os.getpid())
    if (
        process_info is None
        and active_runtime.process_platform in {"linux", "darwin"}
    ):
        raise ProcessOwnershipUnavailable(
            "Research Digest cannot inspect its own exact process start identity, so it "
            "will not acquire a digest run lock. Check local process-inspection "
            "permissions and retry."
        )
    return ProcessRunOwner(
        pid=os.getpid(),
        host=socket.gethostname(),
        start_ticks=None if process_info is None else process_info.start_identity,
        nonce=str(uuid4()),
        boot_id=active_runtime.boot_identity(),
        platform=active_runtime.process_platform,
    ).to_owner_string()


def process_run_owner_state(
    owner: str,
    *,
    current_host: str | None = None,
    start_ticks_reader: StartTicksReader | None = None,
    runtime: PlatformRuntime | None = None,
) -> RunOwnerState:
    parsed = parse_process_run_owner(owner)
    if parsed is None:
        return RunOwnerState.UNKNOWN
    if parsed.host != (current_host or socket.gethostname()):
        return RunOwnerState.UNKNOWN
    active_runtime = runtime or select_platform_runtime()
    if parsed.platform is not None and parsed.platform != active_runtime.process_platform:
        return RunOwnerState.DEAD
    legacy_linux_registration = parsed.platform is None
    current_boot_id = (
        linux_boot_id() if legacy_linux_registration else active_runtime.boot_identity()
    )
    if parsed.boot_id is not None:
        if current_boot_id is None:
            return RunOwnerState.UNKNOWN
        if parsed.boot_id != current_boot_id:
            return RunOwnerState.DEAD
    if parsed.start_ticks is None:
        return RunOwnerState.UNKNOWN
    reader = start_ticks_reader
    if reader is None:
        reader = (
            linux_process_start_ticks
            if legacy_linux_registration
            else lambda pid: _runtime_start_identity(active_runtime, pid)
        )
    current_start_ticks = reader(parsed.pid)
    if current_start_ticks is None:
        if not legacy_linux_registration and active_runtime.pid_exists(parsed.pid) is not False:
            return RunOwnerState.UNKNOWN
        return RunOwnerState.DEAD
    if current_start_ticks != parsed.start_ticks:
        return RunOwnerState.DEAD
    state = (
        linux_process_state(parsed.pid)
        if legacy_linux_registration
        else _runtime_process_state(active_runtime, parsed.pid)
    )
    if state == "Z":
        return RunOwnerState.DEAD
    return RunOwnerState.ALIVE


def linux_process_start_ticks(pid: int) -> int | None:
    return linux_process_start_identity(pid)


def linux_process_state(pid: int) -> str | None:
    """Return the Linux process state; zombies are stopped ownership."""

    return _linux_process_state(pid)


def linux_boot_id() -> str | None:
    return linux_boot_identity()


def parse_process_run_owner(owner: str) -> ProcessRunOwner | None:
    """Parse an exact process-backed lock owner, or reject legacy/invalid owners."""

    try:
        payload = json.loads(owner)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("kind") != "process" or payload.get("version") != 1:
        return None
    pid = payload.get("pid")
    host = payload.get("host")
    nonce = payload.get("nonce")
    start_ticks = payload.get("start_ticks")
    boot_id = payload.get("boot_id")
    platform = payload.get("platform")
    if not isinstance(pid, int) or not isinstance(host, str) or not isinstance(nonce, str):
        return None
    if start_ticks is not None and not isinstance(start_ticks, int):
        return None
    if boot_id is not None and not isinstance(boot_id, str):
        return None
    if platform is not None and platform not in {"linux", "darwin", "generic"}:
        return None
    return ProcessRunOwner(
        pid=pid,
        host=host,
        start_ticks=start_ticks,
        nonce=nonce,
        boot_id=boot_id,
        platform=platform,
    )


def _runtime_start_identity(runtime: PlatformRuntime, pid: int) -> int | None:
    info = runtime.process_info(pid)
    return None if info is None else info.start_identity


def _runtime_process_state(runtime: PlatformRuntime, pid: int) -> str | None:
    info = runtime.process_info(pid)
    return None if info is None else info.state
