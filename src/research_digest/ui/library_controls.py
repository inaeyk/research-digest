"""Shared Streamlit controls for saved Library membership."""

from __future__ import annotations

import hashlib

from research_digest.db import Database
from research_digest.library import (
    is_article_saved,
    is_source_article_saved,
    save_article_by_source_identity_with_personal_interest,
    save_article_with_personal_interest,
    unsave_article,
    unsave_article_by_source_identity,
)
from research_digest.models import Article, InterestProfile
from research_digest.ui.abstracts import ArticleIdentity


def library_button_key(identity: ArticleIdentity, *, context: str) -> str:
    digest = _identity_digest(identity)
    context_digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:12]
    return f"article_library_toggle_{context_digest}_{digest}"


def library_button_label(saved: bool) -> str:
    return "Remove from Library" if saved else "Save to Library"


def render_library_control(
    *,
    db: Database,
    article: Article,
    context: str,
    profile: InterestProfile | None = None,
    profile_fingerprint_value: str | None = None,
) -> None:
    import streamlit as st

    if article.id is None:
        st.caption("Save unavailable until this paper is stored.")
        return
    identity = ArticleIdentity(
        source=article.source,
        source_article_id=article.source_article_id,
    )
    saved = is_article_saved(db, article.id)
    if st.button(
        library_button_label(saved),
        key=library_button_key(identity, context=context),
        icon=":material/bookmark_remove:" if saved else ":material/bookmark_add:",
    ):
        if saved:
            unsave_article(db, article.id)
            st.toast("Removed from Library.", icon=":material/bookmark_remove:")
        else:
            save_article_with_personal_interest(
                db=db,
                article_id=article.id,
                profile=profile,
                profile_fingerprint_value=profile_fingerprint_value,
            )
            st.toast("Saved to Library.", icon=":material/bookmark_add:")
        st.rerun()


def render_library_control_for_source_identity(
    *,
    db: Database,
    source: str,
    source_article_id: str,
    context: str,
    profile: InterestProfile | None = None,
    profile_fingerprint_value: str | None = None,
) -> None:
    import streamlit as st

    identity = ArticleIdentity(source=source, source_article_id=source_article_id)
    saved = is_source_article_saved(
        db,
        source=identity.source,
        source_article_id=identity.source_article_id,
    )
    if st.button(
        library_button_label(saved),
        key=library_button_key(identity, context=context),
        icon=":material/bookmark_remove:" if saved else ":material/bookmark_add:",
    ):
        if saved:
            changed = unsave_article_by_source_identity(
                db,
                source=identity.source,
                source_article_id=identity.source_article_id,
            )
            if changed:
                st.toast("Removed from Library.", icon=":material/bookmark_remove:")
            else:
                st.warning("This historical paper could not be found in Articles.")
        else:
            entry = save_article_by_source_identity_with_personal_interest(
                db,
                source=identity.source,
                source_article_id=identity.source_article_id,
                profile=profile,
                profile_fingerprint_value=profile_fingerprint_value,
            )
            if entry is None:
                st.warning("This historical paper could not be found in Articles.")
            else:
                st.toast("Saved to Library.", icon=":material/bookmark_add:")
        st.rerun()


def _identity_digest(identity: ArticleIdentity) -> str:
    raw = f"{identity.source}\0{identity.source_article_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]
