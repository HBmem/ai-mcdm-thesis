from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from poli_insight.domain.enum import (
    BundleVariant,
    PackageArtifactType,
    RunInclusionStatus,
)
from poli_insight.domain.result_package import (
    ResultPackageArtifact,
    ResultPackageRun,
    ResultPackageSubject,
)
from poli_insight.infrastructure.database.mappers.result_package import (
    result_package_to_domain,
    result_package_to_row,
)


def test_result_package_mapper_round_trips_canonical_decimal_evidence() -> None:
    run_id = str(uuid4())
    input_manifest = ResultPackageArtifact.create(
        package_artifact_id=str(uuid4()),
        package_run_id=run_id,
        artifact_type=PackageArtifactType.INPUT_MANIFEST,
        name="input_manifest",
        sequence=1,
        schema_version=1,
        content_json={"input_hash": "d" * 64},
    )
    manifest = ResultPackageArtifact.create(
        package_artifact_id=str(uuid4()),
        package_run_id=run_id,
        artifact_type=PackageArtifactType.VARIANT_MANIFEST,
        name="public_manifest",
        sequence=2,
        schema_version=1,
        variant=BundleVariant.PUBLIC,
        content_json={"variant": "public", "score": Decimal("0.250")},
    )
    subject = ResultPackageSubject.create(
        package_subject_id=str(uuid4()),
        package_run_id=run_id,
        sequence=1,
        subject_key="subject-opaque",
        participant_id=str(uuid4()),
        alias_snapshot="Participant 001",
        stakeholder_group_id=str(uuid4()),
        stakeholder_group_label="Residents",
        inclusion_status=RunInclusionStatus.INCLUDED,
        result_json={"weights": {"criterion-1": Decimal("0.250")}},
    )
    now = datetime(2026, 9, 12, tzinfo=UTC)
    run = ResultPackageRun.succeeded(
        package_run_id=run_id,
        session_id=str(uuid4()),
        source_processing_run_id=str(uuid4()),
        source_ranking_run_id=str(uuid4()),
        source_analysis_run_ids=(str(uuid4()),),
        variants=(BundleVariant.PUBLIC,),
        run_number=3,
        source_roster_hash="a" * 64,
        source_processing_output_hash="b" * 64,
        source_ranking_output_hash="c" * 64,
        input_hash="d" * 64,
        environment_json={"renderer": "v1"},
        created_at=now,
        created_by="admin-1",
        completed_at=now,
        correlation_id="correlation-1",
        artifacts=(input_manifest, manifest),
        subjects=(subject,),
    )

    restored = result_package_to_domain(result_package_to_row(run))

    assert restored == run
