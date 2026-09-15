from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
    ResultPackageRuleViolation,
    ResultPackageRun,
    ResultPackageSubject,
)


def _artifact(run_id: str, variant: BundleVariant) -> ResultPackageArtifact:
    return ResultPackageArtifact.create(
        package_artifact_id=f"artifact-{variant.value}",
        package_run_id=run_id,
        artifact_type=PackageArtifactType.VARIANT_MANIFEST,
        name=f"{variant.value}_manifest",
        sequence=2 if variant == BundleVariant.ANONYMOUS else 3,
        schema_version=1,
        variant=variant,
        content_json={"variant": variant.value},
    )


def _input_artifact(run_id: str) -> ResultPackageArtifact:
    return ResultPackageArtifact.create(
        package_artifact_id="artifact-input",
        package_run_id=run_id,
        artifact_type=PackageArtifactType.INPUT_MANIFEST,
        name="input_manifest",
        sequence=1,
        schema_version=1,
        content_json={"input_hash": "d" * 64},
    )


def _subject(run_id: str) -> ResultPackageSubject:
    return ResultPackageSubject.create(
        package_subject_id="package-subject-1",
        package_run_id=run_id,
        sequence=1,
        subject_key="subject-opaque-1",
        participant_id="participant-1",
        alias_snapshot="Participant 001",
        stakeholder_group_id="group-1",
        stakeholder_group_label="Residents",
        inclusion_status=RunInclusionStatus.INCLUDED,
        result_json={"inclusion": {"status": "included"}},
    )


def _run_values(run_id: str) -> dict[str, object]:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    return {
        "package_run_id": run_id,
        "session_id": "session-1",
        "source_processing_run_id": "processing-1",
        "source_ranking_run_id": "ranking-1",
        "source_analysis_run_ids": ("analysis-1",),
        "run_number": 1,
        "source_roster_hash": "a" * 64,
        "source_processing_output_hash": "b" * 64,
        "source_ranking_output_hash": "c" * 64,
        "input_hash": "d" * 64,
        "environment_json": {"renderer": "v1"},
        "created_at": now,
        "created_by": "admin-1",
        "completed_at": now,
        "correlation_id": "correlation-1",
    }


def test_successful_public_package_hashes_artifacts_and_subjects() -> None:
    run_id = "package-1"
    run = ResultPackageRun.succeeded(
        **_run_values(run_id),
        variants=(BundleVariant.PUBLIC,),
        artifacts=(_input_artifact(run_id), _artifact(run_id, BundleVariant.PUBLIC)),
        subjects=(_subject(run_id),),
    )

    assert run.status == RunStatus.SUCCEEDED
    assert run.output_hash is not None


def test_anonymous_only_package_rejects_identity_linked_subjects() -> None:
    run_id = "package-1"
    with pytest.raises(ResultPackageRuleViolation, match="Anonymous-only"):
        ResultPackageRun.succeeded(
            **_run_values(run_id),
            variants=(BundleVariant.ANONYMOUS,),
            artifacts=(
                _input_artifact(run_id),
                _artifact(run_id, BundleVariant.ANONYMOUS),
            ),
            subjects=(_subject(run_id),),
        )


def test_release_withdrawal_is_immutable_and_requires_complete_evidence() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    active = ParticipantResultRelease(
        release_id="release-1",
        session_id="session-1",
        package_run_id="package-1",
        package_artifact_id="artifact-public",
        version_number=1,
        status=ParticipantReleaseStatus.ACTIVE,
        released_at=now,
        released_by="admin-1",
    )

    withdrawn = active.withdraw(at=now, actor_id="admin-2", reason="Updated consent")

    assert active.status == ParticipantReleaseStatus.ACTIVE
    assert withdrawn.status == ParticipantReleaseStatus.WITHDRAWN
    assert withdrawn.withdrawal_reason == "Updated consent"
