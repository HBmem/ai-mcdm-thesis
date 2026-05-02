from __future__ import annotations

import json
import sqlite3
from typing import Any

from dashboard.db import get_connection
from dashboard.scenario_loader import ScenarioBundle
from dashboard.utils.ids import generate_access_code, hash_access_code, hash_text, new_id
from dashboard.utils.time import utc_now_iso

def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None

class RepositoryError(RuntimeError):
    pass

def save_scenario_snapshot(bundle: ScenarioBundle) -> None:
    now = utc_now_iso()
    snapshot = {
        "scenario": bundle.scenario,
        "criteria": bundle.criteria,
        "data_sources": bundle.data_sources,
        "preprocessing": bundle.preprocessing,
        "session_rules": bundle.session_rules,
        "ui_config": bundle.ui_config,
    }
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO scenarios (
                scenario_id, scenario_version, title, domain, folder_path, config_hash,
                config_snapshot_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(scenario_id, scenario_version) DO UPDATE SET
                title=excluded.title,
                domain=excluded.domain,
                folder_path=excluded.folder_path,
                config_hash=excluded.config_hash,
                config_snapshot_json=excluded.config_snapshot_json,
                updated_at=excluded.updated_at
            """,
            (
                bundle.scenario_id,
                bundle.scenario_version,
                bundle.title,
                bundle.domain,
                str(bundle.folder),
                bundle.config_hash,
                json.dumps(snapshot, indent=2),
                now,
                now,
            ),
        )

def create_session(
    bundle: ScenarioBundle,
    session_name: str,
    mode: str,
    selected_weighting_method: str,
    selected_ranking_method: str,
    require_access_code: bool,
    allow_resubmission: bool,
    require_moderator_lock: bool,
    created_by: str | None = None,
) -> str:
    save_scenario_snapshot(bundle)
    now = utc_now_iso()
    session_id = new_id("sess")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO polling_sessions (
                session_id, scenario_id, scenario_version, session_name, mode, status,
                selected_weighting_method, selected_ranking_method, require_access_code,
                allow_resubmission, require_moderator_lock, created_by, created_at,
                opened_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                bundle.scenario_id,
                bundle.scenario_version,
                session_name,
                mode,
                selected_weighting_method,
                selected_ranking_method,
                int(require_access_code),
                int(allow_resubmission),
                int(require_moderator_lock),
                created_by,
                now,
                now,
                now,
            ),
        )
    return session_id

def list_sessions(statuses: list[str] | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"SELECT * FROM polling_sessions WHERE status IN ({placeholders}) ORDER BY created_at DESC",
                statuses,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM polling_sessions ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]

def get_session(session_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM polling_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return row_to_dict(row)

def update_session_status(session_id: str, status: str) -> None:
    now = utc_now_iso()
    field_updates = "status = ?, updated_at = ?"
    params: list[Any] = [status, now]
    if "locked" == status:
        field_updates += ", locked_at = ?"
        params.append(now)
    elif status == "completed":
        field_updates += ", completed_at = ?"
        params.append(now)
    params.append(session_id)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE polling_sessions SET {field_updates} WHERE session_id = ?", params
        )

def create_or_get_stakeholder(display_name: str, alias: str | None = None, external_ref: str | None = None) -> str:
    # For prototype testing, create a new stakeholder record for each new identification. In production, this should be replaced with a more robust identity management approach.
    now = utc_now_iso()
    stakeholder_id = new_id("stk")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO stakeholders (stakeholder_id, display_name, alias, external_ref, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (stakeholder_id, display_name, alias, external_ref, now, now),
        )
    return stakeholder_id

def create_participant(
    session_id: str,
    stakeholder_type_id: str,
    default_voting_power: float,
    display_name: str | None = None,
    override_voting_power: float | None = None,
    require_access_code: bool = True,
) -> tuple[str, str | None]:
    now = utc_now_iso()
    participant_id = new_id("part")
    stakeholder_id = None
    if display_name:
        stakeholder_id = create_or_get_stakeholder(display_name)

    code = generate_access_code() if require_access_code else None
    code_hash = hash_access_code(code) if code else None
    effective = override_voting_power if override_voting_power is not None else default_voting_power

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO session_participants (
                participant_id, session_id, stakeholder_id, stakeholder_type_id, access_code_hash,
                status, default_voting_power, override_voting_power, effective_voting_power,
                invited_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'invited', ?, ?, ?, ?, ?)
            """,
            (
                participant_id,
                session_id,
                stakeholder_id,
                stakeholder_type_id,
                code_hash,
                default_voting_power,
                override_voting_power,
                effective,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO voting_power_assignments (
                assignment_id, session_id, participant_id, stakeholder_type_id, assignment_scope,
                source, voting_power, created_at
            ) VALUES (?, ?, ?, ?, 'participant', ?, ?, ?)
            """,
            (
                new_id("vpa"),
                session_id,
                participant_id,
                stakeholder_type_id,
                "moderator_override" if override_voting_power is not None else "scenario_default",
                effective,
                now,
            ),
        )
    return participant_id, code

def list_participants(session_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.*, s.display_name, s.alias
            FROM session_participants p
            LEFT JOIN stakeholders s ON s.stakeholder_id = p.stakeholder_id
            WHERE p.session_id = ?
            ORDER BY p.invited_at ASC
            """,
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def get_participant(participant_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM session_participants WHERE participant_id = ?", (participant_id,)
        ).fetchone()
    return row_to_dict(row)

def update_participant_identity(participant_id: str, display_name: str, alias: str | None = None) -> None:
    stakeholder_id = create_or_get_stakeholder(display_name, alias)
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE session_participants
            SET stakeholder_id = ?, status = CASE WHEN status='invited' THEN 'started' ELSE status END,
                started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE participant_id = ?
            """,
            (stakeholder_id, now, now, participant_id),
        )

def find_participant_by_access_code(session_id: str, access_code: str) -> dict[str, Any] | None:
    code_hash = hash_access_code(access_code)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_participants
            WHERE session_id = ? AND access_code_hash = ?
            """,
            (session_id, code_hash),
        ).fetchone()
    return row_to_dict(row)

def update_voting_power(participant_id: str, override_voting_power: float | None, reason: str | None = None) -> None:
    participant = get_participant(participant_id)
    if not participant:
        raise RepositoryError(f"Unknown participant: {participant_id}")
    effective = override_voting_power if override_voting_power is not None else participant["default_voting_power"]
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE session_participants
            SET override_voting_power = ?, effective_voting_power = ?, updated_at = ?
            WHERE participant_id = ?
            """,
            (override_voting_power, effective, now, participant_id),
        )
        conn.execute(
            """
            INSERT INTO voting_power_assignments (
                assignment_id, session_id, participant_id, stakeholder_type_id, assignment_scope,
                source, voting_power, reason, created_at
            ) VALUES (?, ?, ?, ?, 'participant', 'moderator_override', ?, ?, ?)
            """,
            (
                new_id("vpa"),
                participant["session_id"],
                participant_id,
                participant["stakeholder_type_id"],
                effective,
                reason,
                now,
            ),
        )

def normalize_voting_power(session_id: str) -> None:
    participants = list_participants(session_id)
    eligible = [p for p in participants if p["status"] not in {"excluded", "expired"}]
    total = sum(float(p["effective_voting_power"] or 0) for p in eligible)
    now = utc_now_iso()
    with get_connection() as conn:
        for p in participants:
            if p in eligible and total > 0:
                normalized = float(p["effective_voting_power"] or 0) / total
            else:
                normalized = 0.0
            conn.execute(
                "UPDATE session_participants SET normalized_voting_power = ?, updated_at = ? WHERE participant_id = ?",
                (normalized, now, p["participant_id"]),
            )

def create_submission(
    session_id: str,
    participant_id: str,
    preference_method: str,
    raw_preferences: dict[str, Any],
    transformed_preferences: dict[str, Any],
    allow_resubmission: bool = False,
) -> str:
    session = get_session(session_id)
    if not session:
        raise RepositoryError(f"Unknown session: {session_id}")
    if session["status"] != "open":
        raise RepositoryError("Session is not open for submissions")

    existing = get_current_submission(session_id, participant_id)
    if existing and not allow_resubmission:
        raise RepositoryError("Duplicate submission blocked for this participant")

    now = utc_now_iso()
    submission_id = new_id("sub")
    with get_connection() as conn:
        if existing and allow_resubmission:
            conn.execute(
                "UPDATE preference_submissions SET is_current = 0, updated_at = ? WHERE submission_id = ?",
                (now, existing["submission_id"]),
            )
        conn.execute(
            """
            INSERT INTO preference_submissions (
                submission_id, session_id, participant_id, preference_method,
                raw_preferences_json, transformed_preferences_json, validation_status,
                is_current, submitted_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'valid', 1, ?, ?)
            """,
            (
                submission_id,
                session_id,
                participant_id,
                preference_method,
                json.dumps(raw_preferences, indent=2),
                json.dumps(transformed_preferences, indent=2),
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE session_participants
            SET status = 'submitted', submitted_at = ?, updated_at = ?
            WHERE participant_id = ?
            """,
            (now, now, participant_id),
        )
    normalize_voting_power(session_id)
    return submission_id

def get_current_submission(session_id: str, participant_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM preference_submissions
            WHERE session_id = ? AND participant_id = ? AND is_current = 1
            """,
            (session_id, participant_id),
        ).fetchone()
    return row_to_dict(row)


def list_submissions(session_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ps.*, sp.stakeholder_type_id, sp.normalized_voting_power
            FROM preference_submissions ps
            JOIN session_participants sp ON sp.participant_id = ps.participant_id
            WHERE ps.session_id = ? AND ps.is_current = 1
            ORDER BY ps.submitted_at ASC
            """,
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def delete_submission(submission_id: str) -> None:
    """
    Soft-delete a submission by marking it as non-current.
    Resets participant status to 'invited'.
    """
    session_id: str | None = None

    with get_connection() as conn:
        submission = conn.execute(
            """
            SELECT session_id, participant_id
            FROM preference_submissions
            WHERE submission_id = ?
            """,
            (submission_id,),
        ).fetchone()

        if not submission:
            raise RepositoryError(f"Submission not found: {submission_id}")

        session_id = submission["session_id"]
        participant_id = submission["participant_id"]
        now = utc_now_iso()

        conn.execute(
            """
            UPDATE preference_submissions
            SET is_current = 0, updated_at = ?
            WHERE submission_id = ?
            """,
            (now, submission_id),
        )

        conn.execute(
            """
            UPDATE session_participants
            SET status = 'invited',
                submitted_at = NULL,
                updated_at = ?
            WHERE participant_id = ?
            """,
            (now, participant_id),
        )

    if session_id:
        normalize_voting_power(session_id)

def get_preprocessing_run(run_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM preprocessing_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    return row_to_dict(row)

def create_preprocessing_run(session_id: str | None, scenario_id: str, scenario_version: str, pipeline_id: str, config_hash: str) -> str:
    run_id = new_id("prep")
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO preprocessing_runs (
                run_id, session_id, scenario_id, scenario_version, pipeline_id,
                config_hash, status, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
            """,
            (run_id, session_id, scenario_id, scenario_version, pipeline_id, config_hash, now),
        )
    return run_id


def finish_preprocessing_run(
    run_id: str,
    status: str,
    final_output_ref: str | None = None,
    final_output_hash: str | None = None,
    row_count: int | None = None,
    column_count: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE preprocessing_runs
            SET status = ?, final_output_ref = ?, final_output_hash = ?, row_count = ?,
                column_count = ?, finished_at = ?, error_code = ?, error_message = ?
            WHERE run_id = ?
            """,
            (status, final_output_ref, final_output_hash, row_count, column_count, now, error_code, error_message, run_id),
        )


def log_preprocessing_step(
    run_id: str,
    step_id: str,
    step_type: str,
    status: str,
    input_ref: str | None = None,
    output_ref: str | None = None,
    row_count: int | None = None,
    column_count: int | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    started_at: str | None = None,
) -> None:
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO preprocessing_step_logs (
                step_log_id, run_id, step_id, step_type, status, input_ref, output_ref,
                row_count, column_count, duration_ms, error_code, error_message,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("step"), run_id, step_id, step_type, status, input_ref, output_ref,
                row_count, column_count, duration_ms, error_code, error_message,
                started_at or now, now,
            ),
        )


def get_latest_preprocessing_run(session_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM preprocessing_runs
            WHERE session_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return row_to_dict(row)


def list_preprocessing_step_logs(run_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM preprocessing_step_logs WHERE run_id = ? ORDER BY started_at ASC",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def list_preprocessing_runs(session_id: str | None = None, limit: int = 100) -> list[dict]:
    """
    Return preprocessing runs, newest first.

    If session_id is provided, only runs for that session are returned.
    Includes step success/failure counts for dashboard display.
    """
    with get_connection() as conn:
        if session_id:
            rows = conn.execute(
                """
                SELECT
                    pr.*,
                    COUNT(psl.step_log_id) AS total_steps,
                    COALESCE(SUM(CASE WHEN psl.status = 'success' THEN 1 ELSE 0 END), 0) AS successful_steps,
                    COALESCE(SUM(CASE WHEN psl.status != 'success' THEN 1 ELSE 0 END), 0) AS failed_steps
                FROM preprocessing_runs pr
                LEFT JOIN preprocessing_step_logs psl
                    ON pr.run_id = psl.run_id
                WHERE pr.session_id = ?
                GROUP BY pr.run_id
                ORDER BY pr.started_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    pr.*,
                    COUNT(psl.step_log_id) AS total_steps,
                    COALESCE(SUM(CASE WHEN psl.status = 'success' THEN 1 ELSE 0 END), 0) AS successful_steps,
                    COALESCE(SUM(CASE WHEN psl.status != 'success' THEN 1 ELSE 0 END), 0) AS failed_steps
                FROM preprocessing_runs pr
                LEFT JOIN preprocessing_step_logs psl
                    ON pr.run_id = psl.run_id
                GROUP BY pr.run_id
                ORDER BY pr.started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return [dict(row) for row in rows]

def save_export_record(session_id: str | None, export_type: str, contract_version: str, payload: dict[str, Any], created_by: str | None = None) -> str:
    export_id = new_id("exp")
    payload_json = json.dumps(payload, indent=2, sort_keys=True)
    payload_hash = hash_text(payload_json)
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO export_records (
                export_id, session_id, export_type, contract_version, payload_json,
                payload_hash, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (export_id, session_id, export_type, contract_version, payload_json, payload_hash, now, created_by),
        )
    return export_id


def list_export_records(session_id: str | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM export_records WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM export_records ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]