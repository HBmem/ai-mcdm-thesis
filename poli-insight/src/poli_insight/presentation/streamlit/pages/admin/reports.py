"""Focused analysis preparation, report publication, and deferred LLM setup."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import streamlit as st

from poli_insight.application.queries.page_queries import (
    ProcessingQueueMode,
    SessionSearchFilters,
)
from poli_insight.application.use_cases.manual_reporting import (
    package_warnings,
    shared_evidence,
)
from poli_insight.domain.reporting import ReportingError
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    format_datetime,
    metric_row,
    render_empty_state,
    render_page_header,
    surface,
)
from poli_insight.presentation.streamlit.components.report_view import (
    render_evidence,
    render_shared_report,
)
from poli_insight.presentation.streamlit.components.session_search import (
    render_session_search,
)
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.pages.admin import (
    manual_report_workspace as workspace_ui,
)

TABS = ("AI Analysis", "Report Publication", "LLM Configuration")


def _navigate(key, value):
    st.session_state[key] = value


def render(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="Administration",
            title="Reports & Publication",
            description="Prepare analysis inputs, review session reports, and manage publication.",
        )
    )
    service = context.container.reporting
    if not context.principal.subject or not context.principal.has_role(
        service.admin_role
    ):
        st.error("Administrator access is required.")
        return
    # Stateful tabs execute only the visible branch. Inactive tabs do not query
    # packages/documents, build exports, or construct hidden editing forms.
    tabs = st.tabs(TABS, key="reports:tab", on_change="rerun")
    for label, tab in zip(TABS, tabs, strict=True):
        if not tab.open:
            continue
        with tab:
            if label == "LLM Configuration":
                _configuration_placeholder()
                return
            try:
                selected = _selection(context)
                if selected is None:
                    return
                summary, package = selected
                view_key = f"reports:view:{label}:{summary.session_id}:{package.package_run_id}"
                view = st.session_state.get(view_key, "overview")
                if view != "overview":
                    st.button(
                        "Back to " + label,
                        icon=":material/arrow_back:",
                        on_click=_navigate,
                        args=(view_key, "overview"),
                        key=f"{view_key}:back",
                    )
                if label == "AI Analysis":
                    _analysis(context, summary, package, view_key, view)
                else:
                    _publication(context, summary, package, view_key, view)
            except ReportingError as error:
                st.error(str(error))


@st.dialog("Filter processed sessions", width="large")
def _search_dialog(context):
    filters = render_session_search(
        key="reports:advanced",
        scenarios=context.queries.list_session_scenarios(),
        domains=context.queries.list_scenario_domains(),
    )
    if st.button("Apply filters", type="primary"):
        st.session_state["reports:filters"] = filters
        st.rerun()


def _selection(context):
    with surface(key="reports:selection", variant="filter"):
        a, b = st.columns((4, 1), vertical_alignment="bottom")
        search = a.text_input(
            "Search processed sessions",
            key="reports:quick-search",
            placeholder="Session title or scenario",
        )
        if b.button("Filters", icon=":material/filter_list:"):
            _search_dialog(context)
        saved_filters = st.session_state.get("reports:filters", SessionSearchFilters())
        filters = replace(saved_filters, search=search or saved_filters.search)
        fingerprint = sha256(repr(filters).encode()).hexdigest()[:12]
        a, b = st.columns((4, 1))
        page = int(
            b.number_input(
                "Session search page",
                min_value=1,
                value=1,
                step=1,
                key=f"reports:page:{fingerprint}",
            )
        )
        result = context.queries.list_processing_sessions(
            filters=filters, mode=ProcessingQueueMode.PROCESSED, page=page, page_size=20
        )
        if not result.items:
            render_empty_state(
                "No packaged sessions",
                "Adjust the search or page, or package a session in Session Processing.",
            )
            return None
        by_id = {item.session_id: item for item in result.items}
        requested = st.session_state.get("reports:session_id")
        session_id = a.selectbox(
            "Session",
            tuple(by_id),
            index=list(by_id).index(requested) if requested in by_id else 0,
            format_func=lambda identity: by_id[identity].title,
            key=f"reports:session:{fingerprint}:{page}",
        )
        st.session_state["reports:session_id"] = session_id
        packages = context.container.reporting.package_options(
            context.principal, session_id
        )
        if not packages:
            st.info("This session has no successful result package.")
            return None
        by_package = {p.package_run_id: p for p in packages}
        package_id = st.selectbox(
            "Package run",
            tuple(by_package),
            format_func=lambda identity: _package_label(by_package[identity], context),
            key=f"reports:package:{session_id}",
        )
        st.caption(
            f"{result.total} matching sessions · {len(packages)} package versions"
        )
    return by_id[session_id], by_package[package_id]


def _package_label(package, context):
    return f"Run {package.run_number} · {format_datetime(package.completed_at, timezone_name=context.container.settings.app_timezone)} · {package.output_hash[:10]}"


def _stale(summary, package):
    return (
        package.source_roster_hash != summary.current_roster_hash
        or package.configuration_version_id != summary.active_configuration_version_id
    )


def _analysis(context, summary, package, view_key, view):
    service, actor = context.container.reporting, context.principal
    if view == "evidence":
        st.subheader("Analysis input preview")
        st.caption(
            "Read-only package evidence. No data is being sent to an AI provider."
        )
        evidence = service.package_evidence(actor, package.package_run_id)
        warnings = package_warnings(evidence)
        if warnings:
            st.warning("; ".join(warnings))
        render_evidence(
            shared_evidence(evidence), select_section=True, key=f"{view_key}:evidence"
        )
        return
    if view == "documents":
        workspace_ui.documents(
            context, summary.session_id, service.workspace(actor, summary.session_id)
        )
        return
    with surface(key="reports:analysis:overview", variant="card"):
        st.subheader("Prepare AI analysis")
        st.write(
            "Review the selected session's evidence and approved supporting documents before analysis becomes available."
        )
        columns = metric_row(3, key="reports:analysis:metrics")
        columns[0].metric("Package", package.run_number)
        columns[1].metric("Selected analyses", len(package.source_analysis_run_ids))
        columns[2].metric(
            "Evidence", "Historical" if _stale(summary, package) else "Current"
        )
        if _stale(summary, package):
            st.warning(
                "This package is historical. Current evidence is required for publication."
            )
        a, b = st.columns(2)
        a.button(
            "Inspect analysis inputs",
            on_click=_navigate,
            args=(view_key, "evidence"),
            icon=":material/dataset:",
        )
        b.button(
            "Manage supporting documents",
            on_click=_navigate,
            args=(view_key, "documents"),
            icon=":material/folder:",
        )
    with surface(key="reports:analysis:availability", variant="card"):
        st.subheader("Analysis workflow")
        st.dataframe(
            [
                {
                    "Stage": "Explanation",
                    "Purpose": "Interpret rankings, priorities, and robustness evidence",
                    "Status": "Not connected",
                },
                {
                    "Stage": "Policy advice",
                    "Purpose": "Assess tradeoffs and proposals for further evaluation",
                    "Status": "Not connected",
                },
                {
                    "Stage": "Report drafting",
                    "Purpose": "Assemble a grounded report for moderator review",
                    "Status": "Not connected",
                },
            ],
            hide_index=True,
            width="stretch",
        )
        st.info(
            "AI integration is deferred. Agent prompts, progress, and outputs will appear here when connected."
        )
        st.button(
            "Start AI analysis",
            disabled=True,
            help="AI integration has not been implemented.",
        )
        st.button(
            "Go to Report Publication",
            on_click=_navigate,
            args=("reports:tab", "Report Publication"),
            type="primary",
        )


def _publication(context, summary, package, view_key, view):
    service, actor = context.container.reporting, context.principal
    data = service.workspace(actor, summary.session_id, include_documents=False)
    report = workspace_ui.select_report(context, package, data)
    if view == "editor":
        workspace_ui.editor(
            context,
            package,
            report,
            service.workspace(actor, summary.session_id),
            show_create=False,
        )
        return
    if view == "documents":
        workspace_ui.documents(
            context, summary.session_id, service.workspace(actor, summary.session_id)
        )
        return
    if report is None:
        st.info(
            "No report is available for this package. AI drafting is deferred; moderators may create a report draft for review."
        )
        if st.button("Create report draft", type="primary"):
            workspace_ui.create_report_dialog(context, package)
        return
    history = service.history(actor, report.report_id)
    revision = st.selectbox(
        "Report revision",
        history["revisions"],
        format_func=lambda r: f"Revision {r.number} · {r.change_summary}",
        key=f"review:{report.report_id}:revision",
    )
    reviews = history["reviews"][revision.revision_id]
    status = reviews[0].status if reviews else "draft"
    if view == "preview":
        render_shared_report(
            service.preview(actor, revision.revision_id, include_files=False),
            key=f"review:{revision.revision_id}:preview",
            include_exports=False,
            focused=True,
        )
        return
    if view == "history":
        workspace_ui.release_history(context, data)
        return
    with surface(key="reports:publication:overview", variant="card"):
        st.subheader(report.title)
        st.caption(
            f"Revision {revision.number} · {status.title()} · Source package {package.run_number}"
        )
        a, b, c = st.columns(3)
        a.button("Preview report", on_click=_navigate, args=(view_key, "preview"))
        b.button("Edit report", on_click=_navigate, args=(view_key, "editor"))
        if c.button("Review revision"):
            workspace_ui.review_dialog(context, package, revision, status)
        a, b, c = st.columns(3)
        if a.button("Export report"):
            workspace_ui.export_dialog(context, revision.revision_id)
        b.button("Release history", on_click=_navigate, args=(view_key, "history"))
        c.button(
            "Supporting documents", on_click=_navigate, args=(view_key, "documents")
        )
    with surface(key="reports:publication:release", variant="card"):
        st.subheader("Publish the reviewed report")
        if status != "approved":
            st.caption(
                "Approve this exact revision before releasing it to an audience."
            )
        if _stale(summary, package):
            st.warning("This package is historical and cannot be published.")
        a, b = st.columns(2)
        if a.button(
            "Release to participants",
            disabled=status != "approved" or _stale(summary, package),
        ):
            workspace_ui.publish_dialog(context, revision, "participant")
        if b.button(
            "Publish publicly",
            disabled=status != "approved" or _stale(summary, package),
        ):
            workspace_ui.publish_dialog(context, revision, "public")
        st.caption(
            "Participant and public releases are independent. Private participant results stay private."
        )
    with st.popover("More report actions"):
        if st.button("Create another report draft"):
            workspace_ui.create_report_dialog(context, package)


def _configuration_placeholder():
    with surface(key="reports:llm:placeholder", variant="card"):
        st.subheader("LLM Configuration")
        st.info("Administrator-only setup is reserved for a future AI integration.")
        st.write(
            "Provider and model selection, per-agent instructions, structured output schemas, approved parameters, timeout and retry limits, and version history will be managed here."
        )
        st.caption(
            "No provider is connected. No API keys, prompts, or model settings are collected or saved in this version."
        )
