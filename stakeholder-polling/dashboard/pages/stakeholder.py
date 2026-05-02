from __future__ import annotations

import streamlit as st

from dashboard.scenario_loader import ScenarioBundle, get_scenario_by_key
from dashboard.ui_components import (
    format_session_option,
    render_alternative_cards,
    render_criterion_cards,
    render_scenario_card,
)
from dashboard.preferences import (
    PreferenceValidationError,
    scale_labels,
    transform_linguistic_preferences,
    validate_preferences,
)
from dashboard.repositories import (
    create_participant,
    create_submission,
    find_participant_by_access_code,
    get_current_submission,
    get_participant,
    get_session,
    list_sessions,
    update_participant_identity,
)


def render_stakeholder_dashboard(scenarios: list[ScenarioBundle]) -> None:
    st.header("🗳️ Stakeholder Dashboard")
    st.write("Identify yourself, review the selected scenario, and submit your criterion preferences.")

    step = st.session_state.get("stakeholder_step", "identify")

    with st.container(border=True):
        if step == "identify":
            render_identification_step(scenarios)
        elif step == "summary":
            render_summary_step(scenarios)
        elif step == "review":
            render_review_step(scenarios)
        elif step == "preferences":
            render_preference_step(scenarios)
        elif step == "status":
            render_status_step()
        else:
            st.session_state["stakeholder_step"] = "identify"
            st.rerun()

def _selected_bundle(scenarios: list[ScenarioBundle]) -> ScenarioBundle | None:
    key = st.session_state.get("stakeholder_scenario_key")
    return get_scenario_by_key(scenarios, key) if key else None

def render_identification_step(scenarios: list[ScenarioBundle]) -> None:
    open_sessions = list_sessions(["open"])
    if not open_sessions:
        st.info("No open polling sessions are currently available. Ask a moderator to create one.")
        return

    session_options = {format_session_option(s): s for s in open_sessions}
    selected_label = st.selectbox("Select an open polling session", list(session_options.keys()))
    selected_session = session_options[selected_label]
    scenario_key = f"{selected_session['scenario_id']}:{selected_session['scenario_version']}"
    bundle = get_scenario_by_key(scenarios, scenario_key)
    if not bundle:
        st.error("This session refers to a scenario that is not currently available on disk.")
        return
    
    render_scenario_card(bundle)

    with st.form("stakeholder_identification_form"):
        name = st.text_input("Name or alias", help="You may use a real name or a research alias.")
        alias = st.text_input("Optional alias", help="Optional display alias for the session.")
        stakeholder_types = {g["label"]: g for g in bundle.stakeholder_groups}
        selected_type_label = st.selectbox("Stakeholder type", list(stakeholder_types.keys()))
        access_code = ""
        if selected_session["require_access_code"]:
            access_code = st.text_input("Invitation/access code", type="password")
            st.caption("Access codes are created by the moderator for invited participants.")
        submitted = st.form_submit_button("Continue")

    if not submitted:
        return

    if not name.strip():
        st.error("Please provide a name or alias before continuing.")
        return
    
    stakeholder_type = stakeholder_types[selected_type_label]
    try:
        if selected_session["require_access_code"]:
            participant = find_participant_by_access_code(selected_session["session_id"], access_code)
            if not participant:
                st.error("Invalid or expired access code.")
                return
            if participant["stakeholder_type_id"] != stakeholder_type["id"]:
                st.error("The selected stakeholder type does not match this access code.")
                return
            if get_current_submission(selected_session["session_id"], participant["participant_id"]):
                st.error("This participant has already submitted preferences for this session.")
                return
            participant_id = participant["participant_id"]
            update_participant_identity(participant_id, name.strip(), alias.strip() or None)
        else:
            participant_id, _ = create_participant(
                session_id=selected_session["session_id"],
                stakeholder_type_id=stakeholder_type["id"],
                default_voting_power=float(stakeholder_type.get("default_group_voting_power", 1.0)),
                display_name=name.strip(),
                require_access_code=False,
            )

        st.session_state["stakeholder_session_id"] = selected_session["session_id"]
        st.session_state["stakeholder_scenario_key"] = scenario_key
        st.session_state["stakeholder_participant_id"] = participant_id
        st.session_state["stakeholder_step"] = "summary"
        st.rerun()
    except Exception as exc:
        st.error(f"Could not start stakeholder session: {exc}")

def render_summary_step(scenarios: list[ScenarioBundle]) -> None:
    bundle = _selected_bundle(scenarios)
    if not bundle:
        st.error("Scenario context is missing. Please restart the stakeholder flow.")
        if st.button("Restart", width="stretch"):
            st.session_state["stakeholder_step"] = "identify"
            st.rerun()
        return
    
    render_scenario_card(bundle)
    st.markdown("### Minimal Instructions")
    st.write(
        bundle.ui_config.get(
            "intro_text",
            "You will review the scenario and rate how important each criterion is to your evaluation.",
        )
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back", width='stretch'):
            st.session_state["stakeholder_step"] = "identify"
            st.rerun()
    with col2:
        if st.button("Review full scenario", type="primary", width='stretch'):
            st.session_state["stakeholder_step"] = "review"
            st.rerun()

def render_review_step(scenarios: list[ScenarioBundle]) -> None:
    bundle = _selected_bundle(scenarios)
    if not bundle:
        st.error("Scenario context is missing.")
        return

    st.subheader(bundle.title)
    st.markdown("### Policy Question")
    st.info(bundle.scenario.get("policy_question", "No policy question provided."))

    st.markdown("### Scenario Description")
    st.write(bundle.scenario.get("description", bundle.scenario.get("summary", "No description provided.")))

    with st.expander("Alternatives", expanded=False):
        render_alternative_cards(bundle.scenario.get("alternatives", []))

    with st.expander("Criteria", expanded=False):
        st.write("Benefit criteria are better when larger. Cost criteria are better when smaller.")
        render_criterion_cards(bundle.criteria)

    st.markdown("### Voting Instructions")
    st.write(
        bundle.ui_config.get(
            "voting_instructions",
            "Rate the importance of each criterion using the configured linguistic scale.",
        )
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Back to summary", width='stretch'):
            st.session_state["stakeholder_step"] = "summary"
            st.rerun()
    with col2:
        if st.button("Start preferences", type="primary", width='stretch'):
            st.session_state["stakeholder_step"] = "preferences"
            st.rerun()

def render_preference_step(scenarios: list[ScenarioBundle]) -> None:
    bundle = _selected_bundle(scenarios)
    session_id = st.session_state.get("stakeholder_session_id")
    participant_id = st.session_state.get("stakeholder_participant_id")
    if not bundle or not session_id or not participant_id:
        st.error("Stakeholder context is missing. Please restart the stakeholder flow.")
        return

    session = get_session(session_id)
    if not session or session["status"] != "open":
        st.warning("This session is no longer open for submissions.")
        return

    labels = scale_labels(bundle)
    st.subheader("Submit Criterion Preferences")
    st.write("Select how important each criterion is for this scenario. All required criteria must be rated.")

    raw: dict[str, str] = {}
    with st.form("preference_form"):
        for c in sorted(bundle.criteria, key=lambda x: x.get("display_order", 999)):
            with st.container(border=True):
                st.markdown(f"**{c.get('name', c['id'])}**")
                st.caption(f"Criteria Type: {c.get('criteria_type', 'unknown').upper()} | Unit: {c.get('unit', 'n/a')}")
                st.write(c.get("description", ""))
                raw[c["id"]] = st.select_slider(
                    f"Importance for {c.get('name', c['id'])}",
                    options=labels,
                    value="Medium" if "Medium" in labels else labels[0],
                    key=f"pref_{c['id']}",
                )
        comments = st.text_area("Optional comment for moderator/research notes")
        submitted = st.form_submit_button("Submit preferences", type="primary")

    if not submitted:
        return

    try:
        validate_preferences(bundle, raw)
        transformed = transform_linguistic_preferences(bundle, raw)
        if comments.strip():
            transformed["stakeholder_comment"] = comments.strip()
        submission_id = create_submission(
            session_id=session_id,
            participant_id=participant_id,
            preference_method=bundle.preference_collection.get("default_method", "criterion_linguistic_rating"),
            raw_preferences=raw,
            transformed_preferences=transformed,
            allow_resubmission=bool(session["allow_resubmission"]),
        )
        st.session_state["stakeholder_submission_id"] = submission_id
        st.session_state["stakeholder_step"] = "status"
        st.rerun()
    except PreferenceValidationError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Could not save submission: {exc}")

def render_status_step() -> None:
    session_id = st.session_state.get("stakeholder_session_id")
    participant_id = st.session_state.get("stakeholder_participant_id")
    participant = get_participant(participant_id) if participant_id else None
    session = get_session(session_id) if session_id else None

    st.success("Your preferences were submitted successfully.")
    if participant:
        st.write(f"Participant status: **{participant['status']}**")
    if session:
        if session["status"] in {"open", "locked"}:
            st.info("Waiting for the moderator to lock the session and trigger downstream processing.")
        elif session["status"] == "processing_ready":
            st.info("The session export is ready for downstream MCDM processing.")
        elif session["status"] == "completed":
            st.success("Processing is complete. Results may be available through the moderator or results dashboard.")

    if st.button("Start another submission"):
        for key in [
            "stakeholder_step",
            "stakeholder_session_id",
            "stakeholder_scenario_key",
            "stakeholder_participant_id",
            "stakeholder_submission_id",
        ]:
            st.session_state.pop(key, None)
        st.rerun()