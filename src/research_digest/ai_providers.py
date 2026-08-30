"""Narrow, model-neutral provider boundaries for later Library AI stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from research_digest.models import Article


@dataclass(frozen=True)
class GeneratedAIText:
    """Provider output plus provenance required by the artifact store."""

    content: str
    provider: str
    model_id: str
    reasoning_effort: str | None
    generator_version: str
    input_fingerprint: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("generated AI text content is required")
        for label, value in (
            ("provider", self.provider),
            ("model id", self.model_id),
            ("generator version", self.generator_version),
            ("input fingerprint", self.input_fingerprint),
        ):
            if not value.strip():
                raise ValueError(f"generated AI text {label} is required")


class LibrarySummaryProvider(Protocol):
    provider: str
    model_id: str
    reasoning_effort: str | None
    generator_version: str

    def generate_summary(
        self,
        *,
        article: Article,
        context: str,
    ) -> GeneratedAIText:
        """Generate one explicit Library summary request."""


class ResearchConversationProvider(Protocol):
    provider: str
    model_id: str
    reasoning_effort: str | None
    timeout_seconds: float
    response_generator_version: str
    summary_generator_version: str

    def respond(
        self,
        *,
        article: Article,
        context: str,
    ) -> GeneratedAIText:
        """Generate one explicit conversation response."""

    def summarize_conversation(
        self,
        *,
        article: Article,
        context: str,
    ) -> GeneratedAIText:
        """Compress bounded older turns without replacing the full transcript."""
