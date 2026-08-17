"""Application service boundary shared by UI, CLI, and schedulers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from research_digest.analysis.base import LLMAnalyzer
from research_digest.calibration import CalibrationSummary, build_calibration_summary
from research_digest.db import Database
from research_digest.errors import sanitize_error
from research_digest.history import persist_run_snapshot
from research_digest.models import (
    DateSelection,
    DigestResult,
    RunOrigin,
    profile_semantic_fingerprint,
)
from research_digest.pipeline import DigestPipelineError, run_digest
from research_digest.preselection import AbstractPreselector
from research_digest.sources.base import SourceAdapter
from research_digest.sources.registry import SourceRunRequest
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
            runs.append(HeadlessProfileRun(profile_id=profile.id, success=True, digest=digest))

    return HeadlessDigestRun(profiles=tuple(runs))


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
