"""Read immutable sensitivity and robustness history."""

from __future__ import annotations

from collections.abc import Callable

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.domain.analysis import AnalysisRunSummary


class ListAnalysisRuns:
    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, session_id: str) -> tuple[AnalysisRunSummary, ...]:
        if not session_id.strip():
            raise ValueError("Session ID cannot be empty.")
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.analysis_runs.list_summaries_for_session(session_id)
