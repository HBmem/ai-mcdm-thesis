from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from src.utils.scenario_loader import ScenarioBundle
from src.utils.repositories import create_session

def render_session_creation_form(selected_scenario: ScenarioBundle):
    errors = []

    with st.container():
        st.markdown("###### Session Details")
        session_title = st.text_input("Session Title", help="Enter a clear title that helps users understand the purpose of the session.", value=f"{selected_scenario.title} - {datetime.now().strftime('%Y-%m-%d')}")
        session_description = st.text_area("Session Description", help="Describe what the session is evaluating and what participants will be asked to do.")
        
        visibility_options = ["All","Private", "Public", "Unlisted"]
        session_visibility = st.radio("Session Visibility", help="Controls who can see the session in the public dashboard.", options=visibility_options, horizontal=True)

        admin_notes = st.text_area("Admin Notes", help="Add notes for administrators. These notes are not shown to participants.")

        st.markdown("###### Model Configuration")

        weighting_options = ["AHP", "FUZZY AHP"]
        weighting_method = st.selectbox("Criteria Weighting Method", options=weighting_options, help="Select how the system will calculate the importance of each criterion.")

        ranking_options = ["TOPSIS", "FUZZY TOPSIS"]
        ranking_method = st.selectbox("Ranking Method", options=ranking_options, help="Select how the system will rank the available policy alternatives.")

        preference_options = ["5-point scale", "7-point scale"]
        preference_method = st.selectbox("Preference Method", options=preference_options, help="Select the rating scale participants will use when judging criterion importance.")

        st.markdown("###### Access & Submission Controls")
        participation_options = ["Single Participant", "Multiple Participants"]
        participation_mode = st.radio("Participation Mode", options=participation_options, horizontal=True, help="Select whether the session collects one response or aggregates responses from multiple participants.")

        aggregation_options = ["Grouped Stakeholder", "Individual"]
        voting_power_options = ["Scenario Default", "Equal", "Custom"]

        aggregation_method = None
        voting_power = None
        voting_power_config = {}
        if participation_mode == "Multiple Participants":
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
            aggregation_method = "Individual"
            voting_power = "Equal"
            for group in selected_scenario.stakeholder_groups:
                voting_power_config[group["id"]] = 1.0

        require_access_code = st.radio("Require Access Code", options=["Yes", "No"], horizontal=True, help="Restricts participation to users with a valid access code.", index=1)
        
        access_code_type = None
        if require_access_code == "Yes":
            with st.container(border=True):
                access_code_type_options = ["Shared Session Code", "Unique Participant Codes"]
                access_code_type = st.selectbox("Access Code Type", options=access_code_type_options, help="Select whether all users share one code or each participant receives a unique code.")
        allow_resubmissions = st.radio("Allow Resubmissions", options=["Yes", "No"], horizontal=True, help="Allows participants to update their responses before the session closes.")

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
            if participation_mode not in participation_options:
                errors.append("Participation Mode is required.")
            if participation_mode == "Multiple Participant":
                if aggregation_method not in aggregation_options:
                    errors.append("Aggregation Method is required.")
                if voting_power not in voting_power_options:
                    errors.append("Voting Power is required.")
            
            if require_access_code not in ["Yes", "No"]:
                errors.append("Require Access Code is required.")
            if require_access_code == "Yes":
                if access_code_type not in ["Shared Session Code", "Unique Participant Codes"]:
                    errors.append("Access Code Type is required.")
                    
            if allow_resubmissions not in ["Yes", "No"]:
                errors.append("Allow Resubmissions is required.")
            if not start_date_time:
                errors.append("Start Date & Time is required.")
            if not end_date_time:
                errors.append("End Date & Time is required.")
            if end_date_time <= start_date_time:
                errors.append("End Date & Time must be after Start Date & Time.")
            if require_access_code == "Yes" and not access_code_type is None:
                errors.append("Access Code Type is required.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:     
                    session_id = create_session(
                        session_title=session_title,
                        session_description=session_description,
                        session_visibility=session_visibility,
                        admin_notes=admin_notes,
                        weighting_method=weighting_method,
                        ranking_method=ranking_method,
                        preference_method=preference_method,
                        participation_mode=participation_mode,
                        aggregation_method=aggregation_method,
                        voting_power=voting_power,
                        voting_power_config=voting_power_config,
                        require_access_code=True if require_access_code == "Yes" else False,
                        access_code_type=access_code_type,
                        allow_resubmissions=True if allow_resubmissions == "Yes" else False,
                        start_date_time=start_date_time,
                        end_date_time=end_date_time,
                        bundle=selected_scenario
                    )
                    st.success(f"Session created with ID: {session_id}")
                except Exception as e:
                    st.error(f"Error creating session: {e}")