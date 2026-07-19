from __future__ import annotations

import streamlit as st
from streamlit_extras.skeleton import *

from poli_insight.application.session_queries import SessionFilters
from poli_insight.application.dto import CreateSessionCommand
from poli_insight.application.services.session_service import CreateSessionError
from poli_insight.application.scenario_loader import discover_scenarios
from poli_insight.application.utils import scenario_label

from poli_insight.bootstrap import ApplicationContainer

from poli_insight.presentation.streamlit.auth import get_current_user
from poli_insight.presentation.streamlit.forms.create_session import render as render_create_session
from poli_insight.presentation.streamlit.forms.session_filter import render as render_session_filter
from poli_insight.presentation.streamlit.components.scenario_details import render as render_scenario_details
from poli_insight.presentation.streamlit.components.view_edit_table import render as render_view_edit_table

from poli_insight.domain.scenario import ScenarioBundle
from poli_insight.domain.enums import (
    PreferenceScale,
    RankingMethod,
    SessionStatus,
    SessionVisibility,
    WeightingMethod,
)

def render(container: ApplicationContainer) -> None:
    _render_tabs(container)
    

def _render_tabs(container: ApplicationContainer) -> None:
    st.header("Session :primary[Management]")
    tab1, tab2, tab3, tab4 = st.tabs(["Create Sessions", "View & Edit Sessions", "Manage Participant", "Manage Submissions"])

    with tab1:
        _render_create_session_tab(container)
    with tab2:
        _render_view_edit_sessions_tab(container)

def _render_create_session_tab(container: ApplicationContainer):
    form, details = st.columns([0.6,0.4])

    scenarios, errors = discover_scenarios("scenarios")
    scenario_options = {scenario_label(s): s for s in scenarios}

    with form:
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

            if scenario:
                command: CreateSessionCommand | None = (
                    render_create_session(
                        scenario=scenario_options[scenario],
                        actor_id="dev-admin",
                        app_timezone=container.settings.app_timezone
                    )
                )

                if command is not None:
                    try:
                        session_id = (container.session_service.create_session(command))
                        st.success(f"Session created with ID: {session_id}")
                    except CreateSessionError as error:
                        st.error(str(error))
                    except Exception as e:
                        st.error(f"The session could not be created: {e}")
            else:
                st.write("Please select a scenario")
                form_skeleton = skeleton(height=300)

    with details:
        with st.container(border=True):
            st.markdown("###### Scenario Preview")

            if not scenario:
                details_skeleton = skeleton(height=150)
            else:
                render_scenario_details(scenario_options[scenario])

def _render_view_edit_sessions_tab(
    container: ApplicationContainer,
) -> None:
    filters = render_session_filter(
        session_state_key="view_edit_sessions",
        session_status=None,
        visibility=None,
        weighting_method=None,
        ranking_method=None,
        preference_scale=None,
    )

    session_filters = SessionFilters(
        status=(
            None
            if filters["status"] == "All"
            else SessionStatus(filters["status"])
        ),

        visibility=(
            None
            if filters["visibility"] == "All"
            else SessionVisibility(filters["visibility"])
        ),

        weighting_method=(
            None
            if filters["weighting_method"] == "All"
            else WeightingMethod(
                filters["weighting_method"]
            )
        ),
        ranking_method=(
            None
            if filters["ranking_method"] == "All"
            else RankingMethod(
                filters["ranking_method"]
            )
        ),
        preference_scale=(
            None
            if filters["preference_scale"] == "All"
            else PreferenceScale(
                filters["preference_scale"]
            )
        ),
    )

    render_view_edit_table(
        session_service=container.session_service,
        filters=session_filters,
        actor_id="dev-admin",
        app_timezone=container.settings.app_timezone
        # actor_id=current_user.user_id
    )


def _handle_scenario_change(scenario_options: dict[str, ScenarioBundle]) -> None:
    selected_label = st.session_state["scenario_selectbox"]

    if selected_label is not None:
        selected_scenario = scenario_options[selected_label]
        st.session_state["selected_scenario"] = selected_scenario