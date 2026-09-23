"""Sensitivity and robustness controls and persisted result presentation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st
from streamlit_extras.card_selector import (  # type: ignore[import-untyped]
    card_selector,
)
from streamlit_extras.pagination import pagination  # type: ignore[import-untyped]

from poli_insight.application.queries.page_queries import PageQueryError
from poli_insight.application.use_cases.run_selected_analyses import (
    AnalysisProgress,
    AnalysisTestSpec,
    RunSelectedAnalysesCommand,
    RunSelectedAnalysesError,
)
from poli_insight.domain.enum import (
    AnalysisCaseStatus,
    AnalysisMethod,
    ArtifactType,
    RunStatus,
)
from poli_insight.presentation.streamlit.components.layout import (
    AdminSurfaceVariant,
    admin_surface,
    format_datetime,
    metric_row,
    render_section_heading,
    surface,
)
from poli_insight.presentation.streamlit.context import PageContext


def render_analysis_stage(
    context: PageContext,
    detail: Any,
    weighting_runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...],
    *,
    read_only: bool,
) -> None:
    render_section_heading("Sensitivity and Robustness", level=2)
    st.caption(
        "Run selected counterfactual tests against one immutable ranking. "
        "Each test is stored as a separate, reproducible analysis run. "
        "This iteration supports the registered crisp AHP and TOPSIS path."
    )
    successful = tuple(run for run in ranking_runs if run.status == RunStatus.SUCCEEDED)
    services = getattr(context.container, "analysis", None)
    executor = getattr(services, "run_selected", None)
    history_service = getattr(services, "list_runs", None)
    if not successful:
        st.warning("A successful persisted ranking is required before analysis.")
        return
    latest_id = successful[0].ranking_run_id
    timezone_name = getattr(
        getattr(context.container, "settings", None), "app_timezone", "UTC"
    )
    with surface(key="analysis:configuration", variant="filter"):
        selected_id = st.selectbox(
            "Source ranking run",
            options=tuple(run.ranking_run_id for run in successful),
            format_func=lambda value: _source_label(
                next(run for run in successful if run.ranking_run_id == value),
                latest_id,
                timezone_name,
            ),
            key=f"processing:analysis_source:{detail.summary.session_id}",
        )
        ranking = next(run for run in successful if run.ranking_run_id == selected_id)
        source = next(
            (
                run
                for run in weighting_runs
                if run.processing_run_id == ranking.source_processing_run_id
            ),
            None,
        )
        if source is None:
            st.error("The source weighting evidence for this ranking is unavailable.")
            return

        render_section_heading("Select tests", level=3)
        columns = st.columns(2)
        methods = []
        for position, method in enumerate(AnalysisMethod):
            if columns[position % 2].checkbox(
                method_label(method),
                value=False,
                key=f"processing:analysis_test:{detail.summary.session_id}:{method.value}",
            ):
                methods.append(method)
        perturbation = _perturbation_configuration(
            detail.summary.session_id,
            AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION in methods,
        )
        aggregate_matrices = tuple(
            matrix
            for matrix in source.matrices
            if matrix.level in {"stakeholder_group", "session"}
        )
        session_matrix = next(
            (matrix for matrix in source.matrices if matrix.level == "session"), None
        )
        criteria = len(session_matrix.criterion_ids) if session_matrix else 0
        session_result = next(
            (result for result in ranking.results if result.level == "session"), None
        )
        alternatives = len(session_result.alternatives) if session_result else 0
        groups = sum(
            matrix.level == "stakeholder_group" for matrix in aggregate_matrices
        )
        participants = sum(
            item.inclusion_status.value == "included" for item in source.submissions
        )
        estimates = workload_estimates(
            methods,
            scopes=len(aggregate_matrices),
            criteria=criteria,
            alternatives=alternatives,
            groups=groups,
            participants=participants,
            perturbation_parameters=perturbation,
        )
        case_count = sum(item[1] for item in estimates)
        evaluation_count = sum(item[2] for item in estimates)
        with st.expander("Eligibility and estimated workload", expanded=bool(methods)):
            metrics = st.columns(5)
            for target, label, value in zip(
                metrics,
                (
                    "Criteria",
                    "Alternatives",
                    "Groups",
                    "Participants",
                    "Ranking evaluations",
                ),
                (criteria, alternatives, groups, participants, evaluation_count),
                strict=True,
            ):
                target.metric(label, value, border=True)
            if estimates:
                st.dataframe(
                    [
                        {
                            "Test": method_label(method),
                            "Cases": cases,
                            "Ranking evaluations": evaluations,
                        }
                        for method, cases, evaluations in estimates
                    ],
                    hide_index=True,
                    width="stretch",
                )
            st.caption(
                f"Estimated {case_count} counterfactual cases. Some cases may be "
                "recorded as not evaluable under the frozen group policy."
            )
            if AnalysisMethod.CRITERION_REMOVAL in methods and criteria < 2:
                st.warning(
                    "Criterion removal is not evaluable because the frozen scenario "
                    "contains only one criterion."
                )
            if AnalysisMethod.RANK_REVERSAL in methods and alternatives < 3:
                st.warning(
                    "Rank reversal is not evaluable with fewer than three baseline "
                    "alternatives."
                )
        confirmed = True
        if evaluation_count > 500:
            st.warning("This selection is expected to exceed 500 ranking evaluations.")
            confirmed = st.checkbox(
                "I understand this synchronous analysis may take a while.",
                key=f"processing:analysis_large_confirm:{detail.summary.session_id}",
            )
        blockers = []
        if executor is None:
            blockers.append("The analysis execution service is unavailable.")
        if not methods:
            blockers.append("Select at least one test.")
        if session_result is None or session_matrix is None:
            blockers.append("The ranking lacks a session aggregate baseline.")
        if evaluation_count > 500 and not confirmed:
            blockers.append("Confirm the estimated large workload.")
        if read_only:
            blockers.append("Analysis execution is unavailable in read-only mode.")
        if st.button(
            "Run selected tests",
            icon=":material/query_stats:",
            type="primary",
            disabled=bool(blockers),
            key=f"processing:run_analyses:{detail.summary.session_id}",
        ):
            _execute(
                context,
                detail.summary.session_id,
                selected_id,
                methods,
                perturbation,
            )
        for blocker in blockers:
            st.caption(f"• {blocker}")
    feedback = st.session_state.pop("processing:analysis_feedback", None)
    if isinstance(feedback, Mapping):
        failures = int(feedback.get("failures", 0))
        if failures:
            st.error(
                f"Completed {feedback.get('completed', 0)} test(s); "
                f"{failures} failed. Inspect the result tabs."
            )
        else:
            st.success(
                f"Completed {feedback.get('completed', 0)} selected test(s).",
                icon=":material/check_circle:",
            )
    history = ()
    if history_service is not None:
        try:
            history = history_service.execute(detail.summary.session_id)
        except ValueError as error:
            st.error(str(error), icon=":material/error:")
    with surface(key="analysis:results"):
        _results(context, tuple(history), selected_id, detail.summary.session_id)


def _perturbation_configuration(session_id: str, selected: bool) -> dict[str, Decimal]:
    presets = {
        "Quick": (Decimal("0.05"), Decimal("0.05"), Decimal("0.01")),
        "Standard": (Decimal("0.20"), Decimal("0.20"), Decimal("0.01")),
        "Full": (Decimal("1.00"), Decimal("1.00"), Decimal("0.01")),
    }
    if not selected:
        return {
            "lower_delta": Decimal("0.20"),
            "upper_delta": Decimal("0.20"),
            "step": Decimal("0.01"),
        }
    with st.expander("Weight perturbation configuration", expanded=True):
        preset = st.selectbox(
            "Range preset",
            options=("Quick", "Standard", "Full", "Advanced"),
            index=1,
            key=f"processing:perturbation_preset:{session_id}",
        )
        if preset != "Advanced":
            lower, upper, step = presets[preset]
            st.caption(
                f"Baseline −{lower} to +{upper} weight points in {step} "
                "increments, clipped to 0–1."
            )
        else:
            controls = st.columns(3)
            lower = Decimal(
                str(
                    controls[0].number_input(
                        "Lower delta",
                        0.0,
                        1.0,
                        0.20,
                        0.01,
                        key=f"processing:perturb_lower:{session_id}",
                    )
                )
            )
            upper = Decimal(
                str(
                    controls[1].number_input(
                        "Upper delta",
                        0.0,
                        1.0,
                        0.20,
                        0.01,
                        key=f"processing:perturb_upper:{session_id}",
                    )
                )
            )
            step = Decimal(
                str(
                    controls[2].number_input(
                        "Step",
                        0.001,
                        0.10,
                        0.01,
                        0.001,
                        format="%.3f",
                        key=f"processing:perturb_step:{session_id}",
                    )
                )
            )
        st.info(
            "One criterion changes at a time. Remaining weight is redistributed "
            "proportionally before the configured ranking method is rerun."
        )
    return {"lower_delta": lower, "upper_delta": upper, "step": step}


def workload_estimates(
    methods,
    *,
    scopes,
    criteria,
    alternatives,
    groups,
    participants,
    perturbation_parameters,
):
    result = []
    for method in methods:
        if method == AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION:
            points = (
                int(
                    (
                        perturbation_parameters["lower_delta"]
                        + perturbation_parameters["upper_delta"]
                    )
                    / perturbation_parameters["step"]
                )
                + 3
            )
            cases = scopes * criteria * points
            evaluations = cases
        elif method == AnalysisMethod.CRITERION_REMOVAL:
            cases = evaluations = scopes * criteria
        elif method == AnalysisMethod.RANK_REVERSAL:
            cases = evaluations = scopes * alternatives
        elif method == AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE:
            cases = evaluations = groups
        else:
            cases = participants
            evaluations = participants * 2
        result.append((method, cases, evaluations))
    return tuple(result)


def _execute(context, session_id, ranking_id, methods, perturbation):
    actor_id = context.principal.subject
    executor = getattr(
        getattr(context.container, "analysis", None), "run_selected", None
    )
    if actor_id is None or executor is None:
        st.error("Your administrator session has expired.")
        return
    overall = st.progress(0.0, text="Preparing selected analyses")
    current = st.progress(0.0, text="Waiting for the first test")
    with st.status(
        "Running sensitivity and robustness tests…", expanded=True
    ) as status:
        last_phase = {}

        def update(progress: AnalysisProgress) -> None:
            fraction = progress.completed_cases / max(progress.total_cases, 1)
            phase_fraction = {
                "validating": Decimal("0.02"),
                "preparing_baseline": Decimal("0.05"),
                "evaluating_cases": Decimal("0.05")
                + Decimal("0.90") * Decimal(str(fraction)),
                "summarizing": Decimal("0.96"),
                "persisting": Decimal("0.98")
                + Decimal("0.02") * Decimal(str(fraction)),
            }[progress.phase]
            current_fraction = float(phase_fraction)
            overall.progress(
                ((progress.test_index - 1) + current_fraction)
                / max(progress.total_tests, 1),
                text=(
                    f"Test {progress.test_index} of {progress.total_tests}: "
                    f"{method_label(progress.method)}"
                ),
            )
            current.progress(current_fraction, text=progress.message)
            if last_phase.get(progress.method) != progress.phase:
                status.write(progress.message)
                last_phase[progress.method] = progress.phase

        specs = tuple(
            AnalysisTestSpec(
                method,
                perturbation
                if method == AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION
                else {},
            )
            for method in methods
        )
        try:
            result = executor.execute(
                RunSelectedAnalysesCommand(
                    session_id=session_id,
                    source_ranking_run_id=ranking_id,
                    tests=specs,
                    actor_id=actor_id,
                ),
                on_progress=update,
            )
        except RunSelectedAnalysesError as error:
            status.update(label="Analysis could not start", state="error")
            st.error(str(error), icon=":material/error:")
            return
        failures = sum(item.status == RunStatus.FAILED for item in result.outcomes)
        status.update(
            label="Selected analyses complete",
            state="error" if failures else "complete",
        )
        st.session_state["processing:analysis_feedback"] = {
            "completed": len(result.outcomes),
            "failures": failures,
        }
    st.rerun()


def _results(context, runs, selected_ranking_id: str, session_id: str) -> None:
    render_section_heading("Analysis results", level=3)
    tabs = st.tabs(tuple(method_label(method) for method in AnalysisMethod))
    for tab, method in zip(tabs, AnalysisMethod, strict=True):
        with tab:
            st.info(method_explanation(method))
            matching = tuple(
                run
                for run in runs
                if run.method == method
                and run.source_ranking_run_id == selected_ranking_id
            )
            if not matching:
                st.caption("This test has not been run for the selected ranking.")
                continue

            history_labels = {
                item.analysis_run_id: (
                    f"Run {item.run_number} · "
                    f"{item.status.value.replace('_', ' ').title()}"
                )
                for item in matching
            }

            selected = st.selectbox(
                "Analysis run",
                options=tuple(run.analysis_run_id for run in matching),
                format_func=history_labels.__getitem__,
                key=f"processing:analysis_history:{session_id}:{method.value}",
            )
            run = next(item for item in matching if item.analysis_run_id == selected)
            if run.status == RunStatus.FAILED:
                st.error(run.failure_detail or "This analysis run failed.")
                with st.expander("Failure provenance"):
                    st.json(_provenance(run))
                continue
            summary = _summary(run)
            render_section_heading("Whole analysis run", level=4)
            st.caption(
                "These totals cover every result level evaluated by this immutable run."
            )
            metrics = metric_row(4, key=f"analysis_section:_results:0:{method.value}")
            metrics[0].metric(
                "Evaluated", summary.get("evaluated_count", 0), border=True
            )
            metrics[1].metric(
                "Not evaluable", summary.get("not_evaluable_count", 0), border=True
            )
            metrics[2].metric(
                "Top-set changes", summary.get("top_set_change_count", 0), border=True
            )
            metrics[3].metric(
                "Strict reversals", summary.get("strict_reversal_count", 0), border=True
            )
            if summary.get("instability_detected"):
                st.warning(
                    "The test completed successfully and found ranking instability."
                )
            elif not summary.get("evaluated_count"):
                st.info(
                    "The test completed, but none of its cases were evaluable "
                    "under the frozen inputs and policies."
                )
            else:
                st.success("No instability was observed within the sampled cases.")
            with st.expander(
                "Assumptions, execution provenance, and hashes", expanded=False
            ):
                st.json(_provenance(run))
            render_section_heading("Results by level", level=4)
            _result_levels(context, run, method, summary)
            safe = next(
                (
                    artifact.content_json
                    for artifact in run.artifacts
                    if artifact.artifact_type == ArtifactType.ANALYSIS_BUNDLE
                ),
                None,
            )
            if safe is not None and method != AnalysisMethod.PARTICIPANT_INFLUENCE:
                st.download_button(
                    "Download redacted analysis summary",
                    data=json.dumps(safe, indent=2, default=str),
                    file_name=f"analysis-{run.analysis_run_id}.json",
                    mime="application/json",
                    key=f"processing:analysis_download:{run.analysis_run_id}",
                )


def _result_levels(context, run, method, run_summary) -> None:
    levels = _available_result_levels(method)
    selected_position = 0
    if len(levels) > 1:
        selected = card_selector(
            [
                {
                    "title": _level_presentation(method, level)[0],
                    "description": _level_presentation(method, level)[1],
                    "icon": _level_presentation(method, level)[2],
                }
                for level in levels
            ],
            selection_mode="single",
            default=0,
            key=f"processing:analysis_result_level:{run.analysis_run_id}",
        )
        if isinstance(selected, int) and 0 <= selected < len(levels):
            selected_position = selected
    level = levels[selected_position]
    title, description, _icon, variant = _level_presentation(method, level)
    group_id = None
    group_label = None
    if level in {"stakeholder_group", "participant"}:
        groups = _scope_groups(context, run, method)
        if not groups:
            st.info("No stakeholder-group result scopes are available for this run.")
            return
        labels = {item.scope_id: item.label for item in groups}
        selector_label = (
            "Filter individuals by stakeholder group"
            if level == "participant"
            else "Stakeholder group"
        )
        group_id = st.selectbox(
            selector_label,
            options=tuple(labels),
            format_func=labels.__getitem__,
            key=(f"processing:analysis_group:{run.analysis_run_id}:{level}"),
        )
        group_label = labels[group_id]
    surface_key = f"analysis_{run.analysis_run_id}_{level}_{group_id or 'aggregate'}"
    with admin_surface(key=surface_key, variant=variant):
        render_section_heading(f"{title}", level=4)
        st.caption(description)
        if group_label is not None:
            st.caption(f"Selected stakeholder group: {group_label}")
        level_summary = _render_level_summary(
            context,
            run,
            level=level,
            group_id=group_id,
        )
        if level_summary is None:
            return
        _render_stability_bounds(
            method,
            run_summary,
            level=level,
            group_id=group_id,
        )
        if method == AnalysisMethod.PARTICIPANT_INFLUENCE:
            if level == "participant":
                _participant_case_page(context, run, group_id)
            return
        _case_page(context, run, method, level, group_id)


def _available_result_levels(method: AnalysisMethod) -> tuple[str, ...]:
    if method == AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE:
        return ("session",)
    if method == AnalysisMethod.PARTICIPANT_INFLUENCE:
        return ("session", "stakeholder_group", "participant")
    return ("session", "stakeholder_group")


def _level_presentation(
    method: AnalysisMethod, level: str
) -> tuple[str, str, str, AdminSurfaceVariant]:
    if method == AnalysisMethod.PARTICIPANT_INFLUENCE:
        participant_values: dict[str, tuple[str, str, str, AdminSurfaceVariant]] = {
            "session": (
                "Session impact",
                "Aggregate effects of participant removals on the session ranking; participant identities are omitted.",
                ":material/hub:",
                "session_aggregate",
            ),
            "stakeholder_group": (
                "Stakeholder-group impact",
                "Aggregate effects on the selected stakeholder group's ranking; participant identities are omitted.",
                ":material/groups:",
                "group_aggregate",
            ),
            "participant": (
                "Individual cases",
                "Moderator-only participant influence evidence with session and affected-group effects separated.",
                ":material/person:",
                "individual",
            ),
        }
        return participant_values[level]
    aggregate_values: dict[str, tuple[str, str, str, AdminSurfaceVariant]] = {
        "session": (
            "Session aggregate",
            "Counterfactual effects measured against the session aggregate ranking.",
            ":material/hub:",
            "session_aggregate",
        ),
        "stakeholder_group": (
            "Stakeholder-group results",
            "Counterfactual effects measured within one selected stakeholder group.",
            ":material/groups:",
            "group_aggregate",
        ),
    }
    return aggregate_values[level]


def _scope_groups(context, run, method):
    try:
        scopes = context.queries.list_analysis_scopes(run.analysis_run_id)
    except (PageQueryError, AttributeError) as error:
        st.error(str(error), icon=":material/error:")
        return ()
    scope_type = (
        "participant"
        if method == AnalysisMethod.PARTICIPANT_INFLUENCE
        else "stakeholder_group"
    )
    unique = {}
    for item in scopes:
        if item.scope_type == scope_type and item.scope_id is not None:
            unique[item.scope_id] = item
    return tuple(
        unique[key] for key in sorted(unique, key=lambda value: unique[value].label)
    )


def _render_level_summary(context, run, *, level, group_id):
    try:
        summary = context.queries.summarize_analysis_level(
            run.analysis_run_id,
            result_level=level,
            stakeholder_group_id=group_id,
        )
    except (PageQueryError, AttributeError) as error:
        st.error(str(error), icon=":material/error:")
        return None
    first = metric_row(
        3,
        key=f"analysis_section:_render_level_summary:0:{run.analysis_run_id}:{level}:{group_id}",
    )
    first[0].metric("Evaluated", summary.evaluated_count, border=True)
    first[1].metric("Not evaluable", summary.not_evaluable_count, border=True)
    first[2].metric("Warnings", summary.warning_count, border=True)
    second = metric_row(
        3,
        key=f"analysis_section:_render_level_summary:1:{run.analysis_run_id}:{level}:{group_id}",
    )
    second[0].metric("Top-set changes", summary.top_set_change_count, border=True)
    second[1].metric("Strict reversals", summary.strict_reversal_count, border=True)
    second[2].metric(
        "Maximum displacement", summary.maximum_rank_displacement, border=True
    )
    if summary.evaluated_count == 0:
        st.info("No cases were evaluable at this result level.")
    elif summary.top_set_change_count or summary.strict_reversal_count:
        st.warning("Instability was observed at this result level.")
    else:
        st.success("No instability was observed at this result level.")
    if summary.displacement_distribution:
        frame = pd.DataFrame(
            [
                {"Maximum rank displacement": displacement, "Cases": count}
                for displacement, count in summary.displacement_distribution.items()
            ]
        ).set_index("Maximum rank displacement")
        st.bar_chart(frame)
    return summary


def _render_stability_bounds(method, run_summary, *, level, group_id) -> None:
    if method != AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION:
        return
    rows = _stability_rows(run_summary, level=level, group_id=group_id)
    if not rows:
        return
    render_section_heading("Sampled stability bounds", level=4)
    st.caption(
        "These are observed grid bounds for this result level, not exact "
        "mathematical breakpoints."
    )
    st.dataframe(rows, hide_index=True, width="stretch")


def _stability_rows(run_summary, *, level, group_id):
    return [
        dict(item)
        for item in run_summary.get("sampled_stability", ())
        if isinstance(item, Mapping)
        and item.get("scope_type") == level
        and (level != "stakeholder_group" or item.get("scope_id") == group_id)
    ]


def _case_page(context, run, method, level, group_id):
    namespace = f"{level}:{group_id or 'aggregate'}"
    page_key = f"processing:analysis_page:{run.analysis_run_id}:{namespace}"
    page = max(1, int(st.session_state.get(page_key, 1)))
    try:
        result = context.queries.list_analysis_cases(
            run.analysis_run_id,
            scope_type=level,
            scope_id=group_id,
            page=page,
            page_size=25,
        )
    except (PageQueryError, AttributeError) as error:
        st.error(str(error), icon=":material/error:")
        return
    rows = []
    chart = []
    for item in result.items:
        metrics = item.results.get("metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        rows.append(
            {
                "Subject": item.subject_label,
                "Status": item.status.value.replace("_", " ").title(),
                "Top set changed": metrics.get("top_set_changed"),
                "Kendall tau-b": metrics.get("kendall_tau_b"),
                "Maximum displacement": metrics.get("maximum_rank_displacement"),
                "Strict reversals": metrics.get("strict_reversals"),
                "Reason": item.results.get("reason"),
            }
        )
        if item.status == AnalysisCaseStatus.EVALUATED:
            chart.append(
                {
                    "Subject": item.subject_label,
                    "Maximum rank displacement": float(
                        metrics.get("maximum_rank_displacement", 0)
                    ),
                }
            )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    if chart and method != AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION:
        st.bar_chart(pd.DataFrame(chart).set_index("Subject"), horizontal=True)
    _render_case_pagination(result, page_key, run.analysis_run_id, namespace)
    _render_case_evidence(result.items)


def _participant_case_page(context, run, group_id):
    namespace = f"participant:{group_id}"
    page_key = f"processing:analysis_page:{run.analysis_run_id}:{namespace}"
    page = max(1, int(st.session_state.get(page_key, 1)))
    try:
        result = context.queries.list_analysis_cases(
            run.analysis_run_id,
            scope_type="participant",
            scope_id=group_id,
            page=page,
            page_size=25,
        )
    except (PageQueryError, AttributeError) as error:
        st.error(str(error), icon=":material/error:")
        return
    rows = []
    chart = []
    for item in result.items:
        session_metrics = item.results.get("session_metrics")
        group_metrics = item.results.get("group_metrics")
        session_metrics = (
            session_metrics if isinstance(session_metrics, Mapping) else {}
        )
        group_metrics = group_metrics if isinstance(group_metrics, Mapping) else {}
        rows.append(
            {
                "Participant": item.subject_label,
                "Affected group": item.scope_label,
                "Status": item.status.value.replace("_", " ").title(),
                "Session top set changed": session_metrics.get("top_set_changed"),
                "Session Kendall tau-b": session_metrics.get("kendall_tau_b"),
                "Session maximum displacement": session_metrics.get(
                    "maximum_rank_displacement"
                ),
                "Group top set changed": group_metrics.get("top_set_changed"),
                "Group Kendall tau-b": group_metrics.get("kendall_tau_b"),
                "Group maximum displacement": group_metrics.get(
                    "maximum_rank_displacement"
                ),
                "Reason": item.results.get("reason"),
            }
        )
        if item.status == AnalysisCaseStatus.EVALUATED:
            chart.append(
                {
                    "Participant": item.subject_label,
                    "Session displacement": float(
                        session_metrics.get("maximum_rank_displacement", 0)
                    ),
                    "Group displacement": float(
                        group_metrics.get("maximum_rank_displacement", 0)
                    ),
                }
            )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    if chart:
        st.bar_chart(pd.DataFrame(chart).set_index("Participant"), horizontal=True)
    _render_case_pagination(result, page_key, run.analysis_run_id, namespace)
    _render_case_evidence(result.items)


def _render_case_pagination(result, page_key, run_id, namespace) -> None:
    if result.page_count <= 1:
        return
    selected_page = pagination(
        result.page_count,
        default=result.page,
        key=f"processing:analysis_pagination:{run_id}:{namespace}",
        width="stretch",
    )
    if selected_page != result.page:
        st.session_state[page_key] = selected_page
        st.rerun()


def _render_case_evidence(items) -> None:
    warnings = [
        {
            "case": item.sequence,
            "subject": item.subject_label,
            "warnings": item.warnings,
        }
        for item in items
        if item.warnings
    ]
    with st.expander("Warnings and not-evaluable evidence", expanded=False):
        if warnings:
            st.dataframe(warnings, hide_index=True, width="stretch")
        else:
            st.caption("No warnings are present on this page of results.")
    with st.expander("Detailed counterfactual cases", expanded=False):
        for item in items:
            st.markdown(f"**{item.sequence}. {item.subject_label}**")
            st.json(
                {
                    "status": item.status.value,
                    "scope": item.scope_label,
                    "inputs": dict(item.inputs),
                    "results": dict(item.results),
                    "warnings": item.warnings,
                    "content_hash": item.content_hash,
                }
            )


def _summary(run):
    artifact = next(
        (
            item
            for item in run.artifacts
            if item.artifact_type == ArtifactType.STRUCTURED_RESULT
        ),
        None,
    )
    return dict(artifact.content_json.get("summary", {})) if artifact else {}


def _provenance(run):
    return {
        "analysis_run_id": run.analysis_run_id,
        "method": run.method.value,
        "source_processing_run_id": run.source_processing_run_id,
        "source_ranking_run_id": run.source_ranking_run_id,
        "input_hash": run.input_hash,
        "output_hash": run.output_hash,
        "parameters": dict(run.parameter_json),
        "environment": dict(run.environment_json),
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "correlation_id": run.correlation_id,
    }


def _source_label(run, latest_id, timezone_name):
    state = "current" if run.ranking_run_id == latest_id else "stale"
    return (
        f"Run {run.run_number} · {run.algorithm_implementation_id} · "
        f"{format_datetime(run.completed_at, timezone_name=timezone_name)} · "
        f"{run.output_hash[:12]}… · {state}"
    )


def method_label(method: AnalysisMethod) -> str:
    return {
        AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION: "Weight perturbation",
        AnalysisMethod.CRITERION_REMOVAL: "Criterion removal",
        AnalysisMethod.RANK_REVERSAL: "Rank reversal",
        AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE: "Stakeholder-group influence",
        AnalysisMethod.PARTICIPANT_INFLUENCE: "Participant influence",
    }[method]


def method_explanation(method: AnalysisMethod) -> str:
    return {
        AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION: (
            "Changes one criterion weight at a time, redistributes remaining "
            "weight proportionally, and reruns ranking at session and group levels."
        ),
        AnalysisMethod.CRITERION_REMOVAL: (
            "Removes each criterion from the pairwise matrix, recomputes AHP "
            "weights, and reruns ranking to expose structural dependence."
        ),
        AnalysisMethod.RANK_REVERSAL: (
            "Removes each alternative and checks whether surviving alternatives "
            "reverse order or change to or from a tie."
        ),
        AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE: (
            "Removes one eligible stakeholder group, rebuilds the aggregate, and "
            "measures its effect on the session ranking."
        ),
        AnalysisMethod.PARTICIPANT_INFLUENCE: (
            "Removes one included participant, rebuilds the affected group and "
            "session aggregates, and shows moderator-only influence evidence."
        ),
    }[method]
