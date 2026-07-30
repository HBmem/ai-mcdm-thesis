from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Load, Session, selectinload

from poli_insight.application.ports.scenario_repository import (
    AddScenarioSnapshotResult,
)
from poli_insight.domain.scenario import ScenarioDefinition, ScenarioSnapshot
from poli_insight.infrastructure.database.mappers.scenario import (
    scenario_definition_to_domain,
    scenario_definition_to_row,
    scenario_snapshot_to_domain,
    scenario_snapshot_to_row,
)
from poli_insight.infrastructure.database.models.scenario import (
    ScenarioDefinitionRow,
    ScenarioScaleRow,
    ScenarioSnapshotRow,
)


ROOT_HASH_CONSTRAINT = "uq_scenario_snapshots_root_hash"


class ScenarioSnapshotDeduplicationError(RuntimeError):
    """Raised when a duplicate snapshot exists but cannot be reloaded."""


def _is_root_hash_conflict(error: IntegrityError) -> bool:
    """Return whether *error* is the expected root-hash uniqueness race.

    PostgreSQL exposes the named constraint through ``diag``. SQLite exposes
    the affected table and columns in its exception text instead.
    """

    diagnostic = getattr(error.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == ROOT_HASH_CONSTRAINT:
        return True

    message = str(error.orig).lower()
    return (
        "unique constraint failed" in message
        and "scenario_snapshots.root_hash" in message
    )


def _snapshot_load_options() -> tuple[Load, ...]:
    """Return eager-load options required to reconstruct a snapshot."""

    return (
        selectinload(ScenarioSnapshotRow.files),
        selectinload(ScenarioSnapshotRow.criteria),
        selectinload(ScenarioSnapshotRow.alternatives),
        selectinload(ScenarioSnapshotRow.scales).selectinload(
            ScenarioScaleRow.values
        ),
        selectinload(ScenarioSnapshotRow.matrix_values),
    )


class SqlAlchemyScenarioRepository:
    """SQLAlchemy adapter for the scenario aggregate repository.

    The caller owns the outer transaction. This repository may flush to
    detect integrity conflicts, but it never commits or rolls back the
    caller's transaction.
    """

    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add_definition(
        self,
        definition: ScenarioDefinition,
    ) -> None:
        row = scenario_definition_to_row(definition)
        self._database_session.add(row)

    def get_definition_by_key(
        self,
        scenario_key: str,
    ) -> ScenarioDefinition | None:
        statement = select(ScenarioDefinitionRow).where(
            ScenarioDefinitionRow.scenario_key == scenario_key
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else scenario_definition_to_domain(row)

    def add_snapshot(
        self,
        snapshot: ScenarioSnapshot,
    ) -> AddScenarioSnapshotResult:
        existing = self.get_by_root_hash(snapshot.root_hash)
        if existing is not None:
            return AddScenarioSnapshotResult(
                snapshot=existing,
                created=False,
            )

        row = scenario_snapshot_to_row(snapshot)

        try:
            # The savepoint keeps an expected uniqueness race from poisoning
            # the unit of work's outer transaction.
            with self._database_session.begin_nested():
                self._database_session.add(row)
                self._database_session.flush()
        except IntegrityError as error:
            if not _is_root_hash_conflict(error):
                raise

            existing = self.get_by_root_hash(snapshot.root_hash)
            if existing is None:
                raise ScenarioSnapshotDeduplicationError(
                    "A scenario snapshot with root hash "
                    f"{snapshot.root_hash[:12]}... was inserted concurrently "
                    "but could not be reloaded."
                ) from error

            return AddScenarioSnapshotResult(
                snapshot=existing,
                created=False,
            )

        return AddScenarioSnapshotResult(
            snapshot=snapshot,
            created=True,
        )

    def get_by_id(
        self,
        snapshot_id: str,
    ) -> ScenarioSnapshot | None:
        statement = (
            select(ScenarioSnapshotRow)
            .options(*_snapshot_load_options())
            .where(ScenarioSnapshotRow.scenario_snapshot_id == snapshot_id)
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else scenario_snapshot_to_domain(row)

    def get_by_root_hash(
        self,
        root_hash: str,
    ) -> ScenarioSnapshot | None:
        statement = (
            select(ScenarioSnapshotRow)
            .options(*_snapshot_load_options())
            .where(ScenarioSnapshotRow.root_hash == root_hash)
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else scenario_snapshot_to_domain(row)
