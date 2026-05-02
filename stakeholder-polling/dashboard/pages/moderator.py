from __future__ import annotations

import json
import time

import pandas as pd
import streamlit as st

from dashboard.exports import build_preprocessing_metadata_export, build_session_approved_export, persist_export
from dashboard.preprocessing import PreprocessingError, execute_preprocessing
from dashboard.scenario_loader import ScenarioBundle, get_scenario_by_key
from dashboard.session_manager import SessionStateError, completion_summary, transition_session
from dashboard.ui_components import scenario_label, render_scenario_card
from dashboard.preferences import extract_preference_data
from dashboard.weighting import WeightingError, compute_group_ahp_result, compute_submission_ahp_result
from dashboard.repositories import (
    create_participant,
    create_session,
    delete_submission,
    get_session,
    list_export_records,
    list_participants,
    list_preprocessing_runs,
    list_preprocessing_step_logs,
    list_sessions,
    list_submissions,
    update_voting_power
)

def render_moderator_dashboard(scenarios: list[ScenarioBundle]) -> None:
    st.header("👑 Moderator Dashboard")
    st.write("Create sessions, invite participants, manage voting power, lock sessions, and prepare downstream exports.")

    render_toasts()

    tabs = st.tabs(["Create Session", "Participants", "Submissions & Lock", "Preprocessing Results & Logs", "Exports"])
    with tabs[0]:
        render_create_session(scenarios)
    with tabs[1]:
        render_participant_management(scenarios)
    with tabs[2]:
        render_submission_tracking_and_lock(scenarios)
    with tabs[3]:
        render_preprocessing_results_and_logs(scenarios)
    with tabs[4]:
        render_exports_tab()

def _session_selectbox(label: str, statuses: list[str] | None = None) -> dict | None:
    sessions = list_sessions(statuses)
    if not sessions:
        st.info("No sessions available for this view")
        return None
    options = {f"{s['session_name']} | {s['status']} | {s['session_id']}": s for s in sessions}
    chosen = st.selectbox(label, list(options.keys()))
    return options[chosen]

def push_toast(
    kind: str,
    message: str,
    *,
    duration: int | str = 8,
) -> None:
    """
    Store a toast message that should appear after the next rerun.

    kind:
        success, info, warning, error

    duration:
        - "short" = about 4 seconds
        - "long" = about 10 seconds
        - "infinite" = until dismissed
        - int = custom number of seconds
    """
    st.session_state.setdefault("_toast_messages", [])
    st.session_state["_toast_messages"].append(
        {
            "kind": kind,
            "message": message,
            "duration": duration,
        }
    )


def render_toasts() -> None:
    """
    Render queued toast messages and remove them from session state.

    This should be called once near the top of render_moderator_dashboard().
    The toast is created after the rerun, so it has time to display.
    """
    messages = st.session_state.pop("_toast_messages", [])

    icon_by_kind = {
        "success": "✅",
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "❌",
    }

    for msg in messages:
        kind = msg.get("kind", "info")
        message = msg.get("message", "")
        duration = msg.get("duration", 8)

        st.toast(
            message,
            icon=icon_by_kind.get(kind, "ℹ️"),
            duration=duration,
        )

def render_create_session(scenarios: list[ScenarioBundle]) -> None:
    if not scenarios:
        st.error("No valid scenarios found under ./scenarios. Please add at least one scenario folder with a valid scenario.json manifest.")
        return
    
    options = {scenario_label(s): s for s in scenarios}
    selected_label = st.selectbox("Scenario", list(options.keys()))
    bundle = options[selected_label]
    render_scenario_card(bundle)

    methods = bundle.scenario.get("mcdm_methods", {})

    weighting_available_options = {
        "AHP": "AHP",
        "FUZZY_AHP": "Fuzzy AHP",
    }

    weighting_options = methods.get("weighting_supported", ["AHP"])
    weighting_options = [m for m in weighting_options if m in weighting_available_options]

    if not weighting_options:
        weighting_options = ["AHP"]

    default_weighting = methods.get("default_weighting", "AHP")
    default_weighting_index = (
        weighting_options.index(default_weighting)
        if default_weighting in weighting_options
        else 0
    )
    
    ranking_available_options = {
        "TOPSIS": "TOPSIS",
        "FUZZY_TOPSIS": "Fuzzy TOPSIS",
    }

    ranking_options = methods.get("ranking_supported", ["TOPSIS"])
    ranking_options = [m for m in ranking_options if m in ranking_available_options]

    if not ranking_options:
        ranking_options = ["TOPSIS"]

    default_ranking = methods.get("default_ranking", "TOPSIS")
    default_ranking_index = (
        ranking_options.index(default_ranking)
        if default_ranking in ranking_options
        else 0
    )

    mode_available_options = {
        "single_stakeholder": "Single Stakeholder",
        "multi_stakeholder": "Multi-Stakeholder"
    }

    with st.form("create_session_form"):
        session_name = st.text_input("Session name", value=f"{bundle.title} Session")
        mode = st.radio("Session mode", list(mode_available_options.keys()), format_func=mode_available_options.get, horizontal=True)
        selected_weighting = st.selectbox(
            "Weighting method",
            weighting_options,
            format_func=weighting_available_options.get,
            index=default_weighting_index,
            help=(
                "This controls how stakeholder preferences are converted into final criteria weights. "
            ),
        )

        selected_ranking = st.selectbox(
            "Ranking method",
            ranking_options,
            format_func=ranking_available_options.get,
            index=default_ranking_index,
        )

        require_access_code = st.checkbox("Require invitation/access codes", value=False)
        allow_resubmission = st.checkbox("Allow resubmission before session lock", value=False)
        require_moderator_lock = st.checkbox("Require moderator lock before processing", value=True)
        submitted = st.form_submit_button("Create polling session", type="primary")
    
    if submitted:
        if not session_name.strip():
            st.error("Session name is required.")
            return
        try:
            session_id = create_session(
                bundle=bundle,
                session_name=session_name.strip(),
                mode=mode,
                selected_weighting_method=selected_weighting,
                selected_ranking_method=selected_ranking,
                require_access_code=require_access_code,
                allow_resubmission=allow_resubmission,
                require_moderator_lock=require_moderator_lock,
                created_by="moderator",
            )
            st.success(f"Created session: {session_id}")
            st.info("Next: add participants and assign voting power.")
        except Exception as exc:
            st.error(f"Could not create session: {exc}")

def _bundle_for_session(scenarios: list[ScenarioBundle], session: dict) -> ScenarioBundle | None:
    key = f"{session['scenario_id']}:{session['scenario_version']}"
    return get_scenario_by_key(scenarios, key) if key else None

def render_participant_management(scenarios: list[ScenarioBundle]) -> None:
    session = _session_selectbox("Select session", ["open", "locked", "processing_ready", "completed"])
    if not session:
        return
    bundle = _bundle_for_session(scenarios, session)
    if not bundle:
        st.error("The scenario for this session is not currently available on disk.")
        return
    
    st.subheader(session["session_name"])
    st.caption(f"Session ID: {session['session_id']} | Scenario: {scenario_label(bundle)} | Mode: {session['mode']} | Status: {session['status']}")

    if session["status"] != "open":
        st.warning("Participant management is only available for sessions in 'open' status.")

    groups = {g['label']: g for g in bundle.stakeholder_groups}
    with st.form("add_participant_form"):
        st.markdown("### Add participant")
        display_name = st.text_input("Optional participant display name", help="Leave blank if the participant will identify themselves later.")
        group_label = st.selectbox("Stakeholder group", list(groups.keys()))
        default_power = float(groups[group_label].get("default_group_voting_power", 1.0))
        override_enabled = st.checkbox("Override default voting power")
        override = st.number_input("Override voting power", min_value=0.0, value=default_power, step=0.05) if override_enabled else None
        submitted = st.form_submit_button("Add participant")
    
    if submitted:
        try:
            participant_id, access_code = create_participant(
                session_id=session["session_id"],
                stakeholder_type_id=groups[group_label]["id"],
                default_voting_power=default_power,
                display_name=display_name.strip() or None,
                override_voting_power=override,
                require_access_code=bool(session["require_access_code"]),
            )
            st.success(f"Added participant: {participant_id}")
            if access_code:
                st.code(access_code, language="text")
                st.caption("Copy this code now. Only its hash is stored in the database.")
        except Exception as exc:
            st.error(f"Could not add participant: {exc}")

    participants = list_participants(session["session_id"])
    if participants:
        st.markdown("### Current Participants")
        st.dataframe(pd.DataFrame(participants), width='stretch')

        with st.expander("Edit a participant voting power"):
            participant_options = {f"{p['participant_id']} | {p['stakeholder_type_id']} | {p['status']}": p for p in participants}
            selected = st.selectbox("Participant", list(participant_options.keys()))
            target = participant_options[selected]
            with st.form("edit_power_form"):
                override_power = st.number_input("Override voting power", min_value=0.0, value=float(target["effective_voting_power"]), step=0.05)
                reason = st.text_input("Reason for override")
                update = st.form_submit_button("Save override")
            if update:
                try:
                    update_voting_power(target["participant_id"], override_power, reason or None)
                    push_toast("success", "Voting power updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not update voting power: {exc}")
    else:
        st.info("No participants added yet.")

def render_submission_tracking_and_lock(scenarios: list[ScenarioBundle]) -> None:
    session = _session_selectbox("Select session to monitor", ["open", "locked", "preprocessing", "processing_ready", "completed"])
    if not session:
        return
    bundle = _bundle_for_session(scenarios, session)
    if not bundle:
        st.error("The scenario for this session is not currently available on disk.")
        return
    
    st.subheader(session["session_name"])
    st.caption(f"Status: {session['status']} | Session ID: {session['session_id']}")
    summary = completion_summary(session["session_id"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Participants", summary["total_participants"])
    c2.metric("Submitted", summary["submitted_participants"])
    c3.metric("Completion", f"{summary['completion_ratio']:.0%}")
    c4.metric("Submitted Power", f"{summary['submitted_normalized_power']:.0%}")

    submissions = list_submissions(session["session_id"])
    participants = list_participants(session["session_id"])
    st.markdown("### Participant Status")
    if participants:
        st.dataframe(pd.DataFrame(participants), width='stretch')
    else:
        st.info("No participants yet.")

    st.markdown("### Submissions")
    if submissions:
        lightweight = [
            {
                "submission_id": s["submission_id"],
                "participant_id": s["participant_id"],
                "stakeholder_type_id": s["stakeholder_type_id"],
                "submitted_at": s["submitted_at"],
                "normalized_voting_power": s["normalized_voting_power"],
            }
            for s in submissions
        ]
        st.dataframe(pd.DataFrame(lightweight), width='stretch')
    else:
        st.info("No submissions yet.")

    st.markdown("### Submissions Management")
    if submissions and session["status"] in {"locked", "preprocessing", "processing_ready"}:
        with st.expander("Delete unauthorized or invalid submissions"):
            st.write("Select a submission to remove from the session. This will reset the participant's status to 'invited'.")
            sub_options = {
                f"{s['participant_id']} | {s['stakeholder_type_id']} | {s['submitted_at']}": s
                for s in submissions
            }
            if sub_options:
                selected_sub = st.selectbox("Submission to delete", list(sub_options.keys()), key="delete_submission_select")
                target_sub = sub_options[selected_sub]
                
                col_del1, col_del2 = st.columns([1, 1])
                with col_del1:
                    if st.button("Delete submission", type="secondary"):
                        with st.spinner("Deleting submission..."):
                            try:
                                delete_submission(target_sub["submission_id"])
                                push_toast("success", f"Submission deleted. Participant status reset to 'invited'.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Could not delete submission: {exc}")
                with col_del2:
                    st.info("⚠️ This action cannot be undone within this interface. Database backups may exist.")
    elif submissions:
        st.info("Submission management is only available when session is locked or preprocessing.")

    st.markdown("### Preference Matrix Analysis")
    if submissions:
        with st.expander("View stakeholder preference matrices and scores", expanded=False):
            pref_data = extract_preference_data(submissions)

            submission_by_participant = {
                s["participant_id"]: s
                for s in submissions
            }
            
            view_mode = st.radio(
                "Display mode",
                ["Aggregate Scores by Criterion", "Individual Stakeholder Matrices", "Numeric Comparison Table", "Group AHP Result"],
                index=0,
                horizontal=True,
            )
            
            if view_mode == "Aggregate Scores by Criterion":
                st.write("**Average scores and weights by criterion across all stakeholders**")
                criteria_order = pref_data.get("criteria_order", [])
                if criteria_order and pref_data["all_stakeholders"]["numeric_scores"]:
                    # Build aggregated table
                    agg_data = []
                    for criterion_id in criteria_order:
                        scores = pref_data["all_stakeholders"]["numeric_scores"].get(criterion_id, [])
                        weights = pref_data["all_stakeholders"]["normalized_weights"].get(criterion_id, [])
                        
                        agg_data.append({
                            "Criterion": criterion_id,
                            "Avg Score": round(sum(scores) / len(scores), 2) if scores else 0,
                            "Min Score": min(scores) if scores else 0,
                            "Max Score": max(scores) if scores else 0,
                            "Avg Weight": round(sum(weights) / len(weights), 4) if weights else 0,
                            "# Responses": len(scores),
                        })
                    
                    st.dataframe(pd.DataFrame(agg_data), width='stretch')
                else:
                    st.info("No aggregated data available.")
            
            elif view_mode == "Individual Stakeholder Matrices":
                st.write("**Detailed preference data for each stakeholder**")
                stakeholder_options = {
                    f"{sid} | {data['stakeholder_type']}": sid
                    for sid, data in pref_data["by_stakeholder"].items()
                }
                
                if stakeholder_options:
                    selected_stakeholder = st.selectbox(
                        "Select stakeholder",
                        list(stakeholder_options.keys()),
                        key="matrix_stakeholder_select",
                    )
                    stakeholder_id = stakeholder_options[selected_stakeholder]
                    stakeholder_data = pref_data["by_stakeholder"][stakeholder_id]
                    
                    st.write(f"**Numeric Scores**")
                    scores_df = pd.DataFrame(
                        list(stakeholder_data["numeric_scores"].items()),
                        columns=["Criterion", "Score"],
                    )
                    st.dataframe(scores_df, width='stretch')
                    
                    st.write(f"**Normalized Weights**")
                    weights_df = pd.DataFrame(
                        list(stakeholder_data["normalized_weights"].items()),
                        columns=["Criterion", "Weight"],
                    )
                    st.dataframe(weights_df, width='stretch')
                    
                    if stakeholder_data["pairwise_matrix"]:
                        st.write(f"**AHP Pairwise Matrix**")
                        matrix_data = stakeholder_data["pairwise_matrix"]
                        criteria_order_matrix = matrix_data.get("criteria_order", [])
                        matrix_values = matrix_data.get("matrix", [])
                        
                        if criteria_order_matrix and matrix_values:
                            matrix_df = pd.DataFrame(
                                matrix_values,
                                index=criteria_order_matrix,
                                columns=criteria_order_matrix,
                            )
                            st.dataframe(matrix_df.round(4), width='stretch')
                    
                    st.write("**AHP Weights**")
                    try:
                        selected_submission = submission_by_participant.get(stakeholder_id)
                        if selected_submission:
                            ahp_result = compute_submission_ahp_result(selected_submission)

                            ahp_weights_df = pd.DataFrame(
                                list(ahp_result["weights"].items()),
                                columns=["Criterion", "AHP Weight"],
                            )

                            st.dataframe(ahp_weights_df, width="stretch")

                            metric_col_1, metric_col_2 = st.columns(2)
                            metric_col_1.metric(
                                "Consistency Ratio",
                                round(ahp_result["consistency_ratio"], 4),
                            )
                            metric_col_2.metric(
                                "Consistent?",
                                "Yes" if ahp_result["is_consistent"] else "No",
                            )

                            if not ahp_result["is_consistent"]:
                                st.warning(
                                    "The generated AHP matrix has a consistency ratio above 0.10. "
                                    "For a generated matrix this may indicate that the rating-to-pairwise "
                                    "conversion strategy should be reviewed."
                                )
                    except WeightingError as exc:
                        st.warning(f"Could not compute AHP weights for this stakeholder: {exc}")
                    except Exception as exc:
                        st.error(f"Unexpected AHP calculation error: {exc}")
                else:
                    st.info("No stakeholders available.")
            
            elif view_mode == "Numeric Comparison Table":
                st.write("**All numeric scores side-by-side by stakeholder**")
                criteria_order = pref_data.get("criteria_order", [])
                
                if criteria_order:
                    comparison_data = {}
                    for criterion_id in criteria_order:
                        comparison_data[criterion_id] = {}
                        for stakeholder_id, stakeholder_data in pref_data["by_stakeholder"].items():
                            score = stakeholder_data["numeric_scores"].get(criterion_id, "-")
                            comparison_data[criterion_id][stakeholder_id] = score
                    
                    # Transform to DataFrame format
                    rows = []
                    for criterion_id, stakeholder_scores in comparison_data.items():
                        row = {"Criterion": criterion_id}
                        row.update(stakeholder_scores)
                        rows.append(row)
                    
                    comparison_df = pd.DataFrame(rows)
                    st.dataframe(comparison_df, width='stretch')
                else:
                    st.info("No criteria data available.")

            elif view_mode == "Group AHP Result":
                st.markdown("### Group AHP Result")
                st.write(
                    "This uses the submitted stakeholder pairwise matrices and combines them "
                    "using stakeholder voting power."
                )

                try:
                    group_ahp = compute_group_ahp_result(submissions)

                    group_weights_df = pd.DataFrame(
                        list(group_ahp["group_weights"].items()),
                        columns=["Criterion", "Group AHP Weight"],
                    )

                    st.write("**Group AHP Weights**")
                    st.dataframe(group_weights_df, width="stretch")

                    group_matrix_df = pd.DataFrame(
                        group_ahp["aggregate_pairwise_matrix"],
                        index=group_ahp["criteria_order"],
                        columns=group_ahp["criteria_order"],
                    )

                    st.write("**Aggregated Group Pairwise Matrix**")
                    st.dataframe(group_matrix_df.round(4), width="stretch")

                    metric_col_1, metric_col_2 = st.columns(2)
                    metric_col_1.metric(
                        "Group Consistency Ratio",
                        round(group_ahp["consistency_ratio"], 4),
                    )
                    metric_col_2.metric(
                        "Group Matrix Consistent?",
                        "Yes" if group_ahp["is_consistent"] else "No",
                    )

                except WeightingError as exc:
                    st.warning(f"Could not compute group AHP result: {exc}")
                except Exception as exc:
                    st.error(f"Unexpected group AHP calculation error: {exc}")
    else:
        st.info("Preference matrix analysis requires at least one submission.")

    st.markdown("### Session Actions")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if session["status"] == "open":
            if st.button("Lock session", type="primary", width='stretch'):
                try:
                    transition_session(session["session_id"], "locked")
                    push_toast("success", "Session locked. No more submissions are allowed.")
                    st.rerun()
                except SessionStateError as exc:
                    st.error(str(exc))
        else:
            st.button("Lock session", disabled=True, width='stretch')

    with col2:
        can_preprocess = session["status"] in {"locked", "processing_ready"}

        if st.button("Run preprocessing", disabled=not can_preprocess, width="stretch"):
            try:
                if session["status"] == "locked":
                    transition_session(session["session_id"], "preprocessing")

                df, metadata = execute_preprocessing(bundle, session_id=session["session_id"])

                transition_session(session["session_id"], "processing_ready")

                st.session_state.last_preprocessing_result = {
                    "df": df,
                    "metadata": metadata,
                    "status": "success",
                    "timestamp": pd.Timestamp.now().isoformat(),
                    "session_id": session["session_id"],
                }

                push_toast(
                    "success",
                    "Preprocessing completed successfully. The session was marked as processing_ready."
                )
                st.rerun()

            except (PreprocessingError, SessionStateError, Exception) as exc:
                st.session_state.last_preprocessing_result = {
                    "status": "failed",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "timestamp": pd.Timestamp.now().isoformat(),
                    "session_id": session["session_id"],
                }

                rollback_message = ""

                try:
                    current_session = get_session(session["session_id"])

                    if current_session and current_session["status"] == "preprocessing":
                        transition_session(session["session_id"], "locked")
                        rollback_message = " Session was rolled back to locked state."

                except Exception as rollback_exc:
                    rollback_message = f" Rollback failed: {rollback_exc}"

                push_toast("error", f"Preprocessing failed: {type(exc).__name__}: {exc}.{rollback_message}")
                push_toast("info", "Open the Preprocessing Runs & Logs tab to inspect the failed run and failed step details.")
                st.rerun()

    with col3:
        can_export = session["status"] in {"locked", "processing_ready", "completed"}
        if st.button("Create session export", disabled=not can_export, width='stretch'):
            try:
                payload = build_session_approved_export(bundle, session["session_id"])
                export_id = persist_export(session["session_id"], payload, created_by="moderator")
                push_toast("success", f"Session export saved: {export_id}")
                st.rerun()
            except Exception as exc:
                push_toast("error", f"Could not create export: {exc}")
                st.rerun()

def render_preprocessing_results_and_logs(scenarios: list[ScenarioBundle]) -> None:
    st.subheader("Preprocessing Runs & Logs")
    st.write(
        "Review all preprocessing attempts, including failed runs and failed step details. "
        "This view reads from the database, so it is more reliable than Streamlit session state."
    )

    sessions = list_sessions(None)

    if not sessions:
        st.info("No polling sessions exist yet.")
        return

    session_options = {
        f"{s['session_name']} | {s['status']} | {s['session_id']}": s
        for s in sessions
    }

    selected_session_label = st.selectbox(
        "Select session",
        list(session_options.keys()),
        key="preprocessing_logs_session_select",
    )
    session = session_options[selected_session_label]

    # *** BROWSER RESULT MOVED TO TOP ***
    if (
        "last_preprocessing_result" in st.session_state
        and st.session_state.last_preprocessing_result
        and st.session_state.last_preprocessing_result.get("session_id") == session["session_id"]
    ):
        result = st.session_state.last_preprocessing_result

        with st.expander("Current Browser Latest Preprocessing Result", expanded=False):
            if result["status"] == "success":
                st.success(f"Latest browser run succeeded at {result['timestamp']}")

                df = result.get("df")
                metadata = result.get("metadata")

                if df is not None:
                    st.write(f"Shape: **{len(df)} rows × {len(df.columns)} columns**")
                    st.dataframe(df, width="stretch")

                if metadata:
                    st.json(metadata)

            else:
                st.error(f"Latest browser run failed at {result['timestamp']}")
                push_toast("error", "Browser preprocessing result shows failure.")
                st.code(result.get("error", "No error message available."), language="text")

    bundle = _bundle_for_session(scenarios, session)

    if not bundle:
        st.warning(
            "The scenario for this session is not currently available on disk. "
            "Run logs can still be displayed, but scenario-based exports may not work."
        )

    st.caption(
        f"Session ID: {session['session_id']} | "
        f"Scenario: {session['scenario_id']}:{session['scenario_version']} | "
        f"Status: {session['status']}"
    )

    col_filter_1, col_filter_2 = st.columns([1, 1])

    with col_filter_1:
        show_failed_only = st.checkbox(
            "Show failed runs only",
            value=False,
            key="show_failed_preprocessing_only",
        )

    with col_filter_2:
        limit = st.number_input(
            "Max runs to show",
            min_value=5,
            max_value=500,
            value=100,
            step=5,
            key="preprocessing_runs_limit",
        )

    runs = list_preprocessing_runs(
        session_id=session["session_id"],
        limit=int(limit),
    )

    if show_failed_only:
        runs = [run for run in runs if run.get("status") == "failed"]

    if not runs:
        st.info("No preprocessing runs found for this session.")
        return

    st.markdown("### Run History")

    run_table = pd.DataFrame(runs)

    preferred_columns = [
        "run_id",
        "status",
        "pipeline_id",
        "started_at",
        "finished_at",
        "row_count",
        "column_count",
        "total_steps",
        "successful_steps",
        "failed_steps",
        "error_code",
        "error_message",
    ]

    visible_columns = [col for col in preferred_columns if col in run_table.columns]

    st.dataframe(
        run_table[visible_columns],
        width="stretch",
        hide_index=True,
    )

    run_options = {
        f"{run['started_at']} | {run['status']} | {run['run_id']}": run
        for run in runs
    }

    selected_run_label = st.selectbox(
        "Select preprocessing run to inspect",
        list(run_options.keys()),
        key="preprocessing_run_select",
    )

    selected_run = run_options[selected_run_label]
    run_id = selected_run["run_id"]

    # *** TABBED INTERFACE FOR RUN DETAILS ***
    tab1, tab2, tab3 = st.tabs(["Run Overview", "Step Analysis", "Metadata Export"])

    # TAB 1: Run Overview
    with tab1:
        st.markdown("#### Selected Run Summary")
        with st.container():
            metric_1, metric_2, metric_3, metric_4 = st.columns(4)

            metric_1.metric("Run Status", selected_run.get("status", "unknown"))
            metric_2.metric("Total Steps", int(selected_run.get("total_steps") or 0))
            metric_3.metric("Failed Steps", int(selected_run.get("failed_steps") or 0))
            metric_4.metric(
                "Output Shape",
                f"{selected_run.get('row_count') or 0} × {selected_run.get('column_count') or 0}",
            )

        with st.expander("View raw preprocessing run record", expanded=False):
            st.json(selected_run)

        if selected_run.get("status") == "failed":
            st.error("This preprocessing run failed.")

            err_col_1, err_col_2 = st.columns(2)

            with err_col_1:
                st.write("**Error Code**")
                st.code(selected_run.get("error_code") or "Unknown", language="text")

            with err_col_2:
                st.write("**Error Message**")
                st.code(selected_run.get("error_message") or "No error message recorded.", language="text")

    # TAB 2: Step Analysis
    with tab2:
        step_logs = list_preprocessing_step_logs(run_id)

        if not step_logs:
            st.info("No step logs were recorded for this run.")
        else:
            st.markdown("#### Step Logs")

            step_df = pd.DataFrame(step_logs)

            step_columns = [
                "step_id",
                "step_type",
                "status",
                "input_ref",
                "output_ref",
                "row_count",
                "column_count",
                "duration_ms",
                "error_code",
                "error_message",
                "started_at",
                "finished_at",
            ]

            visible_step_columns = [col for col in step_columns if col in step_df.columns]

            st.dataframe(
                step_df[visible_step_columns],
                width="stretch",
                hide_index=True,
            )

            successful_steps = [step for step in step_logs if step.get("status") == "success"]
            failed_steps = [step for step in step_logs if step.get("status") != "success"]

            st.markdown("#### Step Summary")
            step_metric_1, step_metric_2, step_metric_3 = st.columns(3)
            step_metric_1.metric("Successful Steps", len(successful_steps))
            step_metric_2.metric("Failed Steps", len(failed_steps))
            step_metric_3.metric(
                "Total Duration",
                f"{sum(int(step.get('duration_ms') or 0) for step in step_logs)} ms",
            )

            if failed_steps:
                st.markdown("#### Failed Step Details")

                for idx, step in enumerate(failed_steps, start=1):
                    with st.expander(
                        f"❌ Failed Step {idx}: {step.get('step_id', 'unknown')} "
                        f"({step.get('step_type', 'unknown')})",
                        expanded=True,
                    ):
                        col_a, col_b = st.columns(2)

                        with col_a:
                            st.write("**Step ID**")
                            st.code(step.get("step_id") or "unknown", language="text")

                            st.write("**Step Type**")
                            st.code(step.get("step_type") or "unknown", language="text")

                            st.write("**Input Ref**")
                            st.code(step.get("input_ref") or "N/A", language="text")

                            st.write("**Output Ref**")
                            st.code(step.get("output_ref") or "N/A", language="text")

                        with col_b:
                            st.write("**Error Code**")
                            st.code(step.get("error_code") or "Unknown", language="text")

                            st.write("**Error Message**")
                            st.code(step.get("error_message") or "No error message recorded.", language="text")

                            st.write("**Duration**")
                            st.code(f"{step.get('duration_ms') or 0} ms", language="text")

                        with st.expander("Raw failed step record"):
                            st.json(step)
            else:
                st.success("No failed steps were recorded for this run.")

            st.markdown("#### Timeline View")

            for idx, step in enumerate(step_logs, start=1):
                icon = "✅" if step.get("status") == "success" else "❌"

                with st.expander(
                    f"{icon} Step {idx}: {step.get('step_id', 'unknown')} "
                    f"({step.get('step_type', 'unknown')})",
                    expanded=False,
                ):
                    col_step_1, col_step_2 = st.columns(2)

                    with col_step_1:
                        st.write(f"**Status:** {step.get('status', 'unknown')}")
                        st.write(f"**Input:** `{step.get('input_ref') or 'N/A'}`")
                        st.write(f"**Output:** `{step.get('output_ref') or 'N/A'}`")
                        st.write(f"**Duration:** {step.get('duration_ms') or 0} ms")

                    with col_step_2:
                        st.write(f"**Rows:** {step.get('row_count') or 0}")
                        st.write(f"**Columns:** {step.get('column_count') or 0}")
                        st.write(f"**Started:** {step.get('started_at') or 'N/A'}")
                        st.write(f"**Finished:** {step.get('finished_at') or 'N/A'}")

                    if step.get("status") != "success":
                        st.error(step.get("error_message") or "Step failed without a recorded error message.")

                    with st.expander("Raw step JSON"):
                        st.json(step)

    # TAB 3: Metadata Export
    with tab3:
        if bundle is None:
            st.info("Metadata export requires the scenario files to be available on disk.")
        else:
            with st.expander("Create preprocessing metadata export from latest run", expanded=True):
                st.write(
                    "This export uses the latest preprocessing run for the selected session. "
                    "It is useful for downstream verification and reporting."
                )

                if st.button("Create preprocessing metadata export", key="create_preprocessing_metadata_export_from_logs"):
                    try:
                        payload = build_preprocessing_metadata_export(bundle, session["session_id"])
                        export_id = persist_export(session["session_id"], payload, created_by="moderator")

                        push_toast(
                            "success",
                            f"Preprocessing metadata export saved: {export_id}"
                        )
                        st.rerun()

                    except Exception as exc:
                        push_toast("error", f"Could not create preprocessing metadata export: {exc}")
                        st.error(f"Could not create preprocessing metadata export: {exc}")

def render_exports_tab() -> None:
    session = _session_selectbox("Filter exports by session", None)
    session_id = session["session_id"] if session else None
    exports = list_export_records(session_id)
    if not exports:
        st.info("No exports created yet.")
        return
    st.dataframe(pd.DataFrame([{k: v for k, v in e.items() if k != "payload_json"} for e in exports]), width='stretch')

    with st.expander("View latest export payload", expanded=False):
        latest = exports[0]
        payload = json.loads(latest["payload_json"])

        st.json(payload)

        st.download_button(
            "Download latest export JSON",
            data=json.dumps(payload, indent=2),
            file_name=f"{latest['export_type']}_{latest['export_id']}.json",
            mime="application/json",
        )