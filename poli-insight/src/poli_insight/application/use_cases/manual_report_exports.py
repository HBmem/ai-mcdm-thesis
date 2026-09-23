"""Shared HTML and ZIP rendering consumes only an authorized SharedReport."""

from dataclasses import asdict
from html import escape
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from poli_insight.application.use_cases.result_package_exports import _json_bytes
from poli_insight.domain.reporting import SharedReport, ReportLookups


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
        archive.writestr("report.html", report_html(report))
        archive.writestr("manifest.json", _json_bytes(manifest))
        for name, evidence in report.evidence.items():
            archive.writestr(f"evidence/{name}.json", _json_bytes(evidence))
        for doc in report.documents:
            archive.writestr(f"documents/{doc.version_id}/{doc.filename}", doc.content)
    return buffer.getvalue()

def deterministic_audit_export_html(report: SharedReport) -> bytes:
    evidence = report.evidence

    context = evidence.get("context", {})
    configuration = evidence.get("configuration", {})
    validation = evidence.get("validation", {})
    weighting = evidence.get("weighting", {})
    ranking = evidence.get("ranking", {})
    analyses = evidence.get("analyses", {})
    provenance = evidence.get("provenance", {})

    lookups = _build_report_lookups(
        context=context,
        configuration=configuration,
    )

    sections = [
        _render_report_header(report, context, configuration, validation),
        _render_toc(),
        _render_session_overview(context, configuration, validation),
        _render_scenario_definition(context, lookups),
        _render_configuration(configuration, lookups),
        _render_validation(validation, configuration, lookups),
        _render_weighting(weighting, lookups),
        _render_ranking(ranking, lookups),
        _render_analyses(analyses, lookups),
        _render_provenance(report, provenance),
        _render_appendices(
            context=context,
            configuration=configuration,
            weighting=weighting,
            ranking=ranking,
            analyses=analyses,
            lookups=lookups,
        ),
    ]

def _build_report_lookups(
    context: dict,
    configuration: dict,
) -> ReportLookups:
    scenario = context.get("scenario", {})

    alternatives = {
        str(row["alternative_id"]): row.get("name", str(row["alternative_id"]))
        for row in scenario.get("alternatives", [])
    }

    criteria = {
        str(row["criterion_id"]): row.get("name", str(row["criterion_id"]))
        for row in scenario.get("criteria", [])
    }

    stakeholder_groups = {
        str(row["stakeholder_group_id"]): row.get(
            "name",
            str(row["stakeholder_group_id"]),
        )
        for row in configuration.get("stakeholder_groups", [])
    }

    return ReportLookups(
        alternatives=alternatives,
        criteria=criteria,
        stakeholder_groups=stakeholder_groups,
    )

def _render_report_header(
    report: SharedReport,
    context: dict,
    configuration: dict,
    validation: dict,
) -> str:
    parts = [
        f"<h1>{escape(report.title)}</h1><p>{state} · Revision {report.revision.number}</p>",
        "<dl>",
        f"<dt>Package run ID</dt><dd>{escape(report.package_run_id)}</dd>",
        f"<dt>Package hash</dt><dd>{escape(report.package_hash)}</dd>",
        f"<dt>Revision ID</dt><dd>{escape(report.revision.revision_id)}</dd>",
        f"<dt>Revision number</dt><dd>{escape(str(report.revision.number))}</dd>",
        f"<dt>Release ID</dt><dd>{escape(report.release_id)}</dd>",
        "</dl>",
    ]
    return "".join(parts)

def _render_ranking(
    ranking: dict,
    lookups: ReportLookups,
) -> str:
    results = ranking.get("aggregate_results", [])

    session_result = next(
        (
            result
            for result in results
            if result.get("level") == "session"
        ),
        None,
    )

    if not session_result:
        return section(
            "ranking",
            "Alternative Ranking",
            '<p class="empty">No session-level ranking recorded.</p>',
        )

    alternatives = sorted(
        session_result.get("alternatives", []),
        key=lambda row: row.get("rank", 999999),
    )

    chart_rows = [
        (
            alternative_label(row["alternative_id"], lookups),
            float(row["preference_value"]),
        )
        for row in alternatives
    ]

    chart = horizontal_bar_chart(
        chart_rows,
        value_format=lambda x: f"{x:.6f}",
    )

    table_rows = []

    for row in alternatives:
        alt_id = str(row["alternative_id"])

        table_rows.append(
            [
                row.get("rank"),
                al
            ]
        )