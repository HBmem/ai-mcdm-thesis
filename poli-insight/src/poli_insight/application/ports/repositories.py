from __future__ import annotations

from typing import Protocol, Sequence

from poli_insight.domain.scenario import ScenarioBundle
from poli_insight.domain.sessions import (
    SessionScenario,
    SessionStakeholderGroup,
)
from poli_insight.domain.scenario import ScenarioSnapshot

class SessionRepository(Protocol):
    def add(
        self,
        session: SessionScenario,
        stakeholder_groups: Sequence[SessionStakeholderGroup],
    ) -> None:
        ...
    
    def get(
        self,
        session_id: str,
    ) -> SessionScenario | None:
        ...

class ScenarioRepository(Protocol):
    def ensure_snapshot(
        self,
        bundle: ScenarioBundle,
    ) -> ScenarioSnapshot:
        ...
    
    def get_snapshot(
        self,
        scenario_id: str,
        scenario_version: str,
    ) -> ScenarioSnapshot | None:
        ...