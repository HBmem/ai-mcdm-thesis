from __future__ import annotations

import streamlit as st

from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    render_page_header,
)
from poli_insight.presentation.streamlit.context import PageContext


def render(context: PageContext) -> None:
    del context
    render_page_header(
        PageHeader(
            eyebrow="Thesis research",
            title="About the Research",
            description=(
                "Poli Insight investigates how structured multi-criteria "
                "decision methods and carefully governed AI explanations can "
                "support policy evaluation."
            ),
        )
    )

    st.subheader("Two separate layers", anchor=False)
    deterministic, ai_assisted = st.columns(2)
    with deterministic:
        with st.container(border=True):
            st.markdown("**Deterministic analysis**")
            st.write(
                "Configured MCDM algorithms calculate weights, aggregate "
                "stakeholder input, rank alternatives, and test stability."
            )
    with ai_assisted:
        with st.container(border=True):
            st.markdown("**AI-assisted explanation**")
            st.write(
                "AI may draft explanations from validated outputs. It does not "
                "replace calculations, and public text requires human review."
            )

    st.subheader("Research safeguards", anchor=False)
    st.markdown(
        "- Session configurations and submissions are versioned and hashed.\n"
        "- Participant identity is kept separate from analytical records.\n"
        "- Processing and publication are explicit, audited decisions.\n"
        "- The system supports policy judgment; it is not an automated "
        "decision-maker."
    )
