"""Read-only validation bundle history query."""

from __future__ import annotations

from collections.abc import Callable

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.domain.processing import ProcessingRun


class ListValidationBundles:
    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, session_id: str) -> tuple[ProcessingRun, ...]:
        if not session_id.strip():
            raise ValueError("Session ID cannot be empty.")
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.processing_runs.list_for_session(session_id)

