from __future__ import annotations

from datetime import datetime

from poli_insight.core.time import as_utc
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


def _required_utc(value: datetime, field_name: str) -> datetime:
    utc_value = as_utc(value)
    if utc_value is None:
        raise ValueError(f"Persisted scenario is missing {field_name}.")
    return utc_value


def scenario_definition_to_row(
    definition: ScenarioDefinition,
) -> ScenarioDefinitionRow:
    return ScenarioDefinitionRow(
        scenario_definition_id=definition.scenario_definition_id,
        scenario_key=definition.scenario_key,
        title=definition.title,
        domain=definition.domain,
        description=definition.description,
        status=definition.status.value,
        created_at=definition.created_at,
        created_by=definition.created_by,
        updated_at=definition.updated_at,
        updated_by=definition.updated_by,
    )


def scenario_definition_to_domain(
    row: ScenarioDefinitionRow,
) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_definition_id=str(row.scenario_definition_id),
        scenario_key=row.scenario_key,
        title=row.title,
        domain=row.domain,
        description=row.description,
        status=ScenarioDefinitionStatus(row.status),
        created_at=_required_utc(row.created_at, "created_at"),
        created_by=row.created_by,
        updated_at=_required_utc(row.updated_at, "updated_at"),
        updated_by=row.updated_by,
    )


def scenario_snapshot_to_row(snapshot: ScenarioSnapshot) -> ScenarioSnapshotRow:
    return ScenarioSnapshotRow(
        scenario_snapshot_id=snapshot.scenario_snapshot_id,
        scenario_definition_id=snapshot.scenario_definition_id,
        declared_version=snapshot.declared_version,
        scenario_type=snapshot.scenario_type.value,
        schema_version=snapshot.schema_version,
        status=snapshot.status.value,
        title=snapshot.title,
        domain=snapshot.domain,
        summary=snapshot.summary,
        policy_question=snapshot.policy_question,
        manifest_json=dict(snapshot.manifest_json),
        manifest_schema_version=snapshot.manifest_schema_version,
        root_hash=snapshot.root_hash,
        materialized_input_hash=snapshot.materialized_input_hash,
        source_uri=snapshot.source_uri,
        importer_version=snapshot.importer_version,
        import_environment_json=dict(snapshot.import_environment_json),
        created_at=snapshot.created_at,
        created_by=snapshot.created_by,
        ready_at=snapshot.ready_at,
        files=[
            scenario_snapshot_file_to_row(
                snapshot_file,
                scenario_snapshot_id=snapshot.scenario_snapshot_id,
            )
            for snapshot_file in snapshot.files
        ],
        criteria=[
            scenario_criterion_to_row(
                criterion,
                scenario_snapshot_id=snapshot.scenario_snapshot_id,
            )
            for criterion in snapshot.criteria
        ],
        alternatives=[
            scenario_alternative_to_row(
                alternative,
                scenario_snapshot_id=snapshot.scenario_snapshot_id,
            )
            for alternative in snapshot.alternatives
        ],
        scales=[
            scenario_scale_to_row(
                scale,
                scenario_snapshot_id=snapshot.scenario_snapshot_id,
            )
            for scale in snapshot.scales
        ],
        matrix_values=[
            scenario_matrix_value_to_row(
                matrix_value,
                scenario_snapshot_id=snapshot.scenario_snapshot_id,
            )
            for matrix_value in snapshot.matrix_values
        ],
    )


def scenario_snapshot_to_domain(row: ScenarioSnapshotRow) -> ScenarioSnapshot:
    return ScenarioSnapshot(
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        scenario_definition_id=str(row.scenario_definition_id),
        declared_version=row.declared_version,
        scenario_type=ScenarioType(row.scenario_type),
        schema_version=row.schema_version,
        status=ScenarioSnapshotStatus(row.status),
        title=row.title,
        domain=row.domain,
        summary=row.summary,
        policy_question=row.policy_question,
        manifest_json=dict(row.manifest_json),
        manifest_schema_version=row.manifest_schema_version,
        root_hash=row.root_hash,
        materialized_input_hash=row.materialized_input_hash,
        source_uri=row.source_uri,
        importer_version=row.importer_version,
        import_environment_json=dict(row.import_environment_json),
        created_at=_required_utc(row.created_at, "created_at"),
        created_by=row.created_by,
        ready_at=(
            as_utc(row.ready_at)
            if row.ready_at is not None
            else None
        ),
        files=tuple(
            scenario_snapshot_file_to_domain(snapshot_file_row)
            for snapshot_file_row in sorted(
                row.files,
                key=lambda item: item.logical_path,
            )
        ),
        criteria=tuple(
            scenario_criterion_to_domain(criterion_row)
            for criterion_row in sorted(
                row.criteria,
                key=lambda item: (item.display_order, item.criterion_key),
            )
        ),
        alternatives=tuple(
            scenario_alternative_to_domain(alternative_row)
            for alternative_row in sorted(
                row.alternatives,
                key=lambda item: (item.display_order, item.alternative_key),
            )
        ),
        scales=tuple(
            scenario_scale_to_domain(scale_row)
            for scale_row in sorted(
                row.scales,
                key=lambda item: item.scale_key,
            )
        ),
        matrix_values=tuple(
            scenario_matrix_value_to_domain(matrix_value_row)
            for matrix_value_row in sorted(
                row.matrix_values,
                key=lambda item: (
                    str(item.alternative_id),
                    str(item.criterion_id),
                ),
            )
        ),
    )


def scenario_snapshot_file_to_row(
    snapshot_file: ScenarioSnapshotFile,
    *,
    scenario_snapshot_id: str,
) -> ScenarioSnapshotFileRow:
    return ScenarioSnapshotFileRow(
        snapshot_file_id=snapshot_file.snapshot_file_id,
        scenario_snapshot_id=scenario_snapshot_id,
        logical_path=snapshot_file.logical_path,
        file_role=snapshot_file.file_role.value,
        media_type=snapshot_file.media_type,
        byte_size=snapshot_file.byte_size,
        content_hash=snapshot_file.content_hash,
        inline_bytes=snapshot_file.inline_bytes,
        immutable_object_uri=snapshot_file.immutable_object_uri,
    )


def scenario_snapshot_file_to_domain(
    row: ScenarioSnapshotFileRow,
) -> ScenarioSnapshotFile:
    return ScenarioSnapshotFile(
        snapshot_file_id=str(row.snapshot_file_id),
        logical_path=row.logical_path,
        file_role=ScenarioFileRole(row.file_role),
        media_type=row.media_type,
        byte_size=row.byte_size,
        content_hash=row.content_hash,
        inline_bytes=row.inline_bytes,
        immutable_object_uri=row.immutable_object_uri,
    )


def scenario_criterion_to_row(
    criterion: ScenarioCriterion,
    *,
    scenario_snapshot_id: str,
) -> ScenarioCriterionRow:
    return ScenarioCriterionRow(
        criterion_id=criterion.criterion_id,
        scenario_snapshot_id=scenario_snapshot_id,
        criterion_key=criterion.criterion_key,
        name=criterion.name,
        description=criterion.description,
        direction=criterion.direction.value,
        data_type=criterion.data_type.value,
        unit=criterion.unit,
        parent_criterion_id=criterion.parent_criterion_id,
        required=criterion.required,
        display_order=criterion.display_order,
        source_column=criterion.source_column,
        metadata_json=dict(criterion.metadata_json),
    )


def scenario_criterion_to_domain(row: ScenarioCriterionRow) -> ScenarioCriterion:
    return ScenarioCriterion(
        criterion_id=str(row.criterion_id),
        criterion_key=row.criterion_key,
        name=row.name,
        direction=CriterionDirection(row.direction),
        data_type=CriterionDataType(row.data_type),
        display_order=row.display_order,
        description=row.description,
        unit=row.unit,
        parent_criterion_id=(
            str(row.parent_criterion_id)
            if row.parent_criterion_id is not None
            else None
        ),
        required=row.required,
        source_column=row.source_column,
        metadata_json=dict(row.metadata_json),
    )


def scenario_alternative_to_row(
    alternative: ScenarioAlternative,
    *,
    scenario_snapshot_id: str,
) -> ScenarioAlternativeRow:
    return ScenarioAlternativeRow(
        alternative_id=alternative.alternative_id,
        scenario_snapshot_id=scenario_snapshot_id,
        alternative_key=alternative.alternative_key,
        name=alternative.name,
        display_order=alternative.display_order,
        description=alternative.description,
        metadata_json=dict(alternative.metadata_json),
    )


def scenario_alternative_to_domain(
    row: ScenarioAlternativeRow,
) -> ScenarioAlternative:
    return ScenarioAlternative(
        alternative_id=str(row.alternative_id),
        alternative_key=row.alternative_key,
        name=row.name,
        display_order=row.display_order,
        description=row.description,
        metadata_json=dict(row.metadata_json),
    )


def scenario_scale_to_row(
    scale: ScenarioScale,
    *,
    scenario_snapshot_id: str,
) -> ScenarioScaleRow:
    return ScenarioScaleRow(
        scale_id=scale.scale_id,
        scenario_snapshot_id=scenario_snapshot_id,
        scale_key=scale.scale_key,
        name=scale.name,
        scale_type=scale.scale_type,
        ordered=scale.ordered,
        definition_version=scale.definition_version,
        metadata_json=dict(scale.metadata_json),
        values=[
            scenario_scale_value_to_row(scale_value)
            for scale_value in scale.values
        ],
    )


def scenario_scale_to_domain(row: ScenarioScaleRow) -> ScenarioScale:
    return ScenarioScale(
        scale_id=str(row.scale_id),
        scale_key=row.scale_key,
        name=row.name,
        scale_type=row.scale_type,
        ordered=row.ordered,
        definition_version=row.definition_version,
        metadata_json=dict(row.metadata_json),
        values=tuple(
            scenario_scale_value_to_domain(scale_value_row)
            for scale_value_row in sorted(
                row.values,
                key=lambda item: (item.ordinal, item.stable_value_key),
            )
        ),
    )


def scenario_scale_value_to_row(
    scale_value: ScenarioScaleValue,
) -> ScenarioScaleValueRow:
    return ScenarioScaleValueRow(
        scale_value_id=scale_value.scale_value_id,
        scale_id=scale_value.scale_id,
        stable_value_key=scale_value.stable_value_key,
        label=scale_value.label,
        ordinal=scale_value.ordinal,
        numeric_value=scale_value.numeric_value,
        fuzzy_lower=scale_value.fuzzy_lower,
        fuzzy_middle=scale_value.fuzzy_middle,
        fuzzy_upper=scale_value.fuzzy_upper,
        metadata_json=dict(scale_value.metadata_json),
    )


def scenario_scale_value_to_domain(
    row: ScenarioScaleValueRow,
) -> ScenarioScaleValue:
    return ScenarioScaleValue(
        scale_value_id=str(row.scale_value_id),
        scale_id=str(row.scale_id),
        stable_value_key=row.stable_value_key,
        label=row.label,
        ordinal=row.ordinal,
        numeric_value=row.numeric_value,
        fuzzy_lower=row.fuzzy_lower,
        fuzzy_middle=row.fuzzy_middle,
        fuzzy_upper=row.fuzzy_upper,
        metadata_json=dict(row.metadata_json),
    )


def scenario_matrix_value_to_row(
    matrix_value: ScenarioMatrixValue,
    *,
    scenario_snapshot_id: str,
) -> ScenarioMatrixValueRow:
    return ScenarioMatrixValueRow(
        scenario_snapshot_id=scenario_snapshot_id,
        alternative_id=matrix_value.alternative_id,
        criterion_id=matrix_value.criterion_id,
        value_numeric=matrix_value.value_numeric,
        value_json=(
            dict(matrix_value.value_json)
            if matrix_value.value_json is not None
            else None
        ),
        source_provenance_json=dict(matrix_value.source_provenance_json),
    )


def scenario_matrix_value_to_domain(
    row: ScenarioMatrixValueRow,
) -> ScenarioMatrixValue:
    return ScenarioMatrixValue(
        alternative_id=str(row.alternative_id),
        criterion_id=str(row.criterion_id),
        value_numeric=row.value_numeric,
        value_json=(
            dict(row.value_json)
            if row.value_json is not None
            else None
        ),
        source_provenance_json=dict(row.source_provenance_json),
    )
