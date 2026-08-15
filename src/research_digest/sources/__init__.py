"""Source adapters."""

from research_digest.sources.arxiv import ArxivSource
from research_digest.sources.base import SourceAdapter, SourceError, TypedSourceAdapter
from research_digest.sources.registry import (
    ARXIV_SOURCE_DEFINITION,
    SourceDefinition,
    SourceRegistry,
    SourceRunRequest,
    build_default_source_registry,
)

__all__ = [
    "ARXIV_SOURCE_DEFINITION",
    "ArxivSource",
    "SourceAdapter",
    "SourceDefinition",
    "SourceError",
    "SourceRegistry",
    "SourceRunRequest",
    "TypedSourceAdapter",
    "build_default_source_registry",
]
