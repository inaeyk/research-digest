"""Release settings and diagnostics page."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from research_digest import __version__
from research_digest.automation import (
    AutomationStatus,
    install_or_update_schedule,
    read_schedule_status,
    remove_schedule,
    run_automatic_digest_now,
)
from research_digest.backup import BackupResult, run_backup
from research_digest.config import AppConfig, ConfigError, load_config, save_automation_settings
from research_digest.coverage import (
    build_automatic_coverage_plan,
    build_date_coverage_statuses,
    digest_is_coverage_eligible,
)
from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_PARTIAL,
    SOURCE_ARXIV,
    Database,
)
from research_digest.doctor import DoctorCheck, DoctorReport, DoctorSeverity, run_doctor
from research_digest.errors import sanitize_error
from research_digest.scheduler import ScheduleOperationResult, ScheduleStatus
from research_digest.sources.arxiv import ArxivSource
from research_digest.ui.common import get_analyzer, get_database
from research_digest.ui.date_status import month_bounds, render_date_status_grid

_RUN_NOW_NOTICE_KEY = "automation_run_now_notice"


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
    _render_general(config, db)
    doctor_report = run_doctor(config=config, db=db, include_network=False)
    _render_analysis(config, doctor_report)
    _render_automation(config, db)
    _render_data(config)
    _render_doctor(doctor_report)


def _render_general(config: AppConfig, db: Database) -> None:
    import streamlit as st

    st.subheader("General")
    col1, col2, col3 = st.columns(3)
    col1.metric("App version", __version__)
    col2.metric("Schema version", db.get_schema_version())
    col3.metric("Config version", config.config_version)

    with st.container(border=True):
        st.markdown("**Locations**")
        st.caption("Active SQLite data file")
        st.code(str(config.db_path), language=None)
        st.caption("Data directory")
        st.code(str(config.data_dir), language=None)
        st.caption("Configuration file")
        st.code(str(config.config_path or config.config_dir), language=None)
        st.caption("Configuration directory")
        st.code(str(config.config_dir), language=None)


def _render_analysis(config: AppConfig, report: DoctorReport) -> None:
    import streamlit as st

    st.subheader("Analysis")
    with st.container(border=True):
        provider = provider_label(config)
        st.metric("Provider", provider)
        provider_check = provider_health_check(report)
        if provider_check is not None:
            _render_inline_check(provider_check)
        if config.analyzer_provider == "codex":
            st.caption("Codex uses the signed-in Codex CLI and ChatGPT-managed authentication.")
            st.write(f"Model: {config.codex_model or 'Codex CLI default'}")
            st.write(f"Timeout: {config.codex_timeout_seconds:g} seconds")
        else:
            st.caption("OpenAI API mode reads the API key from the environment.")
            st.write(f"Model: {config.openai_model}")
            st.write("API key: configured" if config.openai_api_key else "API key: missing")
        st.markdown("**Preselection effort**")
        st.caption(preselection_effort_summary())


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
            catch_up_from = st.date_input(
                "Catch up from",
                value=config.automatic_coverage_start_date,
            )
            st.caption("Windows local time; follows Windows daylight-saving rules.")
            st.caption(
                "Earlier successfully covered dates are not reprocessed. "
                "Failed or incomplete dates remain pending. Moving this date earlier may "
                "add pending dates; moving it later changes future pending consideration "
                "without deleting historical runs or coverage records."
            )
            submitted = st.form_submit_button(
                "Save / update schedule",
                type="primary",
                icon=":material/save:",
            )
        if submitted:
            try:
                updated_config = save_automation_settings(
                    catch_up_missed_dates=catch_up,
                    coverage_start_date=_coerce_date(catch_up_from),
                )
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

        _render_coverage_overview(config, db)
        _render_run_now_notice()

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


def _render_coverage_overview(config: AppConfig, db: Database) -> None:
    import streamlit as st

    source_config = db.get_arxiv_config()
    profiles = db.list_interest_profiles(enabled_only=True)
    if source_config is None or not profiles:
        st.info("Coverage status is available after arXiv and an enabled profile are configured.")
        return
    selected_profile = st.selectbox(
        "Coverage profile",
        options=profiles,
        format_func=lambda profile: profile.name,
        key="automation_coverage_profile",
    )
    source = ArxivSource()
    try:
        plan = build_automatic_coverage_plan(
            db=db,
            profiles=tuple(profiles),
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            latest_resolver=source,
            coverage_start_date=config.automatic_coverage_start_date,
            catch_up_missed_dates=config.automatic_catch_up_enabled,
        )
    except Exception as exc:
        st.warning(
            "Pending coverage dates could not be resolved: " + sanitize_error(exc),
            icon=":material/warning:",
        )
        return
    st.caption(f"Catch up from: {config.automatic_coverage_start_date.isoformat()}")
    if plan.latest_available_date is None:
        st.caption("Latest available source date: unavailable")
    else:
        st.caption(f"Latest available source date: {plan.latest_available_date.isoformat()}")
    st.caption(
        "Pending source dates: "
        + (
            ", ".join(value.isoformat() for value in plan.pending_dates)
            if plan.pending_dates
            else "none"
        )
    )
    if (
        plan.latest_available_date is not None
        and config.automatic_coverage_start_date > plan.latest_available_date
    ):
        st.info(
            run_now_noop_message(
                coverage_start_date=config.automatic_coverage_start_date,
                latest_available_source_date=plan.latest_available_date,
            ),
            icon=":material/info:",
        )
    anchor = plan.latest_available_date or config.automatic_coverage_start_date
    start_date, end_date = month_bounds(anchor)
    render_date_status_grid(
        statuses=build_date_coverage_statuses(
            db=db,
            profile=selected_profile,
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            start_date=start_date,
            end_date=end_date,
            pending_dates=plan.pending_dates,
        ),
        title=f"Automation coverage for {anchor:%B %Y}",
    )


def _run_automatic_now(config: AppConfig, db: Database) -> None:
    import streamlit as st

    source_config = db.get_arxiv_config()
    profiles = db.list_interest_profiles(enabled_only=True)
    if source_config is None or not profiles:
        st.warning(
            "Run now is available after arXiv and an enabled profile are configured.",
            icon=":material/warning:",
        )
        return
    source = ArxivSource()
    try:
        plan = build_automatic_coverage_plan(
            db=db,
            profiles=tuple(profiles),
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            latest_resolver=source,
            coverage_start_date=config.automatic_coverage_start_date,
            catch_up_missed_dates=config.automatic_catch_up_enabled,
        )
    except Exception as exc:
        st.error(
            "Run now could not resolve pending dates: " + sanitize_error(exc),
            icon=":material/error:",
        )
        return
    if not plan.pending_dates:
        message = run_now_noop_message(
            coverage_start_date=config.automatic_coverage_start_date,
            latest_available_source_date=plan.latest_available_date,
        )
        st.session_state[_RUN_NOW_NOTICE_KEY] = ("info", message)
        st.info(message, icon=":material/info:")
        return

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
                source=source,
                analyzer=analyzer,
            )
        except Exception as exc:
            status.update(label="Run now failed", state="error")
            message = sanitize_error(exc)
            st.session_state[_RUN_NOW_NOTICE_KEY] = ("error", message)
            st.error(message, icon=":material/error:")
            return
        notice_level = run_now_notice_level(result)
        status_state = "error" if notice_level == "error" else "complete"
        status.update(label="Run now completed", state=status_state)
        st.session_state[_RUN_NOW_NOTICE_KEY] = (notice_level, run_now_summary(result))
        st.rerun()


def _render_run_now_notice() -> None:
    import streamlit as st

    notice = st.session_state.get(_RUN_NOW_NOTICE_KEY)
    if not isinstance(notice, tuple) or len(notice) != 2:
        return
    level, message = notice
    if not isinstance(message, str):
        return
    if level == "success":
        st.success(message, icon=":material/check_circle:")
    elif level == "warning":
        st.warning(message, icon=":material/warning:")
    elif level == "error":
        st.error(message, icon=":material/error:")
    else:
        st.info(message, icon=":material/info:")


def _coerce_date(value: object) -> date:
    if isinstance(value, date):
        return value
    raise ConfigError("catch-up start date must be a calendar date")


def _render_data(config: AppConfig) -> None:
    import streamlit as st

    st.subheader("Data")
    with st.container(border=True):
        st.markdown("**Backup**")
        st.caption("Creates a verified copy of the active SQLite data file.")
        st.caption("Active data file")
        st.code(str(config.db_path), language=None)
        st.caption("Default backup directory")
        st.code(str(default_backup_directory(config.db_path)), language=None)
        export_json = st.toggle("Include JSON export sidecar", value=False)
        if st.button("Backup now", icon=":material/download:"):
            _run_backup_now(export_json=export_json)


def _run_backup_now(*, export_json: bool) -> None:
    import streamlit as st

    with st.status("Creating backup...", expanded=True) as status:
        try:
            result = run_backup(export_json=export_json, timestamp=datetime.now(UTC))
        except Exception as exc:
            status.update(label="Backup failed", state="error")
            st.error(sanitize_error(exc), icon=":material/error:")
            return
        status.update(label="Backup complete", state="complete")
        st.success(backup_result_message(result), icon=":material/check_circle:")
        st.caption("Backup file")
        st.code(str(result.backup_path), language=None)
        if result.export_path is not None:
            st.caption("JSON export")
            st.code(str(result.export_path), language=None)


def _render_doctor(report: DoctorReport) -> None:
    import streamlit as st

    st.subheader("Health")
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


def _render_inline_check(check: DoctorCheck) -> None:
    import streamlit as st

    message = sanitize_error(check.message)
    if check.severity == DoctorSeverity.FAILURE:
        st.error(message, icon=":material/error:")
    elif check.severity == DoctorSeverity.WARNING:
        st.warning(message, icon=":material/warning:")
    else:
        st.success(message, icon=":material/check_circle:")


def _render_check(check: DoctorCheck) -> None:
    import streamlit as st

    label = f"{check.severity}: {check.name}"
    if check.severity == DoctorSeverity.FAILURE:
        st.error(f"{label} - {check.message}", icon=":material/error:")
    elif check.severity == DoctorSeverity.WARNING:
        st.warning(f"{label} - {check.message}", icon=":material/warning:")
    else:
        st.success(f"{label} - {check.message}", icon=":material/check_circle:")


def provider_label(config: AppConfig) -> str:
    if config.analyzer_provider == "codex":
        return "Codex CLI"
    return "OpenAI API"


def provider_health_check(report: DoctorReport) -> DoctorCheck | None:
    for check in report.checks:
        if check.name == "provider":
            return check
    return None


def preselection_effort_summary() -> str:
    return (
        "Research Digest retrieves all eligible articles for the selected source dates. "
        "Cached analyses are reused, and deterministic abstract preselection decides which "
        "cache-miss articles need new full LLM analysis."
    )


def backup_result_message(result: BackupResult) -> str:
    if result.export_path is None:
        return f"Backup created at {result.backup_path}."
    return f"Backup created at {result.backup_path}; JSON export created at {result.export_path}."


def default_backup_directory(db_path: Path) -> Path:
    return db_path.parent / "backups"


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
    run_ids = _run_now_run_ids(result)
    outcome = _run_now_date_outcome_summary(result)
    errors = _run_now_error_messages(result)
    return (
        f"{succeeded} profile(s) succeeded, {failed} failed; "
        f"retrieved {retrieved}, analyzed {analyzed}, relevant {relevant}"
        + (f"; source dates {dates}" if dates else "; no uncovered source dates")
        + (f"; runs {', '.join(f'#{run_id}' for run_id in run_ids)}" if run_ids else "")
        + f"; {outcome}"
        + (f"; errors: {'; '.join(errors)}" if errors else "")
    )


def run_now_notice_level(result: object) -> str:
    failed = int(getattr(result, "failed_count", 0))
    succeeded = int(getattr(result, "succeeded_count", 0))
    if failed and not succeeded:
        return "error"
    if failed:
        return "warning"
    return "success"


def _run_now_run_ids(result: object) -> tuple[int, ...]:
    run_ids: list[int] = []
    for profile in getattr(result, "profiles", ()):
        digest_run = getattr(profile, "digest", None)
        digest = getattr(digest_run, "digest", None)
        run_id = getattr(digest, "run_id", None)
        if isinstance(run_id, int):
            run_ids.append(run_id)
    return tuple(run_ids)


def _run_now_date_outcome_summary(result: object) -> str:
    completed_dates: set[date] = set()
    empty_dates: set[date] = set()
    partial_dates: set[date] = set()
    failed_count = 0
    for profile in getattr(result, "profiles", ()):
        digest_run = getattr(profile, "digest", None)
        digest = getattr(digest_run, "digest", None)
        if digest is None:
            if not bool(getattr(profile, "success", False)):
                failed_count += 1
            continue
        run_status = getattr(digest, "run_status", None)
        if digest_is_coverage_eligible(digest):
            empty = {
                value
                for value in getattr(digest, "empty_source_dates", ())
                if isinstance(value, date)
            }
            covered = {
                value
                for value in getattr(digest, "covered_source_dates", ())
                if isinstance(value, date)
            }
            empty_dates.update(empty)
            completed_dates.update(covered - empty)
        elif run_status in (APP_RUN_PARTIAL, APP_RUN_ANALYSIS_UNAVAILABLE, APP_RUN_COMPLETED):
            partial_dates.update(_run_now_digest_attempted_dates(digest))
        elif run_status == APP_RUN_FAILED:
            failed_count += 1
    return (
        f"date outcomes: completed {len(completed_dates)}, "
        f"empty {len(empty_dates)}, partial {len(partial_dates)}, failed {failed_count}"
    )


def _run_now_digest_attempted_dates(digest: object) -> set[date]:
    incomplete = {
        value
        for value in getattr(digest, "incomplete_source_dates", ())
        if isinstance(value, date)
    }
    if incomplete:
        return incomplete
    requested = {
        value for value in getattr(digest, "requested_source_dates", ()) if isinstance(value, date)
    }
    if requested:
        return requested
    return {
        value for value in getattr(digest, "covered_source_dates", ()) if isinstance(value, date)
    }


def _run_now_error_messages(result: object) -> tuple[str, ...]:
    messages: list[str] = []
    for profile in getattr(result, "profiles", ()):
        if bool(getattr(profile, "success", False)):
            continue
        raw = getattr(profile, "error_message", None)
        profile_id = getattr(profile, "profile_id", "unknown")
        if isinstance(raw, str) and raw.strip():
            message = sanitize_error(raw)
        else:
            message = "profile did not complete successfully"
        messages.append(f"profile {profile_id}: {message}")
    return tuple(messages)


def run_now_noop_message(
    *,
    coverage_start_date: date,
    latest_available_source_date: date | None,
) -> str:
    latest = (
        latest_available_source_date.isoformat()
        if latest_available_source_date is not None
        else "unavailable"
    )
    return (
        "No pending source dates. "
        f"Catch-up starts {coverage_start_date.isoformat()}. "
        f"Latest available source date is {latest}."
    )
