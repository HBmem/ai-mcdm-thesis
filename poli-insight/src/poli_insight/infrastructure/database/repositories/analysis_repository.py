"""SQLAlchemy repository for immutable analysis runs."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from poli_insight.domain.analysis import AnalysisRun
from poli_insight.domain.enum import RunStatus
from poli_insight.infrastructure.database.mappers.analysis import (
    analysis_run_summary_to_domain,
    analysis_run_to_domain,
    analysis_run_to_row,
)
from poli_insight.infrastructure.database.models.analysis import AnalysisRunRow
from poli_insight.infrastructure.database.models.processing import ProcessingRunRow


def _options():
    return (selectinload(AnalysisRunRow.cases), selectinload(AnalysisRunRow.artifacts))


class SqlAlchemyAnalysisRunRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(self, run: AnalysisRun) -> None:
        self._database_session.add(analysis_run_to_row(run))

    def get(self, analysis_run_id: str) -> AnalysisRun | None:
        row = self._database_session.execute(
            select(AnalysisRunRow)
            .options(*_options())
            .where(AnalysisRunRow.analysis_run_id == analysis_run_id)
        ).scalar_one_or_none()
        return None if row is None else analysis_run_to_domain(row)

    def list_for_session(self, session_id: str) -> tuple[AnalysisRun, ...]:
        rows = self._database_session.scalars(
            select(AnalysisRunRow)
            .options(*_options())
            .where(AnalysisRunRow.session_id == session_id)
            .order_by(AnalysisRunRow.run_number.desc())
        ).all()
        return tuple(analysis_run_to_domain(row) for row in rows)

    def list_summaries_for_session(self, session_id: str):
        rows = self._database_session.scalars(
            select(AnalysisRunRow)
            .options(selectinload(AnalysisRunRow.artifacts))
            .where(AnalysisRunRow.session_id == session_id)
            .order_by(AnalysisRunRow.run_number.desc())
        ).all()
        return tuple(analysis_run_summary_to_domain(row) for row in rows)

    def list_for_ranking(self, ranking_run_id: str) -> tuple[AnalysisRun, ...]:
        rows = self._database_session.scalars(
            select(AnalysisRunRow)
            .options(*_options())
            .where(AnalysisRunRow.source_ranking_run_id == ranking_run_id)
            .order_by(AnalysisRunRow.run_number.desc())
        ).all()
        return tuple(analysis_run_to_domain(row) for row in rows)

    def find_success_by_input_hash(self, input_hash: str) -> AnalysisRun | None:
        row = self._database_session.execute(
            select(AnalysisRunRow)
            .options(*_options())
            .where(
                AnalysisRunRow.input_hash == input_hash,
                AnalysisRunRow.status == RunStatus.SUCCEEDED.value,
            )
        ).scalar_one_or_none()
        return None if row is None else analysis_run_to_domain(row)

    def next_run_number(self, processing_run_id: str) -> int:
        dialect = self._database_session.get_bind().dialect.name
        if dialect == "sqlite":
            self._database_session.execute(
                update(ProcessingRunRow)
                .where(ProcessingRunRow.processing_run_id == processing_run_id)
                .values(processing_run_id=ProcessingRunRow.processing_run_id)
            )
        elif dialect == "postgresql":
            self._database_session.execute(
                select(ProcessingRunRow.processing_run_id)
                .where(ProcessingRunRow.processing_run_id == processing_run_id)
                .with_for_update()
            ).scalar_one()
        value = self._database_session.scalar(
            select(func.max(AnalysisRunRow.run_number)).where(
                AnalysisRunRow.source_processing_run_id == processing_run_id
            )
        )
        return 1 if value is None else int(value) + 1
