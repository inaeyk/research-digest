"""Scientific relationship suggestions among saved Library papers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from research_digest.db import Database
from research_digest.library_search import search_tokens
from research_digest.models import (
    Article,
    ConnectionOrigin,
    LibraryConnection,
    LibraryRelevanceContext,
    datetime_to_db,
    utc_now,
)

LIBRARY_CONNECTION_PROMPT_VERSION = "library_connections_v1"
DEFAULT_MAX_CONNECTION_CANDIDATES = 5
DEFAULT_MAX_CONNECTION_SUGGESTIONS = 5


@dataclass(frozen=True)
class ConnectionCandidate:
    article: Article
    score: float
    evidence: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class LibraryConnectionSuggestion:
    candidate_id: str
    relation_label: str
    rationale: str
    confidence: float | None = None


@dataclass(frozen=True)
class LibraryConnectionGeneration:
    suggestions: tuple[LibraryConnectionSuggestion, ...]
    provenance: dict[str, object]


class LibraryConnectionGenerator(Protocol):
    def suggest_connections(
        self,
        *,
        target: Article,
        candidates: Sequence[ConnectionCandidate],
        relevance_context: LibraryRelevanceContext | None,
        max_suggestions: int = DEFAULT_MAX_CONNECTION_SUGGESTIONS,
    ) -> LibraryConnectionGeneration:
        """Suggest scientific relationships to bounded saved candidate papers."""


@dataclass(frozen=True)
class RelatedLibraryConnection:
    connection: LibraryConnection
    related_article: Article


def article_candidate_id(article: Article) -> str:
    return f"{article.source}:{article.source_article_id}"


def select_connection_candidates(
    db: Database,
    *,
    article_id: int,
    max_candidates: int = DEFAULT_MAX_CONNECTION_CANDIDATES,
) -> list[ConnectionCandidate]:
    if max_candidates <= 0:
        raise ValueError("max candidates must be positive")
    target_entry = db.get_library_entry(article_id)
    if target_entry is None:
        raise ValueError("connection candidates require a saved Library article")
    target_features = _article_features(db, target_entry.article)
    candidates: list[ConnectionCandidate] = []
    for entry in db.list_saved_library_entries():
        candidate = entry.article
        if candidate.id is None or candidate.id == article_id:
            continue
        scored = _score_candidate(target_features, _article_features(db, candidate))
        if scored.score > 0:
            candidates.append(
                ConnectionCandidate(
                    article=candidate,
                    score=scored.score,
                    evidence=scored.evidence,
                )
            )
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.score,
            -candidate.article.published_at.timestamp(),
            candidate.article.source,
            candidate.article.source_article_id,
        ),
    )[:max_candidates]


def list_related_connections(db: Database, *, article_id: int) -> list[RelatedLibraryConnection]:
    if db.get_library_entry(article_id) is None:
        return []
    related: list[RelatedLibraryConnection] = []
    for connection in db.list_library_connections_for_article(article_id):
        related_id = (
            connection.article_id_b
            if connection.article_id_a == article_id
            else connection.article_id_a
        )
        if db.get_library_entry(related_id) is None:
            continue
        article = db.get_article(related_id)
        if article is not None:
            related.append(RelatedLibraryConnection(connection=connection, related_article=article))
    return related


def dismiss_connection(db: Database, *, article_id: int, related_article_id: int) -> None:
    db.dismiss_library_connection(article_id_a=article_id, article_id_b=related_article_id)


def generate_connections_for_saved_article(
    db: Database,
    *,
    article_id: int,
    generator: LibraryConnectionGenerator,
    max_candidates: int = DEFAULT_MAX_CONNECTION_CANDIDATES,
    max_suggestions: int = DEFAULT_MAX_CONNECTION_SUGGESTIONS,
    regenerate: bool = False,
) -> list[LibraryConnection]:
    if max_suggestions <= 0:
        raise ValueError("max suggestions must be positive")
    entry = db.get_library_entry(article_id)
    if entry is None:
        raise ValueError("connections can only be generated for saved Library articles")
    candidates = [
        candidate
        for candidate in select_connection_candidates(
            db,
            article_id=article_id,
            max_candidates=max_candidates,
        )
        if _candidate_is_eligible(db, article_id, candidate, regenerate=regenerate)
    ]
    if not candidates:
        return []
    relevance_context = db.get_latest_relevance_context(article_id)
    generation = generator.suggest_connections(
        target=entry.article,
        candidates=candidates,
        relevance_context=relevance_context,
        max_suggestions=max_suggestions,
    )
    return assign_connection_suggestions(
        db,
        article_id=article_id,
        candidates=candidates,
        suggestions=generation.suggestions,
        provenance=_complete_connection_provenance(
            generation.provenance,
            target=entry.article,
            candidates=candidates,
            relevance_context=relevance_context,
        ),
        revive=regenerate,
    )


def assign_connection_suggestions(
    db: Database,
    *,
    article_id: int,
    candidates: Sequence[ConnectionCandidate],
    suggestions: Sequence[LibraryConnectionSuggestion],
    provenance: dict[str, object],
    revive: bool = False,
) -> list[LibraryConnection]:
    by_candidate_id = {
        article_candidate_id(candidate.article): candidate for candidate in candidates
    }
    seen: set[str] = set()
    connections: list[LibraryConnection] = []
    for suggestion in suggestions:
        candidate_key = suggestion.candidate_id.strip()
        if candidate_key in seen:
            raise ValueError(f"duplicate connection suggestion for {candidate_key}")
        seen.add(candidate_key)
        candidate = by_candidate_id.get(candidate_key)
        if candidate is None or candidate.article.id is None:
            raise ValueError(f"unknown connection candidate: {candidate_key}")
        if candidate.article.id == article_id:
            raise ValueError("connection suggestion cannot link an article to itself")
        existing = db.get_library_connection_by_pair(article_id, candidate.article.id)
        if existing is not None and existing.dismissed_at is not None and not revive:
            continue
        connections.append(
            db.upsert_library_connection(
                article_id_a=article_id,
                article_id_b=candidate.article.id,
                relation_label=suggestion.relation_label,
                rationale=suggestion.rationale,
                provenance={
                    **provenance,
                    "candidate_evidence": candidate.evidence,
                    "candidate_score": candidate.score,
                },
                confidence=suggestion.confidence,
                origin=ConnectionOrigin.AI,
                revive=revive,
            )
        )
    return connections


@dataclass(frozen=True)
class _ArticleFeatures:
    tags: frozenset[str]
    tag_labels: dict[str, str]
    categories: frozenset[str]
    collections: frozenset[str]
    collection_labels: dict[str, str]
    tokens: frozenset[str]


@dataclass(frozen=True)
class _ScoredCandidate:
    score: float
    evidence: dict[str, tuple[str, ...]]


def _article_features(db: Database, article: Article) -> _ArticleFeatures:
    article_id = article.id
    tags: set[str] = set()
    tag_labels: dict[str, str] = {}
    collections: set[str] = set()
    collection_labels: dict[str, str] = {}
    text_fields = [article.title, article.abstract, " ".join(article.categories)]
    if article_id is not None:
        for assignment in db.list_library_tag_assignments(article_id):
            tags.add(assignment.tag.normalized_name)
            tag_labels[assignment.tag.normalized_name] = assignment.tag.display_name
        for collection in db.list_library_collections_for_article(article_id):
            collections.add(collection.normalized_name)
            collection_labels[collection.normalized_name] = collection.name
            text_fields.append(collection.name)
            text_fields.append(collection.description)
    return _ArticleFeatures(
        tags=frozenset(tags),
        tag_labels=tag_labels,
        categories=frozenset(category.casefold() for category in article.categories),
        collections=frozenset(collections),
        collection_labels=collection_labels,
        tokens=frozenset(search_tokens(text_fields)),
    )


def _score_candidate(target: _ArticleFeatures, candidate: _ArticleFeatures) -> _ScoredCandidate:
    shared_tags = target.tags & candidate.tags
    shared_categories = target.categories & candidate.categories
    shared_collections = target.collections & candidate.collections
    shared_tokens = target.tokens & candidate.tokens
    evidence = {
        "shared_tags": tuple(sorted(target.tag_labels.get(tag, tag) for tag in shared_tags)),
        "shared_categories": tuple(sorted(shared_categories)),
        "shared_collections": tuple(
            sorted(target.collection_labels.get(name, name) for name in shared_collections)
        ),
        "shared_terms": tuple(sorted(shared_tokens))[:12],
    }
    score = (
        len(shared_tags) * 4.0
        + len(shared_collections) * 3.0
        + len(shared_categories) * 2.0
        + min(len(shared_tokens), 12) * 0.25
    )
    return _ScoredCandidate(score=score, evidence=evidence)


def _candidate_is_eligible(
    db: Database,
    article_id: int,
    candidate: ConnectionCandidate,
    *,
    regenerate: bool,
) -> bool:
    candidate_id = candidate.article.id
    if candidate_id is None:
        return False
    existing = db.get_library_connection_by_pair(article_id, candidate_id)
    if existing is None:
        return True
    if existing.dismissed_at is not None:
        return regenerate
    return regenerate


def _complete_connection_provenance(
    provenance: dict[str, object],
    *,
    target: Article,
    candidates: Sequence[ConnectionCandidate],
    relevance_context: LibraryRelevanceContext | None,
) -> dict[str, object]:
    completed = dict(provenance)
    completed.setdefault("prompt_version", LIBRARY_CONNECTION_PROMPT_VERSION)
    completed.setdefault("generated_at", datetime_to_db(utc_now()))
    completed.setdefault("target", article_candidate_id(target))
    completed.setdefault("candidate_count", len(candidates))
    completed.setdefault("relevance_context_included", relevance_context is not None)
    return completed
