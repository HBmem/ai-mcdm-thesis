from __future__ import annotations
from typing import Any

import streamlit as st

from src.models.scenario import ScenarioBundle

from src.components.tables.sessions_with_actions_row import render_session_row

from src.repositories.scenario_repository import get_scenario_snapshot
from src.repositories.session_repository import get_sessions_by_filter

ROWS_PER_PAGE = 10

def render_sessions_with_actions(filter: dict[str, Any]):
    sessions = get_sessions_by_filter(filter_criteria=filter)
    total_pages = max(1, (len(sessions) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)

    st.markdown(f":primary[Sessions ({len(sessions)})]")
    
    with st.container(border=True):
        table_slot = st.empty()
        page = st.pagination(num_pages=total_pages, key="sessions_pagination")
    
    start_index = (page - 1) * ROWS_PER_PAGE
    end_index = start_index + ROWS_PER_PAGE
    sessions_to_display = sessions[start_index:end_index]

    with table_slot.container():
        for session in sessions_to_display:
            scenario = get_scenario_snapshot(session.scenario_id)
            render_session_row(session, scenario=scenario)