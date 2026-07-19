from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.domain.scenario import ScenarioSnapshot
from poli_insight.domain.sessions import SessionScenario

class ScenarioSnapshotNotFoundError(LookupError):
    pass


UnitOfWorkFactory = Callable[[], UnitOfWork]

class ScenarioSnapshotService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def get_snapshot(
        self,
        scenario_id: str,
        scenario_version: str,
    ) -> ScenarioSnapshot:
        with self._unit_of_work_factory() as unit_of_work:
            snapshot = unit_of_work.scenarios.get_snapshot(
                scenario_id,
                scenario_version,
            )

        if snapshot is None:
            raise ScenarioSnapshotNotFoundError(
                f"Scenario snapshot "
                f"{scenario_id!r} version "
                f"{scenario_version!r} was not found."
            )

        return snapshot
    
    
@dataclass(frozen=True, slots=True)
class SessionScenarioDetails:
    snapshot: ScenarioSnapshot
    session: SessionScenario