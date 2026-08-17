"""Digest orchestration service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from research_digest.analysis.base import AnalyzerError, LLMAnalyzer, article_analysis_key
from research_digest.db import (
    APP_RUN_ANALYSIS_UNAVAILABLE,
    APP_RUN_COMPLETED,
    APP_RUN_FAILED,
    SOURCE_ARXIV,
    Database,
)
from research_digest.errors import sanitize_error
from research_digest.models import (
    AnalysisOrigin,
    AnalysisResult,
    Article,
    DateSelection,
    DigestItem,
    DigestResult,
    InterestProfile,
    RunOrigin,
    is_above_threshold,
    profile_semantic_fingerprint,
    sorted_digest_items,
    source_date_from_datetime,
    utc_now,
)
from research_digest.preselection import AbstractPreselector, TermOverlapPreselector
from research_digest.sources.base import DateNativeSourceAdapter, SourceAdapter
from research_digest.sources.registry import SourceRunRequest


class DigestPipelineError(RuntimeError):
    """Raised when a digest run cannot be completed."""


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
    run_id = db.create_app_run(
        profile_id=profile.id,
        source_name=active_source_request.source_name,
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

        analyses_by_key: dict[str, AnalysisResult] = {}
        origins_by_key: dict[str, AnalysisOrigin] = {}
        missing_articles: list[Article] = []
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

        analysis_candidates = missing_articles
        if missing_articles and analyzer is not None:
            active_preselector = preselector or TermOverlapPreselector()
            preselection = active_preselector.preselect(profile=profile, articles=missing_articles)
            selected_ids = preselection.selected_ids
            analysis_candidates = [
                article
                for article in missing_articles
                if article_analysis_key(article) in selected_ids
            ]
            preselected_count = preselection.selected_count
            skipped_analysis_count = preselection.skipped_count

        if analysis_candidates and analyzer is not None:
            new_analyses = analyzer.analyze_many(profile=profile, articles=analysis_candidates)
            _validate_analyzer_results(analysis_candidates, new_analyses)
            for article in analysis_candidates:
                if article.id is None or profile.id is None:
                    raise DigestPipelineError("saved articles and profiles must have ids")
                key = article_analysis_key(article)
                analysis = new_analyses[key]
                db.upsert_analysis(
                    article_id=article.id,
                    profile_id=profile.id,
                    profile_fingerprint=profile_fingerprint,
                    analysis=analysis,
                )
                analyses_by_key[key] = analysis
                origins_by_key[key] = AnalysisOrigin.NEW_THIS_RUN

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
        if analyzer is None:
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
            analysis_available=analyzer is not None,
            items=all_items,
            started_at=started_at,
            completed_at=completed_at,
            run_origin=run_origin,
            date_selection=date_selection,
            requested_source_dates=_source_date_tuple(requested_source_dates),
            covered_source_dates=_source_date_tuple(covered_source_dates),
            empty_source_dates=_source_date_tuple(empty_source_dates),
            incomplete_source_dates=_source_date_tuple(incomplete_source_dates),
            retrieval_complete=retrieval_complete,
            retrieval_safety_limit=retrieval_safety_limit,
        )
    except Exception as exc:
        error_message = sanitize_error(exc)
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


def _validate_analyzer_results(
    articles: list[Article],
    results: object,
) -> None:
    if not isinstance(results, Mapping):
        raise AnalyzerError("analyzer returned a non-mapping batch result")
    requested_ids = {article_analysis_key(article) for article in articles}
    returned_ids = set(results.keys())
    missing_ids = requested_ids - returned_ids
    unknown_ids = returned_ids - requested_ids
    if missing_ids:
        raise AnalyzerError(
            "analyzer did not return analysis for: " + ", ".join(sorted(missing_ids))
        )
    if unknown_ids:
        raise AnalyzerError(
            "analyzer returned analysis for unknown articles: " + ", ".join(sorted(unknown_ids))
        )
