"""Durable source-date coverage, status presentation, and pending planning.

``source_date_coverage`` is the canonical successful-retrieval index. Coverage
is source-scoped and deliberately independent of profile-analysis identity.
Historical runs with complete retrieval are a read-only compatibility fallback
when an index row is absent.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_CANCELLED,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_PARTIAL,
    Database,
)
from research_digest.models import (
    Article,
    ArxivSourceConfig,
    DateSelection,
    DigestResult,
    InterestProfile,
    RunOrigin,
    canonical_arxiv_categories,
    source_date_from_datetime,
)
from research_digest.sources.base import LatestAvailableDateResolver

_MAX_LEGACY_ALIAS_CATEGORY_COUNT = 6
_MAX_LEGACY_ALIAS_SEQUENCE_LENGTH = 6


@dataclass(frozen=True)
class CoverageScope:
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
        categories=canonical_arxiv_categories(config.categories or ()),
    )


def source_config_accepted_semantic_fingerprints(config: ArxivSourceConfig) -> tuple[str, ...]:
    """Return current and compatible legacy source semantic fingerprints."""

    canonical = canonical_arxiv_categories(config.categories or ())
    values = [_source_config_fingerprint(categories=canonical)]
    for categories in _legacy_source_category_sequences(canonical):
        values.append(_legacy_source_config_fingerprint(enabled=True, categories=categories))
        values.append(_legacy_source_config_fingerprint(enabled=False, categories=categories))
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
    categories: tuple[str, ...],
) -> str:
    payload: dict[str, Any] = {
        "source": "arxiv",
        "categories": list(categories),
        "source_date_timezone": "America/Chicago",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _legacy_source_config_fingerprint(
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
    source_name: str,
    source_config: ArxivSourceConfig,
    profile: InterestProfile | None = None,
) -> CoverageScope:
    del profile  # Backward-compatible caller input; never part of source coverage.
    return CoverageScope(
        source_name=source_name,
        source_fingerprint=source_config_semantic_fingerprint(source_config),
        accepted_source_fingerprints=source_config_accepted_semantic_fingerprints(source_config),
    )


def build_automatic_coverage_plan(
    *,
    db: Database,
    source_name: str,
    source_config: ArxivSourceConfig,
    latest_resolver: LatestAvailableDateResolver[ArxivSourceConfig],
    coverage_start_date: date,
    catch_up_missed_dates: bool,
    profiles: tuple[InterestProfile, ...] | None = None,
) -> AutomaticCoveragePlan:
    del profiles  # Backward-compatible caller input; planning is source-scoped.
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

    scope = build_coverage_scope(
        source_name=source_name,
        source_config=source_config,
    )
    covered = _list_covered_source_dates_for_scope(
        db=db,
        scope=scope,
        start_date=coverage_start_date,
        end_date=latest_date,
    )
    pending = {value for value in candidate_dates if value not in covered}

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
    """Return canonical coverage plus safe complete-retrieval compatibility coverage."""

    covered: set[date] = set()
    for source_fingerprint in scope.accepted_source_fingerprints:
        covered.update(
            db.list_covered_source_dates(
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
        if str(row["source_name"]) != scope.source_name:
            continue
        if row["source_fingerprint"] is None or str(row["source_fingerprint"]) not in accepted:
            continue
        if str(row["status"]) not in {
            APP_RUN_COMPLETED,
            APP_RUN_FAILED,
            APP_RUN_PARTIAL,
            APP_RUN_ANALYSIS_UNAVAILABLE,
            APP_RUN_CANCELLED,
        }:
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
    source_name: str,
    source_config: ArxivSourceConfig,
    start_date: date,
    end_date: date,
    selected_dates: tuple[date, ...] = (),
    pending_dates: tuple[date, ...] = (),
    profile: InterestProfile | None = None,
) -> tuple[DateCoverageStatus, ...]:
    """Reconstruct source-retrieval status from durable rows for one scope.

    ``selected_dates`` is presentation-only and never changes the durable status.
    """

    del profile  # Backward-compatible caller input; calendars are source-scoped.
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    scope = build_coverage_scope(
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
    """Persist source coverage from a complete date-native retrieval."""

    if not digest_is_coverage_eligible(digest):
        return
    scope = build_coverage_scope(
        source_name=source_name,
        source_config=digest.source_config,
    )
    for source_date in digest.covered_source_dates:
        db.mark_source_date_covered(
            source_name=scope.source_name,
            source_fingerprint=scope.source_fingerprint,
            source_date=source_date,
            run_id=digest.run_id,
            run_origin=digest.run_origin,
        )


def digest_is_coverage_eligible(digest: DigestResult) -> bool:
    """Return whether retrieval established the complete eligible source set."""

    if not digest.date_selection:
        return False
    return digest.retrieval_complete and not digest.incomplete_source_dates


def record_complete_retrieval(
    *,
    db: Database,
    source_name: str,
    source_config: ArxivSourceConfig,
    run_id: int,
    run_origin: RunOrigin,
    covered_source_dates: tuple[date, ...],
    requested_source_dates: tuple[date, ...],
    empty_source_dates: tuple[date, ...],
    incomplete_source_dates: tuple[date, ...],
    retrieval_complete: bool,
    retrieval_safety_limit: int | None,
    retrieved_count: int,
    stored_count: int,
    articles: tuple[Article, ...],
) -> None:
    """Persist source coverage and exact article corpora before analysis starts."""

    scope = build_coverage_scope(
        source_name=source_name,
        source_config=source_config,
    )
    articles_by_date: dict[date, list[Article]] = {
        source_date: [] for source_date in covered_source_dates
    }
    for article in articles:
        article_date = source_date_from_datetime(article.published_at)
        if article_date in articles_by_date:
            articles_by_date[article_date].append(article)
    db.record_complete_source_dates(
        source_name=scope.source_name,
        source_fingerprint=scope.source_fingerprint,
        articles_by_date=articles_by_date,
        run_id=run_id,
        run_origin=run_origin,
        requested_source_dates=requested_source_dates,
        empty_source_dates=empty_source_dates,
        incomplete_source_dates=incomplete_source_dates,
        retrieval_complete=retrieval_complete,
        retrieval_safety_limit=retrieval_safety_limit,
        retrieved_count=retrieved_count,
        stored_count=stored_count,
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


def _scoped_run_date_statuses(
    *,
    db: Database,
    source_name: str,
    accepted_source_fingerprints: tuple[str, ...],
    start_date: date,
    end_date: date,
) -> dict[date, DateCoverageStatus]:
    statuses: dict[date, DateCoverageStatus] = {}
    accepted = set(accepted_source_fingerprints)
    for row in reversed(db.get_app_runs()):
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
            covered_by_run = source_date in _json_date_set(
                row["covered_source_dates_json"]
            )
            if source_date in incomplete:
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="partial",
                    label="Partial/incomplete source retrieval",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
            elif covered_by_run and source_date in empty:
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="empty",
                    label="Checked: no submissions",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
            elif covered_by_run:
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="completed",
                    label="Source covered",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
            elif run_status == APP_RUN_FAILED:
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="failed",
                    label="Source retrieval failed",
                    run_id=run_id,
                    retrieved_count=retrieved_count,
                    analyzed_count=analyzed_count,
                    relevant_count=relevant_count,
                )
            elif run_status in (APP_RUN_PARTIAL, APP_RUN_ANALYSIS_UNAVAILABLE):
                statuses[source_date] = DateCoverageStatus(
                    source_date=source_date,
                    status="partial",
                    label="Partial/incomplete source retrieval",
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
    source_name: str,
    accepted_source_fingerprints: tuple[str, ...],
) -> DateCoverageStatus:
    accepted = set(accepted_source_fingerprints)
    for row in db.list_source_date_coverage():
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
        label="Source covered",
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
        empty = source_date in _json_date_set(row["empty_source_dates_json"])
        return DateCoverageStatus(
            source_date=source_date,
            status="empty" if empty else "completed",
            label="Checked: no submissions" if empty else "Source covered",
            run_id=run_id,
            retrieved_count=int(row["retrieved_count"] or 0),
            analyzed_count=int(row["analyzed_count"] or 0),
            relevant_count=int(row["relevant_count"] or 0),
        )
    return DateCoverageStatus(
        source_date=source_date,
        status="completed",
        label="Source covered",
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
