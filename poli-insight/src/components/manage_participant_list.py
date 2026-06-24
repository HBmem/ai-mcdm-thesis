from __future__ import annotations
from typing import Any

import streamlit as st
import pandas as pd

from streamlit_extras.metric_cards import style_metric_cards

from src.utils.scenario_loader import ScenarioBundle
from src.utils.repositories import get_participants_by_session_id, get_sessions_by_filter

def render_manage_participant_list(filters: dict[str, Any], scenarios: list[ScenarioBundle]) -> None:
    sessions = get_sessions_by_filter(filters)
    

    col_title, col_status, col_actions = st.columns([2, 0.5, 2], vertical_alignment="center")

    with col_title:
        selected_session = st.selectbox(key="manage_participant_scenario", label="Select a session", options=sessions, format_func=_session_label)
    
    with col_status:
        st.space("xsmall")
        if selected_session is not None:
            # st.badge(selected.get('status', 'Unknown'))
            st.markdown(f"**Status:** :primary[{selected_session.get('status', 'Unknown')}]")
    
    with col_actions:
        st.space("small")
        col_export, col_add = st.columns([1, 1])
        if selected_session is not None:
            with col_export:
                if st.button("Export Participants CSV", width="stretch"):
                    pass
            with col_add:
                if st.button("Add Participants", width="stretch"):
                    pass

    if selected_session is None:
        st.markdown("Please select a session.")
        return

    scenario = _find_scenario_by_id(scenarios, selected_session['scenario_id'])

    participants = get_participants_by_session_id(selected_session['session_id'])

    total, active, pending, inactive = _participant_stats(participants)

    col1, col2, col3, col4 = st.columns(4, vertical_alignment="center")

    col1.metric("TOTAL", total)
    col2.metric("ACTIVE", active)
    col3.metric("PENDING", pending)
    col4.metric("INACTIVE", inactive)

    style_metric_cards()

    filtered_participants = _participant_filter(participants, scenario.scenario.get('stakeholder_groups', []))

# Helper Components
def _participant_stats(participants: list[dict]) -> tuple[int, int, int, int]:
    total = len(participants)
    active = sum(1 for p in participants if p.get('status') == 'ACTIVE')
    pending = sum(1 for p in participants if p.get('status') == 'PENDING')
    inactive = sum(1 for p in participants if p.get('status') == 'INACTIVE')
    return total, active, pending, inactive

def _participant_filter(participants: list[dict], stakeholder_group: list[dict]) -> list[dict]:
    col1, col2, col3 = st.columns([2, 1, 1], vertical_alignment="center")

    with col1:
        search_term = st.text_input("Search", key="participant_search")

    with col2:
        status_filter = st.selectbox("Status", options=["All", "ACTIVE", "PENDING", "INACTIVE"], key="participant_status")

    with col3:
        stakeholder_group_filter = st.selectbox("Stakeholder Group", options=stakeholder_group, format_func=lambda x: x.get('label', 'Unknown'), key="participant_stakeholder_group")

    return [p for p in participants if search_term.lower() in p.get('name', '').lower() and (status_filter == "All" or p.get('status') == status_filter)]

def _participants_table(participants: list[dict]) -> None:
    if not participants:
        st.markdown("No participants found.")
        return

    # Create a DataFrame for easier display
    df = pd.DataFrame(participants)

    # Display the DataFrame as a table
    st.dataframe(df, use_container_width=True)

# Helper Functions
def _session_label(session: Any) -> str:
    return f"{session.get('session_title', 'Unknown')} - ({session.get('session_id', 'Unknown')})"

def _find_scenario_by_id(scenarios: list[ScenarioBundle], scenario_id: str) -> dict | None:
    for scenario in scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    return None