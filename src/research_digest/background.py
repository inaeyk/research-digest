"""Small local worker boundary used by the responsive Streamlit UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

from research_digest.models import DateSelection
from research_digest.run_locks import linux_process_start_ticks


@dataclass(frozen=True)
class BackgroundLaunch:
    pid: int
    mode: str
    process_start_ticks: int | None = None


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
    return BackgroundLaunch(
        pid=process.pid,
        mode=arguments[0],
        process_start_ticks=linux_process_start_ticks(process.pid),
    )
