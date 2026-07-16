from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.domain.scenario import ScenarioSnapshot
from poli_insight.domain.sessions import SessionScenario

class ScenarioSnapshotNotFoundError(LookupError):
    pass

class SessionScenarioNotFoundError(LookupError):
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

    def get_session(
        self,
        session_id: str,
    ) -> SessionScenario:
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.sessions.get(session_id)

        if session is None:
            raise SessionScenarioNotFoundError(
                f"Session {session_id!r} was not found."
            )

        return session
    
@dataclass(frozen=True, slots=True)
class SessionScenarioDetails:
    snapshot: ScenarioSnapshot
    session: SessionScenario

    def get_session_details(
        self,
        session_id: str,
    ) -> SessionScenarioDetails:
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.sessions.get(session_id)

            if session is None:
                raise SessionScenarioNotFoundError(
                    f"Session {session_id!r} was not found."
                )

            snapshot = unit_of_work.scenarios.get_snapshot(
                session.scenario_id,
                session.scenario_version,
            )

            if snapshot is None:
                raise ScenarioSnapshotNotFoundError(
                    f"Snapshot for session {session_id!r} "
                    f"was not found."
                )

            return SessionScenarioDetails(
                snapshot=snapshot,
                session=session,
            )