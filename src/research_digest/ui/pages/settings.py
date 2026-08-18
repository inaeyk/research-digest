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
from research_digest.config import (
    AppConfig,
    ConfigError,
    load_config,
    model_effort_from_preselection_fraction,
    preselection_fraction_from_model_effort,
    preselection_threshold,
    save_analysis_settings,
    save_automation_settings,
)
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
from research_digest.models import profile_semantic_fingerprint
from research_digest.scheduler import ScheduleOperationResult, ScheduleStatus
from research_digest.sources.arxiv import ArxivSource
from research_digest.suggested_interests import (
    create_profile_from_suggestion,
    dismiss_suggested_interest,
    refresh_suggested_interests,
)
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
    _render_analysis(config, db, doctor_report)
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


def _render_analysis(config: AppConfig, db: Database, report: DoctorReport) -> None:
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
        _render_library_intelligence_settings(config, db)
    _render_scoring_guide(config, db)
    _render_suggested_interests(db)


def _render_library_intelligence_settings(config: AppConfig, db: Database) -> None:
    import streamlit as st

    profiles = db.list_interest_profiles(enabled_only=True)
    profile = profiles[0] if profiles else None
    relevance_threshold = profile.relevance_threshold if profile is not None else 0.6
    st.markdown("**Model effort**")
    with st.form("analysis_settings", border=False):
        model_effort = st.slider(
            "Model effort",
            min_value=0,
            max_value=100,
            value=round(
                model_effort_from_preselection_fraction(config.preselection_fraction) * 100
            ),
            step=5,
            help=(
                "Higher effort sends more papers to full analysis and lowers false-negative "
                "risk. Lower effort filters more aggressively and uses less model work."
            ),
        )
        effort_fraction = preselection_fraction_from_model_effort(model_effort / 100.0)
        derived_preselection = preselection_threshold(
            relevance_threshold=relevance_threshold,
            preselection_fraction=effort_fraction,
        )
        st.caption(
            "Higher Model effort means more papers receive full analysis, lower "
            "false-negative risk, and more model work. Lower Model effort filters more "
            "aggressively, runs faster/cheaper, and has a greater chance of missing "
            "borderline papers."
        )
        if model_effort <= 30:
            st.caption("This is an aggressive Stage-1 filtering setting.")
        st.caption(
            f"Model effort: {model_effort}%. Profile relevance threshold: "
            f"{relevance_threshold:.2f}. Stage-1 cutoff: {derived_preselection:.3f}. "
            f"Internal preselection fraction: {effort_fraction:.2f}."
        )
        st.caption(
            "Example with the values shown here: papers are first scored from title and "
            f"abstract only. Your profile relevance threshold is {relevance_threshold:.2f}; "
            f"Model effort is {model_effort}%, which gives a Stage-1 cutoff of "
            f"{derived_preselection:.3f}. A cache-miss paper with a preselection score at "
            "or above that cutoff goes on to full analysis. A paper below the cutoff is "
            "screened out early and remains available through its source abstract. Higher "
            "effort lowers this early cutoff, so digest runs spend more model work but are "
            "less likely to miss borderline papers. Lower effort raises the cutoff, making "
            "runs faster and cheaper with more false-negative risk."
        )
        st.markdown("**Library Intelligence**")
        automatic_connections = st.toggle(
            "Automatic Library connections",
            value=config.automatic_library_connections_enabled,
        )
        st.caption(
            "When enabled, Research Digest may automatically compare highly relevant "
            "newly analyzed papers with your saved Library. When disabled, digest runs "
            "skip automatic Library-connection reasoning. You can still use "
            "\"Find Library connections\" manually on any paper."
        )
        threshold = st.number_input(
            (
                "Automatically compare with Library when the new paper's relevance is at least"
            ),
            min_value=0.0,
            max_value=1.0,
            value=float(config.automatic_library_context_threshold),
            step=0.01,
            format="%.2f",
            disabled=not automatic_connections,
        )
        st.caption(
            "This threshold controls extra model work, not Library connection confidence. "
            "Papers below it can still be checked manually."
        )
        st.markdown("**Relevance calibration**")
        calibration_probability = st.slider(
            "Occasionally ask me to score a paper",
            min_value=0,
            max_value=100,
            value=round(config.relevance_calibration_prompt_probability * 100),
            step=5,
            help=(
                "Research Digest makes one persisted sampling decision per completed "
                "digest run. A value of 20% means about one in five completed runs can "
                "ask one quantitative relevance question."
            ),
        )
        st.caption(
            f"Frequency: {calibration_probability}% of completed digest runs; at most one "
            "question per run."
        )
        submitted = st.form_submit_button("Save analysis settings", icon=":material/save:")
    if submitted:
        try:
            save_analysis_settings(
                automatic_library_context_threshold=float(threshold),
                automatic_library_connections_enabled=bool(automatic_connections),
                preselection_fraction=effort_fraction,
                relevance_calibration_prompt_probability=calibration_probability / 100.0,
            )
        except Exception as exc:
            st.error(f"Analysis setting update failed: {sanitize_error(exc)}")
        else:
            st.success("Analysis settings saved.", icon=":material/check_circle:")
            st.rerun()


def _render_scoring_guide(config: AppConfig, db: Database) -> None:
    import streamlit as st

    profiles = db.list_interest_profiles(enabled_only=True)
    profile = profiles[0] if profiles else None
    relevance_threshold = profile.relevance_threshold if profile is not None else 0.6
    derived_preselection = preselection_threshold(
        relevance_threshold=relevance_threshold,
        preselection_fraction=config.preselection_fraction,
    )
    completed_calibrations = len(
        db.list_quantitative_calibrations(state="COMPLETED")
    )
    st.markdown("**Scoring Guide**")
    with st.expander("Scoring Guide", icon=":material/rule:"):
        st.markdown("**Relevance score**")
        st.write(
            "Range: 0..1. Meaning: how strongly the paper matches the selected "
            "Interest Profile. A paper is relevant when relevance_score >= the "
            "profile relevance threshold."
        )
        st.caption(
            "This is an LLM ordinal judgment, not a calibrated probability. The Codex "
            "prompt asks it to judge mechanisms, mathematical structures, methods, "
            "physical systems, and defensible conceptual relevance, not keyword matches alone."
        )
        if profile is not None:
            st.write(
                f'Current profile example: "{profile.name}" threshold '
                f"{profile.relevance_threshold:.2f}."
            )
        st.markdown("**Preselection score and model effort**")
        st.write(
            "Preselection is a cheaper model-generated first-impression score for "
            "cache-miss papers, based on title and abstract. It asks how plausible it is "
            "that deeper relevance analysis would find a meaningful match to the profile."
        )
        st.caption(
            "The score is ordinal, not a calibrated probability. Rubric: 0.00-0.19 no "
            "substantive connection; 0.20-0.39 weak/general adjacency; 0.40-0.59 "
            "plausible indirect connection; 0.60-0.79 strong plausible relevance; "
            "0.80-1.00 direct/core apparent match."
        )
        st.caption(
            "Preselection threshold = preselection_fraction * profile relevance threshold. "
            "A paper at the threshold passes Stage 1."
        )
        st.write(
            f"Model effort: "
            f"{model_effort_from_preselection_fraction(config.preselection_fraction) * 100:.0f}%. "
            f"Internal preselection fraction: {config.preselection_fraction:.2f}. "
            f"Derived preselection threshold: {derived_preselection:.3f}."
        )
        st.markdown("**Automatic Library threshold**")
        st.write(
            "This controls model work during digest runs. If automatic Library connections "
            "are ON and a newly analyzed paper's final relevance score is at least the "
            f"stored threshold ({config.automatic_library_context_threshold:.2f}), "
            "Research Digest may spend extra model effort comparing it with saved Library "
            "papers. Below the threshold, automatic Library reasoning is skipped."
        )
        st.caption(
            "Manual Find Library connections remains available and this threshold is not a "
            "Library connection confidence score."
        )
        st.markdown("**Library connection confidence**")
        st.write(
            "Range: 0..1 or unavailable. Meaning: confidence that the specific stated "
            "scientific relationship between two papers is supported by the bounded "
            "evidence inspected. It is not profile relevance, a statistical confidence "
            "interval, or a calibrated probability."
        )
        st.caption(
            "The Codex connection prompt asks for meaningful scientific relationships "
            "grounded in supplied metadata/evidence and validates confidence as a 0..1 "
            "number or null. Research Digest stores validated suggestions and shows "
            "non-dismissed suggestions; deterministic candidate selection happens before "
            "the model call."
        )
        st.markdown("**Human relevance calibration score**")
        st.write(
            "Range: 0..1. Meaning: your own profile-relevance judgment for an occasional "
            "below-threshold analyzed paper. It is separate from personal interest and "
            "does not overwrite the model's historical score."
        )
        st.caption(
            f"Collected completed human calibration samples: {completed_calibrations}. "
            f"Prompt probability: {config.relevance_calibration_prompt_probability:.2f}."
        )


def _render_suggested_interests(db: Database) -> None:
    import streamlit as st

    profiles = db.list_interest_profiles(enabled_only=True)
    if not profiles:
        return
    st.markdown("**Suggested interests**")
    st.caption(
        "Suggestions are generated only when you explicitly refresh them; opening Settings "
        "does not create new suggestions."
    )
    if st.button("Refresh suggested interests", icon=":material/refresh:"):
        refreshed_count = 0
        for profile in profiles:
            refreshed_count += len(refresh_suggested_interests(db, profile=profile))
        st.success(
            f"Suggested interests refreshed; {refreshed_count} active suggestion(s).",
            icon=":material/check_circle:",
        )
        st.rerun()
    found_any = False
    for profile in profiles:
        if profile.id is None:
            continue
        suggestions = db.list_suggested_interest_profiles(
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
        )
        for suggestion in suggestions:
            found_any = True
            with st.container(border=True):
                st.markdown(f"**{suggestion.suggested_name}**")
                st.caption(
                    f"Based on {len(suggestion.evidence_article_ids)} papers you marked "
                    f"as personally interesting but outside \"{profile.name}\"."
                )
                st.write(suggestion.explanation)
                with st.expander("Evidence", icon=":material/article:"):
                    for article_id in suggestion.evidence_article_ids:
                        article = db.get_article(article_id)
                        if article is not None:
                            st.write(
                                f"{article.source}:{article.source_article_id} - "
                                f"{article.title}"
                            )
                with st.form(f"suggested_interest_{suggestion.id}", border=False):
                    name = st.text_input("Profile name", value=suggestion.suggested_name)
                    description = st.text_area(
                        "Profile description",
                        value=suggestion.suggested_description,
                    )
                    with st.container(horizontal=True):
                        create = st.form_submit_button(
                            "Create profile",
                            type="primary",
                            icon=":material/add:",
                        )
                        dismiss = st.form_submit_button(
                            "Not now",
                            icon=":material/close:",
                        )
                if create:
                    try:
                        create_profile_from_suggestion(
                            db,
                            suggestion_id=suggestion.id or 0,
                            name=name,
                            description=description,
                        )
                    except Exception as exc:
                        st.error(f"Profile creation failed: {sanitize_error(exc)}")
                    else:
                        st.success("Interest profile created.", icon=":material/check_circle:")
                        st.rerun()
                if dismiss:
                    dismiss_suggested_interest(db, suggestion_id=suggestion.id or 0)
                    st.success("Suggestion dismissed.", icon=":material/check_circle:")
                    st.rerun()
    if not found_any:
        st.caption(
            "No suggested interests yet. Mark several outside-profile papers as personally "
            "interesting to help Research Digest find a coherent new profile."
        )


def _render_automation(config: AppConfig, db: Database) -> None:
    import streamlit as st

    st.subheader("Automation")
    status = read_schedule_status()
    with st.container(border=True):
        _render_schedule_status(status)
        st.caption("Last scheduled digest outcome: " + last_scheduled_digest_outcome(db))
        default_time = schedule_time_default(status.schedule)
        schedule_enabled = schedule_enabled_state(status)
        with st.form("automation_schedule", border=False):
            if schedule_enabled is None:
                st.info(
                    "Automatic daily digest: Schedule state unavailable.",
                    icon=":material/help:",
                )
                st.caption(
                    "Research Digest could not determine whether the Windows task is enabled, "
                    "so schedule install/remove controls are disabled until status inspection "
                    "succeeds."
                )
                enabled = False
            else:
                enabled = st.toggle(
                    "Automatic daily digest",
                    value=schedule_enabled,
                )
            daily_time = st.text_input(
                "Daily time",
                value=default_time,
                placeholder="07:30",
                disabled=schedule_enabled is None,
            )
            catch_up = st.toggle(
                "Catch up missed source dates",
                value=config.automatic_catch_up_enabled,
                disabled=schedule_enabled is None,
            )
            catch_up_from = st.date_input(
                "Catch up from",
                value=config.automatic_coverage_start_date,
                disabled=schedule_enabled is None,
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
                disabled=schedule_enabled is None,
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
            if st.button(
                "Disable schedule",
                icon=":material/event_busy:",
                disabled=schedule_enabled is None,
            ):
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
            "Schedule state unavailable: "
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
    enabled = schedule_enabled_state(status)
    state_label = "Unknown" if enabled is None else "Enabled" if enabled else "Disabled"
    cols[0].metric("Schedule", state_label)
    cols[1].metric("Next run", schedule.next_run_time or "unknown")
    cols[2].metric("Last scheduled run", schedule.last_run_time or "none")
    st.caption(f"Task state: {schedule.state or 'unknown'}")
    st.caption(schedule.timezone)
    if schedule.message:
        st.caption(sanitize_error(schedule.message))


def schedule_enabled_state(status: AutomationStatus) -> bool | None:
    if not status.ok or status.schedule is None:
        return None
    schedule = status.schedule
    if not schedule.installed:
        return False
    return schedule.state is None or schedule.state.strip().casefold() != "disabled"


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
    st.caption(f"Catch up from: {config.automatic_coverage_start_date.isoformat()}")
    st.caption("Latest available source date: checked when Run now starts.")
    st.caption("Pending source dates: checked when Run now starts.")
    st.caption(
        "Opening Settings is read-only; it does not contact arXiv or process catch-up dates."
    )
    anchor = config.automatic_coverage_start_date
    start_date, end_date = month_bounds(anchor)
    render_date_status_grid(
        statuses=build_date_coverage_statuses(
            db=db,
            profile=selected_profile,
            source_name=SOURCE_ARXIV,
            source_config=source_config,
            start_date=start_date,
            end_date=end_date,
            pending_dates=(),
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
        "Cached analyses are reused, and abstract-level model preselection decides which "
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
