from __future__ import annotations

from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

import streamlit as st

from poli_insight.application.dto import CreateSessionCommand
from poli_insight.domain.enums import (
    AggregationMethod,
    ParticipationMethod,
    PreferenceScale,
    RankingMethod,
    SessionVisibility,
    WeightingMethod,
)
from poli_insight.domain.scenario import ScenarioBundle

def render(
    scenario: ScenarioBundle,
    actor_id: str,
    app_timezone: str,
) -> CreateSessionCommand | None:
    errors = []

    with st.container():
        st.markdown("###### Session Details")
        session_title = st.text_input(
            "Session Title",
            value=f"{scenario.title} - {datetime.now().strftime('%Y-%m-%d')}",
            help="Enter a clear title that helps users understand the purpose of the session.",
        )
        session_description = st.text_area(
            "Session Description",
            help="Describe what the session is evaluating and what participants will be asked to do.",
        )

        visibility_options = [SessionVisibility.PUBLIC, SessionVisibility.PRIVATE, SessionVisibility.UNLISTED]
        session_visibility = st.radio(
            "Session Visibility",
            options=visibility_options,
            format_func=lambda x: x.value,
            horizontal=True,
            help="Controls who can see the session in the public dashboard.",
        )

        admin_notes = st.text_area(
            "Admin Notes",
            help="Add notes for administrators. These notes are not shown to participants."
        )

        weighting_options = [WeightingMethod.AHP, WeightingMethod.FUZZY_AHP]
        weighting_method = st.selectbox(
            "Criteria Weighting Method",
            options=weighting_options,
            format_func=lambda x: x.value,
            help="Select how the system will calculate the importance of each criterion.",
        )

        ranking_options = [RankingMethod.TOPSIS, RankingMethod.FUZZY_TOPSIS]
        ranking_method = st.selectbox(
            "Ranking Method",
            options=ranking_options,
            format_func=lambda x: x.value,
            help="Select how the system will rank the available policy alternatives.",
            )

        preference_options = [PreferenceScale.FIVE_POINT_SCALE, PreferenceScale.SEVEN_POINT_SCALE]
        preference_scale = st.selectbox(
            "Preference Scale",
            options=preference_options,
            format_func=lambda x: x.value,
            help="Select the rating scale participants will use when judging criterion importance."
        )

        st.markdown("###### Access & Submission Controls")
        participation_options = [ParticipationMethod.SINGLE_PARTICIPANT, ParticipationMethod.MULTIPLE_PARTICIPANTS]
        participation_method = st.radio(
            "Participation Method",
            options=participation_options,
            horizontal=True,
            help="Select whether the session collects one response or aggregates responses from multiple participants."
        )

        aggregation_options = [AggregationMethod.GROUP_STAKEHOLDER, AggregationMethod.INDIVIDUAL]
        voting_power_options = ["Scenario Default", "Equal", "Custom"]

        aggregation_method = None
        voting_power_config = {}

        if participation_method == ParticipationMethod.MULTIPLE_PARTICIPANTS:
            st.markdown("###### Aggregation Settings")
            aggregation_method = AggregationMethod.GROUP_STAKEHOLDER
            
            with st.container(border=True):
                voting_power_mode = st.selectbox(
                    "Voting Power",
                    options=voting_power_options,
                    help="Select how stakeholder influence is configured.",
                )

                voting_power_config = _render_voting_power(
                    scenario,
                    voting_power_mode,
                )
        else:
            aggregation_method = AggregationMethod.INDIVIDUAL
            for group in scenario.stakeholder_groups:
                voting_power_config[group["id"]] = 1.0
        
        col1, col2 = st.columns(2)
        with col1:
            access_code_type = None
            require_access_code = st.toggle(
                "Require Access Code",
                value=False,
                help="Restricts participation to users with a valid access code.",)
        
        with col2:
            allow_resubmissions = st.toggle(
                "Allow Resubmissions",
                value=False,
                help="Allows participants to update their responses before the session closes.",
            )

        if require_access_code:
            with st.container(border=True):
                access_code_type_options = ["Shared Session Code", "Unique Participant Codes"]
                access_code_type = st.selectbox(
                    "Access Code Type",
                    options=access_code_type_options,
                    help="Select whether all users share one code or each participant receives a unique code.",
                )

        st.markdown("###### Session Scheduling")
        col3, col4 = st.columns(2)
        with col3:
            start_date_time = st.datetime_input(
                "Start Date & Time",
                value="now",
                min_value="now",
                help="Set when participants can begin submitting responses."
            )

        with col4:
            default_end_date_time = start_date_time + timedelta(days=30)
            default_end_date_time = default_end_date_time.replace(hour=23, minute=59, second=59)
            end_date_time = st.datetime_input(
                "End Date & Time",
                value=default_end_date_time,
                help="Set when the session will close and no more submissions will be accepted.",
            )

        if st.button("Create Session", type="primary"):
            if not session_title.strip():
                errors.append("Session Title is required.")
            if session_visibility not in visibility_options:
                errors.append("Session Visibility is required.")
            if weighting_method not in weighting_options:
                errors.append("Weighting Method is required.")
            if ranking_method not in ranking_options:
                errors.append("Ranking Method is required.")
            if preference_scale not in preference_options:
                errors.append("Preference Method is required.")
            if participation_method not in participation_options:
                errors.append("Participation Method is required.")
            if participation_method == ParticipationMethod.MULTIPLE_PARTICIPANTS:
                if aggregation_method not in aggregation_options:
                    errors.append("Aggregation Method is required.")
                # if voting_power not in voting_power_options:
                #     errors.append("Voting Power is required.")
            
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
                _render_errors(errors)
            else:
                return CreateSessionCommand(
                    scenario=scenario,
                    title=session_title.strip(),
                    description=session_description.strip() or None,
                    admin_notes=admin_notes.strip() or None,
                    visibility=session_visibility,
                    participation_method=participation_method,
                    preference_scale=preference_scale,
                    weighting_method=weighting_method,
                    ranking_method=ranking_method,
                    aggregation_method=aggregation_method,
                    require_access_code=require_access_code,
                    access_code_type=access_code_type,
                    allow_resubmissions=allow_resubmissions,
                    start_at=_to_aware_datetime(start_date_time, app_timezone),
                    end_at=_to_aware_datetime(end_date_time, app_timezone),
                    voting_power=voting_power_config,
                    actor_id=actor_id,
                )
        
def _render_errors(errors: list[str]) -> None:
    with st.container(border=True):
        st.markdown("###### Errors")
        for e in errors:
            st.error(e)

def _to_aware_datetime(
    value: datetime,
    timezone_name: str,
) -> datetime:
    if value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo(timezone_name))

    return value.astimezone(UTC)

def _default_voting_power(
    scenario: ScenarioBundle,
    mode: str,
) -> dict[str, float]:
    if mode == "Equal":
        return {
            group["id"]: 1.0
            for group in scenario.stakeholder_groups
        }

    return {
        group["id"]: float(
            group.get("default_group_voting_power", 1.0)
        )
        for group in scenario.stakeholder_groups
    }

def _render_voting_power(
    scenario: ScenarioBundle,
    mode: str,
) -> dict[str, float]:
    initial_weights = _default_voting_power(scenario, mode)

    rows = [
        {
            "group_id": group["id"],
            "stakeholder_group": group["label"],
            "voting_power": initial_weights[group["id"]],
        }
        for group in scenario.stakeholder_groups
    ]

    if mode != "Custom":
        st.dataframe(
            rows,
            column_order=("stakeholder_group", "voting_power"),
            column_config={
                "stakeholder_group": "Stakeholder Group",
                "voting_power": st.column_config.NumberColumn(
                    "Voting Power",
                    min_value=0.0,
                ),
            },
            hide_index=True,
        )
        return initial_weights

    state_key = (
        f"create-session:{scenario.scenario_id}:"
        f"{scenario.scenario_version}:custom-weights"
    )

    if state_key not in st.session_state:
        st.session_state[state_key] = initial_weights

    rows = [
        {
            "group_id": group["id"],
            "stakeholder_group": group["label"],
            "voting_power": st.session_state[state_key].get(
                group["id"],
                initial_weights[group["id"]],
            ),
        }
        for group in scenario.stakeholder_groups
    ]

    edited_rows = st.data_editor(
        rows,
        key=f"{state_key}:editor",
        column_order=("stakeholder_group", "voting_power"),
        column_config={
            "stakeholder_group": st.column_config.TextColumn(
                "Stakeholder Group",
            ),
            "voting_power": st.column_config.NumberColumn(
                "Voting Power",
                min_value=0.0,
                step=0.01,
                required=True,
            ),
        },
        disabled=["group_id", "stakeholder_group"],
        hide_index=True,
        num_rows="fixed",
    )

    weights = {
        row["group_id"]: float(row["voting_power"])
        for row in edited_rows
    }

    # This is separate from the widget's own state so custom values
    # survive temporarily switching to Equal or Scenario Default.
    st.session_state[state_key] = weights

    return weights

    # with st.form("create-session"):
    #     title = st.text_input(
    #         "Session Title",
    #         value=f"{scenario.title} - {datetime.now():%Y-%m-%d}",
    #     )
    #     description = st.text_area("Session Description")
    #     admin_notes = st.text_area("Admin Notes")

    #     visibility = st.radio(
    #         "Session Visibility",
    #         options=list(SessionVisibility),
    #         format_func=lambda option: option.value,
    #         horizontal=True,
    #     )

    #     participation_method = st.radio(
    #         "Participation Method",
    #         options=list(ParticipationMethod),
    #         format_func=lambda option: option.value,
    #     )

    #     preference_scale = st.selectbox(
    #         "Preference Scale",
    #         options=list(PreferenceScale),
    #         format_func=lambda option: option.value,
    #     )

    #     weighting_method = st.selectbox(
    #         "Weighting Method",
    #         options=list(WeightingMethod),
    #         format_func=lambda option: option.value,
    #     )

    #     ranking_method = st.selectbox(
    #         "Ranking Method",
    #         options=list(RankingMethod),
    #         format_func=lambda option: option.value,
    #     )

    #     aggregation_method = st.selectbox(
    #         "Aggregation Method",
    #         options=list(AggregationMethod),
    #         format_func=lambda option: option.value,
    #     )

    #     require_access_code = st.toggle("Require Access Code")

    #     access_code_type = None
    #     if require_access_code:
    #         access_code_type = st.selectbox(
    #             "Access Code Type",
    #             options=[
    #                 "Shared Session Code",
    #                 "Unique Participant Codes",
    #             ],
    #         )

    #     allow_resubmissions = st.toggle("Allow Resubmissions")

    #     start_at = st.datetime_input(
    #         "Start Date & Time",
    #         value=datetime.now(),
    #     )
    #     end_at = st.datetime_input(
    #         "End Date & Time",
    #         value=datetime.now() + timedelta(days=30),
    #     )

    #     stakeholder_groups = scenario.scenario.get(
    #         "stakeholder_groups",
    #         [],
    #     )
    #     voting_power = {
    #         group["id"]: float(
    #             group.get("default_group_voting_power", 1.0)
    #         )
    #         for group in stakeholder_groups
    #     }

    #     submitted = st.form_submit_button(
    #         "Create Session",
    #         type="primary",
    #     )

    # if not submitted:
    #     return None

    # if not title.strip():
    #     st.error("Session title is required.")
    #     return None

    # return CreateSessionCommand(
    #     scenario=scenario,
    #     title=title.strip(),
    #     description=description.strip() or None,
    #     admin_notes=admin_notes.strip() or None,
    #     visibility=visibility,
    #     participation_method=participation_method,
    #     preference_scale=preference_scale,
    #     weighting_method=weighting_method,
    #     ranking_method=ranking_method,
    #     aggregation_method=aggregation_method,
    #     require_access_code=require_access_code,
    #     access_code_type=access_code_type,
    #     allow_resubmissions=allow_resubmissions,
    #     start_at=start_at,
    #     end_at=end_at,
    #     voting_power=voting_power,
    #     actor_id=actor_id,
    # )
