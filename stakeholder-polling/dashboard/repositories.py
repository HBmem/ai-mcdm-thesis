from __future__ import annotations

import json
import sqlite3

from typing import Any

from dashboard.db import get_connection
from dashboard.scenario_loader import ScenarioBundle
from dashboard.utils.time import utc_now_iso
from dashboard.utils.ids import generate_access_code as generate_access_code_value, hash_access_code, new_id, hash_text
from dashboard.access_codes import generate_participant_access_code

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
            )
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

def list_sessions(
    statuses: list[str] | None = None,
    scenario_id: str | None = None,
    mode: str | None = None,
    selected_weighting_method: str | None = None,
    selected_ranking_method: str | None = None,
    require_access_code: bool | None = None,
    allow_resubmission: bool | None = None,
    require_moderator_lock: bool | None = None,
) -> list[dict[str, Any]]:
    """List polling sessions with optional filtering.
    
    Args:
        statuses: Filter by session status (e.g., ['open', 'locked'])
        scenario_id: Filter by scenario ID
        mode: Filter by session mode (e.g., 'single_stakeholder', 'multi_stakeholder')
        selected_weighting_method: Filter by weighting method (e.g., 'AHP', 'FUZZY_AHP')
        selected_ranking_method: Filter by ranking method (e.g., 'TOPSIS', 'FUZZY_TOPSIS')
        require_access_code: Filter by whether access codes are required
        allow_resubmission: Filter by whether resubmission is allowed
        require_moderator_lock: Filter by whether moderator lock is required
    """
    with get_connection() as conn:
        where_clauses = []
        params = []
        
        # Build WHERE clause based on provided filters
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where_clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        
        if scenario_id is not None:
            where_clauses.append("scenario_id = ?")
            params.append(scenario_id)
        
        if mode is not None:
            where_clauses.append("mode = ?")
            params.append(mode)
        
        if selected_weighting_method is not None:
            where_clauses.append("selected_weighting_method = ?")
            params.append(selected_weighting_method)
        
        if selected_ranking_method is not None:
            where_clauses.append("selected_ranking_method = ?")
            params.append(selected_ranking_method)
        
        if require_access_code is not None:
            where_clauses.append("require_access_code = ?")
            params.append(int(require_access_code))
        
        if allow_resubmission is not None:
            where_clauses.append("allow_resubmission = ?")
            params.append(int(allow_resubmission))
        
        if require_moderator_lock is not None:
            where_clauses.append("require_moderator_lock = ?")
            params.append(int(require_moderator_lock))
        
        # Build final query
        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        query = f"SELECT * FROM polling_sessions WHERE {where_clause} ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
    
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
    """Get existing stakeholder or create new one.
    
    Matching logic:
    - If external_ref is provided, match by external_ref (most authoritative)
    - Otherwise, match by display_name
    
    If a match is found, updates the record with new alias/external_ref if provided.
    """
    now = utc_now_iso()
    
    with get_connection() as conn:
        # Try to find existing stakeholder
        row = None
        if external_ref:
            # If external_ref is provided, use it as the primary key
            row = conn.execute(
                "SELECT stakeholder_id FROM stakeholders WHERE external_ref = ?",
                (external_ref,)
            ).fetchone()
        else:
            # Otherwise, use display_name
            row = conn.execute(
                "SELECT stakeholder_id FROM stakeholders WHERE display_name = ?",
                (display_name,)
            ).fetchone()
        
        if row:
            stakeholder_id = row[0]
            # Update record if new information is provided
            updates = []
            params = []
            if alias is not None:
                updates.append("alias = ?")
                params.append(alias)
            if external_ref is not None:
                updates.append("external_ref = ?")
                params.append(external_ref)
            
            if updates:
                updates.append("updated_at = ?")
                params.append(now)
                params.append(stakeholder_id)
                conn.execute(
                    f"UPDATE stakeholders SET {', '.join(updates)} WHERE stakeholder_id = ?",
                    params
                )
            return stakeholder_id
        
        # Create new stakeholder
        stakeholder_id = new_id("stk")
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

    code = None
    code_hash = None
    code_hint = None

    if require_access_code:
        code, code_hash, code_hint = generate_participant_access_code()
    effective = override_voting_power if override_voting_power is not None else default_voting_power

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO session_participants (
                participant_id, session_id, stakeholder_id, stakeholder_type_id,
                access_code_hash, access_code_hint, access_code_created_at,
                status, default_voting_power, override_voting_power, effective_voting_power,
                invited_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'invited', ?, ?, ?, ?, ?)
            """,
            (
                participant_id,
                session_id,
                stakeholder_id,
                stakeholder_type_id,
                code_hash,
                code_hint,
                now if code_hash else None,
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

def regenerate_participant_access_code(participant_id: str) -> str:
    """
    Generate a new durable participant access code.

    The old code is invalidated because the stored hash is replaced.
    The plain code is returned once and should be copied by the moderator.
    """
    participant = get_participant(participant_id)
    if not participant:
        raise RepositoryError(f"Unknown participant: {participant_id}")

    code, code_hash, code_hint = generate_participant_access_code()
    now = utc_now_iso()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE session_participants
            SET access_code_hash = ?,
                access_code_hint = ?,
                access_code_regenerated_at = ?,
                updated_at = ?
            WHERE participant_id = ?
            """,
            (code_hash, code_hint, now, now, participant_id),
        )

    return code

def normalize_voting_power(session_id: str) -> None:
    """Normalize voting power of participants so their weights sum to 1.0.
    
    Recalculates the normalized_voting_power for all participants in a session,
    ensuring that eligible participants' weights are proportional to their
    effective_voting_power and sum to 1.0. Participants with "excluded" or
    "expired" status receive a normalized weight of 0.0.
    
    Args:
        session_id: The ID of the polling session to normalize.
    """
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

def get_submission_by_id(submission_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT ps.*, sp.stakeholder_type_id, sp.normalized_voting_power
            FROM preference_submissions ps
            JOIN session_participants sp
              ON sp.participant_id = ps.participant_id
            WHERE ps.submission_id = ?
            """,
            (submission_id,),
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

def list_submissions_for_participant(
    session_id: str,
    participant_id: str,
    current_only: bool = False,
) -> list[dict[str, Any]]:
    query = """
        SELECT ps.*, sp.stakeholder_type_id, sp.normalized_voting_power
        FROM preference_submissions ps
        JOIN session_participants sp
          ON sp.participant_id = ps.participant_id
        WHERE ps.session_id = ?
          AND ps.participant_id = ?
    """

    params: list[Any] = [session_id, participant_id]

    if current_only:
        query += " AND ps.is_current = 1"

    query += " ORDER BY ps.submitted_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(r) for r in rows]

def _normalize_voting_power_in_conn(conn, session_id: str) -> None:
    participants = conn.execute(
        """
        SELECT participant_id, status, effective_voting_power
        FROM session_participants
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchall()

    eligible = [
        p for p in participants
        if p["status"] not in {"excluded", "expired"}
    ]

    total = sum(float(p["effective_voting_power"] or 0) for p in eligible)
    now = utc_now_iso()

    for p in participants:
        if p in eligible and total > 0:
            normalized = float(p["effective_voting_power"] or 0) / total
        else:
            normalized = 0.0

        conn.execute(
            """
            UPDATE session_participants
            SET normalized_voting_power = ?, updated_at = ?
            WHERE participant_id = ?
            """,
            (normalized, now, p["participant_id"]),
        )

def submit_preferences_atomic(
    *,
    session_id: str,
    stakeholder_type_id: str,
    display_name: str,
    alias: str | None,
    default_voting_power: float,
    participant_id: str | None,
    preference_method: str,
    raw_preferences: dict[str, Any],
    transformed_preferences: dict[str, Any],
    allow_resubmission: bool = False,
) -> dict[str, str]:
    """
    Atomically create/update the participant and save the submission.

    This prevents the public submit page from creating a participant without
    a matching submission if the second operation fails.
    """
    now = utc_now_iso()

    with get_connection() as conn:
        session = conn.execute(
            """
            SELECT *
            FROM polling_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

        if not session:
            raise RepositoryError(f"Unknown session: {session_id}")

        if session["status"] != "open":
            raise RepositoryError("Session is not open for submissions.")

        # If the session is access-code based, the participant should already exist.
        if session["require_access_code"]:
            if not participant_id:
                raise RepositoryError("Participant ID is required for access-code sessions.")

            participant = conn.execute(
                """
                SELECT *
                FROM session_participants
                WHERE participant_id = ?
                  AND session_id = ?
                """,
                (participant_id, session_id),
            ).fetchone()

            if not participant:
                raise RepositoryError("Participant was not found for this session.")

            if participant["stakeholder_type_id"] != stakeholder_type_id:
                raise RepositoryError("Participant stakeholder type does not match submission.")

            if participant["status"] in {"excluded", "expired"}:
                raise RepositoryError("This participant is not eligible to submit.")

            stakeholder_id = new_id("stk")

            conn.execute(
                """
                INSERT INTO stakeholders (
                    stakeholder_id, display_name, alias, external_ref,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (stakeholder_id, display_name, alias, now, now),
            )

            conn.execute(
                """
                UPDATE session_participants
                SET stakeholder_id = ?,
                    status = CASE
                        WHEN status = 'invited' THEN 'started'
                        ELSE status
                    END,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE participant_id = ?
                """,
                (stakeholder_id, now, now, participant_id),
            )

        # If access codes are not required, create participant and stakeholder now.
        else:
            if session["mode"] == "single_stakeholder":
                active_count = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM session_participants
                    WHERE session_id = ?
                      AND status NOT IN ('excluded', 'expired')
                    """,
                    (session_id,),
                ).fetchone()["count"]

                if active_count >= 1:
                    raise RepositoryError(
                        "This single-stakeholder session already has an active participant."
                    )

            stakeholder_id = new_id("stk")
            participant_id = new_id("part")

            conn.execute(
                """
                INSERT INTO stakeholders (
                    stakeholder_id, display_name, alias, external_ref,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (stakeholder_id, display_name, alias, now, now),
            )

            conn.execute(
                """
                INSERT INTO session_participants (
                    participant_id, session_id, stakeholder_id,
                    stakeholder_type_id, access_code_hash,
                    status, default_voting_power, override_voting_power,
                    effective_voting_power, invited_at, started_at, updated_at
                )
                VALUES (?, ?, ?, ?, NULL, 'started', ?, NULL, ?, ?, ?, ?)
                """,
                (
                    participant_id,
                    session_id,
                    stakeholder_id,
                    stakeholder_type_id,
                    default_voting_power,
                    default_voting_power,
                    now,
                    now,
                    now,
                ),
            )

            conn.execute(
                """
                INSERT INTO voting_power_assignments (
                    assignment_id, session_id, participant_id,
                    stakeholder_type_id, assignment_scope, source,
                    voting_power, reason, assigned_by, created_at
                )
                VALUES (?, ?, ?, ?, 'participant', 'scenario_default', ?, NULL, NULL, ?)
                """,
                (
                    new_id("vpa"),
                    session_id,
                    participant_id,
                    stakeholder_type_id,
                    default_voting_power,
                    now,
                ),
            )

        # Single-stakeholder protection at submission level.
        if session["mode"] == "single_stakeholder":
            other_submission_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM preference_submissions
                WHERE session_id = ?
                  AND is_current = 1
                  AND participant_id <> ?
                """,
                (session_id, participant_id),
            ).fetchone()["count"]

            if other_submission_count >= 1:
                raise RepositoryError(
                    "This single-stakeholder session already has a submitted response."
                )

        existing = conn.execute(
            """
            SELECT *
            FROM preference_submissions
            WHERE session_id = ?
              AND participant_id = ?
              AND is_current = 1
            """,
            (session_id, participant_id),
        ).fetchone()

        if existing and not allow_resubmission:
            raise RepositoryError("Duplicate submission blocked for this participant.")

        if existing and allow_resubmission:
            conn.execute(
                """
                UPDATE preference_submissions
                SET is_current = 0,
                    updated_at = ?
                WHERE submission_id = ?
                """,
                (now, existing["submission_id"]),
            )

        submission_id = new_id("sub")

        conn.execute(
            """
            INSERT INTO preference_submissions (
                submission_id, session_id, participant_id,
                submission_version, preference_method,
                raw_preferences_json, transformed_preferences_json,
                validation_status, is_current, submitted_at, updated_at
            )
            VALUES (?, ?, ?, 1, ?, ?, ?, 'valid', 1, ?, ?)
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
            SET status = 'submitted',
                submitted_at = ?,
                updated_at = ?
            WHERE participant_id = ?
            """,
            (now, now, participant_id),
        )

        _normalize_voting_power_in_conn(conn, session_id)

    return {
        "session_id": session_id,
        "participant_id": participant_id,
        "submission_id": submission_id,
    }

def get_session_stakeholder_type_weights(session_id: str) -> dict[str, float]:
    """
    Return latest group-level stakeholder-type weights for a session.

    These are not participant-level or submission-level weights.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT stakeholder_type_id, voting_power, created_at
            FROM voting_power_assignments
            WHERE session_id = ?
              AND assignment_scope = 'group'
              AND stakeholder_type_id IS NOT NULL
            ORDER BY created_at DESC
            """,
            (session_id,),
        ).fetchall()

    result: dict[str, float] = {}

    for row in rows:
        stakeholder_type_id = row["stakeholder_type_id"]

        if stakeholder_type_id not in result:
            result[stakeholder_type_id] = float(row["voting_power"])

    return result


def update_session_stakeholder_type_weight(
    *,
    session_id: str,
    stakeholder_type_id: str,
    voting_power: float,
    reason: str | None = None,
    assigned_by: str | None = None,
) -> None:
    """
    Save a stakeholder-type/group-level weight for a session and apply it to
    all current participants in that stakeholder type.

    This intentionally avoids submission-level and individual participant-level editing.
    """
    if voting_power < 0:
        raise RepositoryError("Voting power cannot be negative.")

    now = utc_now_iso()

    with get_connection() as conn:
        session = conn.execute(
            "SELECT * FROM polling_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if not session:
            raise RepositoryError(f"Unknown session: {session_id}")

        conn.execute(
            """
            INSERT INTO voting_power_assignments (
                assignment_id, session_id, participant_id, stakeholder_type_id,
                assignment_scope, source, voting_power, reason, assigned_by, created_at
            )
            VALUES (?, ?, NULL, ?, 'group', 'moderator_group_override', ?, ?, ?, ?)
            """,
            (
                new_id("vpa"),
                session_id,
                stakeholder_type_id,
                voting_power,
                reason,
                assigned_by,
                now,
            ),
        )

        conn.execute(
            """
            UPDATE session_participants
            SET override_voting_power = ?,
                effective_voting_power = ?,
                updated_at = ?
            WHERE session_id = ?
              AND stakeholder_type_id = ?
              AND status NOT IN ('excluded', 'expired')
            """,
            (
                voting_power,
                voting_power,
                now,
                session_id,
                stakeholder_type_id,
            ),
        )

    normalize_voting_power(session_id)

def import_submission_atomic(
    *,
    session_id: str,
    stakeholder_type_id: str,
    display_name: str,
    alias: str | None,
    external_ref: str | None,
    default_voting_power: float,
    raw_preferences: dict[str, Any],
    transformed_preferences: dict[str, Any],
    preference_method: str,
    generate_access_code: bool = False,
    allow_locked_session: bool = False,
    source: str = "bulk_import",
) -> dict[str, Any]:
    """
    Import one participant + one submission in a single transaction.

    Used for moderator mass testing. This does not expose participant-level
    weight editing; it applies the session's stakeholder-type weight.
    """
    now = utc_now_iso()

    with get_connection() as conn:
        session = conn.execute(
            "SELECT * FROM polling_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if not session:
            raise RepositoryError(f"Unknown session: {session_id}")

        if session["status"] != "open":
            if not (allow_locked_session and session["status"] == "locked"):
                raise RepositoryError(
                    "Imports are only allowed for open sessions unless locked-session testing is enabled."
                )

        if session["mode"] == "single_stakeholder":
            active_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM session_participants
                WHERE session_id = ?
                  AND status NOT IN ('excluded', 'expired')
                """,
                (session_id,),
            ).fetchone()["count"]

            if active_count >= 1:
                raise RepositoryError(
                    "Cannot import multiple rows into a single-stakeholder session."
                )

        # Latest group-level session weight, if available.
        group_weight_row = conn.execute(
            """
            SELECT voting_power
            FROM voting_power_assignments
            WHERE session_id = ?
              AND stakeholder_type_id = ?
              AND assignment_scope = 'group'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id, stakeholder_type_id),
        ).fetchone()

        effective_voting_power = (
                float(group_weight_row["voting_power"])
                if group_weight_row
                else float(default_voting_power)
        )

        access_code = None
        access_code_hash = None

        if generate_access_code:
            access_code = generate_access_code_value()
            access_code_hash = hash_access_code(access_code)

        stakeholder_id = new_id("stk")
        participant_id = new_id("part")
        submission_id = new_id("sub")

        conn.execute(
            """
            INSERT INTO stakeholders (
                stakeholder_id, display_name, alias, external_ref,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                stakeholder_id,
                display_name,
                alias,
                external_ref,
                now,
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO session_participants (
                participant_id, session_id, stakeholder_id, stakeholder_type_id,
                access_code_hash, status, default_voting_power,
                override_voting_power, effective_voting_power,
                invited_at, started_at, submitted_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'submitted', ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                participant_id,
                session_id,
                stakeholder_id,
                stakeholder_type_id,
                access_code_hash,
                effective_voting_power,
                effective_voting_power,
                now,
                now,
                now,
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO voting_power_assignments (
                assignment_id, session_id, participant_id, stakeholder_type_id,
                assignment_scope, source, voting_power, reason, assigned_by, created_at
            )
            VALUES (?, ?, ?, ?, 'participant', ?, ?, 'Created by submission import', 'moderator', ?)
            """,
            (
                new_id("vpa"),
                session_id,
                participant_id,
                stakeholder_type_id,
                source,
                effective_voting_power,
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO preference_submissions (
                submission_id, session_id, participant_id,
                submission_version, preference_method,
                raw_preferences_json, transformed_preferences_json,
                validation_status, is_current, submitted_at, updated_at
            )
            VALUES (?, ?, ?, 1, ?, ?, ?, 'valid', 1, ?, ?)
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

    normalize_voting_power(session_id)

    result = {
        "row_status": "imported",
        "session_id": session_id,
        "participant_id": participant_id,
        "submission_id": submission_id,
        "stakeholder_type_id": stakeholder_type_id,
        "display_name": display_name,
    }

    if access_code:
        result["access_code"] = access_code

    return result

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