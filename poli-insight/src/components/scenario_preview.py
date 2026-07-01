from __future__ import annotations

import streamlit as st

from src.models.scenario import ScenarioBundle

def render_scenario_preview(bundle: ScenarioBundle) -> None:
    if bundle is None:
        return
    
    st.markdown(f"**:primary[{bundle.title}]**")

    st.caption(f"{bundle.scenario_id} | {bundle.scenario_version}")
    st.write(f"**Policy Domain**: :primary[{bundle.domain}]")
    st.write(f"**Scenario Type**: :primary[{bundle.scenario_type}]")
    st.write(bundle.description)

    # TODO: Add additional metrics for hierarchical structure
    st.html(f"""
            <style>
            .st-key-{bundle.scenario_id} {{
                background: #fff;
            }}
            </style>
            """)
    with st.container(border=True, key=bundle.scenario_id):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"""
                        Alternatives  
                        Criteria
                        """)
        with col2:
            st.markdown(f"""
                        :primary[{len(bundle.alternatives)} defined]  
                        :primary[{len(bundle.criteria)} defined]
                        """, text_alignment="right")

    badge_string = ""
    for tag in bundle.scenario.get("tags", []):
        badge_string += f":primary-badge[ {tag} ] "
    st.markdown(badge_string)