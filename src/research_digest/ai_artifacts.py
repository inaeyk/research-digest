"""Persistence-only services for replaceable AI-derived article artifacts."""

from __future__ import annotations

from datetime import datetime

from research_digest.db import Database
from research_digest.models import (
    AIArtifact,
    AIArtifactRetentionClass,
    AIArtifactType,
    LibrarySummarySource,
    ResolvedLibrarySummary,
)


def create_artifact(
    db: Database,
    *,
    article_id: int,
    artifact_type: AIArtifactType,
    content: str,
    provider: str,
    model_id: str,
    reasoning_effort: str | None,
    generator_version: str,
    input_fingerprint: str,
    retention_class: AIArtifactRetentionClass = AIArtifactRetentionClass.TEMPORARY,
    created_at: datetime | None = None,
) -> AIArtifact:
    """Persist already-generated content; this function performs no generation."""

    return db.create_ai_artifact(
        article_id=article_id,
        artifact_type=artifact_type,
        content=content,
        provider=provider,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        generator_version=generator_version,
        input_fingerprint=input_fingerprint,
        retention_class=retention_class,
        created_at=created_at,
    )


def create_digest_summary_artifact(
    db: Database,
    *,
    article_id: int,
    content: str,
    provider: str,
    model_id: str,
    reasoning_effort: str | None,
    generator_version: str,
    input_fingerprint: str,
    created_at: datetime | None = None,
) -> AIArtifact:
    """Persist a digest summary under the saved/temporary retention policy."""

    retention_class = (
        AIArtifactRetentionClass.LIBRARY
        if db.get_library_entry(article_id) is not None
        else AIArtifactRetentionClass.TEMPORARY
    )
    return create_artifact(
        db,
        article_id=article_id,
        artifact_type=AIArtifactType.DIGEST_SUMMARY,
        content=content,
        provider=provider,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        generator_version=generator_version,
        input_fingerprint=input_fingerprint,
        retention_class=retention_class,
        created_at=created_at,
    )


def resolve_preferred_library_summary(
    db: Database,
    *,
    article_id: int,
    now: datetime | None = None,
) -> ResolvedLibrarySummary | None:
    """Resolve by deterministic precedence without pointers, copies, or AI work."""

    library_artifact = db.get_latest_usable_ai_artifact(
        article_id=article_id,
        artifact_type=AIArtifactType.LIBRARY_SUMMARY,
        now=now,
    )
    if library_artifact is not None:
        assert library_artifact.id is not None
        return ResolvedLibrarySummary(
            article_id=article_id,
            artifact_id=library_artifact.id,
            content=library_artifact.content,
            source=LibrarySummarySource.LIBRARY_ARTIFACT,
            created_at=library_artifact.created_at,
        )
    digest_artifact = db.get_latest_usable_ai_artifact(
        article_id=article_id,
        artifact_type=AIArtifactType.DIGEST_SUMMARY,
        now=now,
    )
    if digest_artifact is not None:
        assert digest_artifact.id is not None
        return ResolvedLibrarySummary(
            article_id=article_id,
            artifact_id=digest_artifact.id,
            content=digest_artifact.content,
            source=LibrarySummarySource.DIGEST_ARTIFACT,
            created_at=digest_artifact.created_at,
        )
    return db.get_latest_legacy_digest_summary(article_id)


def set_artifact_retention(
    db: Database,
    *,
    artifact_id: int,
    retention_class: AIArtifactRetentionClass,
    effective_at: datetime | None = None,
) -> AIArtifact:
    """Apply an explicit internal retention transition without AI work."""

    return db.set_ai_artifact_retention(
        artifact_id,
        retention_class=retention_class,
        effective_at=effective_at,
    )


def collect_expired_artifacts(db: Database, *, now: datetime | None = None) -> int:
    """Run deterministic artifact garbage collection without scheduling it."""

    return db.collect_expired_ai_artifacts(now=now)
