"""Digest orchestration service."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from research_digest.analysis.base import AnalyzerError, LLMAnalyzer, article_analysis_key
from research_digest.db import SOURCE_ARXIV, Database
from research_digest.errors import sanitize_error
from research_digest.models import (
    AnalysisOrigin,
    AnalysisResult,
    Article,
    DigestItem,
    DigestResult,
    InterestProfile,
    is_above_threshold,
    profile_semantic_fingerprint,
    sorted_digest_items,
    utc_now,
)
from research_digest.sources.base import SourceAdapter


class DigestPipelineError(RuntimeError):
    """Raised when a digest run cannot be completed."""


def run_digest(
    *,
    db: Database,
    source: SourceAdapter,
    analyzer: LLMAnalyzer | None,
    profile_id: int | None = None,
    now: datetime | None = None,
) -> DigestResult:
    """Fetch, store, analyze, filter, rank, and return one digest run."""

    profile = _select_profile(db, profile_id)
    source_config = db.get_arxiv_config()
    if source_config is None:
        raise DigestPipelineError("arXiv source configuration is missing")

    profile_fingerprint = profile_semantic_fingerprint(profile)
    run_id = db.create_app_run(profile_id=profile.id, source_name=SOURCE_ARXIV)
    started_at = utc_now()
    retrieved_count = 0
    stored_count = 0
    analyzed_count = 0
    new_analysis_count = 0
    reused_analysis_count = 0
    above_threshold_count = 0
    all_items: list[DigestItem] = []
    status = "success"
    error_message: str | None = None

    try:
        fetched = source.fetch(source_config, now=now)
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

        if missing_articles and analyzer is not None:
            new_analyses = analyzer.analyze_many(profile=profile, articles=missing_articles)
            _validate_analyzer_results(missing_articles, new_analyses)
            for article in missing_articles:
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
            status = "analysis_unavailable"
        completed_at = utc_now()
        db.finish_app_run(
            run_id,
            status=status,
            retrieved_count=retrieved_count,
            stored_count=stored_count,
            analyzed_count=analyzed_count,
            relevant_count=above_threshold_count,
        )
        return DigestResult(
            run_id=run_id,
            profile=profile,
            source_config=source_config,
            retrieved_count=retrieved_count,
            stored_count=stored_count,
            analyzed_count=analyzed_count,
            new_analysis_count=new_analysis_count,
            reused_analysis_count=reused_analysis_count,
            above_threshold_count=above_threshold_count,
            analysis_available=analyzer is not None,
            items=all_items,
            started_at=started_at,
            completed_at=completed_at,
        )
    except Exception as exc:
        error_message = sanitize_error(exc)
        db.finish_app_run(
            run_id,
            status="failed",
            retrieved_count=retrieved_count,
            stored_count=stored_count,
            analyzed_count=analyzed_count,
            relevant_count=above_threshold_count,
            error_message=error_message,
        )
        raise


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
