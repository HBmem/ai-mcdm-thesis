from __future__ import annotations

import json
from typing import Any

import pandas as pd

from dashboard.scenario_loader import ScenarioBundle
from dashboard.utils.time import utc_now_iso
from dashboard.weighting import WeightingError, compute_group_ahp_result, compute_submission_ahp_result
from dashboard.repositories import (
    get_latest_preprocessing_run,
    get_session,
    list_participants,
    list_preprocessing_step_logs,
    list_submissions,
    save_export_record
)

def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)

def _build_submission_weight_derivation_input(submission: dict[str, Any]) -> dict[str, Any]:
    transformed = _json_loads(submission.get("transformed_preferences_json")) or {}

    pairwise_payload = (
        transformed.get("ahp_pairwise_matrix")
        or transformed.get("rating_derived_pairwise_matrix")
    )

    result = {
        "preference_input_method": submission.get("preference_method"),
        "transformation_strategy": transformed.get("strategy"),
        "ahp_pairwise_matrix": pairwise_payload,
        "numeric_scores": transformed.get("numeric_scores"),
        "normalized_direct_weights": transformed.get("normalized_direct_weights"),
    }

    try:
        result["pydecision_ahp_result"] = compute_submission_ahp_result(submission)
    except Exception as exc:
        result["pydecision_ahp_result"] = {
            "status": "not_available",
            "error": str(exc),
        }

    return result

def build_stakeholder_submission_export(
    bundle: ScenarioBundle,
    session_id: str,
    submission: dict[str, Any],
    participant: dict[str, Any],
) -> dict[str, Any]:
    session = get_session(session_id)
    return{
        "contract_type": "stakeholder_submission_export",
        "contract_version": "1.0",
        "session": {
            "session_id": session_id,
            "scenario_id": bundle.scenario_id,
            "scenario_version": bundle.scenario_version,
            "status": session["status"] if session else None,
        },
        "participant": {
            "participant_id": participant["participant_id"],
            "stakeholder_type_id": participant["stakeholder_type_id"],
            "default_voting_power": participant["default_voting_power"],
            "override_voting_power": participant["override_voting_power"],
            "effective_voting_power": participant["effective_voting_power"],
            "normalized_voting_power": participant["normalized_voting_power"],
        },
        "preference_method": submission["preference_method"],
        "raw_preferences": _json_loads(submission["raw_preferences_json"]),
        "transformed_preferences": _json_loads(submission["transformed_preferences_json"]),
        "weight_derivation_input": _build_submission_weight_derivation_input(submission),
        "validation": {"complete": submission["validation_status"] == "valid", "errors": []},
        "submitted_at": submission["submitted_at"],
        "created_at": utc_now_iso(),
    }

def build_session_approved_export(bundle: ScenarioBundle, session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    participants = list_participants(session_id)
    submissions = list_submissions(session_id)
    submission_by_participant = {s["participant_id"]: s for s in submissions}

    participant_exports = []
    for p in participants:
        current_submission = submission_by_participant.get(p["participant_id"])
        participant_exports.append(
            {
                "participant_id": p["participant_id"],
                "stakeholder_type_id": p["stakeholder_type_id"],
                "status": p["status"],
                "effective_voting_power": p["effective_voting_power"],
                "normalized_voting_power": p["normalized_voting_power"],
                "submission_id": current_submission["submission_id"] if current_submission else None,
            }
        )

        try:
            group_ahp_result = compute_group_ahp_result(submissions) if submissions else None
        except Exception as exc:
            group_ahp_result = {
                "status": "not_available",
                "error": str(exc),
            }

    return {
        "contract_type": "session_approved_export",
        "contract_version": "1.0",
        "session": {
            "session_id": session_id,
            "scenario_id": bundle.scenario_id,
            "scenario_version": bundle.scenario_version,
            "status": session["status"] if session else None,
            "mode": session["mode"] if session else None,
            "selected_weighting_method": session["selected_weighting_method"] if session else None,
            "selected_ranking_method": session["selected_ranking_method"] if session else None,
        },
        "scenario_snapshot": {
            "title": bundle.title,
            "domain": bundle.domain,
            "config_hash": bundle.config_hash,
        },
        "criteria": [
            {
                "id": c["id"],
                "name": c.get("name", c["id"]),
                "criteria_type": c.get("criteria_type"),
                "data_type": c.get("data_type", "numeric"),
            }
            for c in bundle.criteria
        ],
        "alternatives": [
            {"id": a["id"], "name": a.get("name", a["id"])}
            for a in bundle.scenario.get("alternatives", [])
        ],
        "participants": participant_exports,
        "weight_derivation": {
            "selected_weighting_method": session["selected_weighting_method"] if session else None,
            "preference_input_method": "criterion_linguistic_rating",
            "transformation_strategy": "linguistic_rating_to_generated_pairwise_matrix",
            "pydecision_method": "ahp_method",
            "group_ahp_result": group_ahp_result,
        },
        "submissions": [
            {
                "submission_id": s["submission_id"],
                "participant_id": s["participant_id"],
                "stakeholder_type_id": s["stakeholder_type_id"],
                "normalized_voting_power": s["normalized_voting_power"],
                "raw_preferences": _json_loads(s["raw_preferences_json"]),
                "transformed_preferences": _json_loads(s["transformed_preferences_json"]),
                "weight_derivation_input": _build_submission_weight_derivation_input(s),
            }
            for s in submissions
        ],
        "aggregation_policy": {
            "voting_power_mode": "participant_effective_power",
            "normalize_submitted_only": False,
            "pairwise_aggregation": "weighted_geometric_mean_deferred",
            "weight_vector_aggregation": "weighted_arithmetic_mean_ready",
        },
        "readiness": {
            "ready_for_weight_derivation": len(submissions) > 0,
            "ready_for_preprocessing": bundle.preprocessing is not None,
            "ready_for_ranking": False,
        },
        "created_at": utc_now_iso(),
    }

def build_preprocessing_metadata_export(
    bundle: ScenarioBundle,
    session_id: str,
    decision_matrix: pd.DataFrame | None = None,
    preprocessing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest_run = get_latest_preprocessing_run(session_id)
    step_logs = list_preprocessing_step_logs(latest_run["run_id"]) if latest_run else []
    final_output = None
    if decision_matrix is not None:
        final_output = {
            "format": "records",
            "alternative_id_column": bundle.preprocessing.get("final_output", {}).get("alternative_id_column") if bundle.preprocessing else None,
            "criteria_columns": bundle.preprocessing.get("final_output", {}).get("criteria_columns", []) if bundle.preprocessing else [],
            "records": decision_matrix.to_dict(orient="records"),
        }

    return {
        "contract_type": "preprocessing_metadata_export",
        "contract_version": "1.0",
        "session": {
            "session_id": session_id,
            "scenario_id": bundle.scenario_id,
            "scenario_version": bundle.scenario_version,
        },
        "preprocessing_run": latest_run or preprocessing_metadata,
        "data_sources": bundle.data_sources.get("data_sources", []),
        "decision_matrix": final_output,
        "criteria_metadata": {
            c["id"]: {
                "criteria_type": c.get("criteria_type"),
                "unit": c.get("unit"),
                "data_type": c.get("data_type", "numeric"),
            }
            for c in bundle.criteria
        },
        "step_logs": step_logs or (preprocessing_metadata or {}).get("step_logs", []),
        "validation": {"valid_matrix": decision_matrix is not None, "errors": [], "warnings": []},
        "created_at": utc_now_iso(),
    }


def persist_export(session_id: str | None, payload: dict[str, Any], created_by: str | None = None) -> str:
    return save_export_record(
        session_id=session_id,
        export_type=payload["contract_type"],
        contract_version=payload.get("contract_version", "1.0"),
        payload=payload,
        created_by=created_by,
    )
