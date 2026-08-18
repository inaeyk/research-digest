"""Quantitative human relevance calibration prompts."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from research_digest.db import APP_RUN_COMPLETED, Database
from research_digest.models import (
    AnalysisOrigin,
    DigestItem,
    DigestResult,
    QuantitativeRelevanceCalibration,
    profile_semantic_fingerprint,
)

RandomFloat = Callable[[], float]


@dataclass(frozen=True)
class CalibrationPromptCandidate:
    item: DigestItem
    preferred: bool


def maybe_create_quantitative_calibration_prompt(
    db: Database,
    *,
    digest: DigestResult,
    probability: float,
    rng: RandomFloat | None = None,
    chooser: random.Random | None = None,
) -> QuantitativeRelevanceCalibration | None:
    """Persist the one-time sampling decision for a completed digest run."""

    if probability < 0 or probability > 1:
        raise ValueError("calibration prompt probability must be between 0 and 1")
    existing = db.get_quantitative_calibration_for_run(digest.run_id)
    if existing is not None:
        return existing if existing.state != "SKIPPED" else None
    if digest.run_status != APP_RUN_COMPLETED or digest.profile.id is None:
        return None
    fingerprint = profile_semantic_fingerprint(digest.profile)
    trial = rng() if rng is not None else random.random()
    if trial >= probability:
        db.create_quantitative_calibration_skipped(
            run_id=digest.run_id,
            profile_id=digest.profile.id,
            profile_fingerprint=fingerprint,
        )
        return None
    candidates = eligible_quantitative_calibration_candidates(db, digest=digest)
    if not candidates:
        db.create_quantitative_calibration_skipped(
            run_id=digest.run_id,
            profile_id=digest.profile.id,
            profile_fingerprint=fingerprint,
        )
        return None
    selected = select_quantitative_calibration_candidate(candidates, chooser=chooser)
    article_id = selected.item.article.id
    if article_id is None:
        raise ValueError("calibration candidate article id is required")
    return db.create_quantitative_calibration_prompt(
        run_id=digest.run_id,
        article_id=article_id,
        profile_id=digest.profile.id,
        profile_fingerprint=fingerprint,
        model_relevance_score=selected.item.analysis.relevance_score,
    )


def eligible_quantitative_calibration_candidates(
    db: Database,
    *,
    digest: DigestResult,
) -> tuple[CalibrationPromptCandidate, ...]:
    profile_id = digest.profile.id
    if profile_id is None:
        return ()
    candidates: list[CalibrationPromptCandidate] = []
    for item in digest.items:
        article_id = item.article.id
        if article_id is None:
            continue
        if item.analysis.relevance_score >= digest.profile.relevance_threshold:
            continue
        if db.has_completed_quantitative_calibration(
            article_id=article_id,
            profile_id=profile_id,
        ):
            continue
        candidates.append(
            CalibrationPromptCandidate(
                item=item,
                preferred=item.analysis_origin == AnalysisOrigin.NEW_THIS_RUN,
            )
        )
    return tuple(candidates)


def select_quantitative_calibration_candidate(
    candidates: Sequence[CalibrationPromptCandidate],
    *,
    chooser: random.Random | None = None,
) -> CalibrationPromptCandidate:
    if not candidates:
        raise ValueError("at least one calibration candidate is required")
    preferred = [candidate for candidate in candidates if candidate.preferred]
    pool = preferred or list(candidates)
    active_chooser = chooser or random.Random()
    return active_chooser.choice(pool)


def submit_quantitative_calibration(
    db: Database,
    *,
    calibration_id: int,
    user_relevance_score: float,
) -> QuantitativeRelevanceCalibration:
    return db.complete_quantitative_calibration(
        calibration_id=calibration_id,
        user_relevance_score=user_relevance_score,
    )


def dismiss_quantitative_calibration(
    db: Database,
    *,
    calibration_id: int,
) -> QuantitativeRelevanceCalibration:
    return db.dismiss_quantitative_calibration(calibration_id=calibration_id)
