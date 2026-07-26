from __future__ import annotations

from typing import Protocol

from poli_insight.application.ports.repositories import (
    ScenarioRepository,
    SessionRepository,
    ParticipantRepository,
    SubmissionRepository,
    SubmissionDashboardQueryRepository
)

class UnitOfWork(Protocol):
    sessions: SessionRepository
    scenarios: ScenarioRepository
    participants: ParticipantRepository
    submissions: SubmissionRepository
    submission_dashboard: SubmissionDashboardQueryRepository

    def __enter__(self) -> "UnitOfWork":
        ...
    
    def __exit__(self, exc_type, exc, tb) -> None:
        ...

    def commit(self) -> None:
        ...