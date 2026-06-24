from __future__ import annotations

import json
import sqlite3

from typing import Any
from collections import defaultdict
from datetime import datetime

from src.utils.db import get_db_connection
from src.utils.scenario_loader import ScenarioBundle
from src.utils.ids import new_id

class RepositoryError(RuntimeError):
    pass

def create_session(
    session_title: str,
    session_description: str,
    session_visibility: str,
    admin_notes: str,
    weighting_method: str,
    ranking_method: str,
    preference_method: str,
    participation_mode: str,
    aggregation_method: str,
    voting_power: str,
    voting_power_config: dict,
    require_access_code: bool,
    access_code_type: str,
    allow_resubmissions: bool,
    start_date_time: datetime,
    end_date_time: datetime,
    bundle: ScenarioBundle
) -> str:
    """
    """
    now = datetime.now()
    session_id = new_id("sess")

    with get_db_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO scenario_sessions (
                    session_id, scenario_id, session_title, session_description, session_visibility, status,
                    admin_notes, weighting_method, ranking_method, preference_method, participation_mode, aggregation_method,
                    voting_power, voting_power_config, require_access_code, access_code_type, allow_resubmissions,
                    start_date_time, end_date_time, created_by, created_at, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'Draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'admin', ?, 'admin', ?)
                """,
                (
                    session_id,
                    bundle.scenario_id,
                    session_title,
                    session_description,
                    session_visibility,
                    # status = "Draft"
                    admin_notes,
                    weighting_method,
                    ranking_method,
                    preference_method,
                    participation_mode,
                    aggregation_method,
                    voting_power,
                    json.dumps(voting_power_config),
                    int(require_access_code),
                    access_code_type,
                    int(allow_resubmissions),
                    start_date_time,
                    end_date_time,
                    # TODO: add admin name
                    now,
                    # TODO: add admin name
                    now
                )
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RepositoryError(f"Error creating session: {e}")
        finally:
            if conn:
                conn.commit()
        return session_id

def get_session(session_id: str) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        try:
            row = conn.execute(
                "SELECT * FROM scenario_sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            return _row_to_dict(row)
        except Exception as e:
            raise RepositoryError(f"Error fetching session: {e}")
    return None

def get_sessions(status: list[str] = ["all"]) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        try:
            if status == ["all"]:
                rows = conn.execute("SELECT * FROM scenario_sessions").fetchall()
            else:
                rows = conn.execute("SELECT * FROM scenario_sessions WHERE status IN ({})".format(','.join('?' * len(status))), tuple(status)).fetchall()
            return [_row_to_dict(row) for row in rows]
        except Exception as e:
            raise RepositoryError(f"Error fetching sessions: {e}")
    return []

def get_sessions_by_filter(filters: dict[str, Any]) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        try:
            # Build the WHERE clause dynamically based on the filters
            where_clauses = []
            params = []
            
            if "status" in filters and filters["status"] != "All":
                where_clauses.append("status = ?")
                params.append(filters["status"])
            
            if "session_visibility" in filters and filters["session_visibility"] != "All":
                where_clauses.append("session_visibility = ?")
                params.append(filters["session_visibility"])

            if "weighting_method" in filters and filters["weighting_method"] != "All":
                where_clauses.append("weighting_method = ?")
                params.append(filters["weighting_method"])
            
            if "ranking_method" in filters and filters["ranking_method"] != "All":
                where_clauses.append("ranking_method = ?")
                params.append(filters["ranking_method"])

            if "preference_method" in filters and filters["preference_method"] != "All":
                where_clauses.append("preference_method = ?")
                params.append(filters["preference_method"])

            if where_clauses:
                query = f"SELECT * FROM scenario_sessions WHERE {' AND '.join(where_clauses)}"
            else:
                query = "SELECT * FROM scenario_sessions"

            rows = conn.execute(query, tuple(params)).fetchall()
            return [_row_to_dict(row) for row in rows]
        except Exception as e:
            raise RepositoryError(f"Error fetching sessions: {e}")
    return []

def get_participants_by_session_id(session_id: str) -> list[dict[str, Any]]:
    with get_db_connection() as conn:
        try:
            rows = conn.execute("SELECT * FROM session_participants WHERE session_id = ?", (session_id,)).fetchall()
            return [_row_to_dict(row) for row in rows]
        except Exception as e:
            raise RepositoryError(f"Error fetching participants: {e}")
    return []

# Helper Functions
def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None