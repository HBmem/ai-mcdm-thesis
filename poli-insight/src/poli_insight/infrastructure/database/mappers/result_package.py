"""Mappings for immutable result-package evidence."""

from __future__ import annotations

from poli_insight.core.time import as_utc
from poli_insight.domain.enum import (
    BundleVariant,
    PackageArtifactType,
    ParticipantReleaseStatus,
    RunInclusionStatus,
    RunStatus,
)
from poli_insight.domain.result_package import (
    ParticipantResultRelease,
    ResultPackageArtifact,
    ResultPackageRun,
    ResultPackageSubject,
)
from poli_insight.infrastructure.database.json_codec import (
    json_from_storage,
    json_to_storage,
)
from poli_insight.infrastructure.database.models.result_package import (
    ParticipantResultReleaseRow,
    ResultPackageArtifactRow,
    ResultPackageRunRow,
    ResultPackageSubjectRow,
)


def result_package_to_row(run: ResultPackageRun) -> ResultPackageRunRow:
    return ResultPackageRunRow(
        package_run_id=run.package_run_id,
        session_id=run.session_id,
        source_processing_run_id=run.source_processing_run_id,
        source_ranking_run_id=run.source_ranking_run_id,
        source_analysis_run_ids_json=json_to_storage(
            {"values": list(run.source_analysis_run_ids)}
        ),
        variants_json=json_to_storage(
            {"values": [item.value for item in run.variants]}
        ),
        run_number=run.run_number,
        status=run.status.value,
        source_roster_hash=run.source_roster_hash,
        source_processing_output_hash=run.source_processing_output_hash,
        source_ranking_output_hash=run.source_ranking_output_hash,
        input_hash=run.input_hash,
        environment_json=json_to_storage(run.environment_json),
        created_at=run.created_at,
        created_by=run.created_by,
        completed_at=run.completed_at,
        correlation_id=run.correlation_id,
        output_hash=run.output_hash,
        failure_code=run.failure_code,
        failure_detail=run.failure_detail,
        artifacts=[_artifact_to_row(item) for item in run.artifacts],
        subjects=[_subject_to_row(item) for item in run.subjects],
    )


def result_package_to_domain(row: ResultPackageRunRow) -> ResultPackageRun:
    created_at = as_utc(row.created_at)
    completed_at = as_utc(row.completed_at)
    if created_at is None or completed_at is None:
        raise RuntimeError("Persisted result package is missing timestamps.")
    analysis_ids = json_from_storage(row.source_analysis_run_ids_json).get("values", [])
    variants = json_from_storage(row.variants_json).get("values", [])
    return ResultPackageRun(
        package_run_id=str(row.package_run_id),
        session_id=str(row.session_id),
        source_processing_run_id=str(row.source_processing_run_id),
        source_ranking_run_id=str(row.source_ranking_run_id),
        source_analysis_run_ids=tuple(str(item) for item in analysis_ids),
        variants=tuple(BundleVariant(str(item)) for item in variants),
        run_number=row.run_number,
        status=RunStatus(row.status),
        source_roster_hash=row.source_roster_hash,
        source_processing_output_hash=row.source_processing_output_hash,
        source_ranking_output_hash=row.source_ranking_output_hash,
        input_hash=row.input_hash,
        environment_json=json_from_storage(row.environment_json),
        created_at=created_at,
        created_by=row.created_by,
        completed_at=completed_at,
        correlation_id=row.correlation_id,
        artifacts=tuple(
            _artifact_to_domain(item)
            for item in sorted(row.artifacts, key=lambda value: value.sequence)
        ),
        subjects=tuple(
            _subject_to_domain(item)
            for item in sorted(row.subjects, key=lambda value: value.sequence)
        ),
        output_hash=row.output_hash,
        failure_code=row.failure_code,
        failure_detail=row.failure_detail,
    )


def release_to_row(release: ParticipantResultRelease) -> ParticipantResultReleaseRow:
    return ParticipantResultReleaseRow(
        release_id=release.release_id,
        session_id=release.session_id,
        package_run_id=release.package_run_id,
        package_artifact_id=release.package_artifact_id,
        version_number=release.version_number,
        status=release.status.value,
        released_at=release.released_at,
        released_by=release.released_by,
        withdrawn_at=release.withdrawn_at,
        withdrawn_by=release.withdrawn_by,
        withdrawal_reason=release.withdrawal_reason,
    )


def release_to_domain(row: ParticipantResultReleaseRow) -> ParticipantResultRelease:
    released_at = as_utc(row.released_at)
    if released_at is None:
        raise RuntimeError("Persisted participant release is missing its timestamp.")
    return ParticipantResultRelease(
        release_id=str(row.release_id),
        session_id=str(row.session_id),
        package_run_id=str(row.package_run_id),
        package_artifact_id=str(row.package_artifact_id),
        version_number=row.version_number,
        status=ParticipantReleaseStatus(row.status),
        released_at=released_at,
        released_by=row.released_by,
        withdrawn_at=as_utc(row.withdrawn_at),
        withdrawn_by=row.withdrawn_by,
        withdrawal_reason=row.withdrawal_reason,
    )


def _artifact_to_row(item: ResultPackageArtifact) -> ResultPackageArtifactRow:
    return ResultPackageArtifactRow(
        package_artifact_id=item.package_artifact_id,
        package_run_id=item.package_run_id,
        artifact_type=item.artifact_type.value,
        name=item.name,
        sequence=item.sequence,
        schema_version=item.schema_version,
        variant=None if item.variant is None else item.variant.value,
        content_json=json_to_storage(item.content_json),
        content_hash=item.content_hash,
    )


def _artifact_to_domain(row: ResultPackageArtifactRow) -> ResultPackageArtifact:
    return ResultPackageArtifact(
        package_artifact_id=str(row.package_artifact_id),
        package_run_id=str(row.package_run_id),
        artifact_type=PackageArtifactType(row.artifact_type),
        name=row.name,
        sequence=row.sequence,
        schema_version=row.schema_version,
        variant=None if row.variant is None else BundleVariant(row.variant),
        content_json=json_from_storage(row.content_json),
        content_hash=row.content_hash,
    )


def _subject_to_row(item: ResultPackageSubject) -> ResultPackageSubjectRow:
    return ResultPackageSubjectRow(
        package_subject_id=item.package_subject_id,
        package_run_id=item.package_run_id,
        sequence=item.sequence,
        subject_key=item.subject_key,
        participant_id=item.participant_id,
        alias_snapshot=item.alias_snapshot,
        stakeholder_group_id=item.stakeholder_group_id,
        stakeholder_group_label=item.stakeholder_group_label,
        inclusion_status=item.inclusion_status.value,
        exclusion_reason=item.exclusion_reason,
        result_json=json_to_storage(item.result_json),
        content_hash=item.content_hash,
    )


def _subject_to_domain(row: ResultPackageSubjectRow) -> ResultPackageSubject:
    return ResultPackageSubject(
        package_subject_id=str(row.package_subject_id),
        package_run_id=str(row.package_run_id),
        sequence=row.sequence,
        subject_key=row.subject_key,
        participant_id=str(row.participant_id),
        alias_snapshot=row.alias_snapshot,
        stakeholder_group_id=str(row.stakeholder_group_id),
        stakeholder_group_label=row.stakeholder_group_label,
        inclusion_status=RunInclusionStatus(row.inclusion_status),
        exclusion_reason=row.exclusion_reason,
        result_json=json_from_storage(row.result_json),
        content_hash=row.content_hash,
    )
