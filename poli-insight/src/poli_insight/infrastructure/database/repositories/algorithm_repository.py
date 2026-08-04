"""SQLAlchemy adapter for the algorithm registry."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from poli_insight.application.ports.algorithm_repository import (
    AlgorithmImplementation,
)
from poli_insight.domain.enum import AlgorithmRole
from poli_insight.infrastructure.database.models.session import (
    AlgorithmImplementationRow,
)


class SqlAlchemyAlgorithmRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def get_many(
        self,
        implementation_ids: tuple[str, ...],
    ) -> tuple[AlgorithmImplementation, ...]:
        if not implementation_ids:
            return ()
        statement = (
            select(AlgorithmImplementationRow)
            .where(
                AlgorithmImplementationRow.algorithm_implementation_id.in_(
                    implementation_ids
                )
            )
            .order_by(
                AlgorithmImplementationRow.role,
                AlgorithmImplementationRow.stable_key,
            )
        )
        rows = self._database_session.scalars(statement).all()
        return tuple(_to_application(row) for row in rows)


def _to_application(
    row: AlgorithmImplementationRow,
) -> AlgorithmImplementation:
    return AlgorithmImplementation(
        algorithm_implementation_id=str(row.algorithm_implementation_id),
        stable_key=row.stable_key,
        role=AlgorithmRole(row.role),
        conceptual_method=row.conceptual_method,
        provider=row.provider,
        library_name=row.library_name,
        library_version=row.library_version,
        implementation_version=row.implementation_version,
        adapter_version=row.adapter_version,
        parameter_schema_json=dict(row.parameter_schema_json),
        capabilities_json=dict(row.capabilities_json),
        active=row.status == "active",
    )
