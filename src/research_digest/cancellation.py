"""Run-scoped cancellation and exact provider-process ownership."""

from __future__ import annotations

import contextvars
import os
import signal
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import cast

from research_digest.db import APP_RUN_CANCELLED, Database
from research_digest.run_locks import (
    RunOwnerState,
    linux_process_start_ticks,
    linux_process_state,
    parse_process_run_owner,
    process_run_owner_state,
)

_CANCEL_SIGNAL = getattr(signal, "SIGUSR1", None)
_CURRENT_RUN: contextvars.ContextVar[RunCancellationToken | None] = contextvars.ContextVar(
    "research_digest_current_run",
    default=None,
)


class RunCancelled(BaseException):
    """Abort application work after a durable run cancellation is accepted."""

    def __init__(self, run_id: int, message: str = "Cancelled by user.") -> None:
        super().__init__(message)
        self.run_id = run_id


@dataclass(frozen=True)
class RunCancellationToken:
    db: Database
    run_id: int

    def raise_if_requested(self) -> None:
        if self.db.app_run_cancellation_requested(self.run_id):
            raise RunCancelled(self.run_id)


@dataclass(frozen=True)
class CancellationResult:
    run_id: int
    accepted: bool
    status: str
    owner_stopped: bool


def stop_abandoned_provider_processes(
    db: Database,
    *,
    stale_after_seconds: float,
    run_id: int | None = None,
    force_uninspectable_owner: bool = False,
) -> int:
    """Stop exact registered provider groups before qualified stale recovery."""

    active = db.get_active_app_run()
    lock = db.get_run_lock()
    if active is None or lock is None:
        return 0
    active_run_id = int(active["id"])
    if run_id is not None and active_run_id != run_id:
        return 0
    run_owner = str(active["run_owner"]) if active["run_owner"] is not None else None
    if run_owner is None or run_owner != lock.owner:
        return 0
    owner_state = process_run_owner_state(run_owner)
    lock_age = max(time.time() - lock.acquired_at.timestamp(), 0.0)
    recoverable = owner_state == RunOwnerState.DEAD or (
        owner_state == RunOwnerState.UNKNOWN
        and (force_uninspectable_owner or lock_age > stale_after_seconds)
    )
    if not recoverable:
        return 0
    stopped = 0
    for provider in db.list_active_provider_processes(run_id=active_run_id):
        if _terminate_registered_process(provider, graceful_seconds=0.5):
            stopped += 1
        db.finish_provider_process(int(provider["id"]), status="ABANDONED")
    return stopped


@contextmanager
def bind_run_cancellation(db: Database, run_id: int) -> Iterator[RunCancellationToken]:
    """Bind provider calls and stage checks to one durable application run."""

    cancellation = RunCancellationToken(db=db, run_id=run_id)
    token = _CURRENT_RUN.set(cancellation)
    try:
        yield cancellation
    finally:
        _CURRENT_RUN.reset(token)


def activate_run_cancellation(
    db: Database,
    run_id: int,
) -> contextvars.Token[RunCancellationToken | None]:
    """Bind a run without requiring orchestration code to add another nesting level."""

    return _CURRENT_RUN.set(RunCancellationToken(db=db, run_id=run_id))


def deactivate_run_cancellation(
    token: contextvars.Token[RunCancellationToken | None],
) -> None:
    _CURRENT_RUN.reset(token)


def current_run_cancellation() -> RunCancellationToken | None:
    return _CURRENT_RUN.get()


def raise_if_cancelled() -> None:
    cancellation = current_run_cancellation()
    if cancellation is not None:
        cancellation.raise_if_requested()


@contextmanager
def cancellation_signal_scope() -> Iterator[None]:
    """Install a run-worker wake-up signal without raising at unsafe bytecodes.

    Cancellation is durable in SQLite and is raised only at explicit pipeline
    checkpoints.  The signal wakes interruptible calls; the cancelling process
    separately stops an exact provider process and has a bounded worker
    termination fallback for calls that cannot return cooperatively.
    """

    if _CANCEL_SIGNAL is None or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous = signal.getsignal(_CANCEL_SIGNAL)

    def _handle_cancel(_signum: int, _frame: FrameType | None) -> None:
        return

    signal.signal(_CANCEL_SIGNAL, _handle_cancel)
    try:
        yield
    finally:
        signal.signal(_CANCEL_SIGNAL, previous)


def run_owned_subprocess(
    command: Sequence[str],
    *,
    input_text: str,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float,
    call_kind: str = "codex",
) -> subprocess.CompletedProcess[str]:
    """Run a provider process in its own group and register exact ownership."""

    raise_if_cancelled()
    previous_signal_mask = _block_cancel_signal()
    process: subprocess.Popen[str] | None = None
    cancellation: RunCancellationToken | None = None
    process_record_id: int | None = None
    process_group_id = 0
    final_status = "FAILED"
    try:
        process = subprocess.Popen(  # noqa: S603 - configured executable is intentional.
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=dict(env),
            text=True,
            start_new_session=os.name == "posix",
        )
        process_group_id = process.pid
        if os.name == "posix":
            process_group_id = os.getpgid(process.pid)
        cancellation = current_run_cancellation()
        if cancellation is not None:
            process_record_id = cancellation.db.register_provider_process(
                run_id=cancellation.run_id,
                call_kind=call_kind,
                pid=process.pid,
                process_group_id=process_group_id,
                process_start_ticks=linux_process_start_ticks(process.pid),
            )
            # Registration and a cancellation request are both committed SQLite
            # operations. This closes the Popen/register race: either the
            # canceller observes this row, or this check observes its request.
            cancellation.raise_if_requested()
        _restore_cancel_signal(previous_signal_mask)
        previous_signal_mask = None
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_local_process(process, process_group_id=process_group_id)
            process.communicate()
            raise
        if cancellation is not None:
            cancellation.raise_if_requested()
        final_status = "COMPLETED" if process.returncode == 0 else "FAILED"
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    except RunCancelled:
        final_status = APP_RUN_CANCELLED
        if process is not None:
            _terminate_local_process(process, process_group_id=process_group_id)
        raise
    except BaseException:
        if process is not None:
            _terminate_local_process(process, process_group_id=process_group_id)
        raise
    finally:
        if process_record_id is not None and cancellation is not None:
            cancellation.db.finish_provider_process(
                process_record_id,
                status=final_status,
            )
        if previous_signal_mask is not None:
            _restore_cancel_signal(previous_signal_mask)


def request_run_cancellation(
    db: Database,
    *,
    run_id: int,
    reason: str = "Cancelled by user.",
    graceful_seconds: float = 1.5,
    terminate_seconds: float = 1.5,
) -> CancellationResult:
    """Request cancellation, stop only exact run-owned processes, and release ownership."""

    accepted = db.request_app_run_cancellation(run_id, reason=reason)
    run = db.get_app_run(run_id)
    if run is None:
        raise ValueError(f"app run {run_id} does not exist")
    if not accepted:
        return CancellationResult(
            run_id=run_id,
            accepted=False,
            status=str(run["status"]),
            owner_stopped=run["completed_at"] is not None,
        )

    expected_owner = str(run["run_owner"]) if run["run_owner"] is not None else None

    for provider in db.list_active_provider_processes(run_id=run_id):
        _terminate_registered_process(provider, graceful_seconds=graceful_seconds)

    lock = db.get_run_lock()
    if lock is None:
        status = db.finish_cancelled_run(run_id)
        return CancellationResult(run_id, True, status, True)

    if expected_owner is None:
        return CancellationResult(run_id, True, str(run["status"]), False)

    if lock.owner != expected_owner:
        status = db.finish_cancelled_run(run_id)
        return CancellationResult(run_id, True, status, True)

    owner = parse_process_run_owner(expected_owner)
    owner_state = process_run_owner_state(expected_owner)
    if owner_state == RunOwnerState.DEAD:
        stopped = db.force_cancel_after_owner_stopped(run_id=run_id, owner=expected_owner)
        current = db.get_app_run(run_id)
        status = APP_RUN_CANCELLED if current is None else str(current["status"])
        return CancellationResult(run_id, True, status, stopped)
    if owner is None or owner_state == RunOwnerState.UNKNOWN:
        return CancellationResult(run_id, True, str(run["status"]), False)

    if owner.pid == os.getpid():
        return CancellationResult(run_id, True, str(run["status"]), False)

    _signal_exact_owner(owner.pid, owner.start_ticks, _CANCEL_SIGNAL)
    if _wait_for_cancel_completion(
        db,
        run_id=run_id,
        lock_owner=expected_owner,
        timeout_seconds=graceful_seconds,
    ):
        current = db.get_app_run(run_id)
        status = APP_RUN_CANCELLED if current is None else str(current["status"])
        return CancellationResult(run_id, True, status, True)

    if _wait_for_retrieval_persistence(
        db,
        run_id=run_id,
        lock_owner=expected_owner,
        timeout_seconds=5.0,
    ) and _wait_for_cancel_completion(
        db,
        run_id=run_id,
        lock_owner=expected_owner,
        timeout_seconds=graceful_seconds,
    ):
        current = db.get_app_run(run_id)
        status = APP_RUN_CANCELLED if current is None else str(current["status"])
        return CancellationResult(run_id, True, status, True)

    _signal_exact_owner(owner.pid, owner.start_ticks, signal.SIGTERM)
    if not _wait_for_process_exit(
        owner.pid,
        owner.start_ticks,
        timeout_seconds=terminate_seconds,
    ):
        _signal_exact_owner(owner.pid, owner.start_ticks, signal.SIGKILL)
        _wait_for_process_exit(
            owner.pid,
            owner.start_ticks,
            timeout_seconds=terminate_seconds,
        )
    owner_stopped = (
        linux_process_start_ticks(owner.pid) != owner.start_ticks
        or linux_process_state(owner.pid) == "Z"
    )
    if owner_stopped:
        db.force_cancel_after_owner_stopped(run_id=run_id, owner=expected_owner)
    current = db.get_app_run(run_id)
    status = APP_RUN_CANCELLED if current is None else str(current["status"])
    return CancellationResult(run_id, True, status, owner_stopped)


def _terminate_local_process(
    process: subprocess.Popen[str],
    *,
    process_group_id: int,
) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        _signal_process_group(process_group_id, signal.SIGTERM)
    else:
        process.terminate()
    try:
        process.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        _signal_process_group(process_group_id, signal.SIGKILL)
    else:
        process.kill()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        return


def _block_cancel_signal() -> set[signal.Signals] | None:
    if _CANCEL_SIGNAL is None or not hasattr(signal, "pthread_sigmask"):
        return None
    return cast(
        set[signal.Signals],
        signal.pthread_sigmask(signal.SIG_BLOCK, {_CANCEL_SIGNAL}),
    )


def _restore_cancel_signal(previous: set[signal.Signals] | None) -> None:
    if previous is None or not hasattr(signal, "pthread_sigmask"):
        return
    signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _terminate_registered_process(
    process: sqlite3.Row,
    *,
    graceful_seconds: float,
) -> bool:
    pid = int(cast(int, process["pid"]))
    pgid = int(cast(int, process["process_group_id"]))
    expected_start = process["process_start_ticks"]
    start_ticks = int(cast(int, expected_start)) if expected_start is not None else None
    if start_ticks is None or linux_process_start_ticks(pid) != start_ticks:
        return False
    try:
        if os.getpgid(pid) != pgid:
            return False
    except ProcessLookupError:
        return False
    _signal_process_group(pgid, signal.SIGTERM)
    if _wait_for_process_exit(pid, start_ticks, timeout_seconds=graceful_seconds):
        return True
    _signal_process_group(pgid, signal.SIGKILL)
    _wait_for_process_exit(pid, start_ticks, timeout_seconds=graceful_seconds)
    # A provider that was our child may remain as a non-executing zombie until
    # its owning worker reaps it. The exact validated process group has still
    # received the terminal signal and can no longer perform provider work.
    return True


def _signal_process_group(process_group_id: int, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(process_group_id, requested_signal)
    except ProcessLookupError:
        return


def _signal_exact_owner(
    pid: int,
    expected_start_ticks: int | None,
    requested_signal: signal.Signals | int | None,
) -> bool:
    if requested_signal is None or expected_start_ticks is None:
        return False
    if linux_process_start_ticks(pid) != expected_start_ticks:
        return False
    try:
        os.kill(pid, requested_signal)
    except ProcessLookupError:
        return False
    return True


def _wait_for_process_exit(
    pid: int,
    expected_start_ticks: int | None,
    *,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while (
        linux_process_start_ticks(pid) == expected_start_ticks
        and linux_process_state(pid) != "Z"
    ):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _wait_for_cancel_completion(
    db: Database,
    *,
    run_id: int,
    lock_owner: str,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while True:
        run = db.get_app_run(run_id)
        lock = db.get_run_lock()
        terminal = run is None or run["completed_at"] is not None
        ownership_released = lock is None or lock.owner != lock_owner
        if terminal and ownership_released:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _wait_for_retrieval_persistence(
    db: Database,
    *,
    run_id: int,
    lock_owner: str,
    timeout_seconds: float,
) -> bool:
    """Give the short atomic corpus/coverage write a chance to finish safely."""

    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while True:
        run = db.get_app_run(run_id)
        lock = db.get_run_lock()
        if run is None or run["completed_at"] is not None:
            return True
        if lock is None or lock.owner != lock_owner:
            return True
        if str(run["progress_stage"] or "") != "retrieval_persistence":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
