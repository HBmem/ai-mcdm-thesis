"""Mappings for immutable analysis evidence."""

from __future__ import annotations

from poli_insight.core.time import as_utc
from poli_insight.domain.analysis import (
    AnalysisArtifact,
    AnalysisCase,
    AnalysisRun,
    AnalysisRunSummary,
)
from poli_insight.domain.enum import (
    AnalysisCaseStatus,
    AnalysisMethod,
    AnalysisType,
    ArtifactType,
    RunStatus,
)
from poli_insight.infrastructure.database.json_codec import (
    json_from_storage,
    json_to_storage,
)
from poli_insight.infrastructure.database.models.analysis import (
    AnalysisArtifactRow,
    AnalysisCaseRow,
    AnalysisRunRow,
)


def analysis_run_to_row(run: AnalysisRun) -> AnalysisRunRow:
    return AnalysisRunRow(
        analysis_run_id=run.analysis_run_id,
        session_id=run.session_id,
        source_processing_run_id=run.source_processing_run_id,
        source_ranking_run_id=run.source_ranking_run_id,
        run_number=run.run_number,
        analysis_type=run.analysis_type.value,
        method=run.method.value,
        status=run.status.value,
        source_processing_output_hash=run.source_processing_output_hash,
        source_ranking_output_hash=run.source_ranking_output_hash,
        input_hash=run.input_hash,
        parameter_json=json_to_storage(run.parameter_json),
        environment_json=json_to_storage(run.environment_json),
        created_at=run.created_at,
        created_by=run.created_by,
        completed_at=run.completed_at,
        correlation_id=run.correlation_id,
        output_hash=run.output_hash,
        failure_code=run.failure_code,
        failure_detail=run.failure_detail,
        cases=[_case_to_row(item) for item in run.cases],
        artifacts=[_artifact_to_row(item) for item in run.artifacts],
    )


def analysis_run_to_domain(row: AnalysisRunRow) -> AnalysisRun:
    created_at = as_utc(row.created_at)
    completed_at = as_utc(row.completed_at)
    if created_at is None or completed_at is None:
        raise RuntimeError("Persisted analysis run is missing timestamps.")
    return AnalysisRun(
        analysis_run_id=str(row.analysis_run_id),
        session_id=str(row.session_id),
        source_processing_run_id=str(row.source_processing_run_id),
        source_ranking_run_id=str(row.source_ranking_run_id),
        run_number=row.run_number,
        analysis_type=AnalysisType(row.analysis_type),
        method=AnalysisMethod(row.method),
        status=RunStatus(row.status),
        source_processing_output_hash=row.source_processing_output_hash,
        source_ranking_output_hash=row.source_ranking_output_hash,
        input_hash=row.input_hash,
        parameter_json=json_from_storage(row.parameter_json),
        environment_json=json_from_storage(row.environment_json),
        created_at=created_at,
        created_by=row.created_by,
        completed_at=completed_at,
        correlation_id=row.correlation_id,
        output_hash=row.output_hash,
        failure_code=row.failure_code,
        failure_detail=row.failure_detail,
        cases=tuple(
            _case_to_domain(item)
            for item in sorted(row.cases, key=lambda value: value.sequence)
        ),
        artifacts=tuple(
            _artifact_to_domain(item)
            for item in sorted(
                row.artifacts,
                key=lambda value: (
                    value.artifact_type,
                    str(value.analysis_artifact_id),
                ),
            )
        ),
    )


def analysis_run_summary_to_domain(row: AnalysisRunRow) -> AnalysisRunSummary:
    created_at = as_utc(row.created_at)
    completed_at = as_utc(row.completed_at)
    if created_at is None or completed_at is None:
        raise RuntimeError("Persisted analysis run is missing timestamps.")
    return AnalysisRunSummary(
        analysis_run_id=str(row.analysis_run_id),
        session_id=str(row.session_id),
        source_processing_run_id=str(row.source_processing_run_id),
        source_ranking_run_id=str(row.source_ranking_run_id),
        run_number=row.run_number,
        analysis_type=AnalysisType(row.analysis_type),
        method=AnalysisMethod(row.method),
        status=RunStatus(row.status),
        source_processing_output_hash=row.source_processing_output_hash,
        source_ranking_output_hash=row.source_ranking_output_hash,
        input_hash=row.input_hash,
        parameter_json=json_from_storage(row.parameter_json),
        environment_json=json_from_storage(row.environment_json),
        created_at=created_at,
        created_by=row.created_by,
        completed_at=completed_at,
        correlation_id=row.correlation_id,
        artifacts=tuple(
            _artifact_to_domain(item)
            for item in sorted(
                row.artifacts,
                key=lambda value: (
                    value.artifact_type,
                    str(value.analysis_artifact_id),
                ),
            )
        ),
        output_hash=row.output_hash,
        failure_code=row.failure_code,
        failure_detail=row.failure_detail,
    )


def _case_to_row(item: AnalysisCase) -> AnalysisCaseRow:
    return AnalysisCaseRow(
        analysis_case_id=item.analysis_case_id,
        analysis_run_id=item.analysis_run_id,
        sequence=item.sequence,
        status=item.status.value,
        scope_type=item.scope_type,
        scope_id=item.scope_id,
        subject_type=item.subject_type,
        subject_id=item.subject_id,
        input_json=json_to_storage(item.input_json),
        result_json=json_to_storage(item.result_json),
        warnings_json=json_to_storage({"values": list(item.warnings)}),
        content_hash=item.content_hash,
    )


def _case_to_domain(row: AnalysisCaseRow) -> AnalysisCase:
    return AnalysisCase(
        analysis_case_id=str(row.analysis_case_id),
        analysis_run_id=str(row.analysis_run_id),
        sequence=row.sequence,
        status=AnalysisCaseStatus(row.status),
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        input_json=json_from_storage(row.input_json),
        result_json=json_from_storage(row.result_json),
        warnings=tuple(
            str(item) for item in json_from_storage(row.warnings_json).get("values", [])
        ),
        content_hash=row.content_hash,
    )


def _artifact_to_row(item: AnalysisArtifact) -> AnalysisArtifactRow:
    return AnalysisArtifactRow(
        analysis_artifact_id=item.analysis_artifact_id,
        analysis_run_id=item.analysis_run_id,
        artifact_type=item.artifact_type.value,
        schema_version=item.schema_version,
        content_json=json_to_storage(item.content_json),
        content_hash=item.content_hash,
    )


def _artifact_to_domain(row: AnalysisArtifactRow) -> AnalysisArtifact:
    return AnalysisArtifact(
        analysis_artifact_id=str(row.analysis_artifact_id),
        analysis_run_id=str(row.analysis_run_id),
        artifact_type=ArtifactType(row.artifact_type),
        schema_version=row.schema_version,
        content_json=json_from_storage(row.content_json),
        content_hash=row.content_hash,
    )
