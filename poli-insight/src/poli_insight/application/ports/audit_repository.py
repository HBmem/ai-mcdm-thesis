from __future__ import annotations

from typing import Protocol, Sequence

from poli_insight.domain.audit import AuditEvent

class AuditEventRepository(Protocol):
    def add(
        self,
        event: AuditEvent
    ) -> None:
        ...

    def get(
        self,
        audit_id: str,
    ) -> AuditEvent | None:
        ...

    def get_for_session(
        self,
        session_id: str
    ) -> Sequence[AuditEvent]:
        ...