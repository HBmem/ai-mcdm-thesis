from __future__ import annotations

from sqlalchemy.orm import Session

from poli_insight.domain.audit import AuditEvent
from poli_insight.infrastructure.database.models.audit import AuditEventRow
from poli_insight.infrastructure.database.mappers.audit import audit_event_to_domain, audit_event_to_row

class SqlAlchemyAuditRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(self, event: AuditEvent) -> None:
        row = audit_event_to_row(event)
        self._database_session.add(row)

    def get(self, audit_event_id: str) -> AuditEvent | None:
        row = self._database_session.get(
            AuditEventRow,
            audit_event_id,
        )
        return None if row is None else audit_event_to_domain(row)

    # TODO: add get_for_session when session is implemented