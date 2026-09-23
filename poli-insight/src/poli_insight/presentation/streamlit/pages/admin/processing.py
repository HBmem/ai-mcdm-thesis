from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256
from typing import Any, Literal

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st
from streamlit_extras.card_selector import (  # type: ignore[import-untyped]
    card_selector,
)
from streamlit_extras.pagination import pagination  # type: ignore[import-untyped]
from streamlit_extras.steps import steps  # type: ignore[import-untyped]

from poli_insight.application.queries.page_queries import (
    PageQueryError,
    ProcessingMatrixView,
    ProcessingQueueMode,
    ProcessingSessionSummary,
    ProcessingSubmissionContext,
    RankingResultView,
    SessionDateField,
    SessionValidationOverview,
)
from poli_insight.application.use_cases.create_ranking import (
    CreateRankingCommand,
    CreateRankingError,
)
from poli_insight.application.use_cases.finalize_validation_bundle import (
    FinalizeValidationBundleCommand,
)
from poli_insight.application.use_cases.review_submission import (
    ReviewSubmissionCommand,
    ReviewSubmissionError,
)
from poli_insight.application.use_cases.validate_current_submissions import (
    ValidateCurrentSubmissionsCommand,
)
from poli_insight.domain.enum import (
    AlgorithmRole,
    ArtifactType,
    RunStatus,
    SessionStatus,
    SubmissionReviewStatus,
    ValidationStatus,
)
from poli_insight.presentation.streamlit.components.layout import (
    AdminSurfaceVariant,
    PageHeader,
    admin_surface,
    format_datetime,
    metric_row,
    render_empty_state,
    render_page_header,
    render_section_heading,
)
from poli_insight.presentation.streamlit.components.session_search import (
    render_session_search,
)
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.pages.admin.analysis_section import (
    render_analysis_stage,
)
from poli_insight.presentation.streamlit.pages.admin.package_section import (
    render_package_stage,
)

_PAGE_SIZE = 10
_STAGES = (
    "Session Validation",
    "Submission Validation",
    "Weight Generation",
    "Create Ranking",
    "Sensitivity and Robustness",
    "Package Results",
)
_STAGE_ICONS = (
    ":material/domain_verification:",
    ":material/fact_check:",
    ":material/weight:",
    ":material/leaderboard:",
    ":material/query_stats:",
    ":material/package_2:",
)
_MATRIX_LEVEL_ORDER = ("participant", "stakeholder_group", "session")
_MATRIX_LEVEL_PRESENTATION: dict[
    str,
    tuple[str, str, str, AdminSurfaceVariant],
] = {
    "participant": (
        "Individual evidence",
        "One participant's validated matrix. This is not aggregate data.",
        ":material/person:",
        "individual",
    ),
    "stakeholder_group": (
        "Stakeholder-group aggregate",
        "Accepted individual evidence combined within one stakeholder group.",
        ":material/groups:",
        "group_aggregate",
    ),
    "session": (
        "Session aggregate",
        "Stakeholder-group matrices combined using configured voting power.",
        ":material/hub:",
        "session_aggregate",
    ),
}


def render(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="Administration",
            title="Session Processing",
            description=(
                "Validate frozen sessions, generate deterministic weights, "
                "and inspect immutable processing evidence."
            ),
        )
    )
    if context.principal.subject is None:
        st.error("Your administrator session has expired.")
        return
    selected_session_id = st.session_state.get("processing:session_id")
    if isinstance(selected_session_id, str) and selected_session_id:
        _render_processing_workspace(context, selected_session_id)
        return

    unprocessed, in_progress, processed = st.tabs(
        ("Unprocessed Sessions", "In Progress Sessions", "Processed Sessions")
    )
    with unprocessed:
        _render_processing_queue(context, ProcessingQueueMode.UNPROCESSED)
    with in_progress:
        _render_processing_queue(context, ProcessingQueueMode.IN_PROGRESS)
    with processed:
        _render_processing_queue(context, ProcessingQueueMode.PROCESSED)


def _render_processing_queue(
    context: PageContext,
    mode: ProcessingQueueMode,
) -> None:
    prefix = f"processing:{mode.value}"
    with admin_surface(key=f"{mode.value}_filters", variant="filter"):
        render_section_heading("Search and filter sessions", level=3)
        st.caption(
            "Narrow the processing queue by lifecycle, scenario, date, or "
            "processing state."
        )
        filters = render_session_search(
            key=f"{prefix}:search",
            scenarios=context.queries.list_session_scenarios(),
            domains=context.queries.list_scenario_domains(),
            default_statuses=_queue_status_options(mode),
            status_options=_queue_status_options(mode),
            default_date_field=SessionDateField.CLOSES,
            processing_state_options=(
                (
                    ("not_started", "Not started"),
                    ("active", "Active"),
                    ("awaiting_review", "Awaiting review"),
                    ("failed", "Failed"),
                    ("stale", "Stale"),
                    ("successful_weighting", "Successful weighting"),
                    ("successful_ranking", "Successful ranking"),
                    ("newer_work", "Newer work after success"),
                )
                if mode == ProcessingQueueMode.IN_PROGRESS
                else (("not_started", "Not started"),)
                if mode == ProcessingQueueMode.UNPROCESSED
                else ()
            ),
        )
    fingerprint = sha256(repr(filters).encode()).hexdigest()[:12]
    page_key = f"{prefix}:page"
    if st.session_state.get(f"{prefix}:fingerprint") != fingerprint:
        st.session_state[f"{prefix}:fingerprint"] = fingerprint
        st.session_state[page_key] = 1
    page = max(1, int(st.session_state.get(page_key, 1)))
    with admin_surface(key=f"{mode.value}_results", variant="results"):
        try:
            result = context.queries.list_processing_sessions(
                filters=filters,
                mode=mode,
                page=page,
                page_size=_PAGE_SIZE,
            )
        except PageQueryError as error:
            st.error(str(error), icon=":material/error:")
            return
        if not result.items:
            if mode == ProcessingQueueMode.PROCESSED:
                render_empty_state(
                    "Final packages are not available yet",
                    "No successful final package matches these filters. Sessions "
                    "with weighting or ranking work remain in progress until "
                    "a package succeeds.",
                    icon=":material/package_2:",
                )
                return
            render_empty_state(
                "No processing sessions",
                "No sessions match the current search and processing state.",
                icon=":material/manufacturing:",
            )
            return
        metrics = metric_row(
            3, key=f"processing:_render_processing_queue:0:{mode.value}"
        )
        metrics[0].metric("Matching sessions", result.total, border=True)
        metrics[1].metric(
            "Successful history on page",
            sum(item.successful_run_count > 0 for item in result.items),
            border=True,
        )
        metrics[2].metric(
            "Blocked on page",
            sum(bool(item.blockers) for item in result.items),
            border=True,
        )
        first_result = ((result.page - 1) * result.page_size) + 1
        last_result = first_result + len(result.items) - 1
        st.caption(
            f"Showing {first_result}–{last_result} of {result.total} matching "
            f"session{'s' if result.total != 1 else ''}."
        )
        for item in result.items:
            _render_processing_session_card(context, item, mode=mode, prefix=prefix)
        if result.page_count > 1:
            selected_page = pagination(
                result.page_count,
                default=result.page,
                key=f"{prefix}:pagination:{fingerprint}",
                width="stretch",
            )
            if selected_page != result.page:
                st.session_state[page_key] = selected_page
                st.rerun()


def _render_processing_session_card(
    context: PageContext,
    item: ProcessingSessionSummary,
    *,
    mode: ProcessingQueueMode,
    prefix: str,
) -> None:
    with admin_surface(
        key=f"{mode.value}_{item.session_id}",
        variant="session_card",
    ):
        heading = st.columns((0.72, 0.28), vertical_alignment="center")
        with heading[0]:
            render_section_heading(f"{item.title}", level=3)
            st.caption(
                f"{item.public_slug} · {item.scenario_title} {item.scenario_version}"
            )
        with heading[1]:
            badges = st.columns(2)
            badges[0].badge(
                item.status.value.replace("_", " ").title(),
                icon=":material/event_available:",
                color="gray" if item.status == SessionStatus.ARCHIVED else "blue",
            )
            badges[1].badge(
                item.next_stage.replace("_", " ").title(),
                icon=":material/route:",
                color="primary",
            )
        facts = st.columns(6)
        facts[0].caption("Submitted evidence")
        facts[0].markdown(f"**{item.effective_submission_count}**")
        facts[1].caption("Latest run")
        facts[1].markdown(f"**{_latest_run_label(item)}**")
        facts[2].caption("Successful runs")
        facts[2].markdown(f"**{item.successful_run_count}**")
        facts[3].caption("Roster")
        facts[3].markdown(
            "**Current**" if item.roster_is_current else "**New or changed**"
        )
        facts[4].caption("Latest ranking")
        facts[4].markdown(f"**{_latest_ranking_label(item)}**")
        facts[5].caption("Final package")
        facts[5].markdown(f"**{_latest_package_label(item)}**")
        footer = st.columns((0.72, 0.28), vertical_alignment="bottom")
        with footer[0]:
            timezone_name = getattr(
                getattr(context.container, "settings", None),
                "app_timezone",
                "UTC",
            )
            st.caption(
                "Closed: "
                + format_datetime(
                    item.closes_at,
                    timezone_name=timezone_name,
                    empty="Not recorded",
                )
            )
            st.caption(
                "Last processing activity: "
                + format_datetime(
                    item.last_processing_activity_at,
                    timezone_name=timezone_name,
                    empty="Not recorded",
                )
            )
            if item.blockers:
                st.warning(
                    "Blocked: " + "; ".join(item.blockers),
                    icon=":material/report_problem:",
                )
            else:
                st.success(
                    "No current processing blockers.",
                    icon=":material/check_circle:",
                )
        if mode == ProcessingQueueMode.UNPROCESSED:
            action_label = "Start processing workspace"
        elif mode == ProcessingQueueMode.PROCESSED:
            action_label = "Inspect final package"
        elif item.status == SessionStatus.ARCHIVED:
            action_label = "Inspect processing"
        else:
            action_label = "Resume processing"
        if footer[1].button(
            action_label,
            icon=":material/arrow_forward:",
            type="primary",
            width="stretch",
            key=f"{prefix}:open:{item.session_id}",
        ):
            st.session_state["processing:session_id"] = item.session_id
            st.session_state["processing:workspace_mode"] = mode.value
            st.session_state.pop("processing:viewed_stage", None)
            st.rerun()


def _latest_run_label(item: ProcessingSessionSummary) -> str:
    if item.latest_run_number is None:
        return "Not started"
    status = (
        "Unknown"
        if item.latest_run_status is None
        else item.latest_run_status.value.replace("_", " ").title()
    )
    return f"Run {item.latest_run_number} · {status}"


def _latest_package_label(item: ProcessingSessionSummary) -> str:
    if item.latest_package_run_number is None:
        return "Not created"
    status = (
        "Unknown"
        if item.latest_package_run_status is None
        else item.latest_package_run_status.value.replace("_", " ").title()
    )
    return f"Run {item.latest_package_run_number} · {status}"


def _latest_ranking_label(item: ProcessingSessionSummary) -> str:
    if item.latest_ranking_run_number is None:
        return "Not generated"
    status = (
        "Unknown"
        if item.latest_ranking_run_status is None
        else item.latest_ranking_run_status.value.replace("_", " ").title()
    )
    return f"Run {item.latest_ranking_run_number} · {status}"


def _queue_status_options(
    mode: ProcessingQueueMode,
) -> tuple[SessionStatus, ...]:
    if mode == ProcessingQueueMode.UNPROCESSED:
        return (SessionStatus.CLOSED,)
    return (SessionStatus.CLOSED, SessionStatus.ARCHIVED)


def _render_processing_workspace(context: PageContext, session_id: str) -> None:
    try:
        overview = context.queries.get_session_validation_overview(session_id)
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
        return
    detail = context.queries.get_admin_session_detail(session_id)
    if overview is None or detail is None:
        st.error("The selected session is no longer available.")
        return
    try:
        runs = context.container.validation.list_bundles.execute(session_id)
        ranking_runs = _list_ranking_runs(context, session_id)
        analysis_runs = _list_analysis_runs(context, session_id)
        package_runs = _list_package_runs(context, session_id)
        submission_context = context.queries.get_processing_submission_context(
            session_id
        )
    except (PageQueryError, ValueError) as error:
        st.error(str(error), icon=":material/error:")
        return
    st.subheader(detail.summary.title, anchor=False)
    st.caption(
        f"{detail.summary.public_slug} · {detail.summary.scenario_title} "
        f"{detail.summary.scenario_version}"
    )
    read_only = overview.session_status == SessionStatus.ARCHIVED or (
        st.session_state.get("processing:workspace_mode")
        == ProcessingQueueMode.PROCESSED.value
    )
    current_index = _current_stage_index(
        overview, runs, ranking_runs, analysis_runs, package_runs
    )
    selected_index = max(
        0,
        min(
            int(st.session_state.get("processing:viewed_stage", current_index)),
            current_index,
        ),
    )
    st.session_state["processing:viewed_stage"] = selected_index
    with admin_surface(key=f"workflow_{session_id}", variant="workflow_navigation"):
        render_section_heading("Session Processing Steps", level=2)
        navigation = st.columns((0.25, 0.5, 0.25))
        if navigation[0].button(
            "Exit to queues",
            icon=":material/arrow_back:",
            key="processing:back",
            width="stretch",
        ):
            _clear_workspace_state()
            st.rerun()
        navigation[1].caption(
            "Archived sessions are inspection-only. Navigation is limited to "
            "stages supported by persisted evidence."
            if read_only
            else "Navigate completed and currently available workflow stages."
        )
        steps(
            _STAGES,
            current=selected_index,
            icons=_STAGE_ICONS,
            horizontal=True,
            key=f"processing:steps:{session_id}:{current_index}",
        )
        _render_stage_badges(
            selected_index=selected_index,
            highest_viewable=current_index,
            overview=overview,
            runs=runs,
            ranking_runs=ranking_runs,
            analysis_runs=analysis_runs,
            package_runs=package_runs,
        )
        controls = st.columns((0.2, 0.6, 0.2))
        if controls[0].button(
            "Previous",
            icon=":material/arrow_back:",
            disabled=selected_index == 0,
            key=f"processing:previous:{session_id}:{selected_index}",
            width="stretch",
        ):
            st.session_state["processing:viewed_stage"] = selected_index - 1
            st.rerun()
        controls[1].write(f"**{_STAGES[selected_index]}**")
        if controls[2].button(
            "Next",
            icon=":material/arrow_forward:",
            disabled=selected_index >= current_index,
            key=f"processing:next:{session_id}:{selected_index}",
            width="stretch",
        ):
            st.session_state["processing:viewed_stage"] = selected_index + 1
            st.rerun()

    _render_processing_details(context, detail, runs)
    with admin_surface(key=f"stage_{session_id}", variant="stage_content"):
        if read_only:
            st.info(
                "Inspection mode is read-only; validation, review, and weight "
                "generation and ranking actions are unavailable."
            )
        if selected_index == 0:
            _render_session_validation_stage(detail, overview)
        elif selected_index == 1:
            _render_submission_validation_stage(
                context,
                detail,
                overview,
                submission_context,
                read_only=read_only,
            )
        elif selected_index == 2:
            _render_weight_generation_stage(
                context,
                detail,
                overview,
                runs,
                read_only=read_only,
            )
        elif selected_index == 3:
            _render_ranking_stage(
                context,
                detail,
                runs,
                submission_context,
                overview=overview,
                ranking_runs=ranking_runs,
                read_only=read_only,
            )
        elif selected_index == 4:
            _render_analysis_stage(
                context,
                detail,
                runs,
                ranking_runs,
                read_only=read_only,
            )
        else:
            render_package_stage(
                context,
                detail,
                overview,
                runs,
                ranking_runs,
                analysis_runs,
                package_runs,
                read_only=overview.session_status == SessionStatus.ARCHIVED,
            )
    _render_bundle_preview(
        detail,
        overview,
        runs,
        ranking_runs,
        package_runs,
        submission_context=submission_context,
        selected_stage=selected_index,
    )


def _current_stage_index(
    overview: SessionValidationOverview,
    runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...] = (),
    analysis_runs: tuple[Any, ...] = (),
    package_runs: tuple[Any, ...] = (),
) -> int:
    current_weighting = next(
        (run for run in runs if run.status == RunStatus.SUCCEEDED),
        None,
    )
    successful_ranking = next(
        (
            run
            for run in ranking_runs
            if run.status == RunStatus.SUCCEEDED
            and run.roster_hash == overview.current_roster_hash
            and current_weighting is not None
            and run.source_processing_run_id == current_weighting.processing_run_id
        ),
        None,
    )
    if successful_ranking is not None and any(
        run.status == RunStatus.SUCCEEDED
        and run.source_ranking_run_id == successful_ranking.ranking_run_id
        for run in analysis_runs
    ):
        return 5
    if any(
        run.status == RunStatus.SUCCEEDED
        and run.roster_hash == overview.current_roster_hash
        and current_weighting is not None
        and run.source_processing_run_id == current_weighting.processing_run_id
        for run in ranking_runs
    ):
        return 4
    latest = runs[0] if runs else None
    if any(run.status == RunStatus.SUCCEEDED for run in runs):
        return 3
    if not (
        overview.session_status in {SessionStatus.CLOSED, SessionStatus.ARCHIVED}
        and overview.has_active_configuration
        and overview.effective_submitted_count > 0
    ):
        return 0
    if latest is None or not overview.validation_complete:
        return 1
    return 2


def _render_stage_badges(
    *,
    selected_index: int,
    highest_viewable: int,
    overview: SessionValidationOverview,
    runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...] = (),
    analysis_runs: tuple[Any, ...] = (),
    package_runs: tuple[Any, ...] = (),
) -> None:
    statuses = _stage_statuses(
        selected_index=selected_index,
        highest_viewable=highest_viewable,
        overview=overview,
        runs=runs,
        ranking_runs=ranking_runs,
        analysis_runs=analysis_runs,
        package_runs=package_runs,
    )
    columns = st.columns(6)
    colors: dict[
        str,
        Literal["green", "blue", "orange", "red", "gray"],
    ] = {
        "completed": "green",
        "current": "blue",
        "blocked": "orange",
        "failed": "red",
        "unavailable": "gray",
    }
    for index, status in enumerate(statuses):
        columns[index].badge(
            status.title(),
            color=colors[status],
            icon=":material/check_circle:" if status == "completed" else None,
        )


def _stage_statuses(
    *,
    selected_index: int,
    highest_viewable: int,
    overview: SessionValidationOverview,
    runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...] = (),
    analysis_runs: tuple[Any, ...] = (),
    package_runs: tuple[Any, ...] = (),
) -> tuple[str, ...]:
    latest = runs[0] if runs else None
    latest_ranking = ranking_runs[0] if ranking_runs else None
    values: list[str] = []
    for index in range(len(_STAGES)):
        if index < highest_viewable:
            values.append("completed")
        elif index > highest_viewable:
            values.append("unavailable")
        elif (
            index == 3
            and latest_ranking is not None
            and latest_ranking.status == RunStatus.FAILED
        ) or (latest is not None and latest.status == RunStatus.FAILED and index >= 1):
            values.append("failed")
        elif index == 5 and any(
            item.status == RunStatus.SUCCEEDED for item in package_runs
        ):
            values.append("completed")
        elif index >= 4 and index != selected_index:
            values.append("blocked")
        elif index == 0 and not (
            overview.session_status in {SessionStatus.CLOSED, SessionStatus.ARCHIVED}
            and overview.has_active_configuration
            and overview.effective_submitted_count > 0
        ):
            values.append("blocked")
        elif index == selected_index:
            values.append("current")
        else:
            values.append("blocked")
    return tuple(values)


def _list_ranking_runs(context: PageContext, session_id: str) -> tuple[Any, ...]:
    ranking_use_cases = getattr(context.container, "ranking", None)
    list_runs = getattr(ranking_use_cases, "list_runs", None)
    if list_runs is None:
        return ()
    return tuple(list_runs.execute(session_id))


def _list_analysis_runs(context: PageContext, session_id: str) -> tuple[Any, ...]:
    analysis_use_cases = getattr(context.container, "analysis", None)
    list_runs = getattr(analysis_use_cases, "list_runs", None)
    if list_runs is None:
        return ()
    return tuple(list_runs.execute(session_id))


def _list_package_runs(context: PageContext, session_id: str) -> tuple[Any, ...]:
    package_use_cases = getattr(context.container, "packages", None)
    list_runs = getattr(package_use_cases, "list_runs", None)
    if list_runs is None:
        return ()
    return tuple(list_runs.execute(session_id))


def _render_processing_details(
    context: PageContext,
    detail: Any,
    runs: tuple[Any, ...],
) -> None:
    session_id = detail.summary.session_id
    with admin_surface(key=f"configuration_{session_id}", variant="configuration"):
        render_section_heading("Session Processing Details", level=2)
        with st.expander("Configuration reference", expanded=False):
            configuration = detail.configuration
            identity = {
                "session_id": session_id,
                "session_slug": detail.summary.public_slug,
                "session_status": detail.summary.status.value,
                "scenario_snapshot_id": detail.summary.scenario_snapshot_id,
                "scenario_version": detail.summary.scenario_version,
                "scenario_status": detail.summary.scenario_status.value,
            }
            if configuration is not None:
                identity.update(
                    {
                        "configuration_version_id": (
                            configuration.configuration_version_id
                        ),
                        "configuration_version": configuration.version_number,
                        "configuration_hash": configuration.config_hash,
                        "minimum_valid_submissions": (
                            configuration.minimum_valid_submissions
                        ),
                        "missing_group_policy": (
                            configuration.missing_group_policy.value
                        ),
                        "consistency_threshold": (configuration.consistency_threshold),
                        "allow_resubmissions": configuration.allow_resubmissions,
                    }
                )
            st.json(identity)
            algorithms: list[dict[str, object]] = []
            for role in (AlgorithmRole.WEIGHTING, AlgorithmRole.RANKING):
                try:
                    configured = context.queries.get_session_algorithm_configuration(
                        session_id,
                        role,
                    )
                except PageQueryError as error:
                    st.warning(str(error))
                    continue
                if configured is not None:
                    algorithms.append(
                        {
                            "role": role.value,
                            "method": configured.conceptual_method,
                            "implementation": configured.stable_key,
                            "provider": configured.provider,
                            "library": (
                                f"{configured.library_name} "
                                f"{configured.library_version}"
                            ),
                            "parameters": dict(configured.parameters),
                        }
                    )
            if algorithms:
                render_section_heading("Version-pinned algorithms", level=4)
                st.dataframe(algorithms, hide_index=True, width="stretch")
            groups = tuple(getattr(detail, "group_progress", ()))
            if groups:
                total_units = sum(group.allocation_units for group in groups)
                render_section_heading("Stakeholder groups and voting power", level=4)
                st.dataframe(
                    [
                        {
                            "Stakeholder group": group.group_name,
                            "Allocation units": group.allocation_units,
                            "Configured voting power": (
                                group.allocation_units / total_units
                                if total_units
                                else 0
                            ),
                        }
                        for group in groups
                    ],
                    hide_index=True,
                    width="stretch",
                )
            if runs:
                latest = runs[0]
                render_section_heading("Latest immutable identifiers", level=4)
                st.json(
                    {
                        "processing_run_id": latest.processing_run_id,
                        "roster_hash": latest.roster_hash,
                        "input_hash": latest.input_hash,
                        "output_hash": latest.output_hash,
                        "environment": dict(latest.environment_json),
                    }
                )
        with st.expander("Immutable processing history and audits", expanded=False):
            if runs:
                st.dataframe(
                    [
                        {
                            "Run": run.run_number,
                            "Status": run.status.value.replace("_", " ").title(),
                            "Created": run.created_at,
                            "Completed": run.completed_at,
                            "Submitted evidence": len(run.submissions),
                            "Input hash": run.input_hash,
                            "Output hash": run.output_hash or "—",
                        }
                        for run in runs
                    ],
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("No immutable processing runs exist yet.")
            audit_events = tuple(getattr(detail, "audit_events", ()))
            processing_events = tuple(
                event
                for event in audit_events
                if event.entity_type == "processing_run"
                or event.action in {"validated", "processed", "approved", "excluded"}
            )
            if processing_events:
                st.dataframe(
                    [
                        {
                            "Occurred": event.occurred_at,
                            "Action": event.action,
                            "Actor": event.actor_display,
                            "Entity": event.entity_type,
                            "Reason": event.reason or "—",
                            "Correlation": event.correlation_id,
                        }
                        for event in processing_events
                    ],
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.caption("No processing-related audit events are available.")


def _render_session_validation_stage(
    detail: Any,
    overview: SessionValidationOverview,
) -> None:
    render_section_heading("Session Validation", level=2)
    st.caption("Live readiness preflight; no approval record is created.")
    metrics = metric_row(4, key="processing:_render_session_validation_stage:0")
    metrics[0].metric(
        "Session status", overview.session_status.value.title(), border=True
    )
    metrics[1].metric(
        "Configuration",
        "Active" if overview.has_active_configuration else "Missing",
        border=True,
    )
    metrics[2].metric(
        "Scenario",
        detail.summary.scenario_status.value.replace("_", " ").title(),
        border=True,
    )
    metrics[3].metric("Current roster", overview.effective_submitted_count, border=True)
    if overview.current_roster_hash is not None:
        st.caption("Current deterministic roster hash")
        st.code(overview.current_roster_hash, language=None)
        if (
            overview.latest_batch_roster_hash is not None
            and not overview.roster_is_current
        ):
            st.warning(
                "The current roster does not match the latest validation run. "
                "Create a new explicit validation run."
            )
    blockers: list[str] = []
    if overview.session_status not in {
        SessionStatus.CLOSED,
        SessionStatus.ARCHIVED,
    }:
        blockers.append("Close the session to freeze its processing roster.")
    if not overview.has_active_configuration:
        blockers.append("Activate an immutable configuration.")
    if detail.summary.scenario_status.value != "ready":
        blockers.append("The pinned scenario snapshot must be ready.")
    if overview.effective_submitted_count == 0:
        blockers.append("At least one current submitted attempt is required.")
    if blockers:
        st.warning("Session preflight is blocked.")
        for blocker in blockers:
            st.markdown(f"- {blocker}")
    else:
        st.success(
            "The frozen session input is ready for submission validation.",
            icon=":material/check_circle:",
        )


def _render_submission_validation_stage(
    context: PageContext,
    detail: Any,
    overview: SessionValidationOverview,
    submission_context: ProcessingSubmissionContext | None,
    *,
    read_only: bool,
) -> None:
    session_id = detail.summary.session_id
    render_section_heading("Submission Validation", level=2)
    level_cards = (
        (
            "Individual evidence",
            "Participant validation records, exact diagnostics, reviews, and matrices.",
            ":material/person:",
        ),
        (
            "Stakeholder-group summaries",
            "Group-level submission and validation counts; no participant records.",
            ":material/groups:",
        ),
        (
            "Session aggregate",
            "Roster-wide validation and attempt-lifecycle totals.",
            ":material/hub:",
        ),
    )
    selected_level = card_selector(
        [
            {"title": title, "description": description, "icon": icon}
            for title, description, icon in level_cards
        ],
        selection_mode="single",
        default=0,
        key=f"processing:submission_level:{session_id}",
    )
    selected_level = selected_level if isinstance(selected_level, int) else 0
    if selected_level == 0:
        with admin_surface(
            key=f"validation_individual_{session_id}",
            variant="individual",
        ):
            render_section_heading("Individual participant evidence", level=3)
            st.caption(
                "Every record here belongs to one participant. A stakeholder-group "
                "filter changes which individuals are visible; it does not aggregate them."
            )
            _render_validation_queue(context, detail, read_only=read_only)
            try:
                matrices = context.queries.list_participant_validation_matrices(
                    session_id
                )
            except PageQueryError as error:
                st.error(str(error), icon=":material/error:")
            else:
                _render_matrix_browser(
                    matrices,
                    title="Validated individual matrices",
                    key=f"processing:participant_matrices:{session_id}",
                    group_filter=True,
                )
    elif selected_level == 1:
        _render_group_submission_summary(session_id, submission_context)
    else:
        _render_session_submission_summary(
            context,
            session_id,
            overview,
            submission_context,
            read_only=read_only,
        )


def _render_group_submission_summary(
    session_id: str,
    submission_context: ProcessingSubmissionContext | None,
) -> None:
    with admin_surface(
        key=f"submission_groups_{session_id}",
        variant="group_aggregate",
    ):
        render_section_heading("Stakeholder-group summaries", level=3)
        st.caption(
            "Counts are aggregated within each stakeholder group. Enrolled "
            "participants are the available baseline, not a configured target."
        )
        if submission_context is None or not submission_context.groups:
            st.info("No stakeholder-group submission context is available.")
            return
        frame = pd.DataFrame(
            [
                {
                    "Stakeholder group": group.stakeholder_group_name,
                    "Enrolled (available baseline)": group.enrolled_count,
                    "Current submitted": group.submitted_count,
                    "Valid": group.valid_count,
                    "Warned": group.warned_count,
                    "Invalid": group.invalid_count,
                    "Errored": group.error_count,
                    "Unvalidated": group.unvalidated_count,
                    "Configured voting power": float(group.configured_voting_power),
                }
                for group in submission_context.groups
            ]
        ).set_index("Stakeholder group")
        st.dataframe(frame, width="stretch")
        comparison = frame[
            [
                "Enrolled (available baseline)",
                "Current submitted",
                "Valid",
                "Warned",
            ]
        ]
        if int(comparison.to_numpy().sum()) == 0:
            st.info("No group comparison counts are available to chart.")
        else:
            st.bar_chart(comparison, stack=False)


def _render_session_submission_summary(
    context: PageContext,
    session_id: str,
    overview: SessionValidationOverview,
    submission_context: ProcessingSubmissionContext | None,
    *,
    read_only: bool,
) -> None:
    with admin_surface(
        key=f"submission_session_{session_id}",
        variant="session_aggregate",
    ):
        render_section_heading("Session aggregate", level=3)
        st.caption(
            "These totals summarize the current roster and all submission attempts. "
            "They do not expose individual validation identities."
        )
        total = submission_context.total if submission_context is not None else None
        metrics = metric_row(4, key="processing:_render_session_submission_summary:0")
        metrics[0].metric(
            "Enrolled (available baseline)",
            total("enrolled_count") if total else 0,
            border=True,
        )
        metrics[1].metric(
            "Current submitted", overview.effective_submitted_count, border=True
        )
        metrics[2].metric("Valid", overview.valid_count, border=True)
        metrics[3].metric(
            "Invalid / errors",
            overview.invalid_count + overview.error_count,
            border=True,
        )
        validation_frame = pd.DataFrame(
            {
                "Count": {
                    "Unvalidated": overview.unvalidated_count,
                    "Active": overview.active_count,
                    "Valid": overview.valid_count,
                    "Warned": overview.warned_count,
                    "Invalid": overview.invalid_count,
                    "Error": overview.error_count,
                }
            }
        )
        if int(validation_frame["Count"].sum()) == 0:
            st.info("No validation statuses are available to chart.")
        else:
            st.bar_chart(validation_frame)
        attempts = pd.DataFrame(
            {
                "Attempt count": {
                    "Current submitted": total("submitted_count") if total else 0,
                    "Superseded": total("superseded_attempt_count") if total else 0,
                    "Draft": total("draft_attempt_count") if total else 0,
                    "Withdrawn": total("withdrawn_attempt_count") if total else 0,
                }
            }
        )
        render_section_heading("Attempt lifecycle", level=4)
        if int(attempts["Attempt count"].sum()) == 0:
            st.info("No submission attempts are available to chart.")
        else:
            st.bar_chart(attempts, horizontal=True)
        st.caption(
            "Resubmission attempts (overlaps the lifecycle categories): "
            f"{total('resubmission_attempt_count') if total else 0}."
        )
        _render_validation_command(
            context,
            session_id,
            overview,
            read_only=read_only,
        )


def _render_validation_command(
    context: PageContext,
    session_id: str,
    overview: SessionValidationOverview,
    *,
    read_only: bool,
) -> None:
    receipt_key = f"processing:validation_receipt:{session_id}"
    receipt = st.session_state.pop(receipt_key, None)
    if isinstance(receipt, dict):
        st.success(
            f"Run {receipt['run_number']}: {receipt['valid']} valid, "
            f"{receipt['warned']} warned, {receipt['invalid']} invalid, "
            f"{receipt['error']} errors; {receipt['executed']} executed and "
            f"{receipt['reused']} reused."
        )
    if read_only:
        st.info("Validation cannot be started while inspecting an archived session.")
        return
    confirmation = st.checkbox(
        "Create a new immutable validation run for the frozen roster.",
        key=f"processing:validate_confirm:{session_id}",
    )
    if st.button(
        "Retry / validate current submissions"
        if overview.error_count
        else "Validate current submissions",
        type="primary",
        icon=":material/fact_check:",
        disabled=overview.active_count > 0 or not confirmation,
        key=f"processing:validate:{session_id}",
    ):
        actor_id = context.principal.subject
        if actor_id is None:
            st.error("Your administrator session has expired.")
            return
        try:
            with st.spinner("Validating current submissions…", show_time=True):
                result = context.container.validation.validate_current.execute(
                    ValidateCurrentSubmissionsCommand(
                        session_id=session_id,
                        actor_id=actor_id,
                    )
                )
        except ValueError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.session_state[receipt_key] = asdict(result)
            st.session_state["processing:selected_run"] = result.processing_run_id
            st.session_state["processing:viewed_stage"] = 2
            st.rerun()


def _render_validation_queue(
    context: PageContext,
    detail: Any,
    *,
    read_only: bool,
) -> None:
    render_section_heading("Current validation results", level=3)
    prefix = f"processing:validation_queue:{detail.summary.session_id}"
    page = max(1, int(st.session_state.get(f"{prefix}:page", 1)))
    try:
        result = context.queries.list_validation_queue(
            detail.summary.session_id,
            page=page,
            page_size=_PAGE_SIZE,
        )
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
        return
    if not result.items:
        st.info("No current validation results are available.")
        return
    selected_submission_id = st.selectbox(
        "Inspect validation result",
        options=tuple(item.submission_id for item in result.items),
        format_func=lambda value: next(
            f"{item.participant_label} · {item.group_name} · "
            f"{item.eligibility.replace('_', ' ')}"
            for item in result.items
            if item.submission_id == value
        ),
        key=f"{prefix}:selection:{result.page}",
    )
    if result.page_count > 1:
        selected_page = pagination(
            result.page_count,
            default=result.page,
            key=f"{prefix}:pagination",
            width="stretch",
        )
        if selected_page != result.page:
            st.session_state[f"{prefix}:page"] = selected_page
            st.rerun()
    selected = next(
        item for item in result.items if item.submission_id == selected_submission_id
    )
    st.dataframe(
        [
            {
                "Participant": item.participant_label,
                "Group": item.group_name,
                "Attempt": item.attempt_number,
                "Validation ID": item.validation_id or "—",
                "Status": (
                    "Unvalidated"
                    if item.validation_status is None
                    else item.validation_status.value.replace("_", " ").title()
                ),
                "Completion": item.completion_ratio or "—",
                "Consistency": item.consistency_ratio or "—",
                "Findings": item.validation_message_count,
                "Eligibility": item.eligibility.replace("_", " ").title(),
            }
            for item in result.items
        ],
        hide_index=True,
        width="stretch",
    )
    submission = context.queries.get_session_submission_detail(
        detail.summary.session_id,
        selected.submission_id,
    )
    if submission is not None:
        with st.expander("Findings and exact-result diagnostics"):
            st.json(
                {
                    "validation_id": submission.validation_id,
                    "completion_ratio": submission.completion_ratio,
                    "consistency_ratio": (submission.summary.consistency_ratio),
                    "consistency_threshold": (submission.consistency_threshold),
                    "validator_version": submission.validator_version,
                    "findings": list(submission.validation_messages),
                }
            )
        _render_exact_review(
            context,
            detail,
            submission,
            read_only=read_only,
        )


def _render_exact_review(
    context: PageContext,
    detail: Any,
    submission: Any,
    *,
    read_only: bool,
) -> None:
    status = submission.summary.validation_status
    if status is None or status in {
        ValidationStatus.PENDING,
        ValidationStatus.RUNNING,
    }:
        return
    if status in {ValidationStatus.INVALID, ValidationStatus.ERROR}:
        st.info("Invalid or errored evidence is excluded from weight generation.")
        return
    if submission.review_status in {
        SubmissionReviewStatus.ACCEPTED,
        SubmissionReviewStatus.REJECTED,
    }:
        st.info("A final decision is recorded for this exact validation result.")
        return
    if read_only:
        st.info("Review actions are unavailable in read-only inspection mode.")
        return
    prefix = f"processing:review:{submission.summary.submission_id}"
    if status == ValidationStatus.VALID_WITH_WARNING:
        decision = st.radio(
            "Validation decision",
            options=(
                SubmissionReviewStatus.ACCEPTED,
                SubmissionReviewStatus.REJECTED,
            ),
            format_func=lambda value: (
                "Acknowledge and include"
                if value == SubmissionReviewStatus.ACCEPTED
                else "Exclude"
            ),
            horizontal=True,
            key=f"{prefix}:decision",
        )
    else:
        st.caption("Clean valid evidence is included automatically.")
        decision = SubmissionReviewStatus.REJECTED
    notes = st.text_area("Exclusion/review notes", key=f"{prefix}:notes")
    confirmed = st.checkbox(
        "Apply this decision to the displayed validation ID.",
        key=f"{prefix}:confirm",
    )
    if st.button(
        (
            "Record warning decision"
            if status == ValidationStatus.VALID_WITH_WARNING
            else "Exclude valid submission"
        ),
        disabled=(
            not confirmed
            or (decision == SubmissionReviewStatus.REJECTED and not notes.strip())
        ),
        key=f"{prefix}:submit",
    ):
        actor_id = context.principal.subject
        if actor_id is None:
            st.error("Your administrator session has expired.")
            return
        try:
            context.container.operations.review_submission.execute(
                ReviewSubmissionCommand(
                    session_id=detail.summary.session_id,
                    submission_id=submission.summary.submission_id,
                    validation_id=submission.validation_id,
                    status=decision,
                    actor_id=actor_id,
                    reviewer_notes=notes.strip() or None,
                )
            )
        except ReviewSubmissionError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.success("Exact validation decision recorded.")
            st.session_state["processing:viewed_stage"] = 2
            st.rerun()


def _render_weight_generation_stage(
    context: PageContext,
    detail: Any,
    overview: SessionValidationOverview,
    runs: tuple[Any, ...],
    *,
    read_only: bool,
) -> None:
    render_section_heading("Weight Generation", level=2)
    if not runs:
        st.warning("Complete submission validation before generating weights.")
        return
    selected_id = st.selectbox(
        "Validation run",
        options=tuple(run.processing_run_id for run in runs),
        format_func=lambda value: next(
            f"Run {run.run_number} · {run.status.value.replace('_', ' ')}"
            for run in runs
            if run.processing_run_id == value
        ),
        key=f"processing:weight_run:{detail.summary.session_id}",
    )
    selected = next(run for run in runs if run.processing_run_id == selected_id)
    st.session_state["processing:selected_run"] = selected.processing_run_id
    configuration = detail.configuration
    st.dataframe(
        [
            {
                "Weighting implementation": selected.algorithm_implementation_id,
                "Parameters": dict(selected.parameter_json),
                "Minimum valid submissions": (
                    "—"
                    if configuration is None
                    else configuration.minimum_valid_submissions
                ),
                "Missing-group policy": (
                    "—"
                    if configuration is None
                    else configuration.missing_group_policy.value.replace(
                        "_", " "
                    ).title()
                ),
            }
        ],
        hide_index=True,
        width="stretch",
    )
    can_generate = (
        selected.status == RunStatus.AWAITING_REVIEW
        and selected.processing_run_id == overview.latest_batch_id
        and overview.roster_is_current
        and overview.validation_complete
        and overview.session_status == SessionStatus.CLOSED
    )
    blockers: list[str] = []
    if selected.processing_run_id != overview.latest_batch_id:
        blockers.append("Select the latest validation run for the current roster.")
    if not overview.roster_is_current:
        blockers.append("The roster changed; run submission validation again.")
    if overview.warning_decisions_required:
        blockers.append("Resolve every exact warned-submission decision.")
    if overview.unvalidated_count or overview.active_count:
        blockers.append("Complete every current submission validation.")
    if overview.session_status != SessionStatus.CLOSED:
        blockers.append("Only a closed session can generate weights.")
    if blockers:
        st.warning("Weight generation prerequisites are not satisfied.")
        for blocker in blockers:
            st.markdown(f"- {blocker}")
    if read_only:
        st.info("Weight generation is unavailable in read-only inspection mode.")
    elif selected.status == RunStatus.AWAITING_REVIEW and st.button(
        "Generate weights",
        icon=":material/weight:",
        type="primary",
        disabled=not can_generate,
        key=f"processing:generate_weights:{selected.processing_run_id}",
    ):
        actor_id = context.principal.subject
        if actor_id is None:
            st.error("Your administrator session has expired.")
        else:
            try:
                result = context.container.validation.finalize_bundle.execute(
                    FinalizeValidationBundleCommand(
                        processing_run_id=selected.processing_run_id,
                        actor_id=actor_id,
                    )
                )
            except ValueError as error:
                st.error(str(error), icon=":material/error:")
            else:
                st.success(
                    f"Generated weights for {result.included_submissions} "
                    "included submission(s)."
                )
                st.session_state["processing:viewed_stage"] = 3
                st.rerun()
    with st.expander("Deterministic execution details", expanded=False):
        st.json(
            {
                "processing_run_id": selected.processing_run_id,
                "status": selected.status.value,
                "created_at": selected.created_at,
                "completed_at": selected.completed_at,
                "roster_hash": selected.roster_hash,
                "input_hash": selected.input_hash,
                "output_hash": selected.output_hash,
                "algorithm_implementation_id": (selected.algorithm_implementation_id),
                "parameters": dict(selected.parameter_json),
                "environment": dict(selected.environment_json),
                "failure_code": selected.failure_code,
                "failure_detail": selected.failure_detail,
                "artifact_hashes": [
                    {
                        "type": artifact.artifact_type.value,
                        "schema_version": artifact.schema_version,
                        "content_hash": artifact.content_hash,
                    }
                    for artifact in selected.artifacts
                ],
            }
        )
        log_artifact = next(
            (
                artifact
                for artifact in selected.artifacts
                if artifact.artifact_type == ArtifactType.LOG
            ),
            None,
        )
        if log_artifact is not None:
            render_section_heading("Persisted execution log", level=4)
            st.json(dict(log_artifact.content_json))
        else:
            st.caption(
                "No persisted LOG artifact exists for this run; the immutable "
                "status, environment, hashes, and failure fields are shown above."
            )
    try:
        matrices = context.queries.list_run_matrices(selected.processing_run_id)
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
    else:
        _render_matrix_browser(
            matrices,
            title="Weight-generation matrices and diagnostics",
            key=f"processing:weight_matrices:{selected.processing_run_id}",
        )


def _render_matrix_browser(
    matrices: tuple[ProcessingMatrixView, ...],
    *,
    title: str,
    key: str,
    group_filter: bool = False,
) -> None:
    render_section_heading(f"{title}", level=3)
    if not matrices:
        st.info("No matrices are available at this stage.")
        return
    partitions = _partition_matrices_by_level(matrices)
    selected_partition = 0
    if len(partitions) > 1:
        selected = card_selector(
            [
                {
                    "icon": _matrix_level_presentation(level)[2],
                    "title": _matrix_level_presentation(level)[0],
                    "description": _matrix_level_presentation(level)[1],
                }
                for level, _items in partitions
            ],
            selection_mode="single",
            default=0,
            key=f"{key}:level",
        )
        if isinstance(selected, int) and 0 <= selected < len(partitions):
            selected_partition = selected
    level, visible = partitions[selected_partition]
    level_title, level_description, _icon, surface_variant = _matrix_level_presentation(
        level
    )
    with admin_surface(
        key=f"{key}_{level}",
        variant=surface_variant,
    ):
        render_section_heading(f"{level_title}", level=4)
        st.caption(level_description)
        _render_matrix_level(
            visible,
            level=level,
            key=f"{key}:{level}",
            group_filter=group_filter,
        )


def _partition_matrices_by_level(
    matrices: tuple[Any, ...],
) -> tuple[tuple[str, tuple[Any, ...]], ...]:
    levels = tuple(dict.fromkeys(item.level for item in matrices))
    ordered_levels = tuple(
        level for level in _MATRIX_LEVEL_ORDER if level in levels
    ) + tuple(sorted(set(levels) - set(_MATRIX_LEVEL_ORDER)))
    return tuple(
        (
            level,
            tuple(item for item in matrices if item.level == level),
        )
        for level in ordered_levels
    )


def _matrix_level_presentation(
    level: str,
) -> tuple[str, str, str, AdminSurfaceVariant]:
    known = _MATRIX_LEVEL_PRESENTATION.get(level)
    if known is not None:
        return known
    return (
        level.replace("_", " ").title() + " evidence",
        "Evidence is isolated at this persisted matrix level.",
        ":material/dataset:",
        "session_aggregate",
    )


def _render_matrix_level(
    matrices: tuple[ProcessingMatrixView, ...],
    *,
    level: str,
    key: str,
    group_filter: bool,
) -> None:
    visible = matrices
    groups = tuple(
        sorted(
            {
                item.stakeholder_group_label
                for item in matrices
                if item.stakeholder_group_label is not None
            }
        )
    )
    if level == "participant" and group_filter and groups:
        selected_group = st.selectbox(
            "Filter individuals by stakeholder group",
            options=(None, *groups),
            format_func=lambda value: "All groups" if value is None else value,
            key=f"{key}:group",
        )
        if selected_group is not None:
            visible = tuple(
                item
                for item in matrices
                if item.stakeholder_group_label == selected_group
            )
    selector_labels = {
        "participant": "Individual matrix",
        "stakeholder_group": "Stakeholder-group matrix",
        "session": "Session aggregate matrix",
    }
    selected_id = st.selectbox(
        selector_labels.get(level, "Matrix"),
        options=tuple(item.matrix_id for item in visible),
        format_func=lambda value: next(
            item.label for item in visible if item.matrix_id == value
        ),
        key=f"{key}:selection",
    )
    selected = next(item for item in visible if item.matrix_id == selected_id)
    frame = pd.DataFrame(
        selected.values,
        index=selected.criterion_labels,
        columns=selected.criterion_labels,
    )
    st.dataframe(frame, width="stretch")
    weights: dict[str, float] = {}
    invalid_weight_labels: list[str] = []
    for label, weight in zip(
        selected.criterion_labels,
        selected.weights,
        strict=True,
    ):
        if weight is None:
            continue
        try:
            weights[label] = float(weight)
        except (TypeError, ValueError):
            invalid_weight_labels.append(label)
    if weights:
        st.bar_chart(pd.Series(weights, name="Weight"), horizontal=True)
    if invalid_weight_labels:
        st.warning(
            "Some persisted weights could not be charted: "
            + ", ".join(invalid_weight_labels)
            + "."
        )
    for warning in selected.warnings:
        st.warning(warning.replace(".", " ").replace("_", " ").title())
    _render_matrix_metadata(selected)
    diagnostic_payload: dict[str, object] = {
        "level": selected.level,
        "diagnostics": dict(selected.diagnostics),
        "matrix_hash": selected.matrix_hash,
        "warnings": selected.warnings,
    }
    if level == "participant":
        diagnostic_payload.update(
            {
                "normalized_answers": [
                    dict(item) for item in selected.normalized_answers
                ],
                "validation_id": selected.validation_id,
            }
        )
    diagnostics_label = (
        "Diagnostics and normalized evidence"
        if level == "participant"
        else "Aggregate diagnostics"
    )
    with st.expander(diagnostics_label):
        st.json(diagnostic_payload)
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "Download matrix CSV",
        data=frame.to_csv(index=True),
        file_name=f"matrix-{selected.matrix_id}.csv",
        mime="text/csv",
        key=f"{key}:csv:{selected.matrix_id}",
    )
    download_columns[1].download_button(
        "Download safe matrix JSON",
        data=json.dumps(
            {
                "level": selected.level,
                "criterion_ids": selected.criterion_ids,
                "criterion_labels": selected.criterion_labels,
                "values": selected.values,
                "weights": selected.weights,
                "diagnostics": dict(selected.diagnostics),
                "matrix_hash": selected.matrix_hash,
                "warnings": selected.warnings,
            },
            indent=2,
            default=str,
        ),
        file_name=f"matrix-{selected.matrix_id}.json",
        mime="application/json",
        key=f"{key}:json:{selected.matrix_id}",
    )


def _render_matrix_metadata(selected: ProcessingMatrixView) -> None:
    details = metric_row(
        5,
        key=f"processing:_render_matrix_metadata:0:{selected.level}:{selected.matrix_hash}",
    )
    if selected.level == "participant":
        details[0].metric("Participant", selected.participant_label or "—", border=True)
        details[1].metric(
            "Stakeholder group", selected.stakeholder_group_label or "—", border=True
        )
        details[2].metric("Criteria", len(selected.criterion_ids), border=True)
        details[3].metric("Validation", selected.validation_id or "—", border=True)
    elif selected.level == "stakeholder_group":
        details[0].metric(
            "Stakeholder group", selected.stakeholder_group_label or "—", border=True
        )
        details[1].metric(
            "Contributors",
            selected.participant_count
            if selected.participant_count is not None
            else "—",
            border=True,
        )
        details[2].metric("Voting power", selected.voting_power or "—", border=True)
        details[3].metric("Criteria", len(selected.criterion_ids), border=True)
    else:
        details[0].metric("Level", "Session aggregate", border=True)
        details[1].metric(
            "Contributors",
            selected.participant_count
            if selected.participant_count is not None
            else "—",
            border=True,
        )
        details[2].metric("Criteria", len(selected.criterion_ids), border=True)
        details[3].metric("Voting power", selected.voting_power or "—", border=True)
    details[4].metric("Matrix hash", selected.matrix_hash[:12] + "…", border=True)


def _render_ranking_stage(
    context: PageContext,
    detail: Any,
    runs: tuple[Any, ...],
    submission_context: ProcessingSubmissionContext | None,
    *,
    overview: SessionValidationOverview,
    ranking_runs: tuple[Any, ...],
    read_only: bool,
) -> None:
    render_section_heading("Create Ranking", level=2)
    successful_weighting = tuple(
        run for run in runs if run.status == RunStatus.SUCCEEDED
    )
    st.caption(
        "Create deterministic alternative rankings from one immutable weighting "
        "run. The configured implementation is resolved through the ranking "
        "adapter registry."
    )
    ranking = None
    try:
        ranking = context.queries.get_session_algorithm_configuration(
            detail.summary.session_id,
            AlgorithmRole.RANKING,
        )
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
    else:
        if ranking is None:
            st.warning("No ranking implementation is configured for this session.")
        else:
            st.dataframe(
                [
                    {
                        "Method": ranking.conceptual_method,
                        "Implementation": ranking.stable_key,
                        "Provider": ranking.provider,
                        "Library": (
                            f"{ranking.library_name} {ranking.library_version}"
                        ),
                        "Parameters": dict(ranking.parameters),
                    }
                ],
                hide_index=True,
                width="stretch",
            )

    selected_source = None
    if successful_weighting:
        selected_source_id = st.selectbox(
            "Source weighting run",
            options=tuple(run.processing_run_id for run in successful_weighting),
            format_func=lambda value: next(
                f"Run {run.run_number} · {run.output_hash[:12]}…"
                for run in successful_weighting
                if run.processing_run_id == value
            ),
            key=f"processing:ranking_source:{detail.summary.session_id}",
        )
        selected_source = next(
            run
            for run in successful_weighting
            if run.processing_run_id == selected_source_id
        )
    else:
        st.warning("A successful weighting run is required before ranking.")

    blockers: list[str] = []
    if selected_source is None:
        blockers.append("Generate a successful weighting artifact.")
    elif (
        overview.current_roster_hash is None
        or selected_source.roster_hash != overview.current_roster_hash
    ):
        blockers.append(
            "The selected weighting run does not match the current frozen roster."
        )
    if ranking is None:
        blockers.append("Configure an available ranking implementation.")
    if overview.session_status != SessionStatus.CLOSED:
        blockers.append("Only a closed session can generate rankings.")
    ranking_use_cases = getattr(context.container, "ranking", None)
    create_ranking = getattr(ranking_use_cases, "create", None)
    if create_ranking is None:
        blockers.append("The ranking execution service is unavailable.")
    if blockers:
        st.warning("Ranking prerequisites are not satisfied.")
        for blocker in blockers:
            st.markdown(f"- {blocker}")
    if read_only:
        st.info("Ranking generation is unavailable in read-only inspection mode.")
    elif st.button(
        "Generate rankings",
        icon=":material/leaderboard:",
        type="primary",
        disabled=bool(blockers),
        key=f"processing:generate_ranking:{detail.summary.session_id}",
    ):
        actor_id = context.principal.subject
        if actor_id is None or selected_source is None or create_ranking is None:
            st.error("Your administrator session has expired.")
        else:
            try:
                with st.spinner("Generating deterministic rankings…"):
                    result = create_ranking.execute(
                        CreateRankingCommand(
                            session_id=detail.summary.session_id,
                            source_processing_run_id=(
                                selected_source.processing_run_id
                            ),
                            actor_id=actor_id,
                        )
                    )
            except CreateRankingError as error:
                st.error(str(error), icon=":material/error:")
            else:
                st.session_state["processing:ranking_feedback"] = {
                    "status": result.status.value,
                    "run_number": result.run_number,
                    "reused": result.reused,
                    "result_count": result.result_count,
                    "failure_detail": result.failure_detail,
                }
                st.session_state["processing:viewed_stage"] = 3
                st.rerun()

    feedback = st.session_state.pop("processing:ranking_feedback", None)
    if isinstance(feedback, Mapping):
        if feedback.get("status") == RunStatus.SUCCEEDED.value:
            reused_text = (
                " Reused the matching immutable result."
                if feedback.get("reused")
                else ""
            )
            st.success(
                f"Ranking run {feedback.get('run_number')} produced "
                f"{feedback.get('result_count')} evidence result(s).{reused_text}",
                icon=":material/check_circle:",
            )
        else:
            st.error(
                str(feedback.get("failure_detail") or "Ranking execution failed."),
                icon=":material/error:",
            )

    if submission_context is not None and submission_context.groups:
        render_section_heading("Group size and configured voting power", level=3)
        group_frame = pd.DataFrame(
            [
                {
                    "Stakeholder group": group.stakeholder_group_name,
                    "Enrolled participants": group.enrolled_count,
                    "Current submitted": group.submitted_count,
                    "Configured voting power": float(group.configured_voting_power),
                }
                for group in submission_context.groups
            ]
        ).set_index("Stakeholder group")
        st.dataframe(group_frame, width="stretch")
        st.bar_chart(group_frame[["Configured voting power"]])

    if selected_source is not None:
        try:
            matrices = context.queries.list_run_matrices(
                selected_source.processing_run_id
            )
        except PageQueryError as error:
            st.error(str(error), icon=":material/error:")
        else:
            with st.expander("Source aggregate weighting context", expanded=False):
                _render_matrix_browser(
                    tuple(
                        matrix
                        for matrix in matrices
                        if matrix.level in {"stakeholder_group", "session"}
                    ),
                    title="Aggregate weighting context",
                    key=(
                        "processing:ranking_context:"
                        f"{selected_source.processing_run_id}"
                    ),
                )

    if not ranking_runs:
        st.info("No immutable ranking history exists for this session.")
        return
    render_section_heading("Immutable ranking history", level=3)
    selected_ranking_id = st.selectbox(
        "Ranking run",
        options=tuple(run.ranking_run_id for run in ranking_runs),
        format_func=lambda value: next(
            f"Run {run.run_number} · {run.status.value.replace('_', ' ').title()}"
            for run in ranking_runs
            if run.ranking_run_id == value
        ),
        key=f"processing:ranking_history:{detail.summary.session_id}",
    )
    selected_ranking = next(
        run for run in ranking_runs if run.ranking_run_id == selected_ranking_id
    )
    with st.expander("Ranking execution and provenance", expanded=False):
        st.json(
            {
                "ranking_run_id": selected_ranking.ranking_run_id,
                "source_processing_run_id": (selected_ranking.source_processing_run_id),
                "status": selected_ranking.status.value,
                "created_at": selected_ranking.created_at,
                "completed_at": selected_ranking.completed_at,
                "roster_hash": selected_ranking.roster_hash,
                "input_hash": selected_ranking.input_hash,
                "output_hash": selected_ranking.output_hash,
                "algorithm_implementation_id": (
                    selected_ranking.algorithm_implementation_id
                ),
                "implementation_version": (selected_ranking.implementation_version),
                "adapter_version": selected_ranking.adapter_version,
                "parameters": dict(selected_ranking.parameter_json),
                "environment": dict(selected_ranking.environment_json),
                "failure_code": selected_ranking.failure_code,
                "failure_detail": selected_ranking.failure_detail,
                "artifact_hashes": [
                    {
                        "type": item.artifact_type.value,
                        "schema_version": item.schema_version,
                        "content_hash": item.content_hash,
                    }
                    for item in selected_ranking.artifacts
                ],
            }
        )
    if selected_ranking.status == RunStatus.FAILED:
        st.error(
            selected_ranking.failure_detail
            or "The ranking run failed without result evidence.",
            icon=":material/error:",
        )
        return
    try:
        ranking_results = context.queries.list_ranking_results(
            selected_ranking.ranking_run_id
        )
    except (AttributeError, PageQueryError) as error:
        st.error(str(error), icon=":material/error:")
        return
    _render_ranking_result_browser(
        ranking_results,
        key=f"processing:ranking_results:{selected_ranking.ranking_run_id}",
    )


def _render_ranking_result_browser(
    results: tuple[RankingResultView, ...],
    *,
    key: str,
) -> None:
    render_section_heading("Ranking results", level=3)
    if not results:
        st.info("This successful run contains no readable ranking results.")
        return
    partitions = _partition_matrices_by_level(results)
    selected_partition = 0
    if len(partitions) > 1:
        selected = card_selector(
            [
                {
                    "icon": _matrix_level_presentation(level)[2],
                    "title": _matrix_level_presentation(level)[0].replace(
                        "evidence", "ranking"
                    ),
                    "description": _ranking_level_description(level),
                }
                for level, _items in partitions
            ],
            selection_mode="single",
            default=0,
            key=f"{key}:level",
        )
        if isinstance(selected, int) and 0 <= selected < len(partitions):
            selected_partition = selected
    level, visible = partitions[selected_partition]
    _title, _description, _icon, surface_variant = _matrix_level_presentation(level)
    with admin_surface(key=f"{key}_{level}", variant=surface_variant):
        render_section_heading(f"{_ranking_level_title(level)}", level=4)
        st.caption(_ranking_level_description(level))
        selector_labels = {
            "participant": "Individual ranking",
            "stakeholder_group": "Stakeholder-group ranking",
            "session": "Session aggregate ranking",
        }
        selected_id = st.selectbox(
            selector_labels.get(level, "Ranking result"),
            options=tuple(item.ranking_result_id for item in visible),
            format_func=lambda value: next(
                item.label for item in visible if item.ranking_result_id == value
            ),
            key=f"{key}:{level}:selection",
        )
        selected_result = next(
            item for item in visible if item.ranking_result_id == selected_id
        )
        frame = pd.DataFrame(
            [
                {
                    "Rank": item.rank,
                    "Alternative": item.alternative_label,
                    selected_result.metric_label: item.preference_value,
                }
                for item in selected_result.alternatives
            ]
        )
        st.dataframe(frame, hide_index=True, width="stretch")
        try:
            chart_values = pd.Series(
                {
                    item.alternative_label: float(item.preference_value)
                    for item in selected_result.alternatives
                },
                name=selected_result.metric_label,
            )
        except (TypeError, ValueError):
            chart_values = pd.Series(dtype=float)
        if not chart_values.empty:
            st.bar_chart(chart_values, horizontal=True)
        details = metric_row(
            4, key=f"processing:_render_ranking_result_browser:0:{key}"
        )
        if level == "participant":
            details[0].metric(
                "Participant", selected_result.participant_label or "—", border=True
            )
            details[1].metric(
                "Stakeholder group",
                selected_result.stakeholder_group_label or "—",
                border=True,
            )
            details[2].metric(
                "Validation", selected_result.validation_id or "—", border=True
            )
        elif level == "stakeholder_group":
            details[0].metric(
                "Stakeholder group",
                selected_result.stakeholder_group_label or "—",
                border=True,
            )
            details[1].metric("Level", "Group aggregate", border=True)
            details[2].metric(
                "Alternatives", len(selected_result.alternatives), border=True
            )
        else:
            details[0].metric("Level", "Session aggregate", border=True)
            details[1].metric(
                "Alternatives", len(selected_result.alternatives), border=True
            )
            details[2].metric("Metric", selected_result.metric_label, border=True)
        details[3].metric(
            "Result hash", selected_result.result_hash[:12] + "…", border=True
        )
        safe_payload: dict[str, object] = {
            "level": level,
            "metric_label": selected_result.metric_label,
            "alternatives": [
                {
                    "alternative_id": item.alternative_id,
                    "alternative_label": item.alternative_label,
                    "rank": item.rank,
                    "preference_value": item.preference_value,
                    "method_metrics": dict(item.method_metrics),
                }
                for item in selected_result.alternatives
            ],
            "diagnostics": dict(selected_result.diagnostics),
            "result_hash": selected_result.result_hash,
        }
        if level == "participant":
            safe_payload.update(
                {
                    "participant_label": selected_result.participant_label,
                    "stakeholder_group": (selected_result.stakeholder_group_label),
                    "validation_id": selected_result.validation_id,
                }
            )
        elif level == "stakeholder_group":
            safe_payload["stakeholder_group"] = selected_result.stakeholder_group_label
        with st.expander(
            "Individual ranking diagnostics"
            if level == "participant"
            else "Aggregate ranking diagnostics",
            expanded=False,
        ):
            st.json(safe_payload)
        downloads = st.columns(2)
        downloads[0].download_button(
            "Download ranking CSV",
            data=frame.to_csv(index=False),
            file_name=f"ranking-{selected_result.ranking_result_id}.csv",
            mime="text/csv",
            key=f"{key}:{level}:csv:{selected_result.ranking_result_id}",
        )
        downloads[1].download_button(
            "Download safe ranking JSON",
            data=json.dumps(safe_payload, indent=2, default=str),
            file_name=f"ranking-{selected_result.ranking_result_id}.json",
            mime="application/json",
            key=f"{key}:{level}:json:{selected_result.ranking_result_id}",
        )


def _ranking_level_title(level: str) -> str:
    return {
        "participant": "Individual participant rankings",
        "stakeholder_group": "Stakeholder-group aggregate rankings",
        "session": "Session aggregate ranking",
    }.get(level, level.replace("_", " ").title())


def _ranking_level_description(level: str) -> str:
    return {
        "participant": (
            "One participant's ranking derived from that participant's "
            "validated weight vector. This is individual evidence."
        ),
        "stakeholder_group": (
            "Alternative rankings derived from accepted evidence aggregated "
            "within one stakeholder group. Individual identities are omitted."
        ),
        "session": (
            "The cross-group ranking derived using configured aggregation and "
            "voting-power rules. Individual identities are omitted."
        ),
    }.get(level, "Ranking evidence isolated at this persisted level.")


def _render_analysis_stage(
    context: PageContext,
    detail: Any,
    runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...] = (),
    *,
    read_only: bool,
) -> None:
    render_analysis_stage(
        context,
        detail,
        runs,
        ranking_runs,
        read_only=read_only,
    )


def _render_bundle_preview(
    detail: Any,
    overview: SessionValidationOverview,
    runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...] = (),
    package_runs: tuple[Any, ...] = (),
    *,
    selected_stage: int,
    submission_context: ProcessingSubmissionContext | None,
) -> None:
    session_id = detail.summary.session_id
    state, payload = _build_bundle_preview(
        detail,
        overview,
        runs,
        ranking_runs,
        submission_context,
        selected_stage=selected_stage,
        package_runs=package_runs,
    )
    with (
        admin_surface(key=f"bundle_{session_id}", variant="bundle_preview"),
        st.expander("Current State of Final Bundle", expanded=False),
    ):
        labels: dict[
            str,
            tuple[str, Literal["gray", "orange", "red", "green"]],
        ] = {
            "unavailable": ("Unavailable", "gray"),
            "partial": ("Partial", "orange"),
            "stale": ("Stale", "red"),
            "stage_finalized": (
                "Deterministic stages finalized; package partial",
                "green",
            ),
            "finalized": ("Finalized", "green"),
        }
        label, color = labels[state]
        st.badge(label, color=color)
        st.caption(
            "This preview is derived from persisted evidence and is deliberately "
            "redacted. It is separate from execution logs and detailed matrices."
        )
        if not payload:
            st.info(
                "No persisted or directly derived preview is available for this stage."
            )
        else:
            st.json(payload)
        if state == "stage_finalized":
            if any(run.status == RunStatus.SUCCEEDED for run in ranking_runs):
                st.warning(
                    "Weighting and ranking are finalized. Sensitivity evidence "
                    "and an AI-safe final package are still missing."
                )
            else:
                st.warning(
                    "Only the deterministic weighting stage is finalized. Ranking, "
                    "sensitivity, and an AI-safe final package are still missing."
                )


def _build_bundle_preview(
    detail: Any,
    overview: SessionValidationOverview,
    runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...],
    submission_context: ProcessingSubmissionContext | None,
    *,
    selected_stage: int,
    package_runs: tuple[Any, ...] = (),
) -> tuple[str, dict[str, object]]:
    latest = runs[0] if runs else None
    successful = next(
        (run for run in runs if run.status == RunStatus.SUCCEEDED),
        None,
    )
    successful_ranking = next(
        (
            run
            for run in ranking_runs
            if run.status == RunStatus.SUCCEEDED
            and run.roster_hash == overview.current_roster_hash
            and successful is not None
            and run.source_processing_run_id == successful.processing_run_id
        ),
        None,
    )
    run = successful or latest
    artifact = (
        next(
            (
                item
                for item in successful.artifacts
                if item.artifact_type == ArtifactType.ANALYSIS_BUNDLE
            ),
            None,
        )
        if successful is not None
        else None
    )
    stale = latest is not None and (
        latest.status == RunStatus.STALE
        or (
            overview.current_roster_hash is not None
            and latest.roster_hash != overview.current_roster_hash
        )
    )
    if ranking_runs and ranking_runs[0].status == RunStatus.SUCCEEDED:
        stale = stale or (
            ranking_runs[0].roster_hash != overview.current_roster_hash
            or successful is None
            or ranking_runs[0].source_processing_run_id != successful.processing_run_id
        )
    successful_package = next(
        (item for item in package_runs if item.status == RunStatus.SUCCEEDED), None
    )
    if successful_package is not None:
        package_configuration = next(
            (
                item.content_json.get("configuration_version_id")
                for item in getattr(successful_package, "artifacts", ())
                if getattr(item, "name", None) == "02_configuration"
            ),
            None,
        )
        current_configuration = (
            None
            if detail.configuration is None
            else detail.configuration.configuration_version_id
        )
        stale = (
            stale
            or successful_package.source_roster_hash != overview.current_roster_hash
            or package_configuration != current_configuration
        )
    if stale:
        state = "stale"
    elif successful_package is not None:
        state = "finalized"
    elif artifact is not None:
        state = "stage_finalized"
    elif run is not None or overview.effective_submitted_count:
        state = "partial"
    else:
        state = "unavailable"
    payload: dict[str, object] = {
        "preview_schema_version": 1,
        "stage": _STAGES[selected_stage],
        "overall_package_complete": False,
        "session_input": {
            "session_status": overview.session_status.value,
            "scenario_snapshot_id": detail.summary.scenario_snapshot_id,
            "scenario_version": detail.summary.scenario_version,
            "configuration_version_id": (
                None
                if detail.configuration is None
                else detail.configuration.configuration_version_id
            ),
            "configuration_hash": (
                None
                if detail.configuration is None
                else detail.configuration.config_hash
            ),
            "current_roster_hash": overview.current_roster_hash,
        },
    }
    if successful_package is not None:
        payload["overall_package_complete"] = True
        payload["final_package"] = {
            "package_run_id": successful_package.package_run_id,
            "run_number": successful_package.run_number,
            "variants": [item.value for item in successful_package.variants],
            "input_hash": successful_package.input_hash,
            "output_hash": successful_package.output_hash,
            "analysis_run_count": len(successful_package.source_analysis_run_ids),
        }
    if selected_stage >= 1:
        payload["aggregate_validation"] = {
            "current_submitted": overview.effective_submitted_count,
            "valid": overview.valid_count,
            "warned": overview.warned_count,
            "invalid": overview.invalid_count,
            "error": overview.error_count,
            "unvalidated": overview.unvalidated_count,
            "groups": [
                {
                    "group": group.stakeholder_group_name,
                    "enrolled_available_baseline": group.enrolled_count,
                    "current_submitted": group.submitted_count,
                    "valid": group.valid_count,
                    "warned": group.warned_count,
                    "invalid": group.invalid_count,
                    "error": group.error_count,
                }
                for group in (
                    submission_context.groups if submission_context is not None else ()
                )
            ],
        }
    if run is not None and selected_stage >= 1:
        payload["run_state"] = {
            "run_number": run.run_number,
            "status": run.status.value,
            "roster_hash": run.roster_hash,
            "input_hash": run.input_hash,
            "output_hash": run.output_hash,
            "included_count": sum(
                item.inclusion_status.value == "included" for item in run.submissions
            ),
            "excluded_count": sum(
                item.inclusion_status.value != "included" for item in run.submissions
            ),
        }
    if artifact is not None and selected_stage >= 2:
        payload["weighting_artifact"] = _redacted_weighting_artifact(artifact)
        payload["completeness"] = {
            "validation": True,
            "weighting": True,
            "ranking": False,
            "sensitivity_and_robustness": False,
            "final_package": False,
        }
    elif selected_stage >= 2:
        payload["weighting_artifact"] = None
    if selected_stage >= 3:
        payload["ranking_artifact"] = (
            None
            if successful_ranking is None
            else _redacted_ranking_run(successful_ranking)
        )
        completeness = payload.setdefault("completeness", {})
        if isinstance(completeness, dict):
            completeness["ranking"] = successful_ranking is not None
            completeness["sensitivity_and_robustness"] = bool(
                successful_package and successful_package.source_analysis_run_ids
            )
            completeness["final_package"] = successful_package is not None
    return state, payload


def _redacted_ranking_run(run: Any) -> dict[str, object]:
    return {
        "ranking_run_id": run.ranking_run_id,
        "source_processing_run_id": run.source_processing_run_id,
        "status": run.status.value,
        "algorithm": {
            "implementation_id": run.algorithm_implementation_id,
            "implementation_version": run.implementation_version,
            "adapter_version": run.adapter_version,
            "parameters": dict(run.parameter_json),
        },
        "input_hash": run.input_hash,
        "output_hash": run.output_hash,
        "aggregate_results": [
            {
                "level": result.level,
                "stakeholder_group_id": result.stakeholder_group_id,
                "metric_label": result.metric_label,
                "result_hash": result.result_hash,
                "alternatives": [item.to_manifest() for item in result.alternatives],
            }
            for result in run.results
            if result.level in {"stakeholder_group", "session"}
        ],
        "redactions": [
            "participant ranking results",
            "participant identifiers",
            "validation identifiers",
        ],
        "overall_package_complete": False,
    }


def _redacted_weighting_artifact(artifact: Any) -> dict[str, object]:
    source = dict(artifact.content_json)
    matrices = source.get("matrices", ())
    aggregate_matrices = (
        [
            _drop_identity_fields(matrix)
            for matrix in matrices
            if isinstance(matrix, Mapping) and matrix.get("level") != "participant"
        ]
        if isinstance(matrices, (list, tuple))
        else []
    )
    groups = source.get("stakeholder_groups", ())
    safe_groups = (
        [_drop_identity_fields(group) for group in groups if isinstance(group, Mapping)]
        if isinstance(groups, (list, tuple))
        else []
    )
    return {
        "source_artifact_type": artifact.artifact_type.value,
        "source_schema_version": artifact.schema_version,
        "source_artifact_hash": artifact.content_hash,
        "algorithm": _drop_identity_fields(source.get("algorithm", {})),
        "ordered_criteria": source.get("ordered_criteria", []),
        "stakeholder_groups": safe_groups,
        "aggregate_matrices": aggregate_matrices,
        "warnings": _drop_identity_fields(source.get("warnings", [])),
        "redactions": [
            "participant identifiers",
            "submission identifiers",
            "validation identifiers",
            "participant matrices",
            "normalized individual answers",
        ],
    }


def _drop_identity_fields(value: object) -> object:
    blocked = {
        "participant_id",
        "participant_label",
        "submission_id",
        "validation_id",
        "normalized_answers",
        "submissions",
    }
    if isinstance(value, Mapping):
        return {
            str(key): _drop_identity_fields(item)
            for key, item in value.items()
            if str(key) not in blocked
        }
    if isinstance(value, (list, tuple)):
        return [_drop_identity_fields(item) for item in value]
    return value


def _clear_workspace_state() -> None:
    for key in (
        "processing:session_id",
        "processing:selected_run",
        "processing:viewed_stage",
        "processing:workspace_mode",
    ):
        st.session_state.pop(key, None)
