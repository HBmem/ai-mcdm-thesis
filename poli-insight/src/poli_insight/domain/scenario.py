from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from poli_insight.core.time import is_aware_datetime
from poli_insight.domain.enum import (
    ScenarioSnapshotStatus,
    ScenarioDefinitionStatus,
    ScenarioFileRole,
    CriterionDirection,
    CriterionDataType,
    ScenarioType,
)

class ScenarioDefinitionRuleViolation(ValueError):
    """Raised when an operation violates Scenario Definition business rules."""
    pass

class ScenarioSnapshotRuleViolation(ValueError):
    """Raised when an operation violates Scenario Snapshot business rules."""
    pass

JsonObject = Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    scenario_definition_id: str
    scenario_key: str
    title: str
    domain: str
    description: str
    status: ScenarioDefinitionStatus

    # Audit timestamps
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_schedule()

    def _validate_identity(self) -> None:
        if not self.scenario_definition_id.strip():
            raise ScenarioDefinitionRuleViolation(
                "Scenario Definition ID cannot be empty."
            )

        if not self.scenario_key.strip():
            raise ScenarioDefinitionRuleViolation(
                "Scenario Key cannot be empty."
            )
        
        if not self.title.strip():
            raise ScenarioDefinitionRuleViolation(
                "Title cannot be empty."
            )

        if not self.domain.strip():
            raise ScenarioDefinitionRuleViolation(
                "Domain cannot be empty."
            )

        if not self.description.strip():
            raise ScenarioDefinitionRuleViolation(
                "Description cannot be empty."
            )
        
        if not self.created_by.strip():
            raise ScenarioDefinitionRuleViolation(
                "Created by cannot be empty."
            )

    def _validate_schedule(self) -> None:
        if not is_aware_datetime(self.created_at):
            raise ScenarioDefinitionRuleViolation(
                "Created_at must include timezone information."
            )
        if not is_aware_datetime(self.updated_at):
            raise ScenarioDefinitionRuleViolation(
                "Updated_at must include timezone information."
            )
        
@dataclass(frozen=True, slots=True)
class ScenarioSnapshot:
    scenario_snapshot_id: str
    scenario_definition_id: str

    declared_version: str
    scenario_type: ScenarioType
    schema_version: int
    status: ScenarioSnapshotStatus

    title: str
    domain: str
    summary: str
    policy_question: str

    manifest_json: JsonObject
    root_hash: str
    materialized_input_hash: str

    source_uri: str | None
    importer_version: str
    import_environment_json: JsonObject

    created_at: datetime
    created_by: str

    files: tuple[ScenarioSnapshotFile, ...]
    criteria: tuple[ScenarioCriterion, ...]
    alternatives: tuple[ScenarioAlternative, ...]
    scales: tuple[ScenarioScale, ...]
    matrix_values: tuple[ScenarioMatrixValue, ...]

    ready_at: datetime | None = None
    manifest_schema_version: int = 1

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_schedule()
        self._validate_criterion_keys()

    def _validate_identity(self) -> None:
        if not self.scenario_snapshot_id.strip():
            raise ScenarioSnapshotRuleViolation(
                "Scenario Snapshot ID cannot be empty."
            )

        if not self.scenario_definition_id.strip():
            raise ScenarioDefinitionRuleViolation(
                "Scenario Definition ID cannot be empty."
            )
        
        if not self.title.strip():
            raise ScenarioSnapshotRuleViolation(
                "Title cannot be empty."
            )

        if not self.domain.strip():
            raise ScenarioSnapshotRuleViolation(
                "Domain cannot be empty."
            )

        if not self.summary.strip():
            raise ScenarioSnapshotRuleViolation(
                "Summary cannot be empty."
            )
        if not self.policy_question.strip():
            raise ScenarioSnapshotRuleViolation(
                "Question cannot be empty."
            )

    def _validate_schedule(self) -> None:
        if not is_aware_datetime(self.created_at):
            raise ScenarioSnapshotRuleViolation(
                "Created_at must include timezone information"
            ) 
        if not is_aware_datetime(self.ready_at):
            raise ScenarioSnapshotRuleViolation(
                "Ready_at must include timezone information"
            )

    def _validate_criterion_keys(self) -> None:
        criterion_keys: list[str] = []

        for criterion in self.criteria:
            criterion_key = criterion.criterion_key

            if not criterion_key.strip():
                raise ScenarioSnapshotRuleViolation(
                    "Criterion key cannot be empty."
                )

            if criterion_key != criterion_key.strip():
                raise ScenarioSnapshotRuleViolation(
                    f"Criterion key {criterion_key!r} cannot contain "
                    "leading or trailing whitespace."
                )

            criterion_keys.append(criterion_key)

        if len(criterion_keys) != len(set(criterion_keys)):
            raise ScenarioSnapshotRuleViolation(
                "Criterion keys must be unique within a scenario snapshot."
            )

@dataclass(frozen=True, slots=True)
class ScenarioSnapshotFile:
    snapshot_file_id: str
    logical_path: str
    file_role: ScenarioFileRole
    media_type: str
    byte_size: int
    content_hash: str
    inline_bytes: bytes | None = None
    immutable_object_uri: str | None = None

@dataclass(frozen=True, slots=True)
class ScenarioCriterion:
    criterion_id: str
    criterion_key: str
    name: str
    direction: CriterionDirection
    data_type: CriterionDataType
    display_order: int
    description: str | None = None
    unit: str | None = None
    parent_criterion_id: str | None = None
    required: bool = True
    source_column: str | None = None
    metadata_json: JsonObject = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ScenarioAlternative:
    alternative_id: str
    alternative_key: str
    name: str
    display_order: int
    description: str | None = None
    metadata_json: JsonObject = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ScenarioScale:
    scale_id: str
    scale_key: str
    name: str
    scale_type: str
    ordered: bool
    definition_version: int
    metadata_json: JsonObject
    values: tuple[ScenarioScaleValue, ...]

@dataclass(frozen=True, slots=True)
class ScenarioScaleValue:
    scale_value_id: str
    scale_id: str
    stable_value_key: str
    label: str
    ordinal: int
    metadata_json: JsonObject
    numeric_value: Decimal | None = None
    fuzzy_lower: Decimal | None = None
    fuzzy_middle: Decimal | None = None
    fuzzy_upper: Decimal | None = None

@dataclass(frozen=True, slots=True)
class ScenarioMatrixValue:
    alternative_id: str
    criterion_id: str
    source_provenance_json: JsonObject
    value_numeric: Decimal | None = None
    value_json: JsonObject | None = None
