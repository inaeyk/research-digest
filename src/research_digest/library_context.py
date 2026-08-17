"""Longitudinal Library context for new digest papers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from research_digest.connections import (
    LIBRARY_CONNECTION_PROMPT_VERSION,
    article_candidate_id,
)
from research_digest.db import Database
from research_digest.library_search import search_tokens
from research_digest.models import (
    AnalysisResult,
    Article,
    CollectionIntelligenceSnapshot,
    LibraryCollection,
    LibraryContextOrigin,
    LibraryContextSuggestion,
    datetime_to_db,
    utc_now,
)

LIBRARY_CONTEXT_PROMPT_VERSION = "library_context_v1"
COLLECTION_INTELLIGENCE_PROMPT_VERSION = "collection_intelligence_v1"
DEFAULT_MAX_CONTEXT_CANDIDATES = 5
DEFAULT_MAX_CONTEXT_SUGGESTIONS = 5
DEFAULT_MAX_CONTEXT_COLLECTIONS = 3


@dataclass(frozen=True)
class LibraryContextCandidate:
    article: Article
    score: float
    evidence: dict[str, tuple[str, ...]]
    collections: tuple[LibraryCollection, ...] = ()


@dataclass(frozen=True)
class LibraryContextSuggestionDraft:
    related_candidate_id: str
    collection_id: int | None
    relation_label: str
    rationale: str
    confidence: float | None = None


@dataclass(frozen=True)
class LibraryContextGeneration:
    suggestions: tuple[LibraryContextSuggestionDraft, ...]
    provenance: dict[str, object]


class LibraryContextGenerator(Protocol):
    def suggest_context(
        self,
        *,
        article: Article,
        analysis: AnalysisResult,
        candidates: Sequence[LibraryContextCandidate],
        max_suggestions: int = DEFAULT_MAX_CONTEXT_SUGGESTIONS,
    ) -> LibraryContextGeneration:
        """Suggest bounded Library context for one newly analyzed paper."""


@dataclass(frozen=True)
class DisplayLibraryContextSuggestion:
    suggestion: LibraryContextSuggestion
    related_article: Article
    collection: LibraryCollection | None = None


def select_library_context_candidates(
    db: Database,
    *,
    article: Article,
    analysis: AnalysisResult,
    max_candidates: int = DEFAULT_MAX_CONTEXT_CANDIDATES,
) -> list[LibraryContextCandidate]:
    if max_candidates <= 0:
        raise ValueError("max context candidates must be positive")
    target_features = _context_features_for_new_article(article, analysis)
    candidates: list[LibraryContextCandidate] = []
    for entry in db.list_saved_library_entries():
        saved = entry.article
        if saved.id is None:
            continue
        if article.id is not None and saved.id == article.id:
            continue
        scored = _score_context_candidate(
            target_features,
            _context_features_for_saved_article(db, saved),
        )
        if scored.score <= 0:
            continue
        candidates.append(
            LibraryContextCandidate(
                article=saved,
                score=scored.score,
                evidence=scored.evidence,
                collections=tuple(db.list_library_collections_for_article(saved.id)),
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


def generate_library_context_for_item(
    db: Database,
    *,
    run_id: int | None,
    article: Article,
    analysis: AnalysisResult,
    generator: LibraryContextGenerator,
    max_candidates: int = DEFAULT_MAX_CONTEXT_CANDIDATES,
    max_suggestions: int = DEFAULT_MAX_CONTEXT_SUGGESTIONS,
    regenerate: bool = False,
) -> list[LibraryContextSuggestion]:
    if article.id is None:
        raise ValueError("context suggestions require a saved article id")
    candidates = [
        candidate
        for candidate in select_library_context_candidates(
            db,
            article=article,
            analysis=analysis,
            max_candidates=max_candidates,
        )
        if _context_candidate_is_eligible(
            db,
            article_id=article.id,
            candidate=candidate,
            regenerate=regenerate,
        )
    ]
    if not candidates:
        return []
    generation = generator.suggest_context(
        article=article,
        analysis=analysis,
        candidates=candidates,
        max_suggestions=max_suggestions,
    )
    return assign_library_context_suggestions(
        db,
        run_id=run_id,
        article_id=article.id,
        candidates=candidates,
        suggestions=generation.suggestions,
        provenance=_complete_context_provenance(
            generation.provenance,
            article=article,
            candidates=candidates,
        ),
        revive=regenerate,
    )


def assign_library_context_suggestions(
    db: Database,
    *,
    run_id: int | None,
    article_id: int,
    candidates: Sequence[LibraryContextCandidate],
    suggestions: Sequence[LibraryContextSuggestionDraft],
    provenance: dict[str, object],
    revive: bool = False,
) -> list[LibraryContextSuggestion]:
    by_candidate_id = {
        article_candidate_id(candidate.article): candidate for candidate in candidates
    }
    validated = _validate_context_suggestions(
        article_id=article_id,
        by_candidate_id=by_candidate_id,
        suggestions=suggestions,
    )
    persisted: list[LibraryContextSuggestion] = []
    for suggestion, candidate in validated:
        assert candidate.article.id is not None
        existing = _find_existing_context_suggestion(
            db,
            article_id=article_id,
            related_article_id=candidate.article.id,
            collection_id=suggestion.collection_id,
        )
        if existing is not None and existing.dismissed_at is not None and not revive:
            continue
        persisted.append(
            db.upsert_library_context_suggestion(
                run_id=run_id,
                article_id=article_id,
                related_article_id=candidate.article.id,
                collection_id=suggestion.collection_id,
                relation_label=suggestion.relation_label,
                rationale=suggestion.rationale,
                provenance={
                    **provenance,
                    "candidate_evidence": candidate.evidence,
                    "candidate_score": candidate.score,
                },
                confidence=suggestion.confidence,
                origin=LibraryContextOrigin.AI,
                revive=revive,
            )
        )
    return persisted


def _validate_context_suggestions(
    *,
    article_id: int,
    by_candidate_id: dict[str, LibraryContextCandidate],
    suggestions: Sequence[LibraryContextSuggestionDraft],
) -> list[tuple[LibraryContextSuggestionDraft, LibraryContextCandidate]]:
    seen: set[tuple[str, int | None]] = set()
    validated: list[tuple[LibraryContextSuggestionDraft, LibraryContextCandidate]] = []
    for suggestion in suggestions:
        key = (suggestion.related_candidate_id.strip(), suggestion.collection_id)
        if key in seen:
            raise ValueError(f"duplicate context suggestion for {key[0]}")
        seen.add(key)
        candidate = by_candidate_id.get(key[0])
        if candidate is None or candidate.article.id is None:
            raise ValueError(f"unknown context candidate: {key[0]}")
        if candidate.article.id == article_id:
            raise ValueError("context suggestion cannot link an article to itself")
        if suggestion.collection_id is not None and suggestion.collection_id not in {
            collection.id for collection in candidate.collections
        }:
            raise ValueError("context suggestion returned an unknown collection id")
        validated.append((suggestion, candidate))
    return validated


def list_display_context_suggestions(
    db: Database,
    *,
    article_id: int,
) -> list[DisplayLibraryContextSuggestion]:
    rows: list[DisplayLibraryContextSuggestion] = []
    for suggestion in db.list_library_context_suggestions_for_article(article_id):
        if db.get_library_entry(suggestion.related_article_id) is None:
            continue
        related = db.get_article(suggestion.related_article_id)
        if related is None:
            continue
        collection = (
            db.get_library_collection(suggestion.collection_id)
            if suggestion.collection_id is not None
            else None
        )
        rows.append(
            DisplayLibraryContextSuggestion(
                suggestion=suggestion,
                related_article=related,
                collection=collection,
            )
        )
    return rows


def dismiss_context_suggestion(db: Database, *, suggestion_id: int) -> None:
    db.dismiss_library_context_suggestion(suggestion_id)


def build_collection_intelligence_snapshot(
    db: Database,
    *,
    collection_id: int,
) -> CollectionIntelligenceSnapshot:
    collection = db.get_library_collection(collection_id)
    if collection is None:
        raise ValueError(f"collection {collection_id} does not exist")
    memberships = db.list_library_collection_memberships(collection_id)
    article_ids = [
        membership.article_id
        for membership in memberships
        if db.get_library_entry(membership.article_id) is not None
    ]
    articles = [article for article_id in article_ids if (article := db.get_article(article_id))]
    tag_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    recent_titles: list[str] = []
    for article in sorted(articles, key=lambda item: item.published_at, reverse=True):
        recent_titles.append(article.title)
        for category in article.categories:
            category_counter[category] += 1
        if article.id is None:
            continue
        for assignment in db.list_library_tag_assignments(article.id):
            tag_counter[assignment.tag.display_name] += 1
    evidence: dict[str, object] = {
        "article_count": len(articles),
        "recent_titles": recent_titles[:5],
        "top_tags": tag_counter.most_common(5),
        "top_categories": category_counter.most_common(5),
    }
    if articles:
        summary = _collection_summary(collection, evidence)
    else:
        summary = f"{collection.name} has no saved papers yet."
    return db.save_collection_intelligence_snapshot(
        collection_id=collection_id,
        title=f"{collection.name} snapshot",
        summary=summary,
        evidence=evidence,
        provenance={
            "prompt_version": COLLECTION_INTELLIGENCE_PROMPT_VERSION,
            "provider": "deterministic",
            "generated_at": datetime_to_db(utc_now()),
        },
        origin=LibraryContextOrigin.DETERMINISTIC,
    )


@dataclass(frozen=True)
class _ContextFeatures:
    tags: frozenset[str]
    tag_labels: dict[str, str]
    categories: frozenset[str]
    collections: frozenset[str]
    collection_labels: dict[str, str]
    tokens: frozenset[str]


@dataclass(frozen=True)
class _ScoredContextCandidate:
    score: float
    evidence: dict[str, tuple[str, ...]]


def _context_features_for_new_article(
    article: Article,
    analysis: AnalysisResult,
) -> _ContextFeatures:
    tags = frozenset(topic.casefold() for topic in analysis.matched_topics)
    return _ContextFeatures(
        tags=tags,
        tag_labels={topic.casefold(): topic for topic in analysis.matched_topics},
        categories=frozenset(category.casefold() for category in article.categories),
        collections=frozenset(),
        collection_labels={},
        tokens=frozenset(search_tokens([article.title, article.abstract])),
    )


def _context_features_for_saved_article(db: Database, article: Article) -> _ContextFeatures:
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
    return _ContextFeatures(
        tags=frozenset(tags),
        tag_labels=tag_labels,
        categories=frozenset(category.casefold() for category in article.categories),
        collections=frozenset(collections),
        collection_labels=collection_labels,
        tokens=frozenset(search_tokens(text_fields)),
    )


def _score_context_candidate(
    target: _ContextFeatures,
    candidate: _ContextFeatures,
) -> _ScoredContextCandidate:
    shared_tags = target.tags & candidate.tags
    shared_categories = target.categories & candidate.categories
    shared_tokens = target.tokens & candidate.tokens
    evidence = {
        "shared_tags": tuple(sorted(candidate.tag_labels.get(tag, tag) for tag in shared_tags)),
        "shared_categories": tuple(sorted(shared_categories)),
        "candidate_collections": tuple(
            sorted(candidate.collection_labels.get(name, name) for name in candidate.collections)
        ),
        "shared_terms": tuple(sorted(shared_tokens))[:12],
    }
    score = (
        len(shared_tags) * 4.0
        + len(shared_categories) * 2.0
        + min(len(shared_tokens), 12) * 0.25
        + min(len(candidate.collections), DEFAULT_MAX_CONTEXT_COLLECTIONS) * 0.5
    )
    return _ScoredContextCandidate(score=score, evidence=evidence)


def _context_candidate_is_eligible(
    db: Database,
    *,
    article_id: int,
    candidate: LibraryContextCandidate,
    regenerate: bool,
) -> bool:
    if candidate.article.id is None:
        return False
    existing = _find_existing_context_suggestion(
        db,
        article_id=article_id,
        related_article_id=candidate.article.id,
        collection_id=None,
    )
    if existing is None:
        return True
    return regenerate


def _find_existing_context_suggestion(
    db: Database,
    *,
    article_id: int,
    related_article_id: int,
    collection_id: int | None,
) -> LibraryContextSuggestion | None:
    for suggestion in db.list_library_context_suggestions_for_article(
        article_id,
        include_dismissed=True,
    ):
        if (
            suggestion.related_article_id == related_article_id
            and suggestion.collection_id == collection_id
        ):
            return suggestion
    return None


def _complete_context_provenance(
    provenance: dict[str, object],
    *,
    article: Article,
    candidates: Sequence[LibraryContextCandidate],
) -> dict[str, object]:
    completed = dict(provenance)
    completed.setdefault("prompt_version", LIBRARY_CONTEXT_PROMPT_VERSION)
    completed.setdefault("generated_at", datetime_to_db(utc_now()))
    completed.setdefault("article", article_candidate_id(article))
    completed.setdefault("candidate_count", len(candidates))
    completed.setdefault("connection_prompt_version", LIBRARY_CONNECTION_PROMPT_VERSION)
    return completed


def _collection_summary(collection: LibraryCollection, evidence: dict[str, object]) -> str:
    raw_article_count = evidence.get("article_count")
    article_count = raw_article_count if isinstance(raw_article_count, int) else 0
    top_tags = _first_values(evidence.get("top_tags"))
    top_categories = _first_values(evidence.get("top_categories"))
    pieces = [f"{collection.name} contains {article_count} saved paper(s)."]
    if top_tags:
        pieces.append("Recurring tags: " + ", ".join(top_tags[:3]) + ".")
    if top_categories:
        pieces.append("Common categories: " + ", ".join(top_categories[:3]) + ".")
    return " ".join(pieces)


def _first_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        if (isinstance(item, tuple) and item) or (isinstance(item, list) and item):
            values.append(str(item[0]))
    return values
