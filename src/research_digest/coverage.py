"""Date coverage planning for automatic digest runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from research_digest.db import Database
from research_digest.models import (
    ArxivSourceConfig,
    DateSelection,
    DigestResult,
    InterestProfile,
    profile_semantic_fingerprint,
)
from research_digest.sources.base import LatestAvailableDateResolver


@dataclass(frozen=True)
class CoverageScope:
    profile_id: int
    profile_fingerprint: str
    source_name: str
    source_fingerprint: str


@dataclass(frozen=True)
class AutomaticCoveragePlan:
    latest_available_date: date | None
    candidate_dates: tuple[date, ...]
    pending_dates: tuple[date, ...]

    @property
    def date_selection(self) -> DateSelection | None:
        return date_selection_from_dates(self.pending_dates)


def source_config_semantic_fingerprint(config: ArxivSourceConfig) -> str:
    """Return the source fields that define date coverage semantics."""

    payload: dict[str, Any] = {
        "source": "arxiv",
        "enabled": config.enabled,
        "categories": config.categories,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_coverage_scope(
    *,
    profile: InterestProfile,
    source_name: str,
    source_config: ArxivSourceConfig,
) -> CoverageScope:
    if profile.id is None:
        raise ValueError("profile id is required for coverage scope")
    return CoverageScope(
        profile_id=profile.id,
        profile_fingerprint=profile_semantic_fingerprint(profile),
        source_name=source_name,
        source_fingerprint=source_config_semantic_fingerprint(source_config),
    )


def build_automatic_coverage_plan(
    *,
    db: Database,
    profiles: tuple[InterestProfile, ...],
    source_name: str,
    source_config: ArxivSourceConfig,
    latest_resolver: LatestAvailableDateResolver[ArxivSourceConfig],
    coverage_start_date: date,
    catch_up_missed_dates: bool,
) -> AutomaticCoveragePlan:
    latest_date = latest_resolver.resolve_latest_available_date(source_config)
    if latest_date is None or latest_date < coverage_start_date:
        return AutomaticCoveragePlan(
            latest_available_date=latest_date,
            candidate_dates=(),
            pending_dates=(),
        )

    if catch_up_missed_dates:
        candidate_dates = _date_range(coverage_start_date, latest_date)
    else:
        candidate_dates = (latest_date,)

    pending: set[date] = set()
    for profile in profiles:
        scope = build_coverage_scope(
            profile=profile,
            source_name=source_name,
            source_config=source_config,
        )
        covered = db.list_covered_source_dates(
            profile_id=scope.profile_id,
            profile_fingerprint=scope.profile_fingerprint,
            source_name=scope.source_name,
            source_fingerprint=scope.source_fingerprint,
            start_date=coverage_start_date,
            end_date=latest_date,
        )
        pending.update(value for value in candidate_dates if value not in covered)

    return AutomaticCoveragePlan(
        latest_available_date=latest_date,
        candidate_dates=candidate_dates,
        pending_dates=tuple(sorted(pending)),
    )


def mark_digest_coverage(
    *,
    db: Database,
    digest: DigestResult,
    source_name: str,
) -> None:
    """Persist COVERED dates from a completed usable date-native digest."""

    if not digest.date_selection:
        return
    if not digest.retrieval_complete or digest.incomplete_source_dates:
        return
    if not digest.analysis_available and digest.retrieved_count > 0:
        return
    scope = build_coverage_scope(
        profile=digest.profile,
        source_name=source_name,
        source_config=digest.source_config,
    )
    for source_date in digest.covered_source_dates:
        db.mark_source_date_covered(
            profile_id=scope.profile_id,
            profile_fingerprint=scope.profile_fingerprint,
            source_name=scope.source_name,
            source_fingerprint=scope.source_fingerprint,
            source_date=source_date,
            run_id=digest.run_id,
            run_origin=digest.run_origin,
        )


def date_selection_from_dates(values: tuple[date, ...]) -> DateSelection | None:
    if not values:
        return None
    dates = tuple(sorted(set(values)))
    if len(dates) == 1:
        return DateSelection.single_date(dates[0])
    if dates == _date_range(dates[0], dates[-1]):
        return DateSelection.date_range(dates[0], dates[-1])
    return DateSelection.explicit_dates(dates)


def _date_range(start: date, end: date) -> tuple[date, ...]:
    days = (end - start).days
    return tuple(start + timedelta(days=offset) for offset in range(days + 1))
