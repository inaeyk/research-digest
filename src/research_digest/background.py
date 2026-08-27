"""Small local worker boundary used by the responsive Streamlit UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass

from research_digest.models import DateSelection
from research_digest.platform_runtime import process_start_identity


@dataclass(frozen=True)
class BackgroundLaunch:
    pid: int
    mode: str
    process_start_ticks: int | None = None


class BackgroundLaunchError(RuntimeError):
    """Raised when a detached digest worker cannot be owned safely."""


def start_manual_digest_worker(
    *,
    profile_id: int,
    date_selection: DateSelection,
) -> BackgroundLaunch:
    return _start_worker(
        (
            "manual",
            "--profile-id",
            str(profile_id),
            "--date-selection-json",
            json.dumps(date_selection.to_mapping(), sort_keys=True, separators=(",", ":")),
        )
    )


def start_automatic_digest_worker() -> BackgroundLaunch:
    return _start_worker(("automatic",))


def _start_worker(arguments: tuple[str, ...]) -> BackgroundLaunch:
    process = subprocess.Popen(  # noqa: S603 - fixed module and structured arguments.
        [sys.executable, "-m", "research_digest.worker", *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=os.name == "posix",
    )
    process_identity = _wait_for_process_identity(process)
    if process_identity is None and process.poll() is None:
        _stop_just_spawned_worker(process)
        raise BackgroundLaunchError(
            "The digest worker started, but Research Digest could not verify its exact "
            "process identity. The worker was stopped; check local process-inspection "
            "permissions and try again."
        )
    return BackgroundLaunch(
        pid=process.pid,
        mode=arguments[0],
        process_start_ticks=process_identity,
    )


def _wait_for_process_identity(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float = 0.25,
) -> int | None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        identity = process_start_identity(process.pid)
        if identity is not None:
            return identity
        if process.poll() is not None or time.monotonic() >= deadline:
            return None
        time.sleep(0.01)


def _stop_just_spawned_worker(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            return
