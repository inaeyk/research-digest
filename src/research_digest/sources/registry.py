"""Source adapter registry for additive source support."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from research_digest.db import Database
from research_digest.models import ArxivSourceConfig
from research_digest.sources.arxiv import ArxivSource
from research_digest.sources.base import TypedSourceAdapter

SourceConfigT = TypeVar("SourceConfigT")


@dataclass(frozen=True)
class SourceDefinition(Generic[SourceConfigT]):
    name: str
    adapter_factory: Callable[[], TypedSourceAdapter[SourceConfigT]]
    config_loader: Callable[[Database], SourceConfigT | None]

    def build_adapter(self) -> TypedSourceAdapter[SourceConfigT]:
        return self.adapter_factory()

    def load_config(self, db: Database) -> SourceConfigT | None:
        return self.config_loader(db)


@dataclass(frozen=True)
class SourceRunRequest(Generic[SourceConfigT]):
    source_name: str
    adapter: TypedSourceAdapter[SourceConfigT]
    config: SourceConfigT


class SourceRegistry:
    """Small explicit registry for first-party source definitions."""

    def __init__(self, definitions: Iterable[SourceDefinition[Any]] = ()) -> None:
        self._definitions: dict[str, SourceDefinition[Any]] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: SourceDefinition[Any]) -> None:
        if not definition.name.strip():
            raise ValueError("source definition name is required")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> SourceDefinition[Any] | None:
        return self._definitions.get(name)

    def require(self, name: str) -> SourceDefinition[Any]:
        definition = self.get(name)
        if definition is None:
            raise KeyError(f"unsupported source: {name}")
        return definition

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


ARXIV_SOURCE_DEFINITION = SourceDefinition[ArxivSourceConfig](
    name="arxiv",
    adapter_factory=ArxivSource,
    config_loader=lambda db: db.get_arxiv_config(),
)


def build_default_source_registry() -> SourceRegistry:
    return SourceRegistry((ARXIV_SOURCE_DEFINITION,))
