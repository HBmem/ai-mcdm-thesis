from __future__ import annotations

import streamlit as st

from poli_insight.bootstrap import ApplicationContainer


def render(container: ApplicationContainer) -> None:
    del container

    with st.container(horizontal_alignment="center"):
        st.title("Poli:primary[Insight]", width="content", anchor=False)

    with st.container(horizontal_alignment="center", width="stretch"):
        with st.container():
            col1, col2 = st.columns(2, vertical_alignment="center")
            with col1:
                st.caption(":primary[AI-Assisted Policy Evaluation]")
                st.markdown("#### Your judgment helps shape :primary[*better*] policy decisions.")
                st.write("Welcome to PoliInsight, an AI-assisted multi-criteria policy decision-support system designed to help stakeholders evaluate smart city policy alternatives through structured preference modeling, MCDM ranking, sensitivity analysis, and verified AI-generated explanations.")
            with col2:
                with st.container(border=True):
                    st.markdown("Active Right Now")
                    st.markdown("")
                    st.divider()
                    # TODO: Add list of open sessions and their status
        
        st.divider()
        st.caption(":primary[What to do]")

        with st.container():
            col1, col2, col3 = st.columns(3)
            with col1:
                with st.container(border=True, height="stretch", vertical_alignment="distribute"):
                    st.markdown("### Participate in an Active Session")
                    st.write("Browse currently open policy evaluation sessions and contribute your structured preferences")
                    if st.button(
                        "Participate in an Active Session", use_container_width=True):
                        st.switch_page(pages["active_sessions"])
            with col2:
                with st.container(border=True, height="stretch", vertical_alignment="distribute"):
                    st.markdown("### View Published Results")
                    st.write("Explore aggregated rankings, criteria weights, and AI-generated decision models from completed sessions")
                    if st.button("View Published Results", use_container_width=True):
                        st.switch_page(pages["published_results"])
            with col3:
                with st.container(border=True, height="stretch", vertical_alignment="distribute"):
                    st.markdown("### Learn about the Research")
                    st.write("Understand how this platform supports a thesis on AI-assisted MCDM for policy contexts")
                    if st.button("Learn About the Research", use_container_width=True):
                        st.switch_page(pages["about"])
            
        st.divider()
        st.caption(":primary[**How it works**]")

        with st.container(border=True):
            col1, col2, col3= st.columns(3)
            with col1:
                st.write("## 01")
                st.markdown("**Join a session**")
                st.write("An admin opens a policy scenario and defines the criteria to be evaluated. You're invited via a session link or the public session list.")
            with col2:
                st.write("## 02")
                st.markdown("**Give your preferences**")
                st.write("You compare criteria and policy alternatives through guided pairwise questions. Answers are aggregated to form a comprehensive preference model.")
            with col3:
                st.write("## 03")
                st.markdown("**Results are published**")
                st.write("Preferences are aggregated and results are published for all participants to view. Along with an individual preference model, the system provides AI-generated explanations for the final rankings.")