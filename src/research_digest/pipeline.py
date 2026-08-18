"""Digest orchestration service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from research_digest.analysis.base import LLMAnalyzer, article_analysis_key
from research_digest.coverage import source_config_semantic_fingerprint
from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    APP_RUN_PARTIAL,
    SOURCE_ARXIV,
    Database,
)
from research_digest.errors import sanitize_error
from research_digest.models import (
    AnalysisOrigin,
    AnalysisResult,
    Article,
    ArxivSourceConfig,
    DateSelection,
    DigestItem,
    DigestResult,
    InterestProfile,
    PreselectionEvidence,
    RunOrigin,
    is_above_threshold,
    profile_semantic_fingerprint,
    sorted_digest_items,
    source_date_from_datetime,
    utc_now,
)
from research_digest.preselection import (
    AbstractPreselectionDecision,
    AbstractPreselector,
    TermOverlapPreselector,
    fail_open_preselection_result,
    reused_analysis_preselection_decision,
)
from research_digest.sources.base import DateNativeSourceAdapter, SourceAdapter
from research_digest.sources.registry import SourceRunRequest


class DigestPipelineError(RuntimeError):
    """Raised when a digest run cannot be completed."""


DEFAULT_FULL_ANALYSIS_CHUNK_SIZE = 5


@dataclass(frozen=True)
class _ChunkAnalysisResult:
    analyses: dict[str, AnalysisResult]
    error_messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class _BoundedAnalysisResult:
    analyses: dict[str, AnalysisResult]
    unresolved_articles: list[Article]
    error_messages: tuple[str, ...]


def run_digest(
    *,
    db: Database,
    source: SourceAdapter | None,
    analyzer: LLMAnalyzer | None,
    source_request: SourceRunRequest[Any] | None = None,
    profile_id: int | None = None,
    date_selection: DateSelection | None = None,
    run_origin: RunOrigin = RunOrigin.LEGACY,
    now: datetime | None = None,
    preselector: AbstractPreselector | None = None,
    analysis_chunk_size: int = DEFAULT_FULL_ANALYSIS_CHUNK_SIZE,
) -> DigestResult:
    """Fetch, store, analyze, filter, rank, and return one digest run."""

    profile = _select_profile(db, profile_id)
    active_source_request = source_request
    if active_source_request is None:
        arxiv_config = db.get_arxiv_config()
        if arxiv_config is None:
            raise DigestPipelineError("source configuration is missing")
        if source is None:
            raise DigestPipelineError("source adapter is missing")
        active_source_request = SourceRunRequest(
            source_name=SOURCE_ARXIV,
            adapter=source,
            config=arxiv_config,
        )

    profile_fingerprint = profile_semantic_fingerprint(profile)
    source_fingerprint = (
        source_config_semantic_fingerprint(active_source_request.config)
        if isinstance(active_source_request.config, ArxivSourceConfig)
        else None
    )
    run_id = db.create_app_run(
        profile_id=profile.id,
        profile_fingerprint=profile_fingerprint,
        source_name=active_source_request.source_name,
        source_fingerprint=source_fingerprint,
        run_origin=run_origin,
        date_selection=date_selection,
    )
    db.mark_app_run_running(run_id)
    started_at = utc_now()
    retrieved_count = 0
    stored_count = 0
    preselected_count = 0
    skipped_analysis_count = 0
    analyzed_count = 0
    new_analysis_count = 0
    reused_analysis_count = 0
    above_threshold_count = 0
    all_items: list[DigestItem] = []
    skipped_articles: list[Article] = []
    unresolved_articles: list[Article] = []
    preselection_decisions: list[AbstractPreselectionDecision] = []
    status = APP_RUN_COMPLETED
    error_message: str | None = None
    requested_source_dates: tuple[str, ...] = (
        tuple(value.isoformat() for value in date_selection.selected_dates())
        if date_selection is not None
        else ()
    )
    covered_source_dates: tuple[str, ...] = ()
    empty_source_dates: tuple[str, ...] = ()
    incomplete_source_dates: tuple[str, ...] = ()
    retrieval_complete = date_selection is None
    retrieval_returned = date_selection is None
    retrieval_safety_limit: int | None = None

    try:
        if date_selection is None:
            fetched = active_source_request.adapter.fetch(active_source_request.config, now=now)
        else:
            if not isinstance(active_source_request.adapter, DateNativeSourceAdapter):
                raise DigestPipelineError("source adapter does not support date selection")
            retrieval = active_source_request.adapter.fetch_date_selection(
                active_source_request.config,
                date_selection,
            )
            retrieval_returned = True
            fetched = list(retrieval.articles)
            requested_source_dates = tuple(value.isoformat() for value in retrieval.requested_dates)
            covered_source_dates = tuple(value.isoformat() for value in retrieval.covered_dates)
            empty_source_dates = tuple(value.isoformat() for value in retrieval.empty_dates)
            incomplete_source_dates = tuple(
                value.isoformat() for value in retrieval.incomplete_dates
            )
            retrieval_complete = bool(retrieval.complete)
            retrieval_safety_limit = int(retrieval.safety_limit)
            if not requested_source_dates:
                article_dates = {
                    source_date_from_datetime(article.published_at).isoformat()
                    for article in fetched
                }
                requested_source_dates = tuple(sorted(article_dates))
                covered_source_dates = requested_source_dates
        retrieved_count = len(fetched)
        saved_articles, stored_count = db.upsert_articles(fetched)
        saved_articles = _unique_articles(saved_articles)
        db.update_app_run_progress(
            run_id,
            progress_stage="retrieval",
            retrieved_count=retrieved_count,
            stored_count=stored_count,
            progress_message=f"Retrieved {retrieved_count} paper(s).",
        )

        active_preselector = preselector or TermOverlapPreselector()
        analyses_by_key: dict[str, AnalysisResult] = {}
        origins_by_key: dict[str, AnalysisOrigin] = {}
        missing_articles: list[Article] = []
        article_by_key = {article_analysis_key(article): article for article in saved_articles}
        for article in saved_articles:
            if article.id is None or profile.id is None:
                raise DigestPipelineError("saved articles and profiles must have ids")
            key = article_analysis_key(article)
            analysis = db.get_analysis(
                article_id=article.id,
                profile_id=profile.id,
                profile_fingerprint=profile_fingerprint,
            )
            if analysis is None:
                missing_articles.append(article)
            else:
                analyses_by_key[key] = analysis
                origins_by_key[key] = AnalysisOrigin.REUSED
                preselection_decisions.append(
                    reused_analysis_preselection_decision(
                        article=article,
                        profile=profile,
                        preselection_fraction=active_preselector.preselection_fraction,
                        preselector_version=active_preselector.preselector_version,
                    )
                )

        analysis_candidates = missing_articles
        if missing_articles and analyzer is not None:
            try:
                preselection = active_preselector.preselect(
                    profile=profile,
                    articles=missing_articles,
                )
            except Exception as exc:
                preselection = fail_open_preselection_result(
                    profile=profile,
                    articles=missing_articles,
                    preselection_fraction=active_preselector.preselection_fraction,
                    preselector_version=active_preselector.preselector_version,
                    reason=f"Model preselection failed: {sanitize_error(exc)}",
                )
            preselection_decisions.extend(preselection.decisions)
            selected_ids = preselection.selected_ids
            analysis_candidates = [
                article
                for article in missing_articles
                if article_analysis_key(article) in selected_ids
            ]
            preselected_count = preselection.selected_count
            skipped_analysis_count = preselection.skipped_count
            skipped_articles = [
                article
                for article in missing_articles
                if article_analysis_key(article) not in selected_ids
            ]
            db.update_app_run_progress(
                run_id,
                progress_stage="preselection",
                retrieved_count=retrieved_count,
                stored_count=stored_count,
                preselected_count=preselected_count,
                skipped_analysis_count=skipped_analysis_count,
                progress_message=(
                    f"Preselected {preselected_count} of {len(missing_articles)} "
                    "cache-miss paper(s)."
                ),
            )
            if profile.id is None:
                raise DigestPipelineError("profile id is required for preselection persistence")
            db.save_preselection_decisions(
                run_id=run_id,
                profile_id=profile.id,
                profile_fingerprint=profile_fingerprint,
                source_name=active_source_request.source_name,
                source_fingerprint=source_fingerprint,
                article_by_key=article_by_key,
                decisions=preselection_decisions,
            )
        elif preselection_decisions and profile.id is not None:
            db.save_preselection_decisions(
                run_id=run_id,
                profile_id=profile.id,
                profile_fingerprint=profile_fingerprint,
                source_name=active_source_request.source_name,
                source_fingerprint=source_fingerprint,
                article_by_key=article_by_key,
                decisions=preselection_decisions,
            )

        if analysis_candidates and analyzer is not None:
            bounded = _analyze_candidates_with_bounded_retries(
                db=db,
                analyzer=analyzer,
                profile=profile,
                profile_fingerprint=profile_fingerprint,
                articles=analysis_candidates,
                chunk_size=analysis_chunk_size,
                run_id=run_id,
            )
            for key, analysis in bounded.analyses.items():
                analyses_by_key[key] = analysis
                origins_by_key[key] = AnalysisOrigin.NEW_THIS_RUN
            unresolved_articles = bounded.unresolved_articles
        elif missing_articles and analyzer is None:
            unresolved_articles = list(missing_articles)

        for article in saved_articles:
            key = article_analysis_key(article)
            analysis = analyses_by_key.get(key)
            if analysis is None:
                continue
            origin = origins_by_key.get(key)
            if origin is None:
                raise DigestPipelineError("analysis origin is missing for analyzed article")
            all_items.append(
                DigestItem(article=article, analysis=analysis, analysis_origin=origin)
            )

        all_items = sorted_digest_items(all_items)
        analyzed_count = len(all_items)
        new_analysis_count = sum(
            item.analysis_origin == AnalysisOrigin.NEW_THIS_RUN for item in all_items
        )
        reused_analysis_count = sum(
            item.analysis_origin == AnalysisOrigin.REUSED for item in all_items
        )
        above_threshold_count = sum(
            is_above_threshold(item, profile.relevance_threshold) for item in all_items
        )
        db.update_app_run_progress(
            run_id,
            progress_stage="analysis",
            analyzed_count=analyzed_count,
            relevant_count=above_threshold_count,
            progress_message=(
                f"Analysis available for {analyzed_count} paper(s); "
                f"{above_threshold_count} above threshold."
            ),
        )
        analysis_complete = not unresolved_articles
        if unresolved_articles:
            status = APP_RUN_PARTIAL if analyzed_count else APP_RUN_ANALYSIS_UNAVAILABLE
            error_message = _unresolved_analysis_message(unresolved_articles)
        elif analyzer is None and retrieved_count > 0:
            status = APP_RUN_ANALYSIS_UNAVAILABLE
        completed_at = utc_now()
        db.finish_app_run(
            run_id,
            status=status,
            retrieved_count=retrieved_count,
            stored_count=stored_count,
            preselected_count=preselected_count,
            skipped_analysis_count=skipped_analysis_count,
            analyzed_count=analyzed_count,
            relevant_count=above_threshold_count,
            requested_source_dates=requested_source_dates,
            covered_source_dates=covered_source_dates,
            empty_source_dates=empty_source_dates,
            incomplete_source_dates=incomplete_source_dates,
            retrieval_complete=retrieval_complete,
            retrieval_safety_limit=retrieval_safety_limit,
            error_message=error_message,
        )
        return DigestResult(
            run_id=run_id,
            profile=profile,
            source_config=active_source_request.config,
            retrieved_count=retrieved_count,
            stored_count=stored_count,
            preselected_count=preselected_count,
            skipped_analysis_count=skipped_analysis_count,
            analyzed_count=analyzed_count,
            new_analysis_count=new_analysis_count,
            reused_analysis_count=reused_analysis_count,
            above_threshold_count=above_threshold_count,
            analysis_available=analyzer is not None or retrieved_count == 0,
            items=all_items,
            started_at=started_at,
            completed_at=completed_at,
            analysis_complete=analysis_complete,
            skipped_articles=skipped_articles,
            unresolved_articles=unresolved_articles,
            run_status=status,
            error_message=error_message,
            run_origin=run_origin,
            date_selection=date_selection,
            requested_source_dates=_source_date_tuple(requested_source_dates),
            covered_source_dates=_source_date_tuple(covered_source_dates),
            empty_source_dates=_source_date_tuple(empty_source_dates),
            incomplete_source_dates=_source_date_tuple(incomplete_source_dates),
            retrieval_complete=retrieval_complete,
            retrieval_safety_limit=retrieval_safety_limit,
            preselection_evidence=_preselection_evidence_tuple(preselection_decisions),
        )
    except BaseException as exc:
        error_message = (
            "Digest interrupted before completion."
            if isinstance(exc, (KeyboardInterrupt, SystemExit))
            else sanitize_error(exc)
        )
        current_run = db.get_app_run(run_id)
        if current_run is not None:
            retrieved_count = max(retrieved_count, int(current_run["retrieved_count"]))
            stored_count = max(stored_count, int(current_run["stored_count"]))
            preselected_count = max(preselected_count, int(current_run["preselected_count"]))
            skipped_analysis_count = max(
                skipped_analysis_count,
                int(current_run["skipped_analysis_count"]),
            )
            analyzed_count = max(analyzed_count, int(current_run["analyzed_count"]))
            above_threshold_count = max(above_threshold_count, int(current_run["relevant_count"]))
        failed_incomplete_dates = incomplete_source_dates
        if date_selection is not None and not retrieval_returned:
            failed_incomplete_dates = requested_source_dates
        failed_retrieval_complete = retrieval_complete
        if date_selection is not None and not retrieval_returned:
            failed_retrieval_complete = False
        db.finish_app_run(
            run_id,
            status=APP_RUN_FAILED,
            retrieved_count=retrieved_count,
            stored_count=stored_count,
            preselected_count=preselected_count,
            skipped_analysis_count=skipped_analysis_count,
            analyzed_count=analyzed_count,
            relevant_count=above_threshold_count,
            error_message=error_message,
            requested_source_dates=requested_source_dates,
            covered_source_dates=covered_source_dates,
            empty_source_dates=empty_source_dates,
            incomplete_source_dates=failed_incomplete_dates,
            retrieval_complete=failed_retrieval_complete,
            retrieval_safety_limit=retrieval_safety_limit,
        )
        raise


def _source_date_tuple(values: tuple[str, ...]) -> tuple[date, ...]:
    return tuple(date.fromisoformat(value) for value in values)


def _preselection_evidence_tuple(
    decisions: Sequence[AbstractPreselectionDecision],
) -> tuple[PreselectionEvidence, ...]:
    return tuple(
        PreselectionEvidence(
            article_id=decision.article_id,
            preselection_score=decision.preselection_score,
            preselection_threshold=decision.preselection_threshold,
            passed=decision.selected,
            stage=decision.stage,
            decision_origin=decision.decision_origin,
            preselector_version=decision.preselector_version,
            reason=decision.reason or None,
        )
        for decision in decisions
    )


def _select_profile(db: Database, profile_id: int | None) -> InterestProfile:
    if profile_id is not None:
        profile = db.get_interest_profile(profile_id)
        if profile is None:
            raise DigestPipelineError(f"interest profile {profile_id} does not exist")
        if not profile.enabled:
            raise DigestPipelineError(f"interest profile {profile_id} is disabled")
        return profile

    enabled_profiles = db.list_interest_profiles(enabled_only=True)
    if not enabled_profiles:
        raise DigestPipelineError("create and enable an interest profile before running a digest")
    return enabled_profiles[0]


def _unique_articles(articles: list[Article]) -> list[Article]:
    seen: set[str] = set()
    unique: list[Article] = []
    for article in articles:
        key = article_analysis_key(article)
        if key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


def _analyze_candidates_with_bounded_retries(
    *,
    db: Database,
    analyzer: LLMAnalyzer,
    profile: InterestProfile,
    profile_fingerprint: str,
    articles: Sequence[Article],
    chunk_size: int,
    run_id: int,
) -> _BoundedAnalysisResult:
    if chunk_size <= 0:
        raise DigestPipelineError("analysis chunk size must be positive")
    if profile.id is None:
        raise DigestPipelineError("profile id is required for analysis persistence")

    remaining = list(articles)
    analyses: dict[str, AnalysisResult] = {}
    error_messages: list[str] = []
    total = len(remaining)
    for active_chunk_size in _analysis_retry_chunk_sizes(chunk_size):
        if not remaining:
            break
        next_remaining: list[Article] = []
        chunks = _chunks(remaining, active_chunk_size)
        for chunk_index, chunk in enumerate(chunks, start=1):
            db.update_app_run_progress(
                run_id,
                progress_stage="analysis",
                analyzed_count=len(analyses),
                progress_message=(
                    f"Full analysis {len(analyses)} / {total}; "
                    f"Codex batch {chunk_index} / {len(chunks)} "
                    f"(size {active_chunk_size})."
                ),
            )
            chunk_result = _analyze_chunk(analyzer=analyzer, profile=profile, articles=chunk)
            error_messages.extend(chunk_result.error_messages)
            for article in chunk:
                key = article_analysis_key(article)
                analysis = chunk_result.analyses.get(key)
                if analysis is None:
                    next_remaining.append(article)
                    continue
                if article.id is None:
                    raise DigestPipelineError("saved article is missing an id")
                db.upsert_analysis(
                    article_id=article.id,
                    profile_id=profile.id,
                    profile_fingerprint=profile_fingerprint,
                    analysis=analysis,
                )
                analyses[key] = analysis
            db.update_app_run_progress(
                run_id,
                progress_stage="analysis",
                analyzed_count=len(analyses),
                progress_message=f"Full analysis {len(analyses)} / {total}.",
            )
        remaining = next_remaining
    return _BoundedAnalysisResult(
        analyses=analyses,
        unresolved_articles=remaining,
        error_messages=tuple(error_messages),
    )


def _analysis_retry_chunk_sizes(chunk_size: int) -> tuple[int, ...]:
    sizes = [chunk_size, max(1, chunk_size // 2), 1]
    unique: list[int] = []
    for size in sizes:
        if size not in unique:
            unique.append(size)
    return tuple(unique)


def _chunks(values: Sequence[Article], size: int) -> list[list[Article]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def _analyze_chunk(
    *,
    analyzer: LLMAnalyzer,
    profile: InterestProfile,
    articles: Sequence[Article],
) -> _ChunkAnalysisResult:
    try:
        results = analyzer.analyze_many(profile=profile, articles=articles)
    except Exception as exc:
        return _ChunkAnalysisResult(analyses={}, error_messages=(sanitize_error(exc),))
    return _validate_analyzer_results(articles, results)


def _validate_analyzer_results(
    articles: Sequence[Article],
    results: object,
) -> _ChunkAnalysisResult:
    if not isinstance(results, Mapping):
        return _ChunkAnalysisResult(
            analyses={},
            error_messages=("analyzer returned a non-mapping batch result",),
        )
    requested_ids = {article_analysis_key(article) for article in articles}
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    analyses: dict[str, AnalysisResult] = {}
    errors: list[str] = []
    for raw_key, raw_analysis in results.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            errors.append("analyzer returned analysis with a missing article id")
            continue
        key = raw_key.strip()
        if key in seen_ids:
            duplicate_ids.add(key)
            analyses.pop(key, None)
            errors.append(f"analyzer returned duplicate analysis for {key}")
            continue
        seen_ids.add(key)
        if key not in requested_ids:
            errors.append(f"analyzer returned unknown article id {key}")
            continue
        if not isinstance(raw_analysis, AnalysisResult):
            errors.append(f"analyzer returned invalid analysis for {key}")
            continue
        analyses[key] = raw_analysis
    for key in duplicate_ids:
        analyses.pop(key, None)
    return _ChunkAnalysisResult(analyses=analyses, error_messages=tuple(errors))


def _unresolved_analysis_message(articles: Sequence[Article]) -> str:
    identifiers = ", ".join(article_analysis_key(article) for article in articles[:10])
    suffix = "" if len(articles) <= 10 else f", and {len(articles) - 10} more"
    return f"Analysis unavailable for {len(articles)} paper(s): {identifiers}{suffix}"
