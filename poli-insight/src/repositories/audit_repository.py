from __future__ import annotations

import sqlite3

from src.models.audit import AuditEvent

from src.utils.db import get_db_connection
from src.utils.ids import new_id

def AuditRepositoryError(RuntimeError):
    pass

def create_audit_event(event: AuditEvent) -> str:
    with get_db_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO audit_events (
                    audit_id, session_id, actor_type, actor_id, action,
                    entity_type, entity_id, before_json, after_json, reason, created_at
                ) VALUES ()
                """,
                (
                    event.audit_id,
                    event.session_id,
                    event.actor_type.value,
                    event.actor_id,
                    event.action,
                    event.entity_type,
                    event.entity_id
                )
            )
        except Exception as e:
            raise AuditRepositoryError(f"Error creating audit event: {e}")

def create_audit_event_with_conn(
    conn: sqlite3.Connection,
    event: AuditEvent
) -> str:
    """
    """
    try:
        conn.execute(
            """
            INSERT INTO audit_events (
                audit_id, session_id, actor_type, actor_id, action,
                entity_type, entity_id, before_json, after_json, reason, created_at
            ) VALUES ()
            """,
            (
                event.audit_id,
                event.session_id,
                event.actor_type.value,
                event.actor_id,
                event.action,
                event.entity_type,
                event.entity_id
            )
        )
    except Exception as e:
        raise AuditRepositoryError(f"Error creating audit event: {e}")