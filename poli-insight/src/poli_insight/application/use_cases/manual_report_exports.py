"""Shared HTML and ZIP rendering consumes only an authorized SharedReport."""

from dataclasses import asdict
from html import escape
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from poli_insight.application.use_cases.result_package_exports import _json_bytes
from poli_insight.application.use_cases.deterministic_audit_renderer import deterministic_audit_export_html
from poli_insight.domain.reporting import SharedReport


def evidence_html(value):
    if isinstance(value, dict):
        return (
            "<dl>"
            + "".join(
                f"<dt>{escape(str(key).replace('_', ' '))}</dt><dd>{evidence_html(item)}</dd>"
                for key, item in value.items()
            )
            + "</dl>"
        )
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(item, dict) for item in value):
            keys = list(dict.fromkeys(key for item in value for key in item))
            return (
                '<div class="table"><table><thead><tr>'
                + "".join(f"<th>{escape(str(k).replace('_', ' '))}</th>" for k in keys)
                + "</tr></thead><tbody>"
                + "".join(
                    "<tr>"
                    + "".join(f"<td>{evidence_html(item.get(k))}</td>" for k in keys)
                    + "</tr>"
                    for item in value
                )
                + "</tbody></table></div>"
            )
        return (
            "<ul>"
            + "".join(f"<li>{evidence_html(item)}</li>" for item in value)
            + "</ul>"
        )
    return escape("Not recorded" if value is None else str(value))


def report_html(report: SharedReport) -> bytes:
    state = (
        "DRAFT — not approved for publication" if report.draft else "Approved report"
    )
    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(report.title)}</title>",
        "<style>body{font:16px system-ui;color:#172B4D;max-width:1100px;margin:2rem auto;padding:1rem}p{white-space:pre-wrap}table{border-collapse:collapse}th,td{border:1px solid #d6dee8;padding:.5rem;text-align:left;vertical-align:top}.table{overflow-x:auto}dt{font-weight:bold;margin-top:.5rem}dd{margin-left:1rem}h2{margin-top:2rem}</style><body><main>",
        f"<h1>{escape(report.title)}</h1><p>{state} · Revision {report.revision.number}</p>",
    ]
    for title, narrative in report.revision.sections.items():
        text = (
            "Not assessed"
            if narrative is None
            else narrative or "Awaiting moderator input"
        )
        parts.append(
            f"<section><h2>{escape(title)}</h2><p>{escape(text)}</p></section>"
        )
    parts.append("<h2>Fixed package evidence</h2>")
    for name, value in report.evidence.items():
        parts.append(
            f'<section id="{escape(name)}"><h2>{escape(name[3:].replace("_", " ").title())}</h2>{evidence_html(value)}</section>'
        )
    parts.append("<h2>Sources and provenance</h2>")
    parts.append(
        f"<p>Package: {escape(report.package_run_id)}<br>Package hash: {escape(report.package_hash)}<br>Revision: {escape(report.revision.revision_id)}</p>"
    )
    for ref in report.revision.evidence_refs:
        parts.append(f"<p>Evidence: {escape(ref)}</p>")
    for doc in report.documents:
        parts.append(
            f"<p>{escape(doc.title)} · version {doc.number}<br>{escape(doc.source_reference)}<br>SHA-256: {escape(doc.content_hash)}</p>"
        )
    parts.append("</main></body></html>")
    return "".join(parts).encode("utf-8")

def report_zip(report: SharedReport) -> bytes:
    # Do not serialize domain records wholesale: actor IDs and internal metadata
    # are intentionally not part of the public revision/source manifest.
    manifest = {
        "schema_version": 1,
        "title": report.title,
        "draft": report.draft,
        "revision_id": report.revision.revision_id,
        "revision_number": report.revision.number,
        "package_run_id": report.package_run_id,
        "package_hash": report.package_hash,
        "release_id": report.release_id,
        "evidence_refs": report.revision.evidence_refs,
        "documents": [
            {
                key: asdict(doc)[key]
                for key in (
                    "version_id",
                    "number",
                    "title",
                    "source_reference",
                    "filename",
                    "media_type",
                    "content_hash",
                )
            }
            for doc in report.documents
        ],
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("report.html", deterministic_audit_export_html(report))
        archive.writestr("manifest.json", _json_bytes(manifest))
        for name, evidence in report.evidence.items():
            archive.writestr(f"evidence/{name}.json", _json_bytes(evidence))
        for doc in report.documents:
            archive.writestr(f"documents/{doc.version_id}/{doc.filename}", doc.content)
    return buffer.getvalue()
