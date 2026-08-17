"""Release settings and diagnostics page."""

from __future__ import annotations

from collections.abc import Iterable

from research_digest import __version__
from research_digest.config import AppConfig, ConfigError, load_config
from research_digest.db import Database
from research_digest.doctor import DoctorCheck, DoctorReport, DoctorSeverity, run_doctor
from research_digest.errors import sanitize_error
from research_digest.ui.common import get_database


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
        "research-digest schedule status",
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
