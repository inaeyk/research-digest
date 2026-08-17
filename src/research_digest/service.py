"""Application service boundary shared by UI, CLI, and schedulers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast
from uuid import uuid4

from research_digest.analysis.base import LLMAnalyzer
from research_digest.calibration import CalibrationSummary, build_calibration_summary
from research_digest.coverage import (
    build_automatic_coverage_plan,
    digest_is_coverage_eligible,
    mark_digest_coverage,
)
from research_digest.db import APP_RUN_COMPLETED, SOURCE_ARXIV, Database
from research_digest.errors import sanitize_error
from research_digest.history import persist_run_snapshot
from research_digest.models import (
    ArxivSourceConfig,
    DateSelection,
    DigestResult,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.pipeline import DigestPipelineError, run_digest
from research_digest.preselection import AbstractPreselector
from research_digest.sources.base import LatestAvailableDateResolver, SourceAdapter
from research_digest.sources.registry import ARXIV_SOURCE_DEFINITION, SourceRunRequest
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
    acquire_lock: bool = True,
    stale_lock_seconds: float = DEFAULT_RUN_LOCK_STALE_SECONDS,
) -> ProfileDigestRun:
    """Run the qualified digest workflow for one enabled profile."""

    if acquire_lock:
        owner = _lock_owner()
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
                acquire_lock=False,
                stale_lock_seconds=stale_lock_seconds,
            )
        finally:
            db.release_run_lock(owner=owner)

    digest = run_digest(
        db=db,
        source=source,
        analyzer=analyzer,
        source_request=source_request,
        date_selection=date_selection,
        run_origin=run_origin,
        profile_id=profile_id,
        now=now,
        preselector=preselector,
    )
    active_synthesis_builder = synthesis_builder or DeterministicCrossPaperSynthesizer()
    synthesis = active_synthesis_builder.build(
        items=digest.items,
        threshold=digest.profile.relevance_threshold,
    )
    persist_run_snapshot(db=db, digest=digest, synthesis=synthesis)
    mark_digest_coverage(
        db=db,
        digest=digest,
        source_name=source_request.source_name if source_request is not None else SOURCE_ARXIV,
    )
    return ProfileDigestRun(
        digest=digest,
        calibration=_build_calibration(db, digest),
        synthesis=synthesis,
    )


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
    stale_lock_seconds: float = DEFAULT_RUN_LOCK_STALE_SECONDS,
) -> HeadlessDigestRun:
    """Run the digest workflow for every enabled profile."""

    owner = _lock_owner()
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
    stale_lock_seconds: float = DEFAULT_RUN_LOCK_STALE_SECONDS,
) -> HeadlessDigestRun:
    """Run scheduled date-native catch-up for every enabled profile."""

    owner = _lock_owner()
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
        profiles=profiles,
        source_name=active_source_request.source_name,
        source_config=source_config,
        latest_resolver=active_source_request.adapter,
        coverage_start_date=coverage_start_date,
        catch_up_missed_dates=catch_up_missed_dates,
    )
    aggregate_date_selection = plan.date_selection
    if aggregate_date_selection is None:
        return HeadlessDigestRun(
            profiles=(),
            date_selection=None,
            pending_source_dates=plan.pending_dates,
            latest_available_source_date=plan.latest_available_date,
        )

    runs: list[HeadlessProfileRun] = []
    for profile in profiles:
        if profile.id is None:
            raise DigestPipelineError("enabled interest profile is missing an id")
        profile_plan = build_automatic_coverage_plan(
            db=db,
            profiles=(profile,),
            source_name=active_source_request.source_name,
            source_config=source_config,
            latest_resolver=active_source_request.adapter,
            coverage_start_date=coverage_start_date,
            catch_up_missed_dates=catch_up_missed_dates,
        )
        profile_date_selection = profile_plan.date_selection
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
    if digest.digest.date_selection is not None:
        return digest_is_coverage_eligible(digest.digest)
    return digest.digest.run_status == APP_RUN_COMPLETED


def _profile_digest_error_message(digest: ProfileDigestRun) -> str:
    if digest.digest.error_message:
        return digest.digest.error_message
    if not digest.digest.retrieval_complete or digest.digest.incomplete_source_dates:
        dates = ", ".join(value.isoformat() for value in digest.digest.incomplete_source_dates)
        return "Retrieval incomplete" + (f" for source date(s): {dates}" if dates else ".")
    if not digest.digest.analysis_complete:
        return f"Analysis incomplete for {len(digest.digest.unresolved_articles)} paper(s)."
    return "Digest did not reach the required completed state."


def _lock_owner() -> str:
    return f"pid:{uuid4()}"


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
