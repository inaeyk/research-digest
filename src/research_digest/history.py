"""Run history query and snapshot helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from research_digest.db import Database
from research_digest.models import DigestResult, datetime_from_db
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


def build_run_snapshot(
    *,
    digest: DigestResult,
    synthesis: CrossPaperSynthesis,
) -> dict[str, Any]:
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
        "incomplete_source_dates": [
            value.isoformat() for value in digest.incomplete_source_dates
        ],
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
                "abstract": item.article.abstract,
                "abstract_url": item.article.abstract_url,
                "published_at": item.article.published_at.isoformat(),
                "relevance_score": item.analysis.relevance_score,
                "summary": item.analysis.summary,
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
                "abstract": article.abstract,
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
                "abstract": article.abstract,
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
    db.save_run_snapshot(
        run_id=digest.run_id,
        snapshot_json=json.dumps(
            build_run_snapshot(digest=digest, synthesis=synthesis),
            sort_keys=True,
        ),
    )


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
