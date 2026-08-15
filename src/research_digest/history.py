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
                "title": item.article.title,
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
