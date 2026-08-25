"""Mappings for versioned validation bundle persistence."""

from __future__ import annotations

from uuid import UUID

from poli_insight.core.time import as_utc
from poli_insight.domain.enum import ArtifactType, RunInclusionStatus, RunStatus
from poli_insight.domain.processing import (
    ProcessingMatrix,
    ProcessingRun,
    ProcessingRunSubmission,
    RunArtifact,
)
from poli_insight.infrastructure.database.json_codec import (
    json_from_storage,
    json_to_storage,
)
from poli_insight.infrastructure.database.models.processing import (
    ProcessingMatrixRow,
    ProcessingRunAlgorithmRow,
    ProcessingRunRow,
    ProcessingRunSubmissionRow,
    RunArtifactRow,
)


def processing_run_to_row(run: ProcessingRun) -> ProcessingRunRow:
    return ProcessingRunRow(
        processing_run_id=run.processing_run_id,
        session_id=run.session_id,
        configuration_version_id=run.configuration_version_id,
        scenario_snapshot_id=run.scenario_snapshot_id,
        run_number=run.run_number,
        status=run.status.value,
        roster_hash=run.roster_hash,
        input_hash=run.input_hash,
        environment_json=json_to_storage(run.environment_json),
        created_at=run.created_at,
        created_by=run.created_by,
        completed_at=run.completed_at,
        output_hash=run.output_hash,
        failure_code=run.failure_code,
        failure_detail=run.failure_detail,
        algorithm=ProcessingRunAlgorithmRow(
            processing_run_id=run.processing_run_id,
            algorithm_implementation_id=run.algorithm_implementation_id,
            parameter_json=json_to_storage(run.parameter_json),
        ),
        submissions=[_submission_to_row(item) for item in run.submissions],
        matrices=[_matrix_to_row(item) for item in run.matrices],
        artifacts=[_artifact_to_row(item) for item in run.artifacts],
    )


def processing_run_to_domain(row: ProcessingRunRow) -> ProcessingRun:
    created_at = as_utc(row.created_at)
    if created_at is None:
        raise RuntimeError("Persisted processing run is missing created_at.")
    return ProcessingRun(
        processing_run_id=str(row.processing_run_id),
        session_id=str(row.session_id),
        configuration_version_id=str(row.configuration_version_id),
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        run_number=row.run_number,
        status=RunStatus(row.status),
        roster_hash=row.roster_hash,
        input_hash=row.input_hash,
        algorithm_implementation_id=str(row.algorithm.algorithm_implementation_id),
        parameter_json=json_from_storage(row.algorithm.parameter_json),
        environment_json=json_from_storage(row.environment_json),
        created_at=created_at,
        created_by=row.created_by,
        completed_at=(as_utc(row.completed_at) if row.completed_at is not None else None),
        output_hash=row.output_hash,
        failure_code=row.failure_code,
        failure_detail=row.failure_detail,
        submissions=tuple(
            _submission_to_domain(item)
            for item in sorted(row.submissions, key=lambda value: str(value.submission_id))
        ),
        matrices=tuple(
            _matrix_to_domain(item)
            for item in sorted(row.matrices, key=lambda value: str(value.processing_matrix_id))
        ),
        artifacts=tuple(
            _artifact_to_domain(item)
            for item in sorted(row.artifacts, key=lambda value: str(value.run_artifact_id))
        ),
    )


def apply_processing_run(row: ProcessingRunRow, run: ProcessingRun) -> None:
    current = processing_run_to_domain(row)
    if current.status == RunStatus.SUCCEEDED:
        if current != run:
            raise RuntimeError("Succeeded processing runs are immutable.")
        return
    if current.input_hash != run.input_hash or current.processing_run_id != run.processing_run_id:
        raise RuntimeError("Processing run inputs are immutable.")
    if current.status != RunStatus.AWAITING_REVIEW or run.status != RunStatus.SUCCEEDED:
        raise RuntimeError("Unsupported processing run transition.")
    row.status = run.status.value
    row.completed_at = run.completed_at
    row.output_hash = run.output_hash
    row.failure_code = run.failure_code
    row.failure_detail = run.failure_detail
    incoming_submissions = {item.submission_id: item for item in run.submissions}
    if set(incoming_submissions) != {
        str(item.submission_id) for item in row.submissions
    }:
        raise RuntimeError("Processing run submissions are immutable.")
    for persisted in row.submissions:
        incoming = incoming_submissions[str(persisted.submission_id)]
        persisted.inclusion_status = incoming.inclusion_status.value
        persisted.exclusion_reason = incoming.exclusion_reason
        persisted.validation_id = (
            UUID(incoming.validation_id)
            if incoming.validation_id is not None
            else None
        )
    row.matrices = [_matrix_to_row(item) for item in run.matrices]
    row.artifacts = [_artifact_to_row(item) for item in run.artifacts]


def _submission_to_row(item: ProcessingRunSubmission) -> ProcessingRunSubmissionRow:
    return ProcessingRunSubmissionRow(
        processing_run_id=item.processing_run_id,
        submission_id=item.submission_id,
        participant_id=item.participant_id,
        stakeholder_group_id=item.stakeholder_group_id,
        validation_id=item.validation_id,
        inclusion_status=item.inclusion_status.value,
        exclusion_reason=item.exclusion_reason,
    )


def _submission_to_domain(row: ProcessingRunSubmissionRow) -> ProcessingRunSubmission:
    return ProcessingRunSubmission(
        processing_run_id=str(row.processing_run_id),
        submission_id=str(row.submission_id),
        participant_id=str(row.participant_id),
        stakeholder_group_id=str(row.stakeholder_group_id),
        validation_id=(str(row.validation_id) if row.validation_id is not None else None),
        inclusion_status=RunInclusionStatus(row.inclusion_status),
        exclusion_reason=row.exclusion_reason,
    )


def _matrix_to_row(item: ProcessingMatrix) -> ProcessingMatrixRow:
    return ProcessingMatrixRow(
        processing_matrix_id=item.processing_matrix_id,
        processing_run_id=item.processing_run_id,
        level=item.level,
        stakeholder_group_id=item.stakeholder_group_id,
        validation_id=item.validation_id,
        criterion_ids_json=list(item.criterion_ids),
        matrix_json=json_to_storage(item.matrix_json),
        weights_json=json_to_storage(item.weights_json),
        diagnostics_json=json_to_storage(item.diagnostics_json),
        matrix_hash=item.matrix_hash,
    )


def _matrix_to_domain(row: ProcessingMatrixRow) -> ProcessingMatrix:
    return ProcessingMatrix(
        processing_matrix_id=str(row.processing_matrix_id),
        processing_run_id=str(row.processing_run_id),
        level=row.level,
        stakeholder_group_id=(str(row.stakeholder_group_id) if row.stakeholder_group_id is not None else None),
        validation_id=(str(row.validation_id) if row.validation_id is not None else None),
        criterion_ids=tuple(str(item) for item in row.criterion_ids_json),
        matrix_json=json_from_storage(row.matrix_json),
        weights_json=json_from_storage(row.weights_json),
        diagnostics_json=json_from_storage(row.diagnostics_json),
        matrix_hash=row.matrix_hash,
    )


def _artifact_to_row(item: RunArtifact) -> RunArtifactRow:
    return RunArtifactRow(
        run_artifact_id=item.run_artifact_id,
        processing_run_id=item.processing_run_id,
        artifact_type=item.artifact_type.value,
        schema_version=item.schema_version,
        content_json=json_to_storage(item.content_json),
        content_hash=item.content_hash,
    )


def _artifact_to_domain(row: RunArtifactRow) -> RunArtifact:
    return RunArtifact(
        run_artifact_id=str(row.run_artifact_id),
        processing_run_id=str(row.processing_run_id),
        artifact_type=ArtifactType(row.artifact_type),
        schema_version=row.schema_version,
        content_json=json_from_storage(row.content_json),
        content_hash=row.content_hash,
    )
