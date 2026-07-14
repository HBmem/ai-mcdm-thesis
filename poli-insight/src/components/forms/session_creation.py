from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from src.models.scenario import ScenarioBundle
from src.models.session import SessionScenario
from src.models.enum import (
    SessionStatus,
    SessionVisibility,
    WeightingMethod,
    RankingMethod,
    PreferenceMethod,
    ParticipationMethod,
    AggregationMethod,
)

from src.repositories.session_repository import create_session

def render_session_creation_form(selected_scenario: ScenarioBundle):
    errors = []

    with st.container():
        st.markdown("###### Session Details")
        session_title = st.text_input("Session Title", help="Enter a clear title that helps users understand the purpose of the session.", value=f"{selected_scenario.title} - {datetime.now().strftime('%Y-%m-%d')}")
        session_description = st.text_area("Session Description", help="Describe what the session is evaluating and what participants will be asked to do.")
        
        visibility_options = [SessionVisibility.PRIVATE, SessionVisibility.PUBLIC, SessionVisibility.UNLISTED]
        session_visibility = st.radio("Session Visibility", help="Controls who can see the session in the public dashboard.", options=visibility_options, format_func=lambda x: x.value, horizontal=True)

        admin_notes = st.text_area("Admin Notes", help="Add notes for administrators. These notes are not shown to participants.")

        st.markdown("###### Model Configuration")

        weighting_options = [WeightingMethod.AHP, WeightingMethod.FUZZY_AHP]
        weighting_method = st.selectbox("Criteria Weighting Method", options=weighting_options, format_func=lambda x: x.value, help="Select how the system will calculate the importance of each criterion.")

        ranking_options = [RankingMethod.TOPSIS, RankingMethod.FUZZY_TOPSIS]
        ranking_method = st.selectbox("Ranking Method", options=ranking_options, format_func=lambda x: x.value, help="Select how the system will rank the available policy alternatives.")

        preference_options = [PreferenceMethod.FIVE_POINT_SCALE, PreferenceMethod.SEVEN_POINT_SCALE]
        preference_method = st.selectbox("Preference Method", options=preference_options, format_func=lambda x: x.value, help="Select the rating scale participants will use when judging criterion importance.")

        st.markdown("###### Access & Submission Controls")
        participation_options = [ParticipationMethod.SINGLE_PARTICIPANT, ParticipationMethod.MULTIPLE_PARTICIPANTS]
        participation_method = st.radio("Participation Method", options=participation_options, horizontal=True, help="Select whether the session collects one response or aggregates responses from multiple participants.")

        aggregation_options = [AggregationMethod.GROUP_STAKEHOLDER, AggregationMethod.INDIVIDUAL]
        voting_power_options = ["Scenario Default", "Equal", "Custom"]

        aggregation_method = None
        voting_power = None
        voting_power_config = {}
        if participation_method == ParticipationMethod.MULTIPLE_PARTICIPANTS:
            with st.container(border=True):
                st.markdown("###### Aggregation Settings")
                aggregation_method = st.selectbox("Aggregation Method", options=aggregation_options, help="Select how participant preferences are aggregated before final ranking.")

                voting_power = st.selectbox("Voting Power", options=voting_power_options, help="Select how stakeholder group influence is assigned. This can be modified later.")

                if voting_power == "Scenario Default":
                    for group in selected_scenario.stakeholder_groups:
                        voting_power_config[group["id"]] = float(group.get("default_group_voting_power", 1.0))
                    voting_power_config = st.data_editor(voting_power_config,
                                   column_config={
                                       0: st.column_config.TextColumn("Stakeholder Group"),
                                       1: st.column_config.NumberColumn(
                                           "Voting Power",
                                           min_value=0.0,
                                           max_value=10.0
                                        )
                                   },
                                   disabled=True
                    )
                elif voting_power == "Equal":
                    for group in selected_scenario.stakeholder_groups:
                        voting_power_config[group["id"]] = 1.0
                    voting_power_config = st.data_editor(voting_power_config,
                                   column_config={
                                       0: st.column_config.TextColumn("Stakeholder Group"),
                                       1: st.column_config.NumberColumn(
                                           "Voting Power",
                                           min_value=0.0,
                                           max_value=1.0
                                        )
                                   },
                                   disabled=True
                    )
                elif voting_power == "Custom":
                    for group in selected_scenario.stakeholder_groups:
                        voting_power_config[group["id"]] = float(group.get("default_group_voting_power", 1.0))
                    voting_power_config = st.data_editor(voting_power_config,
                                   column_config={
                                       0: st.column_config.TextColumn("Stakeholder Group"),
                                       1: st.column_config.NumberColumn(
                                           "Voting Power",
                                           min_value=0.0,
                                           max_value=10.0
                                        )
                                   },
                                   disabled=[0]
                    )
        else:
            aggregation_method = AggregationMethod.INDIVIDUAL
            voting_power = "Equal"
            for group in selected_scenario.stakeholder_groups:
                voting_power_config[group["id"]] = 1.0

        # require_access_code = st.radio("Require Access Code", options=["Yes", "No"], horizontal=True, help="Restricts participation to users with a valid access code.", index=1)
        require_access_code = st.toggle("Require Access Code", help="Restricts participation to users with a valid access code.", value=False)

        access_code_type = None
        if require_access_code:
            with st.container(border=True):
                access_code_type_options = ["Shared Session Code", "Unique Participant Codes"]
                access_code_type = st.selectbox("Access Code Type", options=access_code_type_options, help="Select whether all users share one code or each participant receives a unique code.")
        # allow_resubmissions = st.radio("Allow Resubmissions", options=["Yes", "No"], horizontal=True, help="Allows participants to update their responses before the session closes.")
        allow_resubmissions = st.toggle("Allow Resubmissions", help="Allows participants to update their responses before the session closes.", value=False)

        st.markdown("###### Session Scheduling")
        start_date_time = st.datetime_input("Start Date & Time", value="now", min_value="now", help="Set when participants can begin submitting responses.")

        default_end_date_time = start_date_time + timedelta(days=30)
        default_end_date_time = default_end_date_time.replace(hour=23, minute=59, second=59)
        end_date_time = st.datetime_input("End Date & Time", value=default_end_date_time, help="Set when the session will close and no more submissions will be accepted.")
        
        # TODO: Add the option to select timezones
        # time_zone = st.selectbox("Time Zone", options=["UTC", "EST", "PST"], help="Select the time zone used for the session start and end time.")
        # start_date_time = start_date_time.astimezone(ZoneInfo(time_zone))
        # end_date_time = end_date_time.astimezone(ZoneInfo(time_zone))

        if st.button("Create Session", type="primary"):
            if not session_title.strip():
                errors.append("Session Title is required.")
            if session_visibility not in visibility_options:
                errors.append("Session Visibility is required.")
            if weighting_method not in weighting_options:
                errors.append("Weighting Method is required.")
            if ranking_method not in ranking_options:
                errors.append("Ranking Method is required.")
            if preference_method not in preference_options:
                errors.append("Preference Method is required.")
            if participation_method not in participation_options:
                errors.append("Participation Method is required.")
            if participation_method == ParticipationMethod.MULTIPLE_PARTICIPANTS:
                if aggregation_method not in aggregation_options:
                    errors.append("Aggregation Method is required.")
                if voting_power not in voting_power_options:
                    errors.append("Voting Power is required.")
            
            if require_access_code not in [True, False]:
                errors.append("Require Access Code is required.")
            if require_access_code == True:
                if access_code_type not in ["Shared Session Code", "Unique Participant Codes"]:
                    errors.append("Access Code Type is required.")
                    
            if allow_resubmissions not in [True, False]:
                errors.append("Allow Resubmissions is required.")
            if not start_date_time:
                errors.append("Start Date & Time is required.")
            if not end_date_time:
                errors.append("End Date & Time is required.")
            if end_date_time <= start_date_time:
                errors.append("End Date & Time must be after Start Date & Time.")
            if require_access_code == True and access_code_type is None:
                errors.append("Access Code Type is required.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    session_scenario = SessionScenario(
                        session_id="",
                        scenario_id=selected_scenario.scenario_id,
                        scenario_version=selected_scenario.scenario_version,
                        title=session_title,
                        description=session_description,
                        admin_notes=admin_notes,
                        status=SessionStatus.DRAFT,
                        visibility=session_visibility,
                        weighting_method=weighting_method,
                        ranking_method=ranking_method,
                        preference_method=preference_method,
                        participation_method=participation_method,
                        aggregation_method=aggregation_method,
                        require_access_code=require_access_code,
                        access_code_type=access_code_type,
                        allow_resubmissions=allow_resubmissions,
                        start_at=start_date_time,
                        end_at=end_date_time,
                        opened_at=None,
                        closed_at=None,
                        archived_at=None,
                        created_at=datetime.now(),
                        created_by="admin", # TODO: Add admin info later
                        updated_at=datetime.now(),
                        updated_by="admin" # TODO: Add admin info later
                    )
                    
                    voting_data = {
                        "voting_power_option": voting_power,
                        "voting_config": voting_power_config
                    }

                    session_id = create_session(session_scenario, selected_scenario, voting_data)
                    st.success(f"Session created with ID: {session_id}")
                except Exception as e:
                    st.error(f"Error creating session: {e}")