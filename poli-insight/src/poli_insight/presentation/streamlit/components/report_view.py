"""Read-only package evidence and shared-report presentation."""

import json
from collections.abc import Mapping

import streamlit as st

from poli_insight.application.use_cases.manual_report_exports import (
    report_html,
    report_zip,
)

_SECTION_DESCRIPTIONS = {
    "01_context": "The frozen policy question, alternatives, criteria, and decision matrix.",
    "02_configuration": "The response format, calculation methods, and configured and effective group representation.",
    "03_validation": "Which submissions were included or excluded and the recorded reasons.",
    "04_weighting": "Calculated criterion priorities at stakeholder-group and session levels.",
    "05_ranking": "Calculated alternative ranks and method-specific scores for each group and the session.",
    "06_analyses": "Selected sensitivity and robustness cases, their outcomes, and tests missing from this package.",
    "07_provenance": "Source identifiers and lineage for tracing the report back to its frozen evidence.",
}


def _cell(value):
    if value is None:
        return "Not recorded"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def _evidence_value(value):
    if isinstance(value, Mapping):
        scalars = {
            key: item
            for key, item in value.items()
            if not isinstance(item, (Mapping, list, tuple))
        }
        if scalars:
            st.dataframe(
                [
                    {"Field": key.replace("_", " "), "Value": _cell(item)}
                    for key, item in scalars.items()
                ],
                hide_index=True,
                width="stretch",
            )
        for key, item in value.items():
            if isinstance(item, (Mapping, list, tuple)):
                st.caption(key.replace("_", " ").title())
                _evidence_value(item)
    elif isinstance(value, (list, tuple)):
        if not value:
            st.caption("No records in this package.")
        elif all(isinstance(item, Mapping) for item in value):
            st.dataframe(
                [
                    {
                        str(key).replace("_", " "): _cell(item)
                        for key, item in row.items()
                    }
                    for row in value
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.dataframe(
                [{"Value": _cell(item)} for item in value],
                hide_index=True,
                width="stretch",
            )
    else:
        st.text(_cell(value))


def render_evidence(evidence, *, raw=True, select_section=False, key="report:evidence"):
    if select_section and evidence:
        selected = st.selectbox(
            "Evidence section",
            tuple(evidence),
            format_func=lambda name: name[3:].replace("_", " ").title(),
            key=key,
        )
        evidence = {selected: evidence[selected]}
    for name, value in evidence.items():
        with st.expander(name[3:].replace("_", " ").title(), expanded=select_section):
            st.caption(_SECTION_DESCRIPTIONS.get(name, "Frozen package evidence."))
            _evidence_value(value)
            if name == "02_configuration":
                groups = value.get("stakeholder_groups", ())
                if any("effective_voting_power" not in group for group in groups):
                    st.caption(
                        "Effective voting power was not recorded in this historical package."
                    )
            if raw and st.checkbox("Show structured evidence", key=f"{key}:{name}:raw"):
                st.json(value)


def render_shared_report(report, *, key, include_exports=True, focused=False):
    st.subheader(report.title)
    st.caption(
        f"{'DRAFT — not approved for publication' if report.draft else 'Approved report'} · Revision {report.revision.number}"
    )
    section = (
        st.selectbox(
            "Report content",
            ("Narrative", "Package evidence", "Sources"),
            key=f"{key}:section",
        )
        if focused
        else None
    )
    if section in {None, "Narrative"}:
        for title, value in report.revision.sections.items():
            st.subheader(title)
            st.text(
                "Not assessed" if value is None else value or "Awaiting moderator input"
            )
    if section in {None, "Package evidence"}:
        st.subheader("Fixed package evidence")
        render_evidence(report.evidence, select_section=True, key=f"{key}:evidence")
    if section in {None, "Sources"}:
        st.subheader("Sources and provenance")
        st.caption(f"Package {report.package_run_id} · Hash {report.package_hash}")
        for ref in report.revision.evidence_refs:
            st.text(f"Evidence: {ref}")
        for doc in report.documents:
            st.text(f"{doc.title} · version {doc.number}\n{doc.source_reference}")
            if include_exports:
                st.download_button(
                    "Download supporting document",
                    doc.content,
                    file_name=doc.filename,
                    mime=doc.media_type,
                    key=f"{key}:doc:{doc.version_id}",
                )
    if include_exports and st.toggle(
        "Prepare report downloads", key=f"{key}:downloads"
    ):
        render_report_downloads(report, key=key)


def render_report_downloads(report, *, key):
    a, b = st.columns(2)
    suffix = "-draft" if report.draft else ""
    a.download_button(
        "Export report HTML",
        report_html(report),
        file_name=f"report-{report.revision.number}{suffix}.html",
        mime="text/html",
        key=f"{key}:html",
    )
    b.download_button(
        "Export report and evidence",
        report_zip(report),
        file_name=f"report-{report.revision.number}{suffix}.zip",
        mime="application/zip",
        key=f"{key}:zip",
    )
