"""Automation service shared by CLI and Streamlit."""

from __future__ import annotations

from dataclasses import dataclass

from research_digest.analysis.base import LLMAnalyzer
from research_digest.analysis.codex_context import CodexLibraryContextGenerator
from research_digest.analysis.providers import build_configured_preselector
from research_digest.config import AppConfig
from research_digest.db import Database
from research_digest.errors import sanitize_error
from research_digest.library_context import LibraryContextGenerator
from research_digest.preselection import AbstractPreselector, UnavailableFailOpenPreselector
from research_digest.scheduler import (
    DEFAULT_TASK_NAME,
    ScheduleOperationResult,
    SchedulerBackend,
    ScheduleStatus,
    build_schedule_request,
    select_scheduler_backend,
)
from research_digest.service import (
    HeadlessDigestRun,
    run_automatic_digest_for_enabled_profiles,
)
from research_digest.sources.base import SourceAdapter
from research_digest.sources.registry import ARXIV_SOURCE_DEFINITION, SourceRunRequest


@dataclass(frozen=True)
class AutomationStatus:
    ok: bool
    schedule: ScheduleStatus | None
    error_message: str | None = None


def read_schedule_status(
    *,
    scheduler_backend: SchedulerBackend | None = None,
    task_name: str = DEFAULT_TASK_NAME,
) -> AutomationStatus:
    try:
        backend = scheduler_backend or select_scheduler_backend()
        return AutomationStatus(ok=True, schedule=backend.status(task_name=task_name))
    except Exception as exc:
        return AutomationStatus(ok=False, schedule=None, error_message=sanitize_error(exc))


def install_or_update_schedule(
    *,
    time_of_day: str,
    config: AppConfig | None,
    scheduler_backend: SchedulerBackend | None = None,
    task_name: str = DEFAULT_TASK_NAME,
    wsl_distro: str | None = None,
) -> ScheduleOperationResult:
    backend = scheduler_backend or select_scheduler_backend()
    request = build_schedule_request(
        task_name=task_name,
        time_of_day=time_of_day,
        config=config,
        wsl_distro=wsl_distro,
    )
    return backend.install(request)


def remove_schedule(
    *,
    scheduler_backend: SchedulerBackend | None = None,
    task_name: str = DEFAULT_TASK_NAME,
) -> ScheduleOperationResult:
    backend = scheduler_backend or select_scheduler_backend()
    return backend.remove(task_name=task_name)


def run_automatic_digest_now(
    *,
    config: AppConfig,
    db: Database,
    source: SourceAdapter,
    analyzer: LLMAnalyzer | None,
    preselector: AbstractPreselector | None = None,
    library_context_generator: LibraryContextGenerator | None = None,
    use_configured_preselector: bool | None = None,
) -> HeadlessDigestRun:
    source_config = ARXIV_SOURCE_DEFINITION.load_config(db)
    source_request = (
        None
        if source_config is None
        else SourceRunRequest(
            source_name=ARXIV_SOURCE_DEFINITION.name,
            adapter=source,
            config=source_config,
        )
    )
    context_generator = (
        None
        if not config.automatic_library_connections_enabled
        else (
            library_context_generator
            if library_context_generator is not None
            else _build_library_context_generator(config)
        )
    )
    configured_preselector_enabled = (
        analyzer is None if use_configured_preselector is None else use_configured_preselector
    )
    if preselector is not None:
        active_preselector = preselector
    elif configured_preselector_enabled:
        active_preselector = build_configured_preselector(config).preselector
    else:
        active_preselector = UnavailableFailOpenPreselector(
            preselection_fraction=config.preselection_fraction,
            reason="Injected analyzer supplied without model preselector.",
        )
    return run_automatic_digest_for_enabled_profiles(
        db=db,
        source=source,
        analyzer=analyzer,
        source_request=source_request,
        coverage_start_date=config.automatic_coverage_start_date,
        catch_up_missed_dates=config.automatic_catch_up_enabled,
        preselector=active_preselector,
        library_context_generator=context_generator,
        automatic_library_context_threshold=config.automatic_library_context_threshold,
        relevance_calibration_prompt_probability=(
            config.relevance_calibration_prompt_probability
        ),
    )


def _build_library_context_generator(config: AppConfig) -> LibraryContextGenerator | None:
    if not config.automatic_library_connections_enabled:
        return None
    try:
        return CodexLibraryContextGenerator(
            model=config.codex_model,
            timeout_seconds=config.codex_timeout_seconds,
        )
    except Exception:
        return None
