"""Reviewed public reports and authorized private participant results."""

from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from poli_insight.application.use_cases.participant_result_release import (
    ParticipantResultReleaseError,
)
from poli_insight.application.use_cases.result_package_exports import (
    participant_report_html,
)
from poli_insight.domain.reporting import ReportingError
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    render_page_header,
    surface,
)
from poli_insight.presentation.streamlit.components.report_view import (
    render_shared_report,
)
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.urls import public_report_url


def render(context: PageContext) -> None:
    access_token = _query_value("access")
    if access_token:
        _render_private_result(context, access_token)
        return
    report_id = _query_value("report")
    if report_id:
        render_page_header(
            PageHeader(
                eyebrow="Reviewed release",
                title="Published Report",
                description="A moderator-approved report from frozen session evidence.",
            )
        )
        try:
            report = context.container.reporting.public_report(report_id)
        except ReportingError:
            st.warning(
                "This public report is unavailable. It may have been withdrawn, replaced, or become stale."
            )
            return
        render_shared_report(report, key=f"public:{report_id}")
        return
    render_page_header(
        PageHeader(
            eyebrow="Reviewed releases",
            title="Published Results",
            description=(
                "Browse moderator-approved session reports. Participant-specific "
                "results remain available through authorized private links."
            ),
        )
    )
    search = st.text_input("Search published reports", key="public:reports:search")
    page = int(
        st.number_input(
            "Catalog page",
            min_value=1,
            value=1,
            step=1,
            key=f"public:reports:page:{search}",
        )
    )
    items, total = context.container.reporting.public_catalog(search, page=page)
    st.caption(f"{total} published reports · Page {page}")
    if not items:
        st.info("No published reports match this page and search.")
    for item in items:
        with surface(key=f"public:release:{item['release_id']}", variant="card"):
            st.subheader(item["title"])
            st.caption(
                f"Revision {item['revision']} · Released {item['released_at'].isoformat()}"
            )
            st.link_button(
                "Read report",
                public_report_url(
                    context.container.settings.public_base_url,
                    release_id=item["release_id"],
                ),
            )


def _render_private_result(context: PageContext, access_token: str) -> None:
    try:
        released = context.container.packages.participant_access.execute(access_token)
    except ParticipantResultReleaseError as error:
        render_page_header(
            PageHeader(
                eyebrow="Participant results",
                title="Released results unavailable",
                description=str(error),
            )
        )
        st.warning(
            "The release may have been withdrawn, replaced, or the private link may no "
            "longer be authorized.",
            icon=":material/link_off:",
        )
        return
    requested_session = _query_value("session")
    if requested_session and requested_session != released.public_slug:
        render_page_header(
            PageHeader(
                eyebrow="Participant results",
                title="Released results unavailable",
                description="Released participant results are unavailable for this link.",
            )
        )
        return

    render_page_header(
        PageHeader(
            eyebrow=f"Private participant release · version {released.release_version}",
            title=released.session_title,
            description=(
                f"Personalized deterministic results for {released.alias}. Only your "
                "record and the packaged group/session aggregates are shown."
            ),
        )
    )
    st.info(
        "This breakdown is generated from frozen package evidence and contains no "
        "AI-generated interpretation. Keep this private link confidential."
    )
    result = released.result
    inclusion = result.get("inclusion")
    _section("How your input affected eligibility", inclusion, expanded=True)
    if isinstance(inclusion, Mapping) and inclusion.get("status") != "included":
        st.warning(
            "Your input was not included in the collective calculation for the recorded "
            "reason. No weights, ranking, or influence have been fabricated."
        )
    _section("What you submitted", result.get("preferences"))
    _section("Your criterion weights", result.get("weights"))
    _section("Your ranking", result.get("rankings"))
    _section(
        "How your stakeholder group was represented",
        result.get("stakeholder_representation"),
    )
    _section("Participant-influence testing", result.get("participant_influence"))
    st.caption(
        "Influence testing removes one participant and recalculates the result. It is a "
        "counterfactual robustness check, not proof that one person caused an outcome."
    )
    report = participant_report_html(
        session_title=released.session_title,
        alias=released.alias,
        stakeholder_group=released.stakeholder_group,
        result=result,
        aggregate_sections=released.aggregate_sections,
    )
    with surface(key="results:download", variant="card"):
        st.download_button(
            "Download my readable report",
            data=report,
            file_name=f"participant-results-release-{released.release_version}.html",
            mime="text/html",
            icon=":material/download:",
        )
    st.caption(
        "The complete identity-linked bundle and identity map are not available from "
        "participant access."
    )
    reporting = getattr(context.container, "reporting", None)
    if reporting is not None:
        st.divider()
        st.subheader("Shared session report")
        try:
            report = reporting.participant_report(access_token)
            if report is None:
                st.info(
                    "A shared session report has not been released to participants."
                )
            else:
                render_shared_report(
                    report, key=f"participant:shared:{report.release_id}"
                )
        except ReportingError as error:
            st.info(str(error))


def _section(label: str, value: object, *, expanded: bool = False) -> None:
    with st.expander(label, expanded=expanded):
        if value is None:
            st.caption("Not measured or not applicable in the selected package.")
        else:
            st.json(value)


def _query_value(key: str) -> str | None:
    value = st.query_params.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
