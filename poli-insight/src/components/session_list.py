from __future__ import annotations
from typing import Any

import streamlit as st

from src.components.session_row import render_session_row

from src.utils.scenario_loader import ScenarioBundle
from src.utils.repositories import get_sessions_by_filter

def render_session_list(filters: dict[str, Any], scenarios: list) -> None:
    sessions = get_sessions_by_filter(filters)

    st.markdown(f":primary[Sessions ({len(sessions)})]")
    
    for session in sessions:
        scenario = _get_scenario_by_id(scenarios, session["scenario_id"])
        render_session_row(session, scenario)

# Helper functions
def _get_scenario_by_id(scenarios: list, scenario_id: str) -> ScenarioBundle | None:
    for scenario in scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    return None