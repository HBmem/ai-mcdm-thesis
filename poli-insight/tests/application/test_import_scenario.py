from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from poli_insight.application.ports.scenario_repository import (
    AddScenarioSnapshotResult,
)
from poli_insight.application.use_cases.import_scenario import (
    ImportScenario,
    ImportScenarioCommand,
    ScenarioImportError,
)
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.enum import ScenarioFileRole, ScenarioSnapshotStatus
from poli_insight.domain.scenario import ScenarioDefinition, ScenarioSnapshot


PROJECT_ROOT = Path(__file__).parents[2]
PUBLIC_SAFETY_SCENARIO = (
    PROJECT_ROOT / "scenarios" / "public_safety_resource_allocation"
)
SEATTLE_SCENARIO = PROJECT_ROOT / "scenarios" / "seattle_school_closure"
NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


class FakeScenarioRepository:
    def __init__(self) -> None:
        self.definitions: dict[str, ScenarioDefinition] = {}
        self.snapshots: dict[str, ScenarioSnapshot] = {}

    def add_definition(self, definition: ScenarioDefinition) -> None:
        self.definitions[definition.scenario_key] = definition

    def get_definition_by_key(
        self,
        scenario_key: str,
    ) -> ScenarioDefinition | None:
        return self.definitions.get(scenario_key)

    def add_snapshot(
        self,
        snapshot: ScenarioSnapshot,
    ) -> AddScenarioSnapshotResult:
        existing = self.snapshots.get(snapshot.root_hash)
        if existing is not None:
            return AddScenarioSnapshotResult(snapshot=existing, created=False)
        self.snapshots[snapshot.root_hash] = snapshot
        return AddScenarioSnapshotResult(snapshot=snapshot, created=True)

    def get_by_id(self, snapshot_id: str) -> ScenarioSnapshot | None:
        return next(
            (
                snapshot
                for snapshot in self.snapshots.values()
                if snapshot.scenario_snapshot_id == snapshot_id
            ),
            None,
        )

    def get_by_root_hash(self, root_hash: str) -> ScenarioSnapshot | None:
        return self.snapshots.get(root_hash)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def add(self, event: AuditEvent) -> None:
        self.events.append(event)

    def get(self, audit_id: str) -> AuditEvent | None:
        return next(
            (event for event in self.events if event.audit_event_id == audit_id),
            None,
        )

    def get_for_session(self, session_id: str) -> tuple[AuditEvent, ...]:
        return tuple(
            event for event in self.events if event.session_id == session_id
        )


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.scenarios = FakeScenarioRepository()
        self.audit_events = FakeAuditRepository()
        self.commit_count = 0
        self.rollback_count = 0

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is not None:
            self.rollback()

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def _use_case(unit_of_work: FakeUnitOfWork) -> ImportScenario:
    return ImportScenario(
        lambda: unit_of_work,
        clock=lambda: NOW,
    )


def test_import_materializes_and_captures_public_safety_scenario() -> None:
    unit_of_work = FakeUnitOfWork()

    result = _use_case(unit_of_work).execute(
        ImportScenarioCommand(
            source_directory=PUBLIC_SAFETY_SCENARIO,
            actor_id="test-importer",
            correlation_id="scenario-import-test",
        )
    )

    assert result.created is True
    assert result.ready is True
    assert result.status == ScenarioSnapshotStatus.READY
    assert len(result.root_hash) == 64
    assert len(result.materialized_input_hash) == 64
    assert unit_of_work.commit_count == 1
    assert len(unit_of_work.audit_events.events) == 1

    snapshot = unit_of_work.scenarios.snapshots[result.root_hash]
    assert len(snapshot.criteria) == 4
    assert len(snapshot.alternatives) == 4
    assert len(snapshot.matrix_values) == 16
    assert {scale.scale_key for scale in snapshot.scales} >= {
        "direct_five_point_v1",
        "direct_seven_point_v1",
        "pairwise_five_point_v1",
        "pairwise_seven_point_v1",
    }
    application_scales = tuple(
        scale
        for scale in snapshot.scales
        if scale.metadata_json.get("source") == "application"
    )
    assert len(application_scales) == 4
    assert {len(scale.values) for scale in application_scales} == {5, 7}
    assert {item.logical_path for item in snapshot.files} == {
        "criteria.json",
        "data/data.csv",
        "data_sources.json",
        "preprocessing.json",
        "scenario.json",
        "session_rules.json",
        "ui_config.json",
    }
    assert {
        item.file_role for item in snapshot.files
    } >= {
        ScenarioFileRole.SCENARIO_CONFIG,
        ScenarioFileRole.SOURCE_DATA,
    }
    assert all(item.inline_bytes is not None for item in snapshot.files)


def test_unchanged_import_reuses_content_addressed_snapshot() -> None:
    unit_of_work = FakeUnitOfWork()
    use_case = _use_case(unit_of_work)
    command = ImportScenarioCommand(
        source_directory=PUBLIC_SAFETY_SCENARIO,
        actor_id="test-importer",
        correlation_id="scenario-import-test",
    )

    first = use_case.execute(command)
    second = use_case.execute(command)

    assert first.created is True
    assert second.created is False
    assert second.scenario_snapshot_id == first.scenario_snapshot_id
    assert len(unit_of_work.scenarios.snapshots) == 1
    assert len(unit_of_work.audit_events.events) == 1


def test_changed_source_data_creates_a_different_snapshot(tmp_path: Path) -> None:
    scenario_directory = tmp_path / "scenario"
    shutil.copytree(PUBLIC_SAFETY_SCENARIO, scenario_directory)
    unit_of_work = FakeUnitOfWork()
    use_case = _use_case(unit_of_work)

    first = use_case.execute(
        ImportScenarioCommand(
            source_directory=scenario_directory,
            actor_id="test-importer",
        )
    )
    csv_path = scenario_directory / "data" / "data.csv"
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("2500000", "2500001"),
        encoding="utf-8",
    )
    second = use_case.execute(
        ImportScenarioCommand(
            source_directory=scenario_directory,
            actor_id="test-importer",
        )
    )

    assert second.created is True
    assert second.root_hash != first.root_hash
    assert second.materialized_input_hash != first.materialized_input_hash
    assert len(unit_of_work.scenarios.snapshots) == 2


def test_custom_python_requires_an_explicit_isolated_runner() -> None:
    unit_of_work = FakeUnitOfWork()

    with pytest.raises(
        ScenarioImportError,
        match="no isolated ApprovedFunctionRunner",
    ):
        _use_case(unit_of_work).execute(
            ImportScenarioCommand(
                source_directory=SEATTLE_SCENARIO,
                actor_id="test-importer",
            )
        )

    assert unit_of_work.commit_count == 0
    assert not unit_of_work.scenarios.snapshots
