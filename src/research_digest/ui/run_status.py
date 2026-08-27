"""Shared durable run progress and cancellation controls for Streamlit pages."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from research_digest.background import BackgroundLaunch
from research_digest.cancellation import request_run_cancellation
from research_digest.db import Database
from research_digest.errors import sanitize_error
from research_digest.models import DateSelection
from research_digest.platform_runtime import (
    ExactProcessState,
    exact_process_state,
    process_state,
)
from research_digest.run_locks import (
    RunOwnerState,
    parse_process_run_owner,
    process_run_owner_state,
)

_OBSERVED_ACTIVE_RUN_KEY = "observed_active_digest_run_id"
_LATEST_TERMINAL_RUN_KEY = "latest_terminal_digest_run_id"
_PENDING_LAUNCH_KEY = "pending_digest_worker_launch"
_LAUNCH_FAILURE_KEY = "digest_worker_launch_failure"


@dataclass(frozen=True)
class ActiveDigestStatus:
    run_id: int
    origin: str
    date_selection: str
    stage: str
    message: str
    retrieved_count: int
    preselected_count: int
    analyzed_count: int
    cancellation_requested: bool
    owner_state: RunOwnerState


@dataclass(frozen=True)
class PendingDigestLaunch:
    """Per-browser bridge until a detached worker registers its durable run."""

    pid: int
    mode: str
    process_start_ticks: int | None


def get_active_digest_status(db: Database) -> ActiveDigestStatus | None:
    row = db.get_active_app_run()
    if row is None:
        return None
    lock = db.get_run_lock()
    owner_state = (
        RunOwnerState.DEAD
        if lock is None
        else process_run_owner_state(lock.owner)
    )
    return ActiveDigestStatus(
        run_id=int(row["id"]),
        origin=str(row["run_origin"] or "legacy").lower(),
        date_selection=_date_selection_label(row["date_selection_json"]),
        stage=str(row["progress_stage"] or "starting"),
        message=str(row["progress_message"] or "Digest worker is starting."),
        retrieved_count=int(row["retrieved_count"]),
        preselected_count=int(row["preselected_count"]),
        analyzed_count=int(row["analyzed_count"]),
        cancellation_requested=row["cancel_requested_at"] is not None,
        owner_state=owner_state,
    )


def remember_digest_launch(launch: BackgroundLaunch) -> None:
    """Keep the spawn-to-app-run handoff visible in the launching browser session."""

    import streamlit as st

    st.session_state[_PENDING_LAUNCH_KEY] = PendingDigestLaunch(
        pid=launch.pid,
        mode=launch.mode,
        process_start_ticks=launch.process_start_ticks,
    )


def render_active_digest_control(db: Database) -> bool:
    """Render shared reattachable progress/cancel UI and return the page busy state."""

    import streamlit as st

    fragment = cast(
        Callable[
            ...,
            Callable[[Callable[[], None]], Callable[[], None]],
        ],
        getattr(st, "fragment", _fragment_fallback),
    )
    initial_active = get_active_digest_status(db)
    initial_launch = _pending_launch()
    initial_lock_state = _run_lock_owner_state(db)
    busy_at_page_render = (
        initial_active is not None
        or initial_launch is not None
        or initial_lock_state == RunOwnerState.ALIVE
    )

    def _active_run_fragment() -> None:
        active = get_active_digest_status(db)
        launch = _pending_launch()
        if active is not None:
            if not busy_at_page_render:
                st.rerun(scope="app")
            st.session_state.pop(_PENDING_LAUNCH_KEY, None)
            st.session_state[_OBSERVED_ACTIVE_RUN_KEY] = active.run_id
            _render_active_status(db, active)
            return

        if launch is not None:
            launched_run_id = _matching_launched_run_id(db, launch)
            if launched_run_id is not None:
                st.session_state.pop(_PENDING_LAUNCH_KEY, None)
                st.session_state[_LATEST_TERMINAL_RUN_KEY] = launched_run_id
                st.rerun(scope="app")
            if _pending_process_state(launch) == RunOwnerState.DEAD:
                st.session_state.pop(_PENDING_LAUNCH_KEY, None)
                st.session_state[_LAUNCH_FAILURE_KEY] = (
                    "Digest worker exited before registering a durable run. "
                    "Run digest is available again."
                )
                st.rerun(scope="app")
            _render_starting_status(launch.mode)
            return

        if _run_lock_owner_state(db) == RunOwnerState.ALIVE:
            if not busy_at_page_render:
                st.rerun(scope="app")
            _render_starting_status("digest")
            return

        observed = st.session_state.pop(_OBSERVED_ACTIVE_RUN_KEY, None)
        if isinstance(observed, int):
            st.session_state[_LATEST_TERMINAL_RUN_KEY] = observed
            st.rerun(scope="app")
        if busy_at_page_render:
            st.rerun(scope="app")

    fragment(run_every=1.0 if busy_at_page_render else None)(_active_run_fragment)()
    launch_failure = st.session_state.pop(_LAUNCH_FAILURE_KEY, None)
    if isinstance(launch_failure, str):
        st.error(launch_failure, icon=":material/error:")
    return busy_at_page_render


def _render_active_status(db: Database, active: ActiveDigestStatus) -> None:
    import streamlit as st

    with st.container(border=True):
        st.markdown("**Digest running**")
        st.write(f"Run #{active.run_id}")
        st.caption(f"{active.origin.title()} · {active.date_selection}")
        st.caption(f"{active.stage.replace('_', ' ').title()}: {active.message}")
        st.caption(
            "Research Digest continues running independently of this browser page. "
            'Use "Cancel digest" to stop the actual digest.'
        )
        columns = st.columns(3)
        columns[0].metric("Retrieved", active.retrieved_count)
        columns[1].metric("Passed Stage 1", active.preselected_count)
        columns[2].metric("Analyzed", active.analyzed_count)
        if active.owner_state == RunOwnerState.DEAD:
            st.warning(
                "The worker is no longer alive. Cancel to terminalize this run now, "
                "or the next explicit run will apply stale-owner recovery.",
                icon=":material/warning:",
            )
        elif active.owner_state == RunOwnerState.UNKNOWN:
            st.warning(
                "The worker owner cannot be inspected from this process.",
                icon=":material/warning:",
            )
        if active.cancellation_requested:
            st.info("Cancelling... Run-owned work is stopping.")
        elif st.button(
            "Cancel digest",
            key=f"cancel_digest_{active.run_id}",
            type="secondary",
            icon=":material/cancel:",
            width="stretch",
        ):
            try:
                result = request_run_cancellation(db, run_id=active.run_id)
            except Exception as exc:
                st.error(
                    f"Cancellation failed: {sanitize_error(exc)}",
                    icon=":material/error:",
                )
            else:
                if result.status == "CANCELLED":
                    st.success("Digest cancelled. Preserved work is available for retry.")
                else:
                    st.info("Cancelling... The worker is stopping.")
                st.rerun(scope="app")


def _render_starting_status(mode: str) -> None:
    import streamlit as st

    origin = {"automatic": "scheduled", "manual": "manual"}.get(mode, "digest")
    with st.container(border=True):
        st.markdown("**Starting digest...**")
        st.caption(f"Preparing the detached {origin} worker.")
        st.caption(
            "Cancel digest will be available as soon as the durable run ID is registered."
        )


def _pending_launch() -> PendingDigestLaunch | None:
    import streamlit as st

    value = st.session_state.get(_PENDING_LAUNCH_KEY)
    return value if isinstance(value, PendingDigestLaunch) else None


def _pending_process_state(launch: PendingDigestLaunch) -> RunOwnerState:
    if launch.process_start_ticks is None:
        if process_state(launch.pid) == "Z":
            return RunOwnerState.DEAD
        try:
            os.kill(launch.pid, 0)
        except ProcessLookupError:
            return RunOwnerState.DEAD
        except (OSError, PermissionError):
            return RunOwnerState.UNKNOWN
        return RunOwnerState.UNKNOWN
    state = exact_process_state(launch.pid, launch.process_start_ticks)
    if state == ExactProcessState.DEAD:
        return RunOwnerState.DEAD
    if state == ExactProcessState.UNKNOWN:
        return RunOwnerState.UNKNOWN
    return RunOwnerState.ALIVE


def _run_lock_owner_state(db: Database) -> RunOwnerState:
    lock = db.get_run_lock()
    return RunOwnerState.DEAD if lock is None else process_run_owner_state(lock.owner)


def _matching_launched_run_id(db: Database, launch: PendingDigestLaunch) -> int | None:
    for row in db.get_app_runs():
        owner_text = row["run_owner"]
        if not isinstance(owner_text, str):
            continue
        owner = parse_process_run_owner(owner_text)
        if owner is None or owner.pid != launch.pid:
            continue
        if (
            launch.process_start_ticks is not None
            and owner.start_ticks != launch.process_start_ticks
        ):
            continue
        return int(row["id"])
    return None


def _date_selection_label(raw: object) -> str:
    if not isinstance(raw, str):
        return "Source dates unavailable"
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("date selection must be an object")
        return DateSelection.from_mapping(payload).display_label()
    except (json.JSONDecodeError, ValueError):
        return "Source dates unavailable"


def latest_terminal_digest_run_id() -> int | None:
    """Return the latest run this Streamlit session observed crossing terminal."""

    import streamlit as st

    value = st.session_state.get(_LATEST_TERMINAL_RUN_KEY)
    return value if isinstance(value, int) else None


def _fragment_fallback(
    *,
    run_every: float | None,
) -> Callable[[Callable[[], None]], Callable[[], None]]:
    del run_every

    def _decorate(function: Callable[[], None]) -> Callable[[], None]:
        return function

    return _decorate
