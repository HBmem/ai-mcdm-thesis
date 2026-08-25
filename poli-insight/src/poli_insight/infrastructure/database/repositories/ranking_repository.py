"""SQLAlchemy repository for immutable ranking runs."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from poli_insight.domain.enum import RunStatus
from poli_insight.domain.ranking import RankingRun
from poli_insight.infrastructure.database.mappers.ranking import (
    ranking_run_to_domain,
    ranking_run_to_row,
)
from poli_insight.infrastructure.database.models.ranking import RankingRunRow
from poli_insight.infrastructure.database.models.session import SessionRow


def _options():
    return (
        selectinload(RankingRunRow.results),
        selectinload(RankingRunRow.artifacts),
    )


class SqlAlchemyRankingRunRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(self, run: RankingRun) -> None:
        self._database_session.add(ranking_run_to_row(run))

    def get(self, ranking_run_id: str) -> RankingRun | None:
        row = self._database_session.execute(
            select(RankingRunRow)
            .options(*_options())
            .where(RankingRunRow.ranking_run_id == ranking_run_id)
        ).scalar_one_or_none()
        return None if row is None else ranking_run_to_domain(row)

    def list_for_session(self, session_id: str) -> tuple[RankingRun, ...]:
        rows = self._database_session.scalars(
            select(RankingRunRow)
            .options(*_options())
            .where(RankingRunRow.session_id == session_id)
            .order_by(RankingRunRow.run_number.desc())
        ).all()
        return tuple(ranking_run_to_domain(row) for row in rows)

    def list_for_source(self, processing_run_id: str) -> tuple[RankingRun, ...]:
        rows = self._database_session.scalars(
            select(RankingRunRow)
            .options(*_options())
            .where(RankingRunRow.source_processing_run_id == processing_run_id)
            .order_by(RankingRunRow.run_number.desc())
        ).all()
        return tuple(ranking_run_to_domain(row) for row in rows)

    def find_success_by_input_hash(self, input_hash: str) -> RankingRun | None:
        row = self._database_session.execute(
            select(RankingRunRow)
            .options(*_options())
            .where(
                RankingRunRow.input_hash == input_hash,
                RankingRunRow.status == RunStatus.SUCCEEDED.value,
            )
        ).scalar_one_or_none()
        return None if row is None else ranking_run_to_domain(row)

    def next_run_number(self, session_id: str) -> int:
        dialect = self._database_session.get_bind().dialect.name
        if dialect == "sqlite":
            self._database_session.execute(
                update(SessionRow)
                .where(SessionRow.session_id == session_id)
                .values(session_id=SessionRow.session_id)
            )
        elif dialect == "postgresql":
            self._database_session.execute(
                select(SessionRow.session_id)
                .where(SessionRow.session_id == session_id)
                .with_for_update()
            ).scalar_one()
        value = self._database_session.scalar(
            select(func.max(RankingRunRow.run_number)).where(
                RankingRunRow.session_id == session_id
            )
        )
        return 1 if value is None else int(value) + 1
