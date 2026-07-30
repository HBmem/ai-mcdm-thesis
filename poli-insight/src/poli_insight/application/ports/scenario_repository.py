from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from poli_insight.domain.scenario import ScenarioDefinition, ScenarioSnapshot


@dataclass(frozen=True, slots=True)
class AddScenarioSnapshotResult:
    """Outcome of adding a content-addressed scenario snapshot."""

    snapshot: ScenarioSnapshot
    created: bool


class ScenarioRepository(Protocol):
    def add_definition(
        self,
        definition: ScenarioDefinition,
    ) -> None:
        ...

    def get_definition_by_key(
        self,
        scenario_key: str,
    ) -> ScenarioDefinition | None:
        ...

    def add_snapshot(
        self,
        snapshot: ScenarioSnapshot,
    ) -> AddScenarioSnapshotResult:
        ...

    def get_by_id(
        self,
        snapshot_id: str,
    ) -> ScenarioSnapshot | None:
        ...

    def get_by_root_hash(
        self,
        root_hash: str,
    ) -> ScenarioSnapshot | None:
        ...
