"""Run history query and snapshot helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from research_digest.coverage import source_config_accepted_semantic_fingerprints
from research_digest.db import APP_RUN_CANCELLED, APP_RUN_FAILED, Database
from research_digest.models import (
    AIArtifactRetentionClass,
    AnalysisOrigin,
    AnalysisResult,
    AnalysisSummaryReference,
    AnalysisSummaryStorage,
    Article,
    DateSelection,
    DigestItem,
    DigestResult,
    PreselectionEvidence,
    RunOrigin,
    datetime_from_db,
    profile_semantic_fingerprint,
    utc_now,
)
from research_digest.synthesis import CrossPaperSynthesis


@dataclass(frozen=True)
class RunHistoryEntry:
    run_id: int
    profile_id: int | None
    source_name: str
    started_at: str
    completed_at: str | None
    status: str
    retrieved_count: int
    stored_count: int
    preselected_count: int
    skipped_analysis_count: int
    analyzed_count: int
    relevant_count: int
    error_message: str | None
    has_snapshot: bool
    run_origin: str
    date_selection: dict[str, Any] | None
    requested_source_dates: tuple[str, ...]
    covered_source_dates: tuple[str, ...]
    empty_source_dates: tuple[str, ...]
    incomplete_source_dates: tuple[str, ...]
    retrieval_complete: bool
    retrieval_safety_limit: int | None


SUMMARY_EXPIRED_MESSAGE = "AI summary expired under retention policy."


@dataclass(frozen=True)
class SnapshotSummaryDisplay:
    content: str | None
    unavailable: bool = False


def build_run_snapshot(
    *,
    digest: DigestResult,
    synthesis: CrossPaperSynthesis,
    summary_references: Mapping[int, AnalysisSummaryReference] | None = None,
) -> dict[str, Any]:
    references = summary_references or {}
    return {
        "run_id": digest.run_id,
        "profile_id": digest.profile.id,
        "profile_name": digest.profile.name,
        "source": "arxiv",
        "retrieved_count": digest.retrieved_count,
        "stored_count": digest.stored_count,
        "preselected_count": digest.preselected_count,
        "skipped_analysis_count": digest.skipped_analysis_count,
        "analyzed_count": digest.analyzed_count,
        "relevant_count": digest.relevant_count,
        "analysis_available": digest.analysis_available,
        "analysis_complete": digest.analysis_complete,
        "run_status": digest.run_status,
        "run_origin": digest.run_origin.value,
        "date_selection": (
            digest.date_selection.to_mapping() if digest.date_selection is not None else None
        ),
        "requested_source_dates": [value.isoformat() for value in digest.requested_source_dates],
        "covered_source_dates": [value.isoformat() for value in digest.covered_source_dates],
        "empty_source_dates": [value.isoformat() for value in digest.empty_source_dates],
        "incomplete_source_dates": [value.isoformat() for value in digest.incomplete_source_dates],
        "retrieval_complete": digest.retrieval_complete,
        "retrieval_safety_limit": digest.retrieval_safety_limit,
        "preselection_decisions": [
            {
                "article_id": evidence.article_id,
                "preselection_score": evidence.preselection_score,
                "preselection_threshold": evidence.preselection_threshold,
                "passed": evidence.passed,
                "stage": evidence.stage,
                "decision_origin": evidence.decision_origin,
                "preselector_version": evidence.preselector_version,
                "reason": evidence.reason,
            }
            for evidence in digest.preselection_evidence
        ],
        "started_at": digest.started_at.isoformat(),
        "completed_at": digest.completed_at.isoformat() if digest.completed_at else None,
        "synthesis": {
            "analyzed_count": synthesis.analyzed_count,
            "relevant_count": synthesis.relevant_count,
            "recurring_topics": [
                {
                    "topic": topic.topic,
                    "paper_count": topic.paper_count,
                    "paper_titles": list(topic.paper_titles),
                }
                for topic in synthesis.recurring_topics
            ],
            "high_priority_titles": list(synthesis.high_priority_titles),
            "category_counts": list(synthesis.category_counts),
        },
        "items": [
            {
                "source_article_id": item.article.source_article_id,
                "source": item.article.source,
                "title": item.article.title,
                "authors": list(item.article.authors),
                "abstract": item.article.abstract,
                "categories": list(item.article.categories),
                "abstract_url": item.article.abstract_url,
                "published_at": item.article.published_at.isoformat(),
                "relevance_score": item.analysis.relevance_score,
                "summary_reference": _snapshot_summary_reference(
                    references.get(item.article.id or 0)
                ),
                "why_it_matters": item.analysis.why_it_matters,
                "reading_priority": item.analysis.reading_priority,
                "analysis_origin": item.analysis_origin.value,
            }
            for item in digest.items
        ],
        "skipped_articles": [
            {
                "source": article.source,
                "source_article_id": article.source_article_id,
                "title": article.title,
                "authors": list(article.authors),
                "abstract": article.abstract,
                "categories": list(article.categories),
                "abstract_url": article.abstract_url,
                "published_at": article.published_at.isoformat(),
            }
            for article in digest.skipped_articles
        ],
        "unresolved_articles": [
            {
                "source": article.source,
                "source_article_id": article.source_article_id,
                "title": article.title,
                "authors": list(article.authors),
                "abstract": article.abstract,
                "categories": list(article.categories),
                "abstract_url": article.abstract_url,
                "published_at": article.published_at.isoformat(),
            }
            for article in digest.unresolved_articles
        ],
    }


def persist_run_snapshot(
    *,
    db: Database,
    digest: DigestResult,
    synthesis: CrossPaperSynthesis,
) -> None:
    if digest.profile.id is None:
        raise ValueError("digest profile id is required for summary references")
    references = db.list_analysis_summary_references(
        article_ids=(item.article.id for item in digest.items if item.article.id is not None),
        profile_id=digest.profile.id,
        profile_fingerprint=profile_semantic_fingerprint(digest.profile),
    )
    db.save_run_snapshot(
        run_id=digest.run_id,
        snapshot_json=json.dumps(
            build_run_snapshot(
                digest=digest,
                synthesis=synthesis,
                summary_references=references,
            ),
            sort_keys=True,
        ),
    )


def resolve_snapshot_summaries(
    db: Database,
    payload: object,
    *,
    now: datetime | None = None,
) -> tuple[SnapshotSummaryDisplay, ...]:
    """Resolve legacy prose or new references in at most two batched reads."""

    if not isinstance(payload, list):
        return ()
    artifact_ids: set[int] = set()
    legacy_analysis_ids: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        reference = item.get("summary_reference")
        if not isinstance(reference, dict):
            continue
        kind = reference.get("kind")
        reference_id = reference.get("artifact_id" if kind == "artifact" else "analysis_id")
        if not isinstance(reference_id, int) or reference_id <= 0:
            continue
        if kind == "artifact":
            artifact_ids.add(reference_id)
        elif kind == "legacy_analysis":
            legacy_analysis_ids.add(reference_id)
    artifacts = db.get_ai_artifacts_by_ids(artifact_ids)
    legacy_summaries = db.get_legacy_analysis_summaries(legacy_analysis_ids)
    effective_now = now or utc_now()
    displays: list[SnapshotSummaryDisplay] = []
    for item in payload:
        if not isinstance(item, dict):
            displays.append(SnapshotSummaryDisplay(content=None))
            continue
        inline = item.get("summary")
        if isinstance(inline, str) and inline.strip():
            displays.append(SnapshotSummaryDisplay(content=inline))
            continue
        reference = item.get("summary_reference")
        if not isinstance(reference, dict):
            displays.append(SnapshotSummaryDisplay(content=None))
            continue
        if reference.get("kind") == "artifact":
            artifact_id = reference.get("artifact_id")
            artifact = artifacts.get(artifact_id) if isinstance(artifact_id, int) else None
            if artifact is None or (
                artifact.retention_class == AIArtifactRetentionClass.TEMPORARY
                and artifact.expires_at is not None
                and artifact.expires_at < effective_now
            ):
                displays.append(
                    SnapshotSummaryDisplay(
                        content=SUMMARY_EXPIRED_MESSAGE,
                        unavailable=True,
                    )
                )
            else:
                displays.append(SnapshotSummaryDisplay(content=artifact.content))
            continue
        if reference.get("kind") == "legacy_analysis":
            analysis_id = reference.get("analysis_id")
            content = legacy_summaries.get(analysis_id) if isinstance(analysis_id, int) else None
            displays.append(
                SnapshotSummaryDisplay(
                    content=content or "AI summary unavailable.",
                    unavailable=content is None,
                )
            )
            continue
        displays.append(SnapshotSummaryDisplay(content=None))
    return tuple(displays)


def _snapshot_summary_reference(
    reference: AnalysisSummaryReference | None,
) -> dict[str, object] | None:
    if reference is None:
        return None
    if reference.storage == AnalysisSummaryStorage.ARTIFACT:
        return {
            "kind": "artifact",
            "artifact_id": reference.artifact_id,
            "created_at": reference.analyzed_at.isoformat(),
            "provider": reference.provider,
            "model_id": reference.model_id,
            "reasoning_effort": reference.reasoning_effort,
            "generator_version": reference.generator_version,
        }
    return {
        "kind": "legacy_analysis",
        "analysis_id": reference.analysis_id,
        "analyzed_at": reference.analyzed_at.isoformat(),
    }


def list_run_history(db: Database, *, limit: int = 25) -> list[RunHistoryEntry]:
    if limit <= 0:
        raise ValueError("history limit must be positive")
    rows = db.get_app_runs()[:limit]
    entries: list[RunHistoryEntry] = []
    for row in rows:
        entries.append(
            RunHistoryEntry(
                run_id=int(row["id"]),
                profile_id=int(row["profile_id"]) if row["profile_id"] is not None else None,
                source_name=str(row["source_name"]),
                started_at=_format_history_time(str(row["started_at"])),
                completed_at=(
                    _format_history_time(str(row["completed_at"]))
                    if row["completed_at"] is not None
                    else None
                ),
                status=str(row["status"]),
                retrieved_count=int(row["retrieved_count"]),
                stored_count=int(row["stored_count"]),
                preselected_count=int(row["preselected_count"]),
                skipped_analysis_count=int(row["skipped_analysis_count"]),
                analyzed_count=int(row["analyzed_count"]),
                relevant_count=int(row["relevant_count"]),
                error_message=str(row["error_message"]) if row["error_message"] else None,
                has_snapshot=db.get_run_snapshot(run_id=int(row["id"])) is not None,
                run_origin=str(row["run_origin"]),
                date_selection=_optional_json_object(row["date_selection_json"]),
                requested_source_dates=_json_string_tuple(row["requested_source_dates_json"]),
                covered_source_dates=_json_string_tuple(row["covered_source_dates_json"]),
                empty_source_dates=_json_string_tuple(row["empty_source_dates_json"]),
                incomplete_source_dates=_json_string_tuple(row["incomplete_source_dates_json"]),
                retrieval_complete=bool(row["retrieval_complete"]),
                retrieval_safety_limit=(
                    int(row["retrieval_safety_limit"])
                    if row["retrieval_safety_limit"] is not None
                    else None
                ),
            )
        )
    return entries


def get_run_snapshot(db: Database, *, run_id: int) -> dict[str, Any] | None:
    row = db.get_run_snapshot(run_id=run_id)
    if row is None:
        return None
    payload = json.loads(str(row["snapshot_json"]))
    if not isinstance(payload, dict):
        raise ValueError("run snapshot must be a JSON object")
    return payload


def reconstruct_digest_result(db: Database, *, run_id: int) -> DigestResult | None:
    """Rebuild a completed UI result from durable run, corpus, and analysis state."""

    row = db.get_app_run(run_id)
    snapshot = get_run_snapshot(db, run_id=run_id)
    if row is None or snapshot is None or row["completed_at"] is None:
        return None
    if str(row["status"]) in {APP_RUN_CANCELLED, APP_RUN_FAILED}:
        return None
    if row["profile_id"] is None or row["profile_fingerprint"] is None:
        return None
    profile_id = int(row["profile_id"])
    profile = db.get_interest_profile(profile_id)
    source_config = db.get_arxiv_config()
    if profile is None or source_config is None:
        return None
    profile_fingerprint = str(row["profile_fingerprint"])
    if profile_fingerprint != profile_semantic_fingerprint(profile):
        return None
    if row["source_fingerprint"] is not None and str(row["source_fingerprint"]) not in set(
        source_config_accepted_semantic_fingerprints(source_config)
    ):
        return None
    items = _snapshot_digest_items(
        db,
        snapshot.get("items"),
        profile_id=profile_id,
        profile_fingerprint=profile_fingerprint,
    )
    skipped = _snapshot_articles(db, snapshot.get("skipped_articles"))
    unresolved = _snapshot_articles(db, snapshot.get("unresolved_articles"))
    selection_payload = _optional_json_object(row["date_selection_json"])
    selection = DateSelection.from_mapping(selection_payload) if selection_payload else None
    return DigestResult(
        run_id=run_id,
        profile=profile,
        source_config=source_config,
        retrieved_count=int(row["retrieved_count"]),
        stored_count=int(row["stored_count"]),
        preselected_count=int(row["preselected_count"]),
        skipped_analysis_count=int(row["skipped_analysis_count"]),
        analyzed_count=int(row["analyzed_count"]),
        new_analysis_count=sum(
            item.analysis_origin == AnalysisOrigin.NEW_THIS_RUN for item in items
        ),
        reused_analysis_count=sum(item.analysis_origin == AnalysisOrigin.REUSED for item in items),
        above_threshold_count=int(row["relevant_count"]),
        analysis_available=bool(snapshot.get("analysis_available", True)),
        items=items,
        started_at=datetime_from_db(str(row["started_at"])),
        completed_at=datetime_from_db(str(row["completed_at"])),
        analysis_complete=bool(snapshot.get("analysis_complete", True)),
        skipped_articles=skipped,
        unresolved_articles=unresolved,
        run_status=str(row["status"]),
        error_message=str(row["error_message"]) if row["error_message"] else None,
        run_origin=RunOrigin(str(row["run_origin"])),
        date_selection=selection,
        requested_source_dates=_date_tuple(row["requested_source_dates_json"]),
        covered_source_dates=_date_tuple(row["covered_source_dates_json"]),
        empty_source_dates=_date_tuple(row["empty_source_dates_json"]),
        incomplete_source_dates=_date_tuple(row["incomplete_source_dates_json"]),
        retrieval_complete=bool(row["retrieval_complete"]),
        retrieval_safety_limit=(
            int(row["retrieval_safety_limit"])
            if row["retrieval_safety_limit"] is not None
            else None
        ),
        preselection_evidence=_snapshot_preselection_evidence(
            snapshot.get("preselection_decisions")
        ),
    )


def _snapshot_digest_items(
    db: Database,
    payload: object,
    *,
    profile_id: int,
    profile_fingerprint: str,
) -> list[DigestItem]:
    if not isinstance(payload, list):
        return []
    items: list[DigestItem] = []
    summary_displays = resolve_snapshot_summaries(db, payload)
    for item_index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        article = _snapshot_article(db, item)
        if article is None or article.id is None:
            continue
        analysis = db.get_analysis(
            article_id=article.id,
            profile_id=profile_id,
            profile_fingerprint=profile_fingerprint,
        )
        summary_display = summary_displays[item_index]
        analysis = _snapshot_history_analysis(
            item,
            summary_display,
            fallback=analysis,
        )
        if analysis is None:
            continue
        try:
            origin = AnalysisOrigin(str(item.get("analysis_origin", "REUSED")))
        except ValueError:
            origin = AnalysisOrigin.REUSED
        items.append(DigestItem(article=article, analysis=analysis, analysis_origin=origin))
    return items


def _snapshot_history_analysis(
    item: dict[str, object],
    summary: SnapshotSummaryDisplay,
    *,
    fallback: AnalysisResult | None,
) -> AnalysisResult | None:
    if summary.content is None:
        return fallback
    score = item.get("relevance_score")
    priority = item.get("reading_priority")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if priority not in {"LOW", "MEDIUM", "HIGH"}:
        return None
    why_it_matters = item.get("why_it_matters")
    return AnalysisResult(
        relevance_score=float(score),
        relevance_reason=(
            fallback.relevance_reason
            if fallback is not None
            else "Historical analysis facts retained; detailed explanation unavailable."
        ),
        matched_topics=list(fallback.matched_topics) if fallback is not None else [],
        summary=summary.content,
        why_it_matters=(
            why_it_matters
            if isinstance(why_it_matters, str) and why_it_matters.strip()
            else "Historical relevance judgment retained."
        ),
        reading_priority=priority,
    )


def _snapshot_articles(db: Database, payload: object) -> list[Article]:
    if not isinstance(payload, list):
        return []
    return [
        article
        for item in payload
        if isinstance(item, dict) and (article := _snapshot_article(db, item)) is not None
    ]


def _snapshot_article(db: Database, payload: dict[str, object]) -> Article | None:
    source = payload.get("source")
    source_article_id = payload.get("source_article_id")
    if not isinstance(source, str) or not isinstance(source_article_id, str):
        return None
    return db.get_article_by_source_id(source, source_article_id)


def _snapshot_preselection_evidence(payload: object) -> tuple[PreselectionEvidence, ...]:
    if not isinstance(payload, list):
        return ()
    evidence: list[PreselectionEvidence] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        article_id = item.get("article_id")
        if not isinstance(article_id, str):
            continue
        evidence.append(
            PreselectionEvidence(
                article_id=article_id,
                preselection_score=_optional_float(item.get("preselection_score")),
                preselection_threshold=_optional_float(item.get("preselection_threshold")),
                passed=bool(item.get("passed")),
                stage=str(item.get("stage", "unknown")),
                decision_origin=str(item.get("decision_origin", "unknown")),
                preselector_version=str(item.get("preselector_version", "unknown")),
                reason=str(item["reason"]) if item.get("reason") is not None else None,
            )
        )
    return tuple(evidence)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _date_tuple(value: object) -> tuple[date, ...]:
    return tuple(date.fromisoformat(item) for item in _json_string_tuple(value))


def _format_history_time(value: str) -> str:
    return datetime_from_db(value).strftime("%Y-%m-%d %H:%M:%S UTC")


def _json_string_tuple(value: object) -> tuple[str, ...]:
    payload = json.loads(str(value))
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError("history date metadata must be a JSON string list")
    return tuple(payload)


def _optional_json_object(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = json.loads(str(value))
    if not isinstance(payload, dict):
        raise ValueError("history date selection metadata must be a JSON object")
    return payload
