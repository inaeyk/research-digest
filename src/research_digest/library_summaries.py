"""Lazy, model-neutral Library summary generation and retention service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from research_digest.ai_providers import LibrarySummaryProvider
from research_digest.db import Database
from research_digest.models import (
    AIArtifact,
    AIArtifactProvenance,
    AIArtifactType,
    Article,
)

MAX_LIBRARY_SUMMARY_INPUT_BYTES = 64 * 1024
MAX_LIBRARY_SUMMARY_OUTPUT_BYTES = 8 * 1024


class LibrarySummaryError(RuntimeError):
    """Raised when an explicit Library summary cannot be generated safely."""


@dataclass(frozen=True)
class LibrarySummaryGenerationResult:
    artifact: AIArtifact
    reused: bool
    provider_called: bool


def build_library_summary_context(article: Article) -> str:
    """Serialize the bounded authoritative source context supplied to a provider."""

    context = json.dumps(
        {
            "title": article.title,
            "authors": list(article.authors),
            "abstract": article.abstract,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    size = len(context.encode("utf-8"))
    if size > MAX_LIBRARY_SUMMARY_INPUT_BYTES:
        raise LibrarySummaryError(
            "The stored title, authors, and abstract are too large for one bounded Library summary."
        )
    return context


def library_summary_input_fingerprint(context: str) -> str:
    return hashlib.sha256(context.encode("utf-8")).hexdigest()


def generate_library_summary(
    db: Database,
    *,
    article_id: int,
    provider: LibrarySummaryProvider,
    regenerate: bool = False,
    now: datetime | None = None,
) -> LibrarySummaryGenerationResult:
    """Generate only on explicit invocation and atomically install the result."""

    article = db.get_article(article_id)
    if article is None:
        raise LibrarySummaryError("The paper no longer exists in the local corpus.")
    if db.get_library_entry(article_id) is None:
        raise LibrarySummaryError("Library summary generation requires a saved paper.")
    context = build_library_summary_context(article)
    fingerprint = library_summary_input_fingerprint(context)
    provenance = _provider_provenance(provider, input_fingerprint=fingerprint)

    if not regenerate:
        compatible = db.get_compatible_ai_artifact(
            article_id=article_id,
            artifact_type=AIArtifactType.LIBRARY_SUMMARY,
            provider=provenance.provider,
            model_id=provenance.model_id,
            generator_version=provenance.generator_version,
            input_fingerprint=provenance.input_fingerprint,
            now=now,
        )
        if compatible is not None:
            retained, _ = db.persist_library_summary(
                article_id=article_id,
                content=compatible.content,
                provenance=provenance,
                regenerate=False,
                created_at=now,
            )
            return LibrarySummaryGenerationResult(
                artifact=retained,
                reused=True,
                provider_called=False,
            )

    generated = provider.generate_summary(article=article, context=context)
    generated_provenance = AIArtifactProvenance(
        provider=generated.provider,
        model_id=generated.model_id,
        reasoning_effort=generated.reasoning_effort,
        generator_version=generated.generator_version,
        input_fingerprint=generated.input_fingerprint,
    )
    if generated_provenance != provenance:
        raise LibrarySummaryError(
            "The summary provider returned provenance that did not match the requested policy."
        )
    if len(generated.content.encode("utf-8")) > MAX_LIBRARY_SUMMARY_OUTPUT_BYTES:
        raise LibrarySummaryError("The generated Library summary exceeded its output limit.")
    artifact, reused = db.persist_library_summary(
        article_id=article_id,
        content=generated.content,
        provenance=provenance,
        regenerate=regenerate,
        created_at=now,
    )
    return LibrarySummaryGenerationResult(
        artifact=artifact,
        reused=reused,
        provider_called=True,
    )


def _provider_provenance(
    provider: LibrarySummaryProvider,
    *,
    input_fingerprint: str,
) -> AIArtifactProvenance:
    return AIArtifactProvenance(
        provider=provider.provider,
        model_id=provider.model_id,
        reasoning_effort=provider.reasoning_effort,
        generator_version=provider.generator_version,
        input_fingerprint=input_fingerprint,
    )
