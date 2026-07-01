from __future__ import annotations

import streamlit as st

from src.models.scenario import ScenarioBundle

from src.components.scenario import scenario_label
from src.components.scenario_preview import render_scenario_preview
from src.components.forms.session_creation import render_session_creation_form
from src.components.session_filter import render_session_filter
from src.components.session_list import render_session_list
from src.components.manage_participant_list import render_manage_participant_list
from src.components.tables.sessions_with_actions import render_sessions_with_actions

from src.utils.auth import is_admin_authenticated
from src.utils.scenario_loader import discover_scenarios
from src.utils.page_context import pages
from src.utils.repositories import get_sessions

def render_manage_sessions_page() -> None:
    if not is_admin_authenticated():
        st.switch_page(pages["admin_login"])
    
    st.header("Session :primary[Management]")
    tab1, tab2, tab3, tab4 = st.tabs(["Create Sessions", "View & Edit Sessions", "Manage Participant", "Manage Submissions"])

    with tab1:
        render_create_session_tab()
    with tab2:
        render_view_edit_sessions_tab()
    # with tab3:
    #     render_manage_participant_tab()
    # with tab4:
    #     render_manage_submissions_tab()


def render_create_session_tab() -> None:
    col1, col2 = st.columns([0.6,0.4])

    scenarios, errors = discover_scenarios("scenarios")
    scenario_options = {scenario_label(s): s for s in scenarios}
     
    with col1:
        with st.container(border=True):
            st.markdown("###### Scenario Selection")
            scenario = st.selectbox(
                "Select a scenario",
                list(scenario_options.keys()),
                index=None,
                on_change=_handle_scenario_change,
                args=(scenario_options,),
                key="scenario_selectbox",
                placeholder="Choose a scenario for the session"
            )
            st.space("xxsmall")

            if not scenario:
                st.warning("Please select a scenario to view its details and create a session.")
            else:
                render_session_creation_form(scenario_options[scenario])

    
    with col2:
        with st.container(border=True):
            st.markdown("###### Scenario Preview")

            if not scenario:
                st.warning("Please select a scenario to view its details and create a session.")
            else:
                render_scenario_preview(_get_selected_scenario())

def render_view_edit_sessions_tab() -> None:
    filters = render_session_filter(
        session_state_key="view_edit_sessions",
        session_status="All",
        session_visibility="All",
        weighting_method="All",
        ranking_method="All",
        preference_method="All"
    )

    scenarios, errors = discover_scenarios("scenarios")

    # render_session_list(filters, scenarios)
    render_sessions_with_actions(filters)

def render_manage_participant_tab() -> None:
    filters = render_session_filter(
        session_state_key="manage_participant",
        session_status="All",
        session_visibility="All",
        weighting_method="All",
        ranking_method="All",
        preference_method="All"
    )
    
    scenarios, errors = discover_scenarios("scenarios")

    # render_manage_participant_list(filters, scenarios)
    

def render_manage_submissions_tab() -> None:
    pass

# Helper functions
def _handle_scenario_change(scenario_options: dict[str, ScenarioBundle]) -> None:
    selected_label = st.session_state["scenario_selectbox"]
    selected_scenario = scenario_options[selected_label]
    st.session_state["selected_scenario"] = selected_scenario

def _get_selected_scenario() -> ScenarioBundle | None:
    return st.session_state.get("selected_scenario")