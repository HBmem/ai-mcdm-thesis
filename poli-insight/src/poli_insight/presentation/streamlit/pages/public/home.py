from __future__ import annotations

import streamlit as st

from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    metric_card,
    render_page_header,
    render_section_heading,
    surface,
)
from poli_insight.presentation.streamlit.context import PageContext


def render(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="AI-assisted policy evaluation",
            title="Poli:primary[Insight]",
            description="Your judgment helps shape better policy decisions.",
        )
    )
    metrics = context.queries.get_home_metrics()
    with surface(key="home:overview", variant="feature"):
        st.write(
            "Evaluate policy alternatives through structured preferences, "
            "transparent multi-criteria analysis, and evidence you can inspect."
        )
        with st.container(horizontal=True, gap="medium"):
            with st.container(width=260):
                metric_card(
                    "Active sessions", metrics.total_active_sessions, key="home:active"
                )
            with st.container(width=260):
                metric_card(
                    "Participants today",
                    metrics.total_participants_today,
                    key="home:participants",
                )

    render_section_heading("Find your next step")
    actions = (
        (
            "Participate in a session",
            (
                "Find an open study or follow your invitation. Review the study’s "
                "access and consent requirements before sharing your preferences."
            ),
            "Participate",
            ":material/how_to_vote:",
        ),
        (
            "View released results",
            (
                "Participant results are available through authorized private links. "
                "Visit Results for current publication availability."
            ),
            "Results",
            ":material/analytics:",
        ),
        (
            "Learn about the research",
            (
                "Understand the methods, research safeguards, and role of AI in "
                "policy evaluation."
            ),
            "About",
            ":material/science:",
        ),
    )
    with st.container(horizontal=True, gap="medium"):
        for title, description, route_name, icon in actions:
            with surface(
                key=f"home:{route_name}",
                width=300,
                height="stretch",
                vertical_alignment="distribute",
            ):
                st.subheader(title, anchor=False)
                st.write(description)
                if st.button(
                    route_name,
                    icon=icon,
                    width="stretch",
                    type="primary" if route_name == "Participate" else "secondary",
                ):
                    st.switch_page(context.routes[route_name.lower()])

    render_section_heading("How it works")
    with surface(key="home:how"):
        st.markdown("**1. Join an eligible session**")
        st.write("Review the scenario, access rules, consent, and instructions.")
        st.markdown("**2. Share your judgment**")
        st.write(
            "Complete the configured questions, save your progress, and review before submitting."
        )
        st.markdown("**3. Review released findings**")
        st.write(
            "Return through your private link when the researcher releases results to participants."
        )
    st.info(
        "Participation rules and identity handling vary by session. Review the "
        "selected session’s notice before enrolling.",
        icon=":material/privacy_tip:",
    )
