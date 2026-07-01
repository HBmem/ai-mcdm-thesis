from __future__ import annotations

import sqlite3

from src.models.session import SessionStakeholderGroup

from src.utils.db import get_db_connection

class StakeholderSessionRepositoryError(RuntimeError):
    pass

def create_stakeholder_groups(
    stakeholder_group: SessionStakeholderGroup,
) -> bool:
    """
    """
    with get_db_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO session_stakeholder_groups (
                    session_id, stakeholder_group_id, stakeholder_group_name,
                    default_voting_power, current_voting_power, normalized_voting_power,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    stakeholder_group.session_id,
                    stakeholder_group.stakeholder_group_id,
                    stakeholder_group.stakeholder_group_name,
                    stakeholder_group.default_voting_power,
                    stakeholder_group.current_voting_power,
                    stakeholder_group.normalized_voting_power,
                    stakeholder_group.is_active,
                    stakeholder_group.created_at,
                    stakeholder_group.updated_at
                )
            )
            return True
        except Exception as e:
            raise StakeholderSessionRepositoryError(f"Error creating stakeholder group: {e}")
    return False

def create_stakeholder_groups_with_conn(
    conn: sqlite3.Connection,
    stakeholder_group: SessionStakeholderGroup,
) -> bool:
    """
    """
    try:
        conn.execute(
            """
            INSERT INTO session_stakeholder_groups (
                session_id, stakeholder_group_id, stakeholder_group_name,
                default_voting_power, current_voting_power, normalized_voting_power,
                is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                stakeholder_group.session_id,
                stakeholder_group.stakeholder_group_id,
                stakeholder_group.stakeholder_group_name,
                stakeholder_group.default_voting_power,
                stakeholder_group.current_voting_power,
                stakeholder_group.normalized_voting_power,
                int(stakeholder_group.is_active),
                stakeholder_group.created_at,
                stakeholder_group.updated_at
            )
        )
        return True
    except Exception as e:
        raise StakeholderSessionRepositoryError(f"Error creating stakeholder group: {e}")
    return False