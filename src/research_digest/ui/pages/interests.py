"""Interest profile management page."""

from __future__ import annotations

from research_digest.errors import sanitize_error
from research_digest.models import InterestProfile, ModelValidationError
from research_digest.ui.common import get_database


def render() -> None:
    import streamlit as st

    st.title("Interests")
    db = get_database()
    profiles = db.list_interest_profiles()

    if profiles:
        st.dataframe(
            [
                {
                    "Name": profile.name,
                    "Enabled": profile.enabled,
                    "Threshold": profile.relevance_threshold,
                }
                for profile in profiles
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No interest profiles have been created yet.")

    with st.expander("Create profile", expanded=not profiles), st.form(
        "create_interest_profile"
    ):
        name = st.text_input("Name")
        enabled = st.checkbox("Enabled", value=True)
        threshold = st.slider("Relevance threshold", 0.0, 1.0, 0.6, 0.05)
        description = st.text_area("Description", height=220)
        submitted = st.form_submit_button("Create")
        if submitted:
            try:
                db.create_interest_profile(
                    name=name,
                    description=description,
                    relevance_threshold=threshold,
                    enabled=enabled,
                )
            except ModelValidationError as exc:
                st.error(sanitize_error(exc))
            else:
                st.success("Interest profile created.")
                st.rerun()

    profiles = db.list_interest_profiles()
    if not profiles:
        return

    selected = st.selectbox(
        "Edit profile",
        options=profiles,
        format_func=lambda profile: profile.name,
    )
    with st.form("edit_interest_profile"):
        name = st.text_input("Name", value=selected.name)
        enabled = st.checkbox("Enabled", value=selected.enabled)
        threshold = st.slider(
            "Relevance threshold",
            0.0,
            1.0,
            selected.relevance_threshold,
            0.05,
        )
        description = st.text_area("Description", value=selected.description, height=320)
        submitted = st.form_submit_button("Save")
        if submitted:
            try:
                db.update_interest_profile(
                    InterestProfile(
                        id=selected.id,
                        name=name,
                        description=description,
                        relevance_threshold=threshold,
                        enabled=enabled,
                    )
                )
            except ModelValidationError as exc:
                st.error(sanitize_error(exc))
            else:
                st.success("Interest profile saved.")
                st.rerun()
