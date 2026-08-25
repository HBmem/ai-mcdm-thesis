"""Mappings for immutable ranking evidence."""

from __future__ import annotations

from decimal import Decimal

from poli_insight.core.time import as_utc
from poli_insight.domain.enum import ArtifactType, RunStatus
from poli_insight.domain.ranking import (
    RankedAlternative,
    RankingArtifact,
    RankingResult,
    RankingRun,
)
from poli_insight.infrastructure.database.json_codec import (
    json_from_storage,
    json_to_storage,
)
from poli_insight.infrastructure.database.models.ranking import (
    RankingArtifactRow,
    RankingResultRow,
    RankingRunRow,
)


def ranking_run_to_row(run: RankingRun) -> RankingRunRow:
    return RankingRunRow(
        ranking_run_id=run.ranking_run_id,
        session_id=run.session_id,
        source_processing_run_id=run.source_processing_run_id,
        configuration_version_id=run.configuration_version_id,
        scenario_snapshot_id=run.scenario_snapshot_id,
        run_number=run.run_number,
        status=run.status.value,
        roster_hash=run.roster_hash,
        input_hash=run.input_hash,
        algorithm_implementation_id=run.algorithm_implementation_id,
        implementation_version=run.implementation_version,
        adapter_version=run.adapter_version,
        parameter_json=json_to_storage(run.parameter_json),
        environment_json=json_to_storage(run.environment_json),
        created_at=run.created_at,
        created_by=run.created_by,
        completed_at=run.completed_at,
        output_hash=run.output_hash,
        failure_code=run.failure_code,
        failure_detail=run.failure_detail,
        results=[_result_to_row(item) for item in run.results],
        artifacts=[_artifact_to_row(item) for item in run.artifacts],
    )


def ranking_run_to_domain(row: RankingRunRow) -> RankingRun:
    created_at = as_utc(row.created_at)
    completed_at = as_utc(row.completed_at)
    if created_at is None or completed_at is None:
        raise RuntimeError("Persisted ranking run is missing timestamps.")
    return RankingRun(
        ranking_run_id=str(row.ranking_run_id),
        session_id=str(row.session_id),
        source_processing_run_id=str(row.source_processing_run_id),
        configuration_version_id=str(row.configuration_version_id),
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        run_number=row.run_number,
        status=RunStatus(row.status),
        roster_hash=row.roster_hash,
        input_hash=row.input_hash,
        algorithm_implementation_id=str(row.algorithm_implementation_id),
        implementation_version=row.implementation_version,
        adapter_version=row.adapter_version,
        parameter_json=json_from_storage(row.parameter_json),
        environment_json=json_from_storage(row.environment_json),
        created_at=created_at,
        created_by=row.created_by,
        completed_at=completed_at,
        output_hash=row.output_hash,
        failure_code=row.failure_code,
        failure_detail=row.failure_detail,
        results=tuple(
            _result_to_domain(item)
            for item in sorted(
                row.results,
                key=lambda value: str(value.source_processing_matrix_id),
            )
        ),
        artifacts=tuple(
            _artifact_to_domain(item)
            for item in sorted(
                row.artifacts,
                key=lambda value: (value.artifact_type, str(value.ranking_artifact_id)),
            )
        ),
    )


def _result_to_row(item: RankingResult) -> RankingResultRow:
    return RankingResultRow(
        ranking_result_id=item.ranking_result_id,
        ranking_run_id=item.ranking_run_id,
        source_processing_matrix_id=item.source_processing_matrix_id,
        level=item.level,
        stakeholder_group_id=item.stakeholder_group_id,
        validation_id=item.validation_id,
        alternatives_json=json_to_storage(
            {"values": [value.to_manifest() for value in item.alternatives]}
        ),
        metric_label=item.metric_label,
        diagnostics_json=json_to_storage(item.diagnostics_json),
        result_hash=item.result_hash,
    )


def _result_to_domain(row: RankingResultRow) -> RankingResult:
    values = json_from_storage(row.alternatives_json).get("values", [])
    return RankingResult(
        ranking_result_id=str(row.ranking_result_id),
        ranking_run_id=str(row.ranking_run_id),
        source_processing_matrix_id=str(row.source_processing_matrix_id),
        level=row.level,
        stakeholder_group_id=(
            str(row.stakeholder_group_id)
            if row.stakeholder_group_id is not None
            else None
        ),
        validation_id=(
            str(row.validation_id) if row.validation_id is not None else None
        ),
        alternatives=tuple(
            RankedAlternative(
                alternative_id=str(item["alternative_id"]),
                rank=int(item["rank"]),
                preference_value=(
                    item["preference_value"]
                    if isinstance(item["preference_value"], Decimal)
                    else Decimal(str(item["preference_value"]))
                ),
                method_metrics_json=dict(item.get("method_metrics", {})),
            )
            for item in values
        ),
        metric_label=row.metric_label,
        diagnostics_json=json_from_storage(row.diagnostics_json),
        result_hash=row.result_hash,
    )


def _artifact_to_row(item: RankingArtifact) -> RankingArtifactRow:
    return RankingArtifactRow(
        ranking_artifact_id=item.ranking_artifact_id,
        ranking_run_id=item.ranking_run_id,
        artifact_type=item.artifact_type.value,
        schema_version=item.schema_version,
        content_json=json_to_storage(item.content_json),
        content_hash=item.content_hash,
    )


def _artifact_to_domain(row: RankingArtifactRow) -> RankingArtifact:
    return RankingArtifact(
        ranking_artifact_id=str(row.ranking_artifact_id),
        ranking_run_id=str(row.ranking_run_id),
        artifact_type=ArtifactType(row.artifact_type),
        schema_version=row.schema_version,
        content_json=json_from_storage(row.content_json),
        content_hash=row.content_hash,
    )
