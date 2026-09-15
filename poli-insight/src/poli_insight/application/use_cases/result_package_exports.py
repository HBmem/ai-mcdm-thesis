"""Deterministic ZIP and HTML projections of canonical result packages."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from html import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.domain.enum import BundleVariant, PackageArtifactType, RunStatus
from poli_insight.domain.result_package import ResultPackageRun

_SAFE_NAME = re.compile(r"^[0-9a-z_]+$")


class ResultPackageExportError(ValueError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class ResultPackageDownload:
    filename: str
    media_type: str
    content: bytes


class ExportResultPackage:
    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self, package_run_id: str, variant: BundleVariant
    ) -> ResultPackageDownload:
        run = self._load(package_run_id, variant)
        files = _bundle_files(run, variant)
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for path, content in files.items():
                info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, content)
        return ResultPackageDownload(
            filename=f"result-package-{run.run_number}-{variant.value}.zip",
            media_type="application/zip",
            content=buffer.getvalue(),
        )

    def _load(self, package_run_id: str, variant: BundleVariant) -> ResultPackageRun:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.result_packages.get(package_run_id)
        if run is None or run.status != RunStatus.SUCCEEDED:
            raise ResultPackageExportError(
                "The selected result package is unavailable."
            )
        if variant not in run.variants:
            raise ResultPackageExportError(
                "The selected package version was not generated."
            )
        return run


class RenderDeterministicReport:
    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self, package_run_id: str, variant: BundleVariant
    ) -> ResultPackageDownload:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.result_packages.get(package_run_id)
        if (
            run is None
            or run.status != RunStatus.SUCCEEDED
            or variant not in run.variants
        ):
            raise ResultPackageExportError(
                "The selected result package is unavailable."
            )
        html = _complete_report_html(run, variant)
        return ResultPackageDownload(
            filename=f"result-report-{run.run_number}-{variant.value}.html",
            media_type="text/html",
            content=html.encode("utf-8"),
        )


def participant_report_html(
    *,
    session_title: str,
    alias: str,
    stakeholder_group: str,
    result: Mapping[str, object],
    aggregate_sections: Mapping[str, Mapping[str, object]],
) -> bytes:
    sections = [
        _html_header(f"Personalized results — {alias}"),
        f"<p><strong>Session:</strong> {escape(session_title)}</p>",
        f"<p><strong>Stakeholder group:</strong> {escape(stakeholder_group)}</p>",
        _result_explanation(result),
        _html_object("What you submitted", result.get("preferences")),
        _html_object("Your weights and aggregate comparisons", result.get("weights")),
        _html_object("Your rankings and aggregate comparisons", result.get("rankings")),
        _html_object(
            "How your group was represented", result.get("stakeholder_representation")
        ),
        _html_object("Participant-influence test", result.get("participant_influence")),
        _html_object("Session context", aggregate_sections.get("01_context")),
        "</main></body></html>",
    ]
    return "".join(sections).encode("utf-8")


def _bundle_files(run: ResultPackageRun, variant: BundleVariant) -> dict[str, bytes]:
    variant_artifact = next(
        item
        for item in run.artifacts
        if item.artifact_type == PackageArtifactType.VARIANT_MANIFEST
        and item.variant == variant
    )
    common = [
        item
        for item in run.artifacts
        if item.artifact_type == PackageArtifactType.COMMON_SECTION
    ]
    files: dict[str, bytes] = {}
    manifest = {
        **dict(variant_artifact.content_json),
        "package": {
            "package_run_id": run.package_run_id,
            "run_number": run.run_number,
            "created_at": run.created_at,
            "output_hash": run.output_hash,
            "source_processing_output_hash": run.source_processing_output_hash,
            "source_ranking_output_hash": run.source_ranking_output_hash,
        },
    }
    files["manifest.json"] = _json_bytes(manifest)
    for artifact in common:
        if not _SAFE_NAME.fullmatch(artifact.name):
            raise ResultPackageExportError("A package section has an unsafe name.")
        files[f"sections/{artifact.name}.json"] = _json_bytes(artifact.content_json)
    if variant == BundleVariant.PUBLIC:
        identity_map = []
        for subject in run.subjects:
            if not _SAFE_NAME.fullmatch(subject.subject_key.replace("-", "_")):
                raise ResultPackageExportError("A package subject has an unsafe key.")
            identity_map.append(
                {
                    "subject_key": subject.subject_key,
                    "participant_id": subject.participant_id,
                    "alias": subject.alias_snapshot,
                    "stakeholder_group_id": subject.stakeholder_group_id,
                    "stakeholder_group": subject.stakeholder_group_label,
                    "inclusion_status": subject.inclusion_status.value,
                    "exclusion_reason": subject.exclusion_reason,
                }
            )
            files[f"participants/{subject.subject_key}.json"] = _json_bytes(
                {
                    "schema_version": 1,
                    "subject_key": subject.subject_key,
                    "result": dict(subject.result_json),
                    "content_hash": subject.content_hash,
                }
            )
        files["identity-map.json"] = _json_bytes(
            {"schema_version": 1, "subjects": identity_map}
        )
    checksums = "".join(
        f"{sha256(content).hexdigest()}  {path}\n"
        for path, content in sorted(files.items())
    )
    files["checksums.sha256"] = checksums.encode("ascii")
    return dict(sorted(files.items()))


def _complete_report_html(run: ResultPackageRun, variant: BundleVariant) -> str:
    common = {
        item.name: item.content_json
        for item in run.artifacts
        if item.artifact_type == PackageArtifactType.COMMON_SECTION
    }
    title = (
        common.get("01_context", {}).get("session", {}).get("title", "Result package")
        if isinstance(common.get("01_context", {}).get("session", {}), Mapping)
        else "Result package"
    )
    sections = [
        _html_header(f"{title} — {variant.value.title()} deterministic report"),
        (
            "<p>This report is generated from deterministic packaged evidence. "
            "It contains no AI-generated content.</p>"
        ),
    ]
    labels = {
        "01_context": "Session and scenario context",
        "02_configuration": "Configuration and stakeholder representation",
        "03_validation": "Validation and inclusion",
        "04_weighting": "Criteria weights",
        "05_ranking": "Alternative rankings",
        "06_analyses": "Sensitivity and robustness",
        "07_provenance": "Warnings and provenance",
    }
    for name, label in labels.items():
        sections.append(_html_object(label, common.get(name)))
    if variant == BundleVariant.PUBLIC:
        sections.append("<h2>Participant appendix</h2>")
        for subject in run.subjects:
            sections.append(
                f"<h3>{escape(subject.alias_snapshot)}</h3>"
                f"<p><strong>Package subject key:</strong> "
                f"{escape(subject.subject_key)}</p>"
            )
            sections.append(_result_explanation(subject.result_json))
            sections.append(
                _html_object("Packaged participant evidence", subject.result_json)
            )
    sections.append("</main></body></html>")
    return "".join(sections)


def _html_header(title: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title><style>"
        "body{font-family:system-ui,sans-serif;line-height:1.5;color:#172033;"
        "max-width:1100px;margin:2rem auto;padding:0 1rem}"
        "h1,h2,h3{color:#14213d}section{margin:1.5rem 0;break-inside:avoid}"
        "pre{white-space:pre-wrap;background:#f4f6f8;padding:1rem;border-radius:.4rem;"
        "overflow-wrap:anywhere}@media print{body{margin:0;max-width:none}}"
        "</style></head><body><main>"
        f"<h1>{escape(title)}</h1>"
    )


def _html_object(label: str, value: object) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default
    )
    return f"<section><h2>{escape(label)}</h2><pre>{escape(serialized)}</pre></section>"


def _result_explanation(result: Mapping[str, object]) -> str:
    inclusion = result.get("inclusion", {})
    status = inclusion.get("status") if isinstance(inclusion, Mapping) else None
    if status != "included":
        reason = (
            inclusion.get("exclusion_reason")
            if isinstance(inclusion, Mapping)
            else None
        )
        return (
            "<p>This input was not included in the collective calculation. "
            f"Recorded reason: <strong>{escape(str(reason or 'not recorded'))}</strong>. "
            "No individual influence is inferred.</p>"
        )
    influence = result.get("participant_influence", {})
    influence_status = (
        influence.get("status") if isinstance(influence, Mapping) else "not_measured"
    )
    return (
        "<p>This participant's accepted judgments contributed to their stakeholder "
        "group aggregate, which then contributed according to the frozen group allocation. "
        f"Participant influence status: <strong>{escape(str(influence_status))}</strong>. "
        "Leave-one-out results are counterfactual sensitivity evidence, not proof of causation.</p>"
    )


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)
