from __future__ import annotations

import streamlit as st

from poli_insight.presentation.streamlit.context import PageContext


def render(context: PageContext) -> None:
    with st.container(horizontal_alignment="center"):
        st.title("Poli:primary[Insight]", width="content", anchor=False)

    metrics = context.queries.get_home_metrics()

    with st.container(horizontal_alignment="center", width="stretch"):
        with st.container():
            col1, col2 = st.columns([0.75,0.25], vertical_alignment="center")
            with col1:
                st.caption(":primary[AI-Assisted Policy Evaluation]")
                st.markdown("#### Your judgment helps shape :primary[*better*] policy decisions.")
                st.write("Welcome to PoliInsight, an AI-assisted multi-criteria policy decision-support system designed to help stakeholders evaluate smart city policy alternatives through structured preference modeling, MCDM ranking, sensitivity analysis, and verified AI-generated explanations.")
            with col2:
                st.html(f"""
                    <style>
                    .st-key-home_metrics {{
                        background: #fff;
                        
                    }}
                    </style>
                """)
                with st.container(border=True, key="home_metrics"):
                    st.markdown("Active Right Now")
                    st.html(f"<p style='font-size:24px;'>{metrics.total_active_sessions}</p>")
                    st.markdown(f"**{metrics.total_participants_today} participants today**")

    st.divider()
    st.caption(":primary[What to do]")

    columns = st.columns(3)
    actions = (
        (
            "Participate in a session",
            "Browse listed sessions or use an invitation to contribute your "
            "preferences. No account required — takes 5–15 minutes.",
            "Participate",
            ":material/how_to_vote:",
        ),
        (
            "View published results",
            "Explore deterministic findings and any separately approved AI "
            "explanations.",
            "Results",
            ":material/analytics:",
        ),
        (
            "Learn about the research",
            "Understand the thesis, methods, safeguards, and role of AI.",
            "About",
            ":material/science:",
        ),
    )
    for column, (title, description, route_name, icon) in zip(
        columns,
        actions,
        strict=True,
    ):
        with column:
            st.html(f"""
                <style>
                .st-key-{route_name} {{
                    background: #fff;
                    
                }}
                .st-key-{route_name}:hover {{
                    background: #f0f0f0;
                    transition: background 0.3s ease;
                    cursor: pointer;
                }}
                </style>
            """)
            with st.container(border=True, height="stretch", vertical_alignment="distribute", key=route_name):
                st.markdown(f"### {title}")
                st.write(description)
                if st.button(f"{route_name}", use_container_width=True):
                    st.switch_page(context.routes[route_name]),

    st.divider()
    st.subheader("How it works", anchor=False)
    steps = st.columns(3)
    with steps[0]:
        st.markdown("**1. Join an eligible session**")
        st.write("Review the scenario, access rules, consent, and instructions.")
    with steps[1]:
        st.markdown("**2. Share your judgment**")
        st.write("Complete the configured questions and review before submitting.")
    with steps[2]:
        st.markdown("**3. Review released findings**")
        st.write(
            "Only explicitly approved results are published; AI text is labeled "
            "and kept separate from deterministic calculations."
        )

    st.info(
        "Participation rules and identity handling vary by session. Review the "
        "selected session's notice before enrolling.",
        icon=":material/privacy_tip:",
    )
