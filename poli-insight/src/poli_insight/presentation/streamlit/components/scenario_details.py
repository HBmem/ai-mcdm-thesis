import streamlit as st

from poli_insight.domain.scenario import ScenarioBundle

def render(
    scenario: ScenarioBundle,
) -> None:
    if scenario is None:
        st.write("Please select a scenario")
        return
    
    st.markdown(f"**:primary[{scenario.title}]**")

    st.caption(f"{scenario.scenario_id} | {scenario.scenario_version}")
    st.write(f"**Policy Domain**: :primary[{scenario.domain}]")
    st.write(f"**Scenario Type**: :primary[{scenario.scenario_type}]")
    st.write(scenario.description)

    # TODO: Add additional metrics for hierarchical structure
    st.html(f"""
            <style>
            .st-key-{scenario.scenario_id} {{
                background: #fff;
            }}
            </style>
            """)
    
    with st.container(border=True, key=scenario.scenario_id):
        key, values = st.columns(2)
        with key:
            st.markdown(f"""
                        Alternatives  
                        Criteria
                        """)
        with values:
            st.markdown(f"""
                        :primary[{len(scenario.alternatives)} defined]  
                        :primary[{len(scenario.criteria)} defined]
                        """, text_alignment="right")

    badge_string = ""
    for tag in scenario.scenario.get("tags", []):
        badge_string += f":primary-badge[ {tag} ] "
    st.markdown(badge_string)