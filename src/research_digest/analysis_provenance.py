"""Stable provenance for canonical digest-summary artifacts."""

from __future__ import annotations

import hashlib
import json

from research_digest.models import (
    AIArtifactProvenance,
    Article,
    InterestProfile,
    profile_semantic_payload,
)


def digest_analysis_provenance(
    analyzer: object,
    *,
    profile: InterestProfile,
    article: Article,
) -> AIArtifactProvenance:
    """Describe the provider call without binding persistence to an implementation."""

    provider = _string_attribute(analyzer, "artifact_provider") or (
        f"{type(analyzer).__module__}.{type(analyzer).__qualname__}"
    )
    model_id = (
        _string_attribute(analyzer, "artifact_model_id")
        or _string_attribute(analyzer, "model")
        or "UNAVAILABLE"
    )
    generator_version = (
        _string_attribute(
            analyzer,
            "artifact_generator_version",
        )
        or f"{type(analyzer).__module__}.{type(analyzer).__qualname__}"
    )
    reasoning_effort = _string_attribute(analyzer, "artifact_reasoning_effort")
    fingerprint_payload = {
        "article": {
            "source": article.source,
            "source_article_id": article.source_article_id,
            "title": article.title,
            "authors": list(article.authors),
            "abstract": article.abstract,
            "categories": list(article.categories),
            "published_at": article.published_at.isoformat(),
            "updated_at": article.updated_at.isoformat(),
            "abstract_url": article.abstract_url,
        },
        "profile": profile_semantic_payload(profile),
        "provider": provider,
        "model_id": model_id,
        "generator_version": generator_version,
    }
    serialized = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return AIArtifactProvenance(
        provider=provider,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        generator_version=generator_version,
        input_fingerprint=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )


def _string_attribute(value: object, name: str) -> str | None:
    candidate = getattr(value, name, None)
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    return candidate.strip()
