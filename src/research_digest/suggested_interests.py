"""Suggested Interest Profile services from explicit new-interest feedback."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from research_digest.db import Database
from research_digest.models import (
    Article,
    InterestProfile,
    SuggestedInterestProfile,
    profile_semantic_fingerprint,
)
from research_digest.tags import list_article_tags

MIN_NEW_INTEREST_EVIDENCE = 3
MAX_NEW_INTEREST_EVIDENCE_SCAN = 200
SuggestionDecision = Literal["created", "dismissed", "not_found"]
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.-]{2,}")
_STOPWORDS = {
    "and",
    "abstract",
    "are",
    "for",
    "from",
    "into",
    "paper",
    "papers",
    "the",
    "this",
    "with",
}


@dataclass(frozen=True)
class NewInterestEvidence:
    article: Article
    tags: tuple[str, ...]


def list_new_interest_evidence(
    db: Database,
    *,
    profile: InterestProfile,
    max_evidence: int = MAX_NEW_INTEREST_EVIDENCE_SCAN,
) -> list[NewInterestEvidence]:
    if profile.id is None:
        return []
    if max_evidence <= 0:
        raise ValueError("max new-interest evidence must be positive")
    fingerprint = profile_semantic_fingerprint(profile)
    rows = db.list_new_interest_feedback(
        profile_id=profile.id,
        profile_fingerprint=fingerprint,
        limit=max_evidence,
    )
    evidence: list[NewInterestEvidence] = []
    for feedback in rows:
        article = db.get_article(feedback.article_id)
        if article is None:
            continue
        tags = list_article_tags(db, article_id=feedback.article_id)
        tag_labels = tuple(
            assignment.tag.display_name for assignment in (*tags.user_tags, *tags.ai_tags)
        )
        evidence.append(NewInterestEvidence(article=article, tags=tag_labels))
    return evidence


def refresh_suggested_interests(
    db: Database,
    *,
    profile: InterestProfile,
    min_evidence: int = MIN_NEW_INTEREST_EVIDENCE,
    max_evidence: int = MAX_NEW_INTEREST_EVIDENCE_SCAN,
) -> list[SuggestedInterestProfile]:
    if profile.id is None:
        return []
    fingerprint = profile_semantic_fingerprint(profile)
    evidence = list_new_interest_evidence(
        db,
        profile=profile,
        max_evidence=max_evidence,
    )
    draft = _build_suggestion_draft(evidence, min_evidence=min_evidence)
    if draft is None:
        return db.list_suggested_interest_profiles(
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
        )
    suggestion_key = _suggestion_key(draft.theme)
    existing = db.list_suggested_interest_profiles(
        profile_id=profile.id,
        profile_fingerprint=fingerprint,
        include_dismissed=True,
    )
    if any(suggestion.suggestion_key == suggestion_key for suggestion in existing):
        return db.list_suggested_interest_profiles(
            profile_id=profile.id,
            profile_fingerprint=fingerprint,
        )
    db.upsert_suggested_interest_profile(
        profile_id=profile.id,
        profile_fingerprint=fingerprint,
        suggested_name=_suggested_name(draft.theme),
        suggested_description=_suggested_description(draft.theme, draft.articles),
        evidence_article_ids=draft.article_ids,
        explanation=(
            f"{len(draft.article_ids)} outside-profile papers share "
            f"{draft.theme_label}."
        ),
        suggestion_key=suggestion_key,
        provenance={
            "origin": "deterministic",
            "min_evidence": min_evidence,
            "theme": draft.theme,
            "theme_label": draft.theme_label,
        },
    )
    return db.list_suggested_interest_profiles(
        profile_id=profile.id,
        profile_fingerprint=fingerprint,
    )


def dismiss_suggested_interest(
    db: Database,
    *,
    suggestion_id: int,
) -> None:
    db.dismiss_suggested_interest_profile(suggestion_id)


def create_profile_from_suggestion(
    db: Database,
    *,
    suggestion_id: int,
    name: str,
    description: str,
) -> InterestProfile:
    suggestion = _find_suggestion(db, suggestion_id=suggestion_id)
    if suggestion is None:
        raise ValueError("suggested interest was not found")
    created = db.create_interest_profile(name=name, description=description)
    if created.id is None:
        raise RuntimeError("created profile is missing an id")
    db.accept_suggested_interest_profile(
        suggestion_id=suggestion_id,
        accepted_profile_id=created.id,
    )
    return created


@dataclass(frozen=True)
class _SuggestionDraft:
    theme: str
    theme_label: str
    articles: tuple[Article, ...]
    article_ids: tuple[int, ...]


def _build_suggestion_draft(
    evidence: list[NewInterestEvidence],
    *,
    min_evidence: int,
) -> _SuggestionDraft | None:
    if len(evidence) < min_evidence:
        return None
    by_key = _coherent_keys(evidence, min_evidence=min_evidence)
    if not by_key:
        return None
    theme, matches = by_key[0]
    if len(matches) < min_evidence:
        return None
    articles = tuple(item.article for item in matches[:8])
    article_ids = tuple(article.id for article in articles if article.id is not None)
    if len(article_ids) < min_evidence:
        return None
    return _SuggestionDraft(
        theme=theme,
        theme_label=theme.replace("category:", "category ").replace("tag:", "tag "),
        articles=articles,
        article_ids=article_ids,
    )


def _coherent_keys(
    evidence: list[NewInterestEvidence],
    *,
    min_evidence: int,
) -> list[tuple[str, list[NewInterestEvidence]]]:
    keys_by_item: list[tuple[NewInterestEvidence, set[str]]] = []
    counts: Counter[str] = Counter()
    for item in evidence:
        keys = {
            f"category:{category.strip()}"
            for category in item.article.categories
            if category.strip()
        }
        keys.update(f"tag:{tag.strip().casefold()}" for tag in item.tags if tag.strip())
        keys.update(f"term:{token}" for token in _article_tokens(item.article))
        keys_by_item.append((item, keys))
        counts.update(keys)
    ranked = sorted(
        ((key, count) for key, count in counts.items() if count >= min_evidence),
        key=lambda item: (-item[1], _key_rank(item[0]), item[0]),
    )
    return [
        (key, [item for item, keys in keys_by_item if key in keys])
        for key, _count in ranked
    ]


def _key_rank(key: str) -> int:
    if key.startswith("tag:"):
        return 0
    if key.startswith("category:"):
        return 1
    return 2


def _article_tokens(article: Article) -> set[str]:
    text = f"{article.title} {article.abstract}"
    return {
        normalized
        for token in _TOKEN_RE.findall(text)
        if (normalized := token.strip(".-").casefold())
        and normalized not in _STOPWORDS
    }


def _suggestion_key(theme: str) -> str:
    return hashlib.sha256(theme.encode("utf-8")).hexdigest()


def _suggested_name(theme: str) -> str:
    if theme.startswith("category:"):
        return f"{theme.removeprefix('category:')} papers"
    if theme.startswith("tag:"):
        return theme.removeprefix("tag:").title()
    return theme.removeprefix("term:").replace("-", " ").title()


def _suggested_description(theme: str, articles: tuple[Article, ...]) -> str:
    titles = "; ".join(article.title for article in articles[:3])
    label = theme.replace("category:", "arXiv category ").replace("tag:", "tag ")
    return f"Follow papers connected by {label}. Evidence examples: {titles}."


def _find_suggestion(
    db: Database,
    *,
    suggestion_id: int,
) -> SuggestedInterestProfile | None:
    for profile in db.list_interest_profiles(enabled_only=False):
        if profile.id is None:
            continue
        for suggestion in db.list_suggested_interest_profiles(
            profile_id=profile.id,
            profile_fingerprint=profile_semantic_fingerprint(profile),
            include_dismissed=True,
        ):
            if suggestion.id == suggestion_id:
                return suggestion
    return None
