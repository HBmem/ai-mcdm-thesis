from __future__ import annotations

import streamlit as st

from dashboard.db import init_db
from dashboard.pages.stakeholder import render_stakeholder_dashboard
from dashboard.pages.moderator import render_moderator_dashboard
from dashboard.scenario_loader import discover_scenarios

st.set_page_config(
    page_title="Policy Evaluation MCDM - Stakeholder Polling",
    layout="wide",
)

init_db()

scenarios, errors = discover_scenarios("scenarios")
if errors:
    with st.expander("Scenario configuration warnings", expanded=False):
        for err in errors:
            st.error(err)

st.sidebar.title("📊 Policy Evaluation MCDM Stakeholder Polling")
st.sidebar.caption("Scenario-driven stakeholder preference collection and session orchestration layer")

mode = st.sidebar.radio("Dashboard" ,["🗳️ Stakeholder", "👑 Moderator"], index=0)
st.sidebar.markdown("---")
st.sidebar.write(f"Valid scenarios loaded: **{len(scenarios)}**")

if mode == "🗳️ Stakeholder":
    render_stakeholder_dashboard(scenarios)
else:
    render_moderator_dashboard(scenarios)
