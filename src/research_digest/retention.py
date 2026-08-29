"""Named retention policy for replaceable AI-derived artifacts."""

from __future__ import annotations

from datetime import datetime, timedelta

from research_digest.models import ensure_utc

DEFAULT_TEMPORARY_AI_ARTIFACT_RETENTION = timedelta(days=90)


def temporary_artifact_expiration(
    started_at: datetime,
    *,
    retention_period: timedelta = DEFAULT_TEMPORARY_AI_ARTIFACT_RETENTION,
) -> datetime:
    """Return the deterministic expiration for a temporary derived artifact."""

    if retention_period <= timedelta(0):
        raise ValueError("temporary AI artifact retention period must be positive")
    return ensure_utc(started_at) + retention_period
