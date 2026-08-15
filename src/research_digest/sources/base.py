"""Source adapter abstractions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, TypeVar

from research_digest.models import Article

SourceConfigT = TypeVar("SourceConfigT", contravariant=True)


class SourceError(RuntimeError):
    """Raised when a source adapter cannot retrieve or parse articles."""


class TypedSourceAdapter(Protocol[SourceConfigT]):
    def fetch(self, config: SourceConfigT, *, now: datetime | None = None) -> list[Article]:
        """Fetch normalized articles for the supplied source configuration."""


SourceAdapter = TypedSourceAdapter[Any]
