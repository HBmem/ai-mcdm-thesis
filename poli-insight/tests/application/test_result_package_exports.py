from __future__ import annotations

import io
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from zipfile import ZipFile

from poli_insight.application.use_cases.result_package_exports import (
    ExportResultPackage,
    RenderDeterministicReport,
)
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


class _UnitOfWork:
    def __init__(self, package: ResultPackageRun) -> None:
        self.result_packages = SimpleNamespace(get=lambda _run_id: package)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _package() -> ResultPackageRun:
    run_id = "package-1"
    input_manifest = ResultPackageArtifact.create(
        package_artifact_id="artifact-input",
        package_run_id=run_id,
        artifact_type=PackageArtifactType.INPUT_MANIFEST,
        name="input_manifest",
        sequence=1,
        schema_version=1,
        content_json={"input_hash": "d" * 64},
    )
    common = ResultPackageArtifact.create(
        package_artifact_id="artifact-common",
        package_run_id=run_id,
        artifact_type=PackageArtifactType.COMMON_SECTION,
        name="01_context",
        sequence=2,
        schema_version=1,
        content_json={"session": {"title": "<Transit & Housing>"}},
    )
    manifests = tuple(
        ResultPackageArtifact.create(
            package_artifact_id=f"artifact-{variant.value}",
            package_run_id=run_id,
            artifact_type=PackageArtifactType.VARIANT_MANIFEST,
            name=f"{variant.value}_manifest",
            sequence=index,
            schema_version=1,
            variant=variant,
            content_json={"schema_version": 1, "variant": variant.value},
        )
        for index, variant in enumerate(BundleVariant, start=3)
    )
    subject = ResultPackageSubject.create(
        package_subject_id="package-subject-1",
        package_run_id=run_id,
        sequence=1,
        subject_key="subject-opaque-1",
        participant_id="participant-secret-1",
        alias_snapshot="Private Alias",
        stakeholder_group_id="group-1",
        stakeholder_group_label="Residents",
        inclusion_status=RunInclusionStatus.INCLUDED,
        result_json={"inclusion": {"status": "included"}},
    )
    now = datetime(2026, 9, 12, tzinfo=UTC)
    return ResultPackageRun.succeeded(
        package_run_id=run_id,
        session_id="session-1",
        source_processing_run_id="processing-1",
        source_ranking_run_id="ranking-1",
        source_analysis_run_ids=("analysis-1",),
        variants=(BundleVariant.ANONYMOUS, BundleVariant.PUBLIC),
        run_number=1,
        source_roster_hash="a" * 64,
        source_processing_output_hash="b" * 64,
        source_ranking_output_hash="c" * 64,
        input_hash="d" * 64,
        environment_json={},
        created_at=now,
        created_by="admin-1",
        completed_at=now,
        correlation_id="correlation-1",
        artifacts=(input_manifest, common, *manifests),
        subjects=(subject,),
    )


def test_anonymous_zip_is_deterministic_and_contains_no_subject_identity() -> None:
    package = _package()
    exporter = ExportResultPackage(lambda: _UnitOfWork(package))

    first = exporter.execute(package.package_run_id, BundleVariant.ANONYMOUS)
    second = exporter.execute(package.package_run_id, BundleVariant.ANONYMOUS)

    assert first.content == second.content
    with ZipFile(io.BytesIO(first.content)) as archive:
        assert archive.namelist() == [
            "checksums.sha256",
            "manifest.json",
            "sections/01_context.json",
        ]
        assert "identity-map.json" not in archive.namelist()
        unpacked = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"participant-secret-1" not in unpacked
        assert b"Private Alias" not in unpacked
        checksum_lines = archive.read("checksums.sha256").decode("ascii").splitlines()
        expected_lines = [
            f"{sha256(archive.read(name)).hexdigest()}  {name}"
            for name in archive.namelist()
            if name != "checksums.sha256"
        ]
        assert checksum_lines == expected_lines


def test_public_zip_isolates_association_in_identity_map() -> None:
    package = _package()
    exported = ExportResultPackage(lambda: _UnitOfWork(package)).execute(
        package.package_run_id, BundleVariant.PUBLIC
    )

    with ZipFile(io.BytesIO(exported.content)) as archive:
        identity = archive.read("identity-map.json")
        participant = archive.read("participants/subject-opaque-1.json")
        assert b"participant-secret-1" in identity
        assert b"Private Alias" in identity
        assert b"participant-secret-1" not in participant
        assert b"Private Alias" not in participant


def test_readable_report_escapes_packaged_text_and_declares_no_ai_content() -> None:
    package = _package()
    report = RenderDeterministicReport(lambda: _UnitOfWork(package)).execute(
        package.package_run_id, BundleVariant.ANONYMOUS
    )

    assert b"&lt;Transit &amp; Housing&gt;" in report.content
    assert b"contains no AI-generated content" in report.content
    assert b"<script" not in report.content.lower()
