"""SQLAlchemy repository for validation bundle processing runs."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from poli_insight.domain.processing import ProcessingRun
from poli_insight.infrastructure.database.mappers.processing import (
    apply_processing_run,
    processing_run_to_domain,
    processing_run_to_row,
)
from poli_insight.infrastructure.database.models.processing import ProcessingRunRow
from poli_insight.infrastructure.database.models.session import SessionRow


def _options():
    return (
        selectinload(ProcessingRunRow.algorithm),
        selectinload(ProcessingRunRow.submissions),
        selectinload(ProcessingRunRow.matrices),
        selectinload(ProcessingRunRow.artifacts),
    )


class SqlAlchemyProcessingRunRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(self, run: ProcessingRun) -> None:
        self._database_session.add(processing_run_to_row(run))

    def get(self, processing_run_id: str) -> ProcessingRun | None:
        row = self._load(processing_run_id, False)
        return None if row is None else processing_run_to_domain(row)

    def get_for_update(self, processing_run_id: str) -> ProcessingRun | None:
        row = self._load(processing_run_id, True)
        return None if row is None else processing_run_to_domain(row)

    def save(self, run: ProcessingRun) -> None:
        row = self._load(run.processing_run_id, True)
        if row is None:
            raise LookupError("Processing run does not exist.")
        apply_processing_run(row, run)
        self._database_session.flush()

    def next_run_number(self, session_id: str) -> int:
        dialect = self._database_session.get_bind().dialect.name
        if dialect == "sqlite":
            # Acquire SQLite's write reservation before reading MAX so two
            # explicit admin actions cannot allocate the same run number.
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
            select(func.max(ProcessingRunRow.run_number)).where(
                ProcessingRunRow.session_id == session_id
            )
        )
        return 1 if value is None else int(value) + 1

    def list_for_session(self, session_id: str) -> tuple[ProcessingRun, ...]:
        rows = self._database_session.scalars(
            select(ProcessingRunRow)
            .options(*_options())
            .where(ProcessingRunRow.session_id == session_id)
            .order_by(ProcessingRunRow.run_number.desc())
        ).all()
        return tuple(processing_run_to_domain(row) for row in rows)

    def _load(self, processing_run_id: str, for_update: bool) -> ProcessingRunRow | None:
        statement = (
            select(ProcessingRunRow)
            .options(*_options())
            .where(ProcessingRunRow.processing_run_id == processing_run_id)
        )
        if for_update and self._database_session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()
