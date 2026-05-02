from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.scenario_loader import ScenarioBundle

def scenario_label(bundle: ScenarioBundle) -> str:
    return f"{bundle.title} ({bundle.scenario_id}:{bundle.scenario_version})"

def render_scenario_card(bundle: ScenarioBundle) -> None:
    with st.container(border=True):
        st.subheader(bundle.title)
        st.caption(f"Scenario ID: {bundle.scenario_id} | Domain: {bundle.domain} | Version: {bundle.scenario_version}")
        st.write(bundle.scenario.get("summary", "No summary provided."))

def render_criterion_cards(criteria: list[dict[str, Any]]) -> None:
    for c in sorted(criteria, key=lambda x: x.get("display_order", 999)):
        with st.container(border=True):
            criteria_type = c.get("criteria_type", "unknown")
            st.markdown(f"**{c.get('name', c['id'])}**")
            st.caption(f"Criteria Type: {criteria_type.upper()} | Unit: {c.get('unit', 'n/a')}")
            st.write(c.get("description", "No description provided."))


def render_alternative_cards(alternatives: list[dict[str, Any]]) -> None:
    for a in alternatives:
        with st.container(border=True):
            st.markdown(f"**{a.get('name', a['id'])}**")
            st.write(a.get("description", "No description provided."))


def format_session_option(session: dict[str, Any]) -> str:
    return f"{session['session_name']} | {session['scenario_id']} | {session['status']} | {session['session_id']}"