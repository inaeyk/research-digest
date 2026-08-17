"""Release settings and diagnostics page."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from research_digest import __version__
from research_digest.automation import (
    AutomationStatus,
    install_or_update_schedule,
    read_schedule_status,
    remove_schedule,
    run_automatic_digest_now,
)
from research_digest.config import AppConfig, ConfigError, load_config, save_automation_settings
from research_digest.db import Database
from research_digest.doctor import DoctorCheck, DoctorReport, DoctorSeverity, run_doctor
from research_digest.errors import sanitize_error
from research_digest.scheduler import ScheduleOperationResult, ScheduleStatus
from research_digest.sources.arxiv import ArxivSource
from research_digest.ui.common import get_analyzer, get_database


def render() -> None:
    import streamlit as st

    st.title("Settings")
    try:
        config = load_config()
    except ConfigError as exc:
        st.error(f"Configuration is invalid: {sanitize_error(exc)}", icon=":material/error:")
        st.caption("Run `research-digest doctor` for the same checks outside the UI.")
        return

    db = get_database()
    _render_runtime_summary(config, db)
    _render_provider_summary(config)
    _render_automation(config, db)
    _render_doctor(config, db)
    _render_release_commands()


def _render_runtime_summary(config: AppConfig, db: Database) -> None:
    import streamlit as st

    st.subheader("Runtime")
    col1, col2, col3 = st.columns(3)
    col1.metric("Application version", __version__)
    col2.metric("Schema version", db.get_schema_version())
    col3.metric("Config version", config.config_version)

    with st.container(border=True):
        st.markdown("**Locations**")
        st.caption("Active SQLite data")
        st.code(str(config.db_path), language=None)
        st.caption("Configuration file")
        st.code(str(config.config_path or config.config_dir), language=None)


def _render_provider_summary(config: AppConfig) -> None:
    import streamlit as st

    st.subheader("Analyzer")
    with st.container(border=True):
        provider = provider_label(config)
        st.metric("Provider", provider)
        if config.analyzer_provider == "codex":
            st.caption("Codex uses the signed-in Codex CLI and ChatGPT-managed authentication.")
            st.write(f"Model: {config.codex_model or 'Codex CLI default'}")
            st.write(f"Timeout: {config.codex_timeout_seconds:g} seconds")
        else:
            st.caption("OpenAI API mode reads the API key from the environment.")
            st.write(f"Model: {config.openai_model}")
            st.write("API key: configured" if config.openai_api_key else "API key: missing")


def _render_automation(config: AppConfig, db: Database) -> None:
    import streamlit as st

    st.subheader("Automation")
    status = read_schedule_status()
    with st.container(border=True):
        _render_schedule_status(status)
        st.caption("Last scheduled digest outcome: " + last_scheduled_digest_outcome(db))
        default_time = schedule_time_default(status.schedule)
        with st.form("automation_schedule", border=False):
            enabled = st.toggle(
                "Automatic daily digest",
                value=bool(status.schedule and status.schedule.installed),
            )
            daily_time = st.text_input(
                "Daily time",
                value=default_time,
                placeholder="07:30",
            )
            catch_up = st.toggle(
                "Catch up missed source dates",
                value=config.automatic_catch_up_enabled,
            )
            st.caption("Windows local time; follows Windows daylight-saving rules.")
            submitted = st.form_submit_button(
                "Save / update schedule",
                type="primary",
                icon=":material/save:",
            )
        if submitted:
            try:
                updated_config = save_automation_settings(catch_up_missed_dates=catch_up)
                if enabled:
                    result = install_or_update_schedule(
                        time_of_day=daily_time,
                        config=updated_config,
                    )
                else:
                    result = remove_schedule()
            except Exception as exc:
                st.error(
                    f"Schedule update failed: {sanitize_error(exc)}",
                    icon=":material/error:",
                )
            else:
                st.success(schedule_operation_message(result), icon=":material/check_circle:")
                st.rerun()

        with st.container(horizontal=True):
            if st.button("Run now", icon=":material/play_arrow:"):
                _run_automatic_now(config, db)
            if st.button("Disable schedule", icon=":material/event_busy:"):
                try:
                    result = remove_schedule()
                except Exception as exc:
                    st.error(
                        f"Schedule disable failed: {sanitize_error(exc)}",
                        icon=":material/error:",
                    )
                else:
                    st.success(schedule_operation_message(result), icon=":material/check_circle:")
                    st.rerun()


def _render_schedule_status(status: AutomationStatus) -> None:
    import streamlit as st

    if not status.ok:
        st.warning(
            "Automatic scheduling is unavailable: "
            f"{status.error_message or 'unknown scheduler error'}",
            icon=":material/warning:",
        )
        return
    schedule = status.schedule
    if schedule is None or not schedule.installed:
        st.info("Schedule is not installed.", icon=":material/info:")
        return
    if schedule.last_task_result not in (None, 0):
        st.warning(
            "Schedule is installed, but the last run reported a warning.",
            icon=":material/warning:",
        )
    else:
        st.success("Schedule is installed.", icon=":material/check_circle:")
    cols = st.columns(3)
    cols[0].metric("State", schedule.state or "unknown")
    cols[1].metric("Next run", schedule.next_run_time or "unknown")
    cols[2].metric("Last scheduled run", schedule.last_run_time or "none")
    st.caption(schedule.timezone)
    if schedule.message:
        st.caption(sanitize_error(schedule.message))


def _run_automatic_now(config: AppConfig, db: Database) -> None:
    import streamlit as st

    analyzer, analyzer_message = get_analyzer()
    if analyzer_message is not None:
        st.warning(
            "Analysis provider needs attention: "
            f"{sanitize_error(analyzer_message)}",
            icon=":material/warning:",
        )
    with st.status("Running automatic digest now...", expanded=True) as status:
        try:
            result = run_automatic_digest_now(
                config=config,
                db=db,
                source=ArxivSource(),
                analyzer=analyzer,
            )
        except Exception as exc:
            status.update(label="Run now failed", state="error")
            st.error(sanitize_error(exc), icon=":material/error:")
            return
        status.update(label="Run now completed", state="complete")
        st.write(run_now_summary(result))


def _render_doctor(config: AppConfig, db: Database) -> None:
    import streamlit as st

    st.subheader("Health")
    report = run_doctor(config=config, db=db, include_network=False)
    severity = doctor_overall_severity(report)
    if severity == DoctorSeverity.FAILURE:
        st.error(doctor_summary(report), icon=":material/error:")
    elif severity == DoctorSeverity.WARNING:
        st.warning(doctor_summary(report), icon=":material/warning:")
    else:
        st.success(doctor_summary(report), icon=":material/check_circle:")

    with st.expander("Doctor checks", icon=":material/stethoscope:"):
        for check in report.checks:
            _render_check(check)


def _render_check(check: DoctorCheck) -> None:
    import streamlit as st

    label = f"{check.severity}: {check.name}"
    if check.severity == DoctorSeverity.FAILURE:
        st.error(f"{label} - {check.message}", icon=":material/error:")
    elif check.severity == DoctorSeverity.WARNING:
        st.warning(f"{label} - {check.message}", icon=":material/warning:")
    else:
        st.success(f"{label} - {check.message}", icon=":material/check_circle:")


def _render_release_commands() -> None:
    import streamlit as st

    st.subheader("Release commands")
    commands = [
        "research-digest serve",
        "research-digest run",
        "research-digest status",
        "research-digest doctor",
        "research-digest backup --export-json",
    ]
    with st.container(border=True):
        st.caption("Use the installed CLI for release operations.")
        st.code("\n".join(commands), language="bash")


def provider_label(config: AppConfig) -> str:
    if config.analyzer_provider == "codex":
        return "Codex CLI"
    return "OpenAI API"


def doctor_overall_severity(report: DoctorReport) -> DoctorSeverity:
    if report.failure_count:
        return DoctorSeverity.FAILURE
    if report.warning_count:
        return DoctorSeverity.WARNING
    return DoctorSeverity.PASS


def doctor_summary(report: DoctorReport) -> str:
    severity = doctor_overall_severity(report)
    if severity == DoctorSeverity.FAILURE:
        return f"{report.failure_count} failure(s), {report.warning_count} warning(s)"
    if severity == DoctorSeverity.WARNING:
        return f"No failures, {report.warning_count} warning(s)"
    return "All checks passed"


def check_names(checks: Iterable[DoctorCheck]) -> list[str]:
    return [check.name for check in checks]


def last_scheduled_digest_outcome(db: Database) -> str:
    for row in db.get_app_runs():
        if str(row["run_origin"]) != "SCHEDULED":
            continue
        status = str(row["status"]).lower().replace("_", " ")
        completed = row["completed_at"]
        when = str(completed) if completed is not None else str(row["started_at"])
        return (
            f"run #{row['id']} {status}, retrieved {row['retrieved_count']}, "
            f"analyzed {row['analyzed_count']}, relevant {row['relevant_count']} at {when}"
        )
    return "none"


def schedule_time_default(status: ScheduleStatus | None) -> str:
    if status is None:
        return "07:30"
    for value in (status.next_run_time, status.last_run_time):
        parsed = _time_from_scheduler_timestamp(value)
        if parsed is not None:
            return parsed
    return "07:30"


def _time_from_scheduler_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    time_part = value.split("T", 1)[1] if "T" in value else value
    parts = time_part.split(":", 2)
    if len(parts) < 2:
        return None
    hour, minute = parts[0], parts[1]
    if len(hour) == 2 and len(minute) == 2 and hour.isdigit() and minute.isdigit():
        return f"{hour}:{minute}"
    return None


def schedule_operation_message(result: ScheduleOperationResult) -> str:
    if result.installed:
        return "Schedule updated."
    if result.operation == "removed":
        return "Schedule disabled."
    return "Schedule is not installed."


def run_now_summary(result: object) -> str:
    succeeded = getattr(result, "succeeded_count", 0)
    failed = getattr(result, "failed_count", 0)
    retrieved = getattr(result, "retrieved_count", 0)
    analyzed = getattr(result, "analyzed_count", 0)
    relevant = getattr(result, "relevant_count", 0)
    pending = getattr(result, "pending_source_dates", ())
    dates = ", ".join(value.isoformat() for value in pending if isinstance(value, date))
    return (
        f"{succeeded} profile(s) succeeded, {failed} failed; "
        f"retrieved {retrieved}, analyzed {analyzed}, relevant {relevant}"
        + (f"; source dates {dates}" if dates else "; no uncovered source dates")
    )
