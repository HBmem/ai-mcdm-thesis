from __future__ import annotations

from src.models.session import SessionParticipant

from src.utils.db import get_db_connection

class ParticipantRepositoryError(RuntimeError):
    pass

def create_participant(participant: SessionParticipant):
    """
    Create a new participant in the database.

    Args:
        participant (SessionParticipant): The participant to create.
    """

def get_participant_by_id(participant_id: str) -> SessionParticipant | None:
    """
    Retrieve a participant by their ID.

    Args:
        participant_id (str): The ID of the participant to retrieve.

    Returns:
        SessionParticipant | None: The participant if found, otherwise None.
    """

def get_participants_by_session(session_id: str) -> list[SessionParticipant]:
    """
    Retrieve all participants for a given session.

    Args:
        session_id (str): The ID of the session.

    Returns:
        list[SessionParticipant]: A list of participants for the given session.
    """
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                """
                SELECT participant_id, session_id, stakeholder_group_id, display_name
                FROM session_participants
                WHERE session_id = ?
                """,
                (session_id,)
            )
            rows = cursor.fetchall()
            return [
                SessionParticipant(
                    participant_id=row["participant_id"],
                    session_id=row["session_id"],
                    stakeholder_group_id=row["stakeholder_group_id"],
                    display_name=row["display_name"]
                )
                for row in rows
            ]
        except Exception as e:
            raise ParticipantRepositoryError(f"Error fetching participants for session {session_id}: {e}")