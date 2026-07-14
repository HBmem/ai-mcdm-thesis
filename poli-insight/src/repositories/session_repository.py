from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from src.models.enum import (
    SessionStatus,
    SessionVisibility,
    WeightingMethod, 
    RankingMethod,
    PreferenceMethod,
    ParticipationMethod,
    AggregationMethod
)
from src.models.scenario import ScenarioBundle
from src.models.session import SessionScenario, SessionStakeholderGroup

from src.repositories.stakeholder_repository import create_stakeholder_groups_with_conn
from src.repositories.scenario_repository import get_or_create_scenario_snapshot

from src.utils.db import get_db_connection
from src.utils.ids import new_id

class SessionRepositoryError(RuntimeError):
    pass

def create_session(
    session: SessionScenario,
    scenario_bundle: ScenarioBundle,
    voting_data: dict
) -> str:
    """
    Create a new session in the database.

    Args:
        session (SessionScenario): The session to create.
        scenario_bundle (ScenarioBundle): The scenario bundle associated with the session.

    Returns:
        str: The ID of the newly created session.
    """
    _validate_session_bundle_match(session, scenario_bundle)
    session_id = session.session_id.strip() if session.session_id else new_id("session")

    with get_db_connection() as conn:
        try:
            snapshot_scenario_id, snapshot_scenario_version = (
                get_or_create_scenario_snapshot(conn, scenario_bundle)
            )

            conn.execute(
                """
                INSERT INTO scenario_sessions (
                    session_id, scenario_id, scenario_version, title, description, admin_notes,
                    visibility, participation_method, preference_method, weighting_method, ranking_method,
                    aggregation_method, require_access_code, access_code_type, allow_resubmissions,
                    start_at, end_at, status, created_at, created_by, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    session_id,
                    snapshot_scenario_id,
                    snapshot_scenario_version,
                    session.title,
                    session.description,
                    session.admin_notes,
                    session.visibility.value,
                    session.participation_method.value,
                    session.preference_method.value,
                    session.weighting_method.value,
                    session.ranking_method.value,
                    session.aggregation_method.value,
                    int(session.require_access_code),
                    session.access_code_type,
                    int(session.allow_resubmissions),
                    _serialize_datetime(session.start_at),
                    _serialize_datetime(session.end_at),
                    session.status.value,
                    _serialize_datetime(session.created_at),
                    session.created_by,
                    _serialize_datetime(session.updated_at),
                    session.updated_by
                )
            )

            voting_power_config = voting_data.get("voting_config")
            total = sum(voting_power_config.values())
            
            for sg in scenario_bundle.stakeholder_groups:
                create_stakeholder_groups_with_conn(conn,
                                                    SessionStakeholderGroup(
                                                        session_id=session_id,
                                                        stakeholder_group_id=sg.get("id"),
                                                        stakeholder_group_name=sg.get("label"),
                                                        default_voting_power=sg.get("default_group_voting_power"),
                                                        current_voting_power=voting_power_config[sg.get("id")],
                                                        normalized_voting_power=voting_power_config[sg.get("id")] / total,
                                                        is_active=True,
                                                        created_at=utc_now(),
                                                        updated_at=utc_now(),
                                                    )
                )
        except SessionRepositoryError:
            raise
        except sqlite3.Error as exc:
            raise SessionRepositoryError(
                f"Error creating session: {exc}"
            ) from exc

    return session_id

def get_sessions() -> list[SessionScenario]:
    """
    Retrieve all sessions from the database.

    Returns:
        list[SessionScenario]: A list of SessionScenario objects.
    """
    with get_db_connection() as conn:
        try:
            cursor = conn.execute("SELECT * FROM scenario_sessions;")
            rows = cursor.fetchall()
            return [_row_to_session(row) for row in rows]
        except Exception as e:
            raise SessionRepositoryError(f"Error fetching sessions: {e}")
    return []

def get_sessions_by_filter(filter_criteria: dict | None = None) -> list[SessionScenario]:
    """
    Retrieve sessions based on filter criteria.

    Args:
        filter_criteria (dict): A dictionary containing filter criteria.

    Returns:
        list[SessionScenario]: A list of SessionScenario objects that match the filter criteria.
    """
    filter_criteria = filter_criteria or {}
    where_clauses = []
    params = []

    if "scenario_id" in filter_criteria:
        where_clauses.append("scenario_id = ?")
        params.append(filter_criteria['scenario_id'])
    
    if "scenario_version" in filter_criteria:
        where_clauses.append("scenario_version = ?")
        params.append(filter_criteria['scenario_version'])

    if "title" in filter_criteria:
        where_clauses.append("title LIKE ?")
        params.append(f"%{filter_criteria['title']}%")

    if "status" in filter_criteria and filter_criteria['status'] != "All":
        where_clauses.append("status = ?")
        params.append(filter_criteria['status'])
    
    if "session_visibility" in filter_criteria and filter_criteria['session_visibility'] != "All":
        where_clauses.append("session_visibility = ?")
        params.append(filter_criteria['session_visibility'])

    with get_db_connection() as conn:
        try:
            query = "SELECT * FROM scenario_sessions"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [_row_to_session(row) for row in rows]
        except Exception as e:
            raise SessionRepositoryError(f"Error fetching sessions by filter: {e}")
    return []

def get_session(session_id: str) -> SessionScenario | None:
    """
    Retrieve a specific session by its ID.

    Args:
        session_id (str): The ID of the session to retrieve.

    Returns:
        SessionScenario | None: The SessionScenario object if found, otherwise None.
    """
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM scenario_sessions WHERE session_id = ?;", (session_id,))
        row = cursor.fetchone()
        return _row_to_session(row) if row else None

# Helper functions
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_datetime(value):
    return datetime.fromisoformat(value) if value else None

def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

def _validate_session_bundle_match(
    session: SessionScenario,
    bundle: ScenarioBundle,
) -> None:
    if session.scenario_id != bundle.scenario_id:
        raise SessionRepositoryError(
            "Session scenario_id does not match the selected scenario bundle."
        )
    if session.scenario_version != bundle.scenario_version:
        raise SessionRepositoryError(
            "Session scenario_version does not match the selected scenario bundle."
        )
    if session.end_at is not None and session.start_at is not None:
        if session.end_at <= session.start_at:
            raise SessionRepositoryError(
                "Session end_at must be later than start_at."
            )
    if session.require_access_code and not session.access_code_type:
        raise SessionRepositoryError(
            "access_code_type is required when access codes are enabled."
        )

def _row_to_session(row: sqlite3.Row) -> SessionScenario:
    return SessionScenario(
        session_id=row["session_id"],
        scenario_id=row["scenario_id"],
        scenario_version=row["scenario_version"],
        title=row["title"],
        description=row["description"],
        admin_notes=row["admin_notes"],
        status=SessionStatus(row["status"]),
        visibility=SessionVisibility(row["visibility"]),
        weighting_method=WeightingMethod(row["weighting_method"]),
        ranking_method=RankingMethod(row["ranking_method"]),
        preference_method=PreferenceMethod(row["preference_method"]),
        participation_method=ParticipationMethod(row["participation_method"]),
        aggregation_method=AggregationMethod(row["aggregation_method"]),
        require_access_code=row["require_access_code"],
        access_code_type=row["access_code_type"],
        allow_resubmissions=row["allow_resubmissions"],
        start_at=parse_datetime(row["start_at"]),
        end_at=parse_datetime(row["end_at"]),
        opened_at=parse_datetime(row["opened_at"]),
        closed_at=parse_datetime(row["closed_at"]),
        archived_at=parse_datetime(row["archived_at"]),
        created_at=parse_datetime(row["created_at"]),
        created_by=row["created_by"],
        updated_at=parse_datetime(row["updated_at"]),
        updated_by=row["updated_by"]
    )



