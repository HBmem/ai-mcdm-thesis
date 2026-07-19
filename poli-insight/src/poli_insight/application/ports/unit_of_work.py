from __future__ import annotations

from typing import Protocol

from poli_insight.application.ports.repositories import (
    ScenarioRepository,
    SessionRepository,
)

class UnitOfWork(Protocol):
    sessions: SessionRepository
    scenarios: ScenarioRepository

    def __enter__(self) -> "UnitOfWork":
        ...
    
    def __exit__(self, exc_type, exc, tb) -> None:
        ...

    def commit(self) -> None:
        ...