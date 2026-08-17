"""Shared Streamlit helpers for article abstract display."""

from __future__ import annotations

import hashlib
from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ArticleIdentity:
    source: str
    source_article_id: str

    def __post_init__(self) -> None:
        source = self.source.strip()
        source_article_id = self.source_article_id.strip()
        if not source:
            source = "unknown"
        if not source_article_id:
            source_article_id = "unknown"
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_article_id", source_article_id)


def abstract_state_key(identity: ArticleIdentity) -> str:
    digest = _identity_digest(identity)
    return f"article_abstract_visible_{digest}"


def abstract_button_key(identity: ArticleIdentity, *, context: str) -> str:
    digest = _identity_digest(identity)
    context_digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:12]
    return f"article_abstract_toggle_{context_digest}_{digest}"


def abstract_is_visible(
    state: MutableMapping[str, object],
    identity: ArticleIdentity,
) -> bool:
    return bool(state.get(abstract_state_key(identity), False))


def toggle_abstract_visibility(
    state: MutableMapping[str, object],
    identity: ArticleIdentity,
) -> bool:
    key = abstract_state_key(identity)
    visible = not bool(state.get(key, False))
    state[key] = visible
    return visible


def abstract_toggle_label(visible: bool) -> str:
    return "Hide abstract" if visible else "Show abstract"


def displayable_abstract(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    abstract = value.strip()
    return abstract or None


def render_abstract_control(
    *,
    source: str,
    source_article_id: str,
    abstract: object,
    context: str,
) -> None:
    import streamlit as st

    identity = ArticleIdentity(source=source, source_article_id=source_article_id)
    visible = abstract_is_visible(st.session_state, identity)
    if st.button(
        abstract_toggle_label(visible),
        key=abstract_button_key(identity, context=context),
        icon=":material/visibility_off:" if visible else ":material/visibility:",
    ):
        visible = toggle_abstract_visibility(st.session_state, identity)
    if not visible:
        return
    display_text = displayable_abstract(abstract)
    if display_text is None:
        st.caption("Abstract unavailable")
        return
    st.text(display_text)


def _identity_digest(identity: ArticleIdentity) -> str:
    raw = f"{identity.source}\0{identity.source_article_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
