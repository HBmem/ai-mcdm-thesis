from __future__ import annotations

import streamlit as st

from src.utils.scenario_loader import ScenarioBundle

def render_session_preview(bundle: ScenarioBundle) -> None:
    if bundle is None:
        return
    
    st.markdown(f"**{bundle.title}**")

    st.caption(f"{bundle.scenario_id} | {bundle.scenario_version}")
    st.write(f"**Policy Domain**: :primary[{bundle.domain}]")
    st.write(f"**Scenario Type**: :primary[{bundle.scenario_type}]")
    st.write(bundle.scenario.get("description", "No description provided."))

    st.divider()

    # TODO: Add additional metrics for hierarchical structure
    col1, col2 = st.columns(2)
    with col1:
        # st.write("Alternatives")
        # st.write("Criteria")
        st.markdown(f"""
                    Alternatives  
                    Criteria
                    """)
    with col2:
        # st.write(f":primary[{len(bundle.scenario.get('alternatives', []))} defined]")
        # st.write(f":primary[{len(bundle.criteria)} defined]")
        st.markdown(f"""
                    :primary[{len(bundle.scenario.get('alternatives', []))} defined]  
                    :primary[{len(bundle.criteria)} defined]
                    """)

    st.divider()

    badge_string = ""
    for tag in bundle.scenario.get("tags", []):
        badge_string += f":blue-badge[ {tag} ] "
    st.markdown(badge_string)