"""Source adapter abstractions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

from research_digest.models import Article, DateSelection

SourceConfigT = TypeVar("SourceConfigT", contravariant=True)


class SourceError(RuntimeError):
    """Raised when a source adapter cannot retrieve or parse articles."""


class TypedSourceAdapter(Protocol[SourceConfigT]):
    def fetch(self, config: SourceConfigT, *, now: datetime | None = None) -> list[Article]:
        """Fetch normalized articles for the supplied source configuration."""


@runtime_checkable
class DateNativeSourceAdapter(Protocol[SourceConfigT]):
    def fetch_date_selection(
        self,
        config: SourceConfigT,
        selection: DateSelection,
    ) -> Any:
        """Fetch normalized articles and coverage metadata for source dates."""


@runtime_checkable
class LatestAvailableDateResolver(Protocol[SourceConfigT]):
    def resolve_latest_available_date(self, config: SourceConfigT) -> date | None:
        """Return the latest source date with eligible material, if one exists."""


SourceAdapter = TypedSourceAdapter[Any]
