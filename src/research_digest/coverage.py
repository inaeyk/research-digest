"""Date coverage planning for automatic digest runs."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_PARTIAL,
    Database,
)
from research_digest.models import (
    ArxivSourceConfig,
    DateSelection,
    DigestResult,
    InterestProfile,
    canonical_arxiv_categories,
    profile_semantic_fingerprint,
)
from research_digest.sources.base import LatestAvailableDateResolver

_MAX_LEGACY_ALIAS_CATEGORY_COUNT = 6
_MAX_LEGACY_ALIAS_SEQUENCE_LENGTH = 6


@dataclass(frozen=True)
class CoverageScope:
    profile_id: int
    profile_fingerprint: str
    source_name: str
    source_fingerprint: str
    accepted_source_fingerprints: tuple[str, ...]


@dataclass(frozen=True)
class AutomaticCoveragePlan:
    latest_available_date: date | None
    candidate_dates: tuple[date, ...]
    pending_dates: tuple[date, ...]

    @property
    def date_selection(self) -> DateSelection | None:
        return date_selection_from_dates(self.pending_dates)


@dataclass(frozen=True)
class DateCoverageStatus:
    source_date: date
    status: str
    label: str
    selected: bool = False
    run_id: int | None = None
    retrieved_count: int | None = None
    analyzed_count: int | None = None
    relevant_count: int | None = None


def source_config_semantic_fingerprint(config: ArxivSourceConfig) -> str:
    """Return the source fields that define date coverage semantics."""

    return _source_config_fingerprint(
        enabled=config.enabled,
        categories=canonical_arxiv_categories(config.categories or ()),
    )


def source_config_accepted_semantic_fingerprints(config: ArxivSourceConfig) -> tuple[str, ...]:
    """Return current and compatible legacy source semantic fingerprints."""

    canonical = canonical_arxiv_categories(config.categories or ())
    values = [_source_config_fingerprint(enabled=config.enabled, categories=canonical)]
    for categories in _legacy_source_category_sequences(canonical):
        values.append(_source_config_fingerprint(enabled=config.enabled, categories=categories))
    return tuple(dict.fromkeys(values))


def _legacy_source_category_sequences(categories: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    if not categories:
        return ((),)
    if len(categories) > _MAX_LEGACY_ALIAS_CATEGORY_COUNT:
        return (categories,)
    category_set = set(categories)
    sequences: list[tuple[str, ...]] = []
    for length in range(len(categories), _MAX_LEGACY_ALIAS_SEQUENCE_LENGTH + 1):
        for candidate in itertools.product(categories, repeat=length):
            if set(candidate) == category_set:
                sequences.append(candidate)
    return tuple(sequences)


def _source_config_fingerprint(
    *,
    enabled: bool,
    categories: tuple[str, ...],
) -> str:
    payload: dict[str, Any] = {
        "source": "arxiv",
        "enabled": enabled,
        "categories": list(categories),
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
        accepted_source_fingerprints=source_config_accepted_semantic_fingerprints(source_config),
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
        covered = _list_covered_source_dates_for_scope(
            db=db,
            scope=scope,
            start_date=coverage_start_date,
            end_date=latest_date,
        )
        pending.update(value for value in candidate_dates if value not in covered)

    return AutomaticCoveragePlan(
        latest_available_date=latest_date,
        candidate_dates=candidate_dates,
        pending_dates=tuple(sorted(pending)),
    )


def _list_covered_source_dates_for_scope(
    *,
    db: Database,
    scope: CoverageScope,
    start_date: date,
    end_date: date,
) -> set[date]:
    covered: set[date] = set()
    for source_fingerprint in scope.accepted_source_fingerprints:
        covered.update(
            db.list_covered_source_dates(
                profile_id=scope.profile_id,
                profile_fingerprint=scope.profile_fingerprint,
                source_name=scope.source_name,
                source_fingerprint=source_fingerprint,
                start_date=start_date,
                end_date=end_date,
            )
        )
    covered.update(
        _list_completed_app_run_source_dates_for_scope(
            db=db,
            scope=scope,
            start_date=start_date,
            end_date=end_date,
        )
    )
    return covered


def _list_completed_app_run_source_dates_for_scope(
    *,
    db: Database,
    scope: CoverageScope,
    start_date: date,
    end_date: date,
) -> set[date]:
    covered: set[date] = set()
    accepted = set(scope.accepted_source_fingerprints)
    for row in db.get_app_runs():
        if row["profile_id"] is None or int(row["profile_id"]) != scope.profile_id:
            continue
        if (
            row["profile_fingerprint"] is None
            or str(row["profile_fingerprint"]) != scope.profile_fingerprint
        ):
            continue
        if str(row["source_name"]) != scope.source_name:
            continue
        if row["source_fingerprint"] is None or str(row["source_fingerprint"]) not in accepted:
            continue
        if str(row["status"]) != APP_RUN_COMPLETED or not bool(row["retrieval_complete"]):
            continue
        incomplete = _json_date_set(row["incomplete_source_dates_json"])
        for source_date in _json_date_set(row["covered_source_dates_json"]):
            if source_date < start_date or source_date > end_date:
                continue
            if source_date in incomplete:
                continue
            covered.add(source_date)
    return covered


def build_date_coverage_statuses(
    *,
    db: Database,
    profile: InterestProfile,
    source_name: str,
    source_config: ArxivSourceConfig,
    start_date: date,
    end_date: date,
    selected_dates: tuple[date, ...] = (),
    pending_dates: tuple[date, ...] = (),
) -> tuple[DateCoverageStatus, ...]:
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    scope = build_coverage_scope(
        profile=profile,
        source_name=source_name,
        source_config=source_config,
    )
    days = _date_range(start_date, end_date)
    selected = set(selected_dates)
    pending = set(pending_dates)
    covered = _list_covered_source_dates_for_scope(
        db=db,
        scope=scope,
        start_date=start_date,
        end_date=end_date,
    )
    labels_by_date: dict[date, DateCoverageStatus] = {
        value: DateCoverageStatus(
            source_date=value,
            status="out_of_scope",
            label="Outside catch-up interval",
        )
        for value in days
    }
    for value in pending:
        if value in labels_by_date:
            labels_by_date[value] = DateCoverageStatus(
                source_date=value,
                status="pending",
                label="Pending/uncovered",
            )
    for source_date, status in _scoped_run_date_statuses(
        db=db,
        profile_id=scope.profile_id,
        profile_fingerprint=scope.profile_fingerprint,
        source_name=scope.source_name,
        accepted_source_fingerprints=scope.accepted_source_fingerprints,
        start_date=start_date,
        end_date=end_date,
    ).items():
        labels_by_date[source_date] = status
    for value in covered:
        if labels_by_date[value].status == "empty":
            continue
        completed_status = _completed_coverage_status(
            db=db,
            source_date=value,
            profile_id=scope.profile_id,
            profile_fingerprint=scope.profile_fingerprint,
            source_name=scope.source_name,
            accepted_source_fingerprints=scope.accepted_source_fingerprints,
        )
        if completed_status.run_id is None and labels_by_date[value].status == "completed":
            continue
        labels_by_date[value] = completed_status
    return tuple(
        DateCoverageStatus(
            source_date=value,
            status=labels_by_date[value].status,
            label=labels_by_date[value].label,
            selected=value in selected,
            run_id=labels_by_date[value].run_id,
            retrieved_count=labels_by_date[value].retrieved_count,
            analyzed_count=labels_by_date[value].analyzed_count,
            relevant_count=labels_by_date[value].relevant_count,
        )
        for value in days
    )


def mark_digest_coverage(
    *,
    db: Database,
    digest: DigestResult,
    source_name: str,
) -> None:
    """Persist COVERED dates from a completed usable date-native digest."""

    if not digest_is_coverage_eligible(digest):
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


def digest_is_coverage_eligible(digest: DigestResult) -> bool:
    """Return whether a digest satisfies durable date-coverage semantics."""

    if not digest.date_selection:
        return False
    if digest.run_status != APP_RUN_COMPLETED:
        return False
    if not digest.retrieval_complete or digest.incomplete_source_dates:
        return False
    return digest.analysis_complete or digest.retrieved_count == 0


def date_selection_from_dates(values: tuple[date, ...]) -> DateSelection | None:
    if not values:
        return None
    dates = tuple(sorted(set(values)))
    if len(dates) == 1:
        return DateSelection.single_date(dates[0])
    if dates == _date_range(dates[0], dates[-1]):
        return DateSelection.date_range(dates[0], dates[-1])
    return DateSelection.explicit_dates(dates)


def _scoped_run_date_statuses(
    *,
    db: Database,
    profile_id: int,
    profile_fingerprint: str,
    source_name: str,
    accepted_source_fingerprints: tuple[str, ...],
    start_date: date,
    end_date: date,
) -> dict[date, DateCoverageStatus]:
    statuses: dict[date, DateCoverageStatus] = {}
    accepted = set(accepted_source_fingerprints)
    for row in reversed(db.get_app_runs()):
        if row["profile_id"] is None or int(row["profile_id"]) != profile_id:
            continue
        if (
            row["profile_fingerprint"] is None
            or str(row["profile_fingerprint"]) != profile_fingerprint
        ):
            continue
        if str(row["source_name"]) != source_name:
            continue
        if row["source_fingerprint"] is None or str(row["source_fingerprint"]) not in accepted:
            continue
        run_status = str(row["status"])
        requested = _json_date_set(row["requested_source_dates_json"])
        empty = _json_date_set(row["empty_source_dates_json"])
        incomplete = _json_date_set(row["incomplete_source_dates_json"])
        for source_date in requested:
            if source_date < start_date or source_date > end_date:
                continue
            run_id = int(row["id"])
            retrieved_count = int(row["retrieved_count"] or 0)
            analyzed_count = int(row["analyzed_count"] or 0)
            relevant_count = int(row["relevant_count"] or 0)
            if run_status == APP_RUN_FAILED:
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="failed",
                    label="Failed digest",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
            elif (
                run_status in (APP_RUN_PARTIAL, APP_RUN_ANALYSIS_UNAVAILABLE)
                or source_date in incomplete
            ):
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="partial",
                    label="Partial/incomplete digest",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
            elif run_status == APP_RUN_COMPLETED and source_date in empty:
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="empty",
                    label="Checked: no submissions",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
            elif (
                run_status == APP_RUN_COMPLETED
                and bool(row["retrieval_complete"])
                and source_date in _json_date_set(row["covered_source_dates_json"])
                and source_date not in incomplete
            ):
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="completed",
                    label="Completed digest",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
    return statuses


def _completed_coverage_status(
    *,
    db: Database,
    source_date: date,
    profile_id: int,
    profile_fingerprint: str,
    source_name: str,
    accepted_source_fingerprints: tuple[str, ...],
) -> DateCoverageStatus:
    accepted = set(accepted_source_fingerprints)
    for row in db.list_source_date_coverage():
        if int(row["profile_id"]) != profile_id:
            continue
        if str(row["profile_fingerprint"]) != profile_fingerprint:
            continue
        if str(row["source_name"]) != source_name:
            continue
        if str(row["source_fingerprint"]) not in accepted:
            continue
        if str(row["source_date"]) != source_date.isoformat():
            continue
        run_id = int(row["last_covered_run_id"])
        return _completed_status_from_run(db=db, source_date=source_date, run_id=run_id)
    return DateCoverageStatus(
        source_date=source_date,
        status="completed",
        label="Completed digest",
    )


def _completed_status_from_run(
    *,
    db: Database,
    source_date: date,
    run_id: int,
) -> DateCoverageStatus:
    for row in db.get_app_runs():
        if int(row["id"]) != run_id:
            continue
        return DateCoverageStatus(
            source_date=source_date,
            status="completed",
            label="Completed digest",
            run_id=run_id,
            retrieved_count=int(row["retrieved_count"] or 0),
            analyzed_count=int(row["analyzed_count"] or 0),
            relevant_count=int(row["relevant_count"] or 0),
        )
    return DateCoverageStatus(
        source_date=source_date,
        status="completed",
        label="Completed digest",
        run_id=run_id,
    )


def _json_date_set(value: object) -> set[date]:
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
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


def _date_range(start: date, end: date) -> tuple[date, ...]:
    days = (end - start).days
    return tuple(start + timedelta(days=offset) for offset in range(days + 1))
