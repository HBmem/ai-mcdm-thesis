from __future__ import annotations

from typing import Protocol, Sequence

from poli_insight.domain.scenario import ScenarioBundle
from poli_insight.domain.sessions import (
    SessionScenario,
    SessionStakeholderGroup,
)
from poli_insight.domain.scenario import ScenarioSnapshot
from poli_insight.application.session_queries import (
    SessionFilters,
    SessionPage,
)

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

    def list_filtered(
        self,
        filters: SessionFilters,
        *,
        page: int,
        page_size: int,
    ) -> SessionPage:
        ...

    def save(
        self,
        session: SessionScenario,
    ) -> None:
        ...

    def delete(
        self,
        session_id: str,
    ) -> bool:
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
    
    def get_many(
        self,
        identities: set[tuple[str, str]],
    ) -> dict[tuple[str, str], ScenarioSnapshot]:
        ...