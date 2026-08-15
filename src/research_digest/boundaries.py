"""Typed extension boundaries for future additive release work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from research_digest.models import Article, DigestResult
from research_digest.synthesis import CrossPaperSynthesis

ContentKind = Literal["abstract", "full_text"]


@dataclass(frozen=True)
class RetrievedArticleContent:
    article: Article
    content_kind: ContentKind
    text: str
    retrieved_at: datetime


class ContentReader(Protocol):
    def read_content(self, article: Article) -> RetrievedArticleContent:
        """Return deeper content for an existing normalized article."""


class DigestDelivery(Protocol):
    def deliver(
        self,
        *,
        digest: DigestResult,
        synthesis: CrossPaperSynthesis,
    ) -> None:
        """Deliver or export a completed digest without owning pipeline logic."""


class ResearchMemoryStore(Protocol):
    def record_digest(
        self,
        *,
        digest: DigestResult,
        synthesis: CrossPaperSynthesis,
    ) -> None:
        """Observe completed digest outputs for future memory/index services."""
