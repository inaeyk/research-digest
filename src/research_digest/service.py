"""Application service boundary shared by UI, CLI, and schedulers."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

from research_digest.analysis.base import LLMAnalyzer
from research_digest.calibration import CalibrationSummary, build_calibration_summary
from research_digest.cancellation import (
    RunCancelled,
    bind_run_cancellation,
    cancellation_signal_scope,
    raise_if_cancelled,
    stop_abandoned_provider_processes,
)
from research_digest.coverage import (
    CoverageScope,
    build_automatic_coverage_plan,
    build_coverage_scope,
    date_selection_from_dates,
    digest_is_coverage_eligible,
)
from research_digest.db import (
    APP_RUN_CANCELLED,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    SOURCE_ARXIV,
    Database,
)
from research_digest.errors import sanitize_error
from research_digest.history import persist_run_snapshot
from research_digest.library_context import (
    LibraryContextGenerator,
    generate_automatic_library_context_for_digest,
)
from research_digest.models import (
    Article,
    ArxivSourceConfig,
    DateSelection,
    DigestResult,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.pipeline import DigestPipelineError, run_digest
from research_digest.preselection import AbstractPreselector
from research_digest.quantitative_calibration import (
    RandomFloat,
    maybe_create_quantitative_calibration_prompt,
)
from research_digest.run_locks import current_process_run_owner
from research_digest.sources.base import LatestAvailableDateResolver, SourceAdapter
from research_digest.sources.registry import ARXIV_SOURCE_DEFINITION, SourceRunRequest
from research_digest.sources.stored import StoredDateSource
from research_digest.synthesis import (
    CrossPaperSynthesis,
    CrossPaperSynthesizer,
    DeterministicCrossPaperSynthesizer,
)

DEFAULT_RUN_LOCK_STALE_SECONDS = 60.0 * 60.0 * 6.0


@dataclass(frozen=True)
class ProfileDigestRun:
    digest: DigestResult
    calibration: CalibrationSummary
    synthesis: CrossPaperSynthesis


@dataclass(frozen=True)
class HeadlessProfileRun:
    profile_id: int
    success: bool
    digest: ProfileDigestRun | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class HeadlessDigestRun:
    profiles: tuple[HeadlessProfileRun, ...]
    date_selection: DateSelection | None = None
    pending_source_dates: tuple[date, ...] = ()
    latest_available_source_date: date | None = None

    @property
    def succeeded_count(self) -> int:
        return sum(profile.success for profile in self.profiles)

    @property
    def failed_count(self) -> int:
        return sum(not profile.success for profile in self.profiles)

    @property
    def retrieved_count(self) -> int:
        return sum(
            profile.digest.digest.retrieved_count
            for profile in self.profiles
            if profile.digest is not None
        )

    @property
    def analyzed_count(self) -> int:
        return sum(
            profile.digest.digest.analyzed_count
            for profile in self.profiles
            if profile.digest is not None
        )

    @property
    def relevant_count(self) -> int:
        return sum(
            profile.digest.digest.relevant_count
            for profile in self.profiles
            if profile.digest is not None
        )

    @property
    def analysis_unavailable_count(self) -> int:
        return sum(
            profile.digest is not None and not profile.digest.digest.analysis_available
            for profile in self.profiles
        )

    @property
    def analysis_incomplete_count(self) -> int:
        return sum(
            profile.digest is not None and not profile.digest.digest.analysis_complete
            for profile in self.profiles
        )


def run_digest_for_profile(
    *,
    db: Database,
    source: SourceAdapter,
    analyzer: LLMAnalyzer | None,
    profile_id: int,
    source_request: SourceRunRequest[Any] | None = None,
    date_selection: DateSelection | None = None,
    run_origin: RunOrigin = RunOrigin.LEGACY,
    now: datetime | None = None,
    preselector: AbstractPreselector | None = None,
    synthesis_builder: CrossPaperSynthesizer | None = None,
    library_context_generator: LibraryContextGenerator | None = None,
    automatic_library_context_threshold: float | None = None,
    relevance_calibration_prompt_probability: float = 0.0,
    calibration_rng: RandomFloat | None = None,
    acquire_lock: bool = True,
    stale_lock_seconds: float = DEFAULT_RUN_LOCK_STALE_SECONDS,
) -> ProfileDigestRun:
    """Run the qualified digest workflow for one enabled profile."""

    if acquire_lock:
        owner = _lock_owner()
        with cancellation_signal_scope():
            stop_abandoned_provider_processes(
                db,
                stale_after_seconds=stale_lock_seconds,
            )
            db.acquire_run_lock(owner=owner, stale_after_seconds=stale_lock_seconds)
            try:
                return run_digest_for_profile(
                    db=db,
                    source=source,
                    analyzer=analyzer,
                    profile_id=profile_id,
                    source_request=source_request,
                    date_selection=date_selection,
                    run_origin=run_origin,
                    now=now,
                    preselector=preselector,
                    synthesis_builder=synthesis_builder,
                    library_context_generator=library_context_generator,
                    automatic_library_context_threshold=automatic_library_context_threshold,
                    relevance_calibration_prompt_probability=(
                        relevance_calibration_prompt_probability
                    ),
                    calibration_rng=calibration_rng,
                    acquire_lock=False,
                    stale_lock_seconds=stale_lock_seconds,
                )
            finally:
                db.release_run_lock(owner=owner)

    active_source_request = _resolve_source_request(
        db=db,
        source=source,
        source_request=source_request,
    )
    effective_source_request = _use_stored_corpus_when_complete(
        db=db,
        source_request=active_source_request,
        date_selection=date_selection,
    )
    digest = run_digest(
        db=db,
        source=source,
        analyzer=analyzer,
        source_request=effective_source_request,
        date_selection=date_selection,
        run_origin=run_origin,
        profile_id=profile_id,
        now=now,
        preselector=preselector,
        defer_terminalization=True,
    )
    try:
        with bind_run_cancellation(db, digest.run_id):
            raise_if_cancelled()
            active_synthesis_builder = synthesis_builder or DeterministicCrossPaperSynthesizer()
            synthesis = active_synthesis_builder.build(
                items=digest.items,
                threshold=digest.profile.relevance_threshold,
            )
            raise_if_cancelled()
            if library_context_generator is not None:
                if automatic_library_context_threshold is None:
                    raise DigestPipelineError("automatic Library context threshold is missing")
                try:
                    generate_automatic_library_context_for_digest(
                        db,
                        digest=digest,
                        generator=library_context_generator,
                        threshold=automatic_library_context_threshold,
                    )
                except Exception as exc:
                    _ = sanitize_error(exc)
            raise_if_cancelled()
            persist_run_snapshot(db=db, digest=digest, synthesis=synthesis)
            raise_if_cancelled()
            maybe_create_quantitative_calibration_prompt(
                db,
                digest=digest,
                probability=relevance_calibration_prompt_probability,
                rng=calibration_rng,
            )
            raise_if_cancelled()
            calibration = _build_calibration(db, digest)
            effective_status = _finish_digest_result(
                db,
                digest=digest,
                status=digest.run_status,
                error_message=digest.error_message,
            )
            if effective_status == APP_RUN_CANCELLED:
                raise RunCancelled(digest.run_id)
            _collect_terminal_artifacts(db)
            return ProfileDigestRun(
                digest=digest,
                calibration=calibration,
                synthesis=synthesis,
            )
    except BaseException as exc:
        cancelled = isinstance(exc, RunCancelled) or db.app_run_cancellation_requested(
            digest.run_id
        )
        _finish_digest_result(
            db,
            digest=digest,
            status=APP_RUN_CANCELLED if cancelled else APP_RUN_FAILED,
            error_message="Cancelled by user." if cancelled else sanitize_error(exc),
        )
        _collect_terminal_artifacts(db)
        raise


def run_digest_for_enabled_profiles(
    *,
    db: Database,
    source: SourceAdapter,
    analyzer: LLMAnalyzer | None,
    source_request: SourceRunRequest[Any] | None = None,
    date_selection: DateSelection | None = None,
    run_origin: RunOrigin = RunOrigin.LEGACY,
    now: datetime | None = None,
    preselector: AbstractPreselector | None = None,
    synthesis_builder: CrossPaperSynthesizer | None = None,
    library_context_generator: LibraryContextGenerator | None = None,
    automatic_library_context_threshold: float | None = None,
    relevance_calibration_prompt_probability: float = 0.0,
    stale_lock_seconds: float = DEFAULT_RUN_LOCK_STALE_SECONDS,
) -> HeadlessDigestRun:
    """Run the digest workflow for every enabled profile."""

    owner = _lock_owner()
    with cancellation_signal_scope():
        stop_abandoned_provider_processes(
            db,
            stale_after_seconds=stale_lock_seconds,
        )
        db.acquire_run_lock(owner=owner, stale_after_seconds=stale_lock_seconds)
        try:
            return _run_digest_for_enabled_profiles_unlocked(
                db=db,
                source=source,
                analyzer=analyzer,
                source_request=source_request,
                date_selection=date_selection,
                run_origin=run_origin,
                now=now,
                preselector=preselector,
                synthesis_builder=synthesis_builder,
                library_context_generator=library_context_generator,
                automatic_library_context_threshold=automatic_library_context_threshold,
                relevance_calibration_prompt_probability=(
                    relevance_calibration_prompt_probability
                ),
                stale_lock_seconds=stale_lock_seconds,
            )
        finally:
            db.release_run_lock(owner=owner)


def run_automatic_digest_for_enabled_profiles(
    *,
    db: Database,
    source: SourceAdapter,
    analyzer: LLMAnalyzer | None,
    coverage_start_date: date,
    catch_up_missed_dates: bool,
    source_request: SourceRunRequest[Any] | None = None,
    now: datetime | None = None,
    preselector: AbstractPreselector | None = None,
    synthesis_builder: CrossPaperSynthesizer | None = None,
    library_context_generator: LibraryContextGenerator | None = None,
    automatic_library_context_threshold: float | None = None,
    relevance_calibration_prompt_probability: float = 0.0,
    stale_lock_seconds: float = DEFAULT_RUN_LOCK_STALE_SECONDS,
) -> HeadlessDigestRun:
    """Run scheduled date-native catch-up for every enabled profile."""

    owner = _lock_owner()
    with cancellation_signal_scope():
        stop_abandoned_provider_processes(
            db,
            stale_after_seconds=stale_lock_seconds,
        )
        db.acquire_run_lock(owner=owner, stale_after_seconds=stale_lock_seconds)
        try:
            return _run_automatic_digest_for_enabled_profiles_unlocked(
                db=db,
                source=source,
                analyzer=analyzer,
                coverage_start_date=coverage_start_date,
                catch_up_missed_dates=catch_up_missed_dates,
                source_request=source_request,
                now=now,
                preselector=preselector,
                synthesis_builder=synthesis_builder,
                library_context_generator=library_context_generator,
                automatic_library_context_threshold=automatic_library_context_threshold,
                relevance_calibration_prompt_probability=(
                    relevance_calibration_prompt_probability
                ),
                stale_lock_seconds=stale_lock_seconds,
            )
        finally:
            db.release_run_lock(owner=owner)


def _run_automatic_digest_for_enabled_profiles_unlocked(
    *,
    db: Database,
    source: SourceAdapter,
    analyzer: LLMAnalyzer | None,
    coverage_start_date: date,
    catch_up_missed_dates: bool,
    source_request: SourceRunRequest[Any] | None,
    now: datetime | None,
    preselector: AbstractPreselector | None,
    synthesis_builder: CrossPaperSynthesizer | None,
    library_context_generator: LibraryContextGenerator | None,
    automatic_library_context_threshold: float | None,
    relevance_calibration_prompt_probability: float,
    stale_lock_seconds: float,
) -> HeadlessDigestRun:
    profiles = tuple(db.list_interest_profiles(enabled_only=True))
    if not profiles:
        raise DigestPipelineError("create and enable an interest profile before running a digest")

    active_source_request = source_request
    if active_source_request is None:
        source_config = ARXIV_SOURCE_DEFINITION.load_config(db)
        if source_config is None:
            raise DigestPipelineError("source configuration is missing")
        active_source_request = SourceRunRequest(
            source_name=ARXIV_SOURCE_DEFINITION.name,
            adapter=source,
            config=source_config,
        )

    if not isinstance(active_source_request.adapter, LatestAvailableDateResolver):
        raise DigestPipelineError("source adapter cannot resolve latest available source date")
    source_config = cast(ArxivSourceConfig, active_source_request.config)
    plan = build_automatic_coverage_plan(
        db=db,
        source_name=active_source_request.source_name,
        source_config=source_config,
        latest_resolver=active_source_request.adapter,
        coverage_start_date=coverage_start_date,
        catch_up_missed_dates=catch_up_missed_dates,
    )
    aggregate_date_selection = plan.date_selection

    runs: list[HeadlessProfileRun] = []
    for profile in profiles:
        if profile.id is None:
            raise DigestPipelineError("enabled interest profile is missing an id")
        profile_date_selection = aggregate_date_selection
        if profile_date_selection is None:
            profile_date_selection = date_selection_from_dates(
                _pending_local_profile_analysis_dates(
                    db=db,
                    profile_id=profile.id,
                    profile_fingerprint=profile_semantic_fingerprint(profile),
                    source_request=active_source_request,
                    candidate_dates=plan.candidate_dates,
                )
            )
        if profile_date_selection is None:
            continue
        try:
            digest = run_digest_for_profile(
                db=db,
                source=source,
                analyzer=analyzer,
                profile_id=profile.id,
                source_request=active_source_request,
                date_selection=profile_date_selection,
                run_origin=RunOrigin.SCHEDULED,
                now=now,
                preselector=preselector,
                synthesis_builder=synthesis_builder,
                library_context_generator=library_context_generator,
                automatic_library_context_threshold=automatic_library_context_threshold,
                relevance_calibration_prompt_probability=(
                    relevance_calibration_prompt_probability
                ),
                acquire_lock=False,
                stale_lock_seconds=stale_lock_seconds,
            )
        except Exception as exc:
            runs.append(
                HeadlessProfileRun(
                    profile_id=profile.id,
                    success=False,
                    error_message=sanitize_error(exc),
                )
            )
        else:
            success = _profile_digest_succeeded(digest)
            runs.append(
                HeadlessProfileRun(
                    profile_id=profile.id,
                    success=success,
                    digest=digest,
                    error_message=None if success else _profile_digest_error_message(digest),
                )
            )

    return HeadlessDigestRun(
        profiles=tuple(runs),
        date_selection=aggregate_date_selection,
        pending_source_dates=plan.pending_dates,
        latest_available_source_date=plan.latest_available_date,
    )


def _run_digest_for_enabled_profiles_unlocked(
    *,
    db: Database,
    source: SourceAdapter,
    analyzer: LLMAnalyzer | None,
    source_request: SourceRunRequest[Any] | None,
    date_selection: DateSelection | None,
    run_origin: RunOrigin,
    now: datetime | None,
    preselector: AbstractPreselector | None,
    synthesis_builder: CrossPaperSynthesizer | None,
    library_context_generator: LibraryContextGenerator | None,
    automatic_library_context_threshold: float | None,
    relevance_calibration_prompt_probability: float,
    stale_lock_seconds: float,
) -> HeadlessDigestRun:
    profiles = db.list_interest_profiles(enabled_only=True)
    if not profiles:
        raise DigestPipelineError("create and enable an interest profile before running a digest")

    runs: list[HeadlessProfileRun] = []
    for profile in profiles:
        if profile.id is None:
            raise DigestPipelineError("enabled interest profile is missing an id")
        try:
            digest = run_digest_for_profile(
                db=db,
                source=source,
                analyzer=analyzer,
                profile_id=profile.id,
                source_request=source_request,
                date_selection=date_selection,
                run_origin=run_origin,
                now=now,
                preselector=preselector,
                synthesis_builder=synthesis_builder,
                library_context_generator=library_context_generator,
                automatic_library_context_threshold=automatic_library_context_threshold,
                relevance_calibration_prompt_probability=(
                    relevance_calibration_prompt_probability
                ),
                acquire_lock=False,
                stale_lock_seconds=stale_lock_seconds,
            )
        except Exception as exc:
            runs.append(
                HeadlessProfileRun(
                    profile_id=profile.id,
                    success=False,
                    error_message=sanitize_error(exc),
                )
            )
        else:
            success = _profile_digest_succeeded(digest)
            runs.append(
                HeadlessProfileRun(
                    profile_id=profile.id,
                    success=success,
                    digest=digest,
                    error_message=None if success else _profile_digest_error_message(digest),
                )
            )

    return HeadlessDigestRun(profiles=tuple(runs))


def _profile_digest_succeeded(digest: ProfileDigestRun) -> bool:
    if digest.digest.run_status != APP_RUN_COMPLETED:
        return False
    return (
        digest.digest.date_selection is None
        or digest_is_coverage_eligible(digest.digest)
    )


def _finish_digest_result(
    db: Database,
    *,
    digest: DigestResult,
    status: str,
    error_message: str | None,
) -> str:
    """Terminalize once while preserving every progress and retrieval fact."""

    return db.finish_app_run(
        digest.run_id,
        status=status,
        retrieved_count=digest.retrieved_count,
        stored_count=digest.stored_count,
        preselected_count=digest.preselected_count,
        skipped_analysis_count=digest.skipped_analysis_count,
        analyzed_count=digest.analyzed_count,
        relevant_count=digest.above_threshold_count,
        error_message=error_message,
        requested_source_dates=tuple(
            value.isoformat() for value in digest.requested_source_dates
        ),
        covered_source_dates=tuple(
            value.isoformat() for value in digest.covered_source_dates
        ),
        empty_source_dates=tuple(value.isoformat() for value in digest.empty_source_dates),
        incomplete_source_dates=tuple(
            value.isoformat() for value in digest.incomplete_source_dates
        ),
        retrieval_complete=digest.retrieval_complete,
        retrieval_safety_limit=digest.retrieval_safety_limit,
    )


def _collect_terminal_artifacts(db: Database) -> None:
    """Run low-frequency GC after any durable terminal run state."""

    with suppress(Exception):
        db.collect_expired_ai_artifacts()


def _profile_digest_error_message(digest: ProfileDigestRun) -> str:
    if digest.digest.error_message:
        return digest.digest.error_message
    if not digest.digest.retrieval_complete or digest.digest.incomplete_source_dates:
        dates = ", ".join(value.isoformat() for value in digest.digest.incomplete_source_dates)
        return "Retrieval incomplete" + (f" for source date(s): {dates}" if dates else ".")
    if not digest.digest.analysis_complete:
        return f"Analysis incomplete for {len(digest.digest.unresolved_articles)} paper(s)."
    return "Digest did not reach the required completed state."


def _resolve_source_request(
    *,
    db: Database,
    source: SourceAdapter,
    source_request: SourceRunRequest[Any] | None,
) -> SourceRunRequest[Any]:
    if source_request is not None:
        return source_request
    source_config = db.get_arxiv_config()
    if source_config is None:
        raise DigestPipelineError("source configuration is missing")
    return SourceRunRequest(
        source_name=SOURCE_ARXIV,
        adapter=source,
        config=source_config,
    )


def _use_stored_corpus_when_complete(
    *,
    db: Database,
    source_request: SourceRunRequest[Any],
    date_selection: DateSelection | None,
) -> SourceRunRequest[Any]:
    if date_selection is None or not isinstance(source_request.config, ArxivSourceConfig):
        return source_request
    selected_dates = date_selection.selected_dates()
    if not selected_dates:
        return source_request
    scope = build_coverage_scope(
        source_name=source_request.source_name,
        source_config=source_request.config,
    )
    corpora: dict[date, tuple[Article, ...]] = {}
    for source_date in selected_dates:
        corpus = db.load_source_date_corpus(
            source_name=scope.source_name,
            source_fingerprints=scope.accepted_source_fingerprints,
            source_date=source_date,
        )
        if corpus is None:
            corpus = _recover_legacy_covered_corpus(
                db=db,
                scope=scope,
                source_config=source_request.config,
                source_date=source_date,
            )
        if corpus is None:
            return source_request
        corpora[source_date] = corpus
    return SourceRunRequest(
        source_name=source_request.source_name,
        adapter=StoredDateSource(corpora),
        config=source_request.config,
    )


def _recover_legacy_covered_corpus(
    *,
    db: Database,
    scope: CoverageScope,
    source_config: ArxivSourceConfig,
    source_date: date,
) -> tuple[Article, ...] | None:
    """Boundedly reconstruct v16 covered corpora from locally stored articles."""

    covered = any(
        source_date
        in db.list_covered_source_dates(
            source_name=scope.source_name,
            source_fingerprint=fingerprint,
            start_date=source_date,
            end_date=source_date,
        )
        for fingerprint in scope.accepted_source_fingerprints
    )
    if not covered:
        return None
    return db.list_articles_for_source_date(
        source_name=scope.source_name,
        source_date=source_date,
        categories=source_config.categories or (),
    )


def _pending_local_profile_analysis_dates(
    *,
    db: Database,
    profile_id: int,
    profile_fingerprint: str,
    source_request: SourceRunRequest[Any],
    candidate_dates: tuple[date, ...],
) -> tuple[date, ...]:
    """Return source-covered dates needing analysis for this profile semantics."""

    if not isinstance(source_request.config, ArxivSourceConfig):
        return ()
    scope = build_coverage_scope(
        source_name=source_request.source_name,
        source_config=source_request.config,
    )
    accepted = set(scope.accepted_source_fingerprints)
    completed: set[date] = set()
    candidate_set = set(candidate_dates)
    for row in db.get_app_runs():
        if row["profile_id"] is None or int(row["profile_id"]) != profile_id:
            continue
        if str(row["profile_fingerprint"] or "") != profile_fingerprint:
            continue
        if str(row["source_name"]) != scope.source_name:
            continue
        if str(row["source_fingerprint"] or "") not in accepted:
            continue
        if str(row["status"]) != APP_RUN_COMPLETED:
            continue
        completed.update(
            _date_values_from_json(row["covered_source_dates_json"]) & candidate_set
        )

    pending: list[date] = []
    for source_date in candidate_dates:
        if source_date in completed:
            continue
        corpus = db.load_source_date_corpus(
            source_name=scope.source_name,
            source_fingerprints=scope.accepted_source_fingerprints,
            source_date=source_date,
        )
        if corpus is None:
            corpus = _recover_legacy_covered_corpus(
                db=db,
                scope=scope,
                source_config=source_request.config,
                source_date=source_date,
            )
        if corpus is not None:
            pending.append(source_date)
    return tuple(pending)


def _date_values_from_json(value: object) -> set[date]:
    try:
        payload = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(payload, list):
        return set()
    dates: set[date] = set()
    for item in payload:
        if not isinstance(item, str):
            continue
        try:
            dates.add(date.fromisoformat(item))
        except ValueError:
            continue
    return dates


def _lock_owner() -> str:
    return current_process_run_owner()


def _build_calibration(db: Database, digest: DigestResult) -> CalibrationSummary:
    if digest.profile.id is None:
        feedback_by_article_id = {}
    else:
        fingerprint = profile_semantic_fingerprint(digest.profile)
        feedback_by_article_id = {
            feedback.article_id: feedback
            for feedback in db.list_article_feedback(
                profile_id=digest.profile.id,
                profile_fingerprint=fingerprint,
            )
        }
    return build_calibration_summary(
        items=digest.items,
        feedback_by_article_id=feedback_by_article_id,
        threshold=digest.profile.relevance_threshold,
    )
