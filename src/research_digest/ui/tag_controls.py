"""Shared UI helper functions for Library tag controls."""

from __future__ import annotations

import hashlib

from research_digest.models import TagOrigin


def tag_action_key(
    *,
    article_id: int,
    action: str,
    origin: TagOrigin,
    normalized_name: str | None = None,
) -> str:
    if article_id <= 0:
        raise ValueError("article id must be positive")
    raw = f"{article_id}\0{action}\0{origin.value}\0{normalized_name or ''}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"library_tag_{action}_{digest}"


def ai_tag_generation_label(*, has_ai_tags: bool) -> str:
    return "Regenerate AI tags" if has_ai_tags else "Generate AI tags"


def collection_action_key(
    *,
    action: str,
    collection_id: int | None = None,
    article_id: int | None = None,
    suffix: str = "",
) -> str:
    raw = f"{action}\0{collection_id or ''}\0{article_id or ''}\0{suffix}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"library_collection_{action}_{digest}"


def connection_action_key(
    *,
    action: str,
    article_id: int,
    related_article_id: int | None = None,
) -> str:
    if article_id <= 0:
        raise ValueError("article id must be positive")
    raw = f"{action}\0{article_id}\0{related_article_id or ''}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"library_connection_{action}_{digest}"


def context_action_key(
    *,
    action: str,
    article_id: int,
    suggestion_id: int | None = None,
) -> str:
    if article_id <= 0:
        raise ValueError("article id must be positive")
    raw = f"{action}\0{article_id}\0{suggestion_id or ''}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"library_context_{action}_{digest}"


def collection_intelligence_action_key(
    *,
    action: str,
    collection_id: int,
    snapshot_id: int | None = None,
) -> str:
    if collection_id <= 0:
        raise ValueError("collection id must be positive")
    raw = f"{action}\0{collection_id}\0{snapshot_id or ''}".encode()
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"collection_intelligence_{action}_{digest}"
