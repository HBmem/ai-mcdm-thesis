from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import sqlite3
from contextlib import nullcontext
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from poli_insight.domain.enum import (
    CriterionDataType,
    CriterionDirection,
    ScenarioDefinitionStatus,
    ScenarioFileRole,
    ScenarioSnapshotStatus,
    ScenarioType,
)
from poli_insight.domain.scenario import (
    ScenarioAlternative,
    ScenarioCriterion,
    ScenarioDefinition,
    ScenarioMatrixValue,
    ScenarioScale,
    ScenarioScaleValue,
    ScenarioSnapshot,
    ScenarioSnapshotFile,
)
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.models.scenario import (
    ScenarioAlternativeRow,
    ScenarioCriterionRow,
    ScenarioDefinitionRow,
    ScenarioMatrixValueRow,
    ScenarioScaleRow,
    ScenarioScaleValueRow,
    ScenarioSnapshotFileRow,
    ScenarioSnapshotRow,
)
from poli_insight.infrastructure.database.repositories.scenario_repository import (
    SqlAlchemyScenarioRepository,
)


@pytest.fixture
def engine():
    database_engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(database_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


def _id() -> str:
    return str(uuid4())


def _definition() -> ScenarioDefinition:
    now = datetime(2026, 7, 29, 12, tzinfo=UTC)
    return ScenarioDefinition(
        scenario_definition_id=_id(),
        scenario_key="school_selection",
        title="School selection",
        domain="education",
        description="Select a school using multiple criteria.",
        status=ScenarioDefinitionStatus.ACTIVE,
        created_at=now,
        created_by="test-suite",
        updated_at=now,
        updated_by="test-suite",
    )


def _snapshot(
    definition_id: str,
    *,
    snapshot_id: str | None = None,
    root_hash: str = "a" * 64,
) -> ScenarioSnapshot:
    criterion_cost_id = _id()
    criterion_quality_id = _id()
    alternative_north_id = _id()
    alternative_south_id = _id()
    scale_id = _id()
    now = datetime(2026, 7, 29, 12, 5, tzinfo=UTC)

    return ScenarioSnapshot(
        scenario_snapshot_id=snapshot_id or _id(),
        scenario_definition_id=definition_id,
        declared_version="1.0",
        scenario_type=ScenarioType.STANDARD,
        schema_version=1,
        status=ScenarioSnapshotStatus.READY,
        title="School selection 1.0",
        domain="education",
        summary="A reproducible school-selection scenario.",
        policy_question="Which school should be selected?",
        manifest_json={"schema_version": 1, "files": ["scenario.json"]},
        manifest_schema_version=1,
        root_hash=root_hash,
        materialized_input_hash="b" * 64,
        source_uri=None,
        importer_version="test-importer/1",
        import_environment_json={"python": "3.12"},
        created_at=now,
        created_by="test-suite",
        ready_at=now,
        files=(
            ScenarioSnapshotFile(
                snapshot_file_id=_id(),
                logical_path="scenario.json",
                file_role=ScenarioFileRole.SCENARIO_CONFIG,
                media_type="application/json",
                byte_size=2,
                content_hash="c" * 64,
                inline_bytes=b"{}",
            ),
        ),
        # Deliberately reverse display order to verify deterministic mapping.
        criteria=(
            ScenarioCriterion(
                criterion_id=criterion_quality_id,
                criterion_key="quality",
                name="Quality",
                direction=CriterionDirection.BENEFIT,
                data_type=CriterionDataType.NUMERIC,
                display_order=1,
            ),
            ScenarioCriterion(
                criterion_id=criterion_cost_id,
                criterion_key="cost",
                name="Cost",
                direction=CriterionDirection.COST,
                data_type=CriterionDataType.NUMERIC,
                display_order=0,
            ),
        ),
        alternatives=(
            ScenarioAlternative(
                alternative_id=alternative_south_id,
                alternative_key="south",
                name="South School",
                display_order=1,
            ),
            ScenarioAlternative(
                alternative_id=alternative_north_id,
                alternative_key="north",
                name="North School",
                display_order=0,
            ),
        ),
        scales=(
            ScenarioScale(
                scale_id=scale_id,
                scale_key="importance",
                name="Importance",
                scale_type="crisp",
                ordered=True,
                definition_version=1,
                metadata_json={},
                values=(
                    ScenarioScaleValue(
                        scale_value_id=_id(),
                        scale_id=scale_id,
                        stable_value_key="high",
                        label="High",
                        ordinal=1,
                        numeric_value=Decimal("2"),
                        metadata_json={},
                    ),
                    ScenarioScaleValue(
                        scale_value_id=_id(),
                        scale_id=scale_id,
                        stable_value_key="low",
                        label="Low",
                        ordinal=0,
                        numeric_value=Decimal("1"),
                        metadata_json={},
                    ),
                ),
            ),
        ),
        matrix_values=(
            ScenarioMatrixValue(
                alternative_id=alternative_north_id,
                criterion_id=criterion_cost_id,
                value_numeric=Decimal("10"),
                source_provenance_json={"row": 1},
            ),
            ScenarioMatrixValue(
                alternative_id=alternative_north_id,
                criterion_id=criterion_quality_id,
                value_numeric=Decimal("8"),
                source_provenance_json={"row": 1},
            ),
            ScenarioMatrixValue(
                alternative_id=alternative_south_id,
                criterion_id=criterion_cost_id,
                value_numeric=Decimal("12"),
                source_provenance_json={"row": 2},
            ),
            ScenarioMatrixValue(
                alternative_id=alternative_south_id,
                criterion_id=criterion_quality_id,
                value_numeric=Decimal("9"),
                source_provenance_json={"row": 2},
            ),
        ),
    )


def test_add_and_load_complete_snapshot_aggregate(engine) -> None:
    definition = _definition()
    snapshot = _snapshot(definition.scenario_definition_id)

    with Session(engine) as session:
        repository = SqlAlchemyScenarioRepository(session)
        repository.add_definition(definition)
        result = repository.add_snapshot(snapshot)
        session.commit()

        assert result.created is True
        assert result.snapshot == snapshot

    with Session(engine) as session:
        repository = SqlAlchemyScenarioRepository(session)
        loaded_definition = repository.get_definition_by_key(
            definition.scenario_key
        )
        loaded = repository.get_by_id(snapshot.scenario_snapshot_id)

    assert loaded_definition == definition
    assert loaded is not None
    assert loaded.scenario_snapshot_id == snapshot.scenario_snapshot_id
    assert [item.criterion_key for item in loaded.criteria] == [
        "cost",
        "quality",
    ]
    assert [item.alternative_key for item in loaded.alternatives] == [
        "north",
        "south",
    ]
    assert [item.stable_value_key for item in loaded.scales[0].values] == [
        "low",
        "high",
    ]
    assert len(loaded.files) == 1
    assert len(loaded.matrix_values) == 4


def test_add_snapshot_deduplicates_by_root_hash(engine) -> None:
    definition = _definition()
    first = _snapshot(definition.scenario_definition_id)

    with Session(engine) as session:
        repository = SqlAlchemyScenarioRepository(session)
        repository.add_definition(definition)
        first_result = repository.add_snapshot(first)
        session.commit()

    duplicate = _snapshot(
        definition.scenario_definition_id,
        snapshot_id=_id(),
        root_hash=first.root_hash,
    )
    with Session(engine) as session:
        repository = SqlAlchemyScenarioRepository(session)
        duplicate_result = repository.add_snapshot(duplicate)
        session.commit()

        assert first_result.created is True
        assert duplicate_result.created is False
        assert (
            duplicate_result.snapshot.scenario_snapshot_id
            == first.scenario_snapshot_id
        )
        counts = {
            row_type: session.scalar(select(func.count()).select_from(row_type))
            for row_type in (
                ScenarioSnapshotRow,
                ScenarioSnapshotFileRow,
                ScenarioCriterionRow,
                ScenarioAlternativeRow,
                ScenarioScaleRow,
                ScenarioScaleValueRow,
                ScenarioMatrixValueRow,
            )
        }
        assert counts == {
            ScenarioSnapshotRow: 1,
            ScenarioSnapshotFileRow: 1,
            ScenarioCriterionRow: 2,
            ScenarioAlternativeRow: 2,
            ScenarioScaleRow: 1,
            ScenarioScaleValueRow: 2,
            ScenarioMatrixValueRow: 4,
        }


def test_repository_does_not_commit_outer_transaction(engine) -> None:
    definition = _definition()
    snapshot = _snapshot(definition.scenario_definition_id)

    with Session(engine) as session:
        transaction = session.begin()
        repository = SqlAlchemyScenarioRepository(session)
        repository.add_definition(definition)
        repository.add_snapshot(snapshot)
        transaction.rollback()

    with Session(engine) as session:
        assert session.get(
            ScenarioDefinitionRow,
            definition.scenario_definition_id,
        ) is None
        assert session.get(
            ScenarioSnapshotRow,
            snapshot.scenario_snapshot_id,
        ) is None


def test_unexpected_integrity_error_is_not_treated_as_deduplication(engine) -> None:
    snapshot = _snapshot(_id())

    with Session(engine) as session:
        transaction = session.begin()
        repository = SqlAlchemyScenarioRepository(session)

        with pytest.raises(IntegrityError):
            repository.add_snapshot(snapshot)

        # The failed insert was isolated to a savepoint. The caller still
        # controls a usable outer transaction.
        assert session.in_transaction()
        snapshot_count = session.scalar(
            select(func.count()).select_from(ScenarioSnapshotRow)
        )
        assert snapshot_count == 0
        transaction.rollback()


def test_expected_root_hash_race_returns_winning_snapshot() -> None:
    definition = _definition()
    winner = _snapshot(definition.scenario_definition_id)
    contender = _snapshot(
        definition.scenario_definition_id,
        snapshot_id=_id(),
        root_hash=winner.root_hash,
    )

    class RaceSession:
        def begin_nested(self):
            return nullcontext()

        def add(self, row) -> None:
            del row

        def flush(self) -> None:
            original = sqlite3.IntegrityError(
                "UNIQUE constraint failed: scenario_snapshots.root_hash"
            )
            raise IntegrityError("INSERT", {}, original)

    repository = SqlAlchemyScenarioRepository(RaceSession())  # type: ignore[arg-type]
    with patch.object(
        repository,
        "get_by_root_hash",
        side_effect=(None, winner),
    ):
        result = repository.add_snapshot(contender)

    assert result.created is False
    assert result.snapshot == winner
