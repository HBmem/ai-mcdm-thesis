from __future__ import annotations

from typing import Protocol

from poli_insight.application.ports.audit_repository import AuditEventRepository
from poli_insight.application.ports.participant_repository import (
    ParticipantRepository,
)
from poli_insight.application.ports.scenario_repository import ScenarioRepository
from poli_insight.application.ports.session_repository import SessionRepository
from poli_insight.application.ports.submission_repository import (
    SubmissionRepository,
)


class UnitOfWork(Protocol):
    audit_events: AuditEventRepository
    scenarios: ScenarioRepository
    session: SessionRepository
    participants: ParticipantRepository
    submissions: SubmissionRepository

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type, exc, tb) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
