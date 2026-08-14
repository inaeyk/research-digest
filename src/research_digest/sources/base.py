"""Source adapter abstractions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from research_digest.models import Article, ArxivSourceConfig


class SourceError(RuntimeError):
    """Raised when a source adapter cannot retrieve or parse articles."""


class SourceAdapter(Protocol):
    def fetch(self, config: ArxivSourceConfig, *, now: datetime | None = None) -> list[Article]:
        """Fetch normalized articles for the supplied source configuration."""
