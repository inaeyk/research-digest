"""Process-aware run-lock owner helpers."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


class RunOwnerState(StrEnum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProcessRunOwner:
    pid: int
    host: str
    start_ticks: int | None
    nonce: str
    boot_id: str | None = None

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
            },
            sort_keys=True,
            separators=(",", ":"),
        )


StartTicksReader = Callable[[int], int | None]


def current_process_run_owner() -> str:
    return ProcessRunOwner(
        pid=os.getpid(),
        host=socket.gethostname(),
        start_ticks=linux_process_start_ticks(os.getpid()),
        nonce=str(uuid4()),
        boot_id=linux_boot_id(),
    ).to_owner_string()


def process_run_owner_state(
    owner: str,
    *,
    current_host: str | None = None,
    start_ticks_reader: StartTicksReader = lambda pid: linux_process_start_ticks(pid),
) -> RunOwnerState:
    parsed = _parse_process_owner(owner)
    if parsed is None:
        return RunOwnerState.UNKNOWN
    if parsed.host != (current_host or socket.gethostname()):
        return RunOwnerState.UNKNOWN
    current_boot_id = linux_boot_id()
    if (
        parsed.boot_id is not None
        and current_boot_id is not None
        and parsed.boot_id != current_boot_id
    ):
        return RunOwnerState.DEAD
    if parsed.start_ticks is None:
        return RunOwnerState.UNKNOWN
    current_start_ticks = start_ticks_reader(parsed.pid)
    if current_start_ticks is None:
        return RunOwnerState.DEAD
    if current_start_ticks != parsed.start_ticks:
        return RunOwnerState.DEAD
    return RunOwnerState.ALIVE


def linux_process_start_ticks(pid: int) -> int | None:
    if pid <= 0:
        return None
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        after_name = text.rsplit(") ", 1)[1]
        fields = after_name.split()
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def linux_boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _parse_process_owner(owner: str) -> ProcessRunOwner | None:
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
    if not isinstance(pid, int) or not isinstance(host, str) or not isinstance(nonce, str):
        return None
    if start_ticks is not None and not isinstance(start_ticks, int):
        return None
    if boot_id is not None and not isinstance(boot_id, str):
        return None
    return ProcessRunOwner(
        pid=pid,
        host=host,
        start_ticks=start_ticks,
        nonce=nonce,
        boot_id=boot_id,
    )
