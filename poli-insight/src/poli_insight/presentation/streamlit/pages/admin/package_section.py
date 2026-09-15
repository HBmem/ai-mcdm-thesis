"""Package Results stage for immutable deterministic result bundles."""

from __future__ import annotations

from collections import Counter
from typing import Any

import streamlit as st

from poli_insight.application.use_cases.create_result_package import (
    CreateResultPackageCommand,
    CreateResultPackageError,
    PackageProgress,
)
from poli_insight.domain.enum import (
    AnalysisMethod,
    BundleVariant,
    RunInclusionStatus,
    RunStatus,
)
from poli_insight.presentation.streamlit.components.layout import (
    format_datetime,
)
from poli_insight.presentation.streamlit.context import PageContext

_METHOD_LABELS = {
    AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION: "Weight perturbation",
    AnalysisMethod.CRITERION_REMOVAL: "Criterion removal",
    AnalysisMethod.RANK_REVERSAL: "Rank reversal",
    AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE: "Stakeholder-group influence",
    AnalysisMethod.PARTICIPANT_INFLUENCE: "Participant influence",
}


def render_package_stage(
    context: PageContext,
    detail: Any,
    overview: Any,
    processing_runs: tuple[Any, ...],
    ranking_runs: tuple[Any, ...],
    analysis_runs: tuple[Any, ...],
    package_runs: tuple[Any, ...],
    *,
    read_only: bool,
) -> None:
    st.markdown("### Package Results")
    st.write(
        "Freeze one coherent processing, ranking, and analysis lineage into "
        "machine-readable bundle versions. Packaging does not publish results."
    )
    successful_rankings = tuple(
        item for item in ranking_runs if item.status == RunStatus.SUCCEEDED
    )
    eligible_rankings = tuple(
        item
        for item in successful_rankings
        if any(
            analysis.status == RunStatus.SUCCEEDED
            and analysis.source_ranking_run_id == item.ranking_run_id
            for analysis in analysis_runs
        )
    )
    if not eligible_rankings:
        st.info(
            "Run at least one sensitivity or robustness analysis against a "
            "successful ranking before packaging."
        )
        _package_history(package_runs, context)
        return
    ranking_labels = {
        item.ranking_run_id: _ranking_label(item, overview)
        for item in eligible_rankings
    }
    selected_ranking_id = st.selectbox(
        "Source ranking run",
        options=tuple(ranking_labels),
        format_func=ranking_labels.__getitem__,
        key=f"processing:package:ranking:{detail.summary.session_id}",
    )
    ranking = next(
        item for item in eligible_rankings if item.ranking_run_id == selected_ranking_id
    )
    processing = next(
        (
            item
            for item in processing_runs
            if item.processing_run_id == ranking.source_processing_run_id
        ),
        None,
    )
    matching = tuple(
        item
        for item in analysis_runs
        if item.source_ranking_run_id == ranking.ranking_run_id
    )
    selected_analysis_ids: list[str] = []
    st.markdown("#### Analysis evidence")
    for method in AnalysisMethod:
        method_runs = tuple(
            item
            for item in matching
            if item.method == method and item.status == RunStatus.SUCCEEDED
        )
        if not method_runs:
            failed = any(item.method == method for item in matching)
            st.caption(
                f"{_METHOD_LABELS[method]}: "
                + ("failed — not packaged" if failed else "not run")
            )
            continue
        include = st.checkbox(
            f"Include {_METHOD_LABELS[method]}",
            value=True,
            key=f"processing:package:include:{ranking.ranking_run_id}:{method.value}",
        )
        labels = {
            item.analysis_run_id: (
                f"Run {item.run_number} · {format_datetime(item.completed_at, timezone_name=context.container.settings.app_timezone)} "
                f"· {item.output_hash[:10] if item.output_hash else 'no hash'}"
            )
            for item in method_runs
        }
        selected = st.selectbox(
            f"{_METHOD_LABELS[method]} analysis run",
            options=tuple(labels),
            format_func=labels.__getitem__,
            disabled=not include,
            key=f"processing:package:analysis:{ranking.ranking_run_id}:{method.value}",
        )
        if include:
            selected_analysis_ids.append(selected)

    st.markdown("#### Bundle versions")
    columns = st.columns(2)
    anonymous = columns[0].checkbox(
        "Anonymous aggregate bundle",
        value=False,
        help="Contains session and stakeholder-group aggregates only.",
        key=f"processing:package:anonymous:{ranking.ranking_run_id}",
    )
    public_disabled = detail.identity_policy.casefold() == "anonymous"
    public = columns[1].checkbox(
        "Public / identity-linked bundle",
        value=False,
        disabled=public_disabled,
        help=(
            "Unavailable because this session is configured as anonymous."
            if public_disabled
            else "Retains package-scoped participant mappings for controlled reporting."
        ),
        key=f"processing:package:public:{ranking.ranking_run_id}",
    )
    if public_disabled:
        st.info("Anonymous sessions cannot create identity-linked bundles.")

    counts = Counter(
        item.stakeholder_group_id
        for item in (() if processing is None else processing.submissions)
        if item.inclusion_status == RunInclusionStatus.INCLUDED
    )
    group_names = {
        item.group_id: item.group_name for item in getattr(detail, "group_progress", ())
    }
    small_groups = tuple(
        (group_names.get(group_id, group_id), count)
        for group_id, count in counts.items()
        if 0 < count < 3
    )
    acknowledged = False
    if anonymous and small_groups:
        st.warning(
            "Small stakeholder-group aggregates can permit re-identification: "
            + ", ".join(f"{name} ({count})" for name, count in small_groups)
            + ". These results will be retained as requested."
        )
        acknowledged = st.checkbox(
            "I understand that small-group aggregates remain in the anonymous bundle.",
            key=f"processing:package:small-group:{ranking.ranking_run_id}",
        )

    variants = tuple(
        item
        for item, selected in (
            (BundleVariant.ANONYMOUS, anonymous),
            (BundleVariant.PUBLIC, public),
        )
        if selected
    )
    with st.expander("Package content, omissions, and privacy", expanded=True):
        st.json(
            {
                "source_processing_run_id": ranking.source_processing_run_id,
                "source_ranking_run_id": ranking.ranking_run_id,
                "selected_analysis_run_ids": selected_analysis_ids,
                "selected_variants": [item.value for item in variants],
                "participants_represented": (
                    0 if processing is None else len(processing.submissions)
                ),
                "included_participants": sum(counts.values()),
                "excluded_participants": (
                    0
                    if processing is None
                    else len(processing.submissions) - sum(counts.values())
                ),
                "stakeholder_groups_with_included_evidence": len(counts),
                "small_group_warning_count": len(small_groups),
                "public_identity_fields": (
                    ["package subject key", "participant ID", "alias snapshot", "group"]
                    if public
                    else []
                ),
                "excluded_identity_fields": [
                    "stored names and email addresses",
                    "invitation data",
                    "access tokens and credentials",
                ],
            }
        )

    actor_id = context.principal.subject
    invalid = (
        read_only
        or actor_id is None
        or not selected_analysis_ids
        or not variants
        or (anonymous and bool(small_groups) and not acknowledged)
    )
    if read_only:
        st.info(
            "Archived sessions are inspection-only; existing packages remain available."
        )
    overall = st.progress(0.0, text="Ready to package selected evidence")
    current = st.progress(0.0, text="Waiting")
    status = st.status("Package activity", expanded=False)

    def on_progress(progress: PackageProgress) -> None:
        fraction = progress.completed_steps / max(progress.total_steps, 1)
        overall.progress(fraction, text=progress.message)
        current.progress(fraction, text=progress.phase.replace("_", " ").title())
        status.write(progress.message)

    if st.button(
        "Create selected bundle versions",
        type="primary",
        disabled=invalid,
        key=f"processing:package:create:{ranking.ranking_run_id}",
    ):
        try:
            result = context.container.packages.create.execute(
                CreateResultPackageCommand(
                    session_id=detail.summary.session_id,
                    source_ranking_run_id=ranking.ranking_run_id,
                    source_analysis_run_ids=tuple(selected_analysis_ids),
                    variants=variants,
                    actor_id=actor_id or "",
                    small_group_acknowledged=acknowledged,
                ),
                on_progress=on_progress,
            )
        except CreateResultPackageError as error:
            status.update(label="Package creation failed", state="error", expanded=True)
            st.error(str(error))
        else:
            status.update(label="Package complete", state="complete", expanded=True)
            st.success(
                f"Package run {result.run_number} created with "
                + ", ".join(item.value for item in result.variants)
                + "."
            )
            st.session_state["reports:session_id"] = detail.summary.session_id
            if st.button(
                "Open AI Reports & Publication",
                icon=":material/arrow_forward:",
                key=f"processing:package:reports:{result.package_run_id}",
            ):
                st.switch_page(context.routes["admin_reports"])
    _package_history(package_runs, context)


def _package_history(package_runs: tuple[Any, ...], context: PageContext) -> None:
    st.markdown("#### Immutable package history")
    if not package_runs:
        st.caption("No final result package has been created for this session.")
        return
    st.dataframe(
        [
            {
                "Run": item.run_number,
                "Status": item.status.value.replace("_", " ").title(),
                "Versions": ", ".join(value.value for value in item.variants),
                "Created": format_datetime(
                    item.created_at,
                    timezone_name=context.container.settings.app_timezone,
                ),
                "Analyses": len(item.source_analysis_run_ids),
                "Processing lineage": item.source_processing_run_id,
                "Ranking lineage": item.source_ranking_run_id,
                "Warnings": _warning_count(item),
                "Input hash": item.input_hash,
                "Output hash": item.output_hash or "—",
                "Failure": item.failure_detail or "—",
            }
            for item in package_runs
        ],
        hide_index=True,
        width="stretch",
    )


def _warning_count(package_run: Any) -> int:
    provenance = next(
        (
            artifact
            for artifact in getattr(package_run, "artifacts", ())
            if getattr(artifact, "name", None) == "07_provenance"
        ),
        None,
    )
    if provenance is None:
        return 0
    warnings = provenance.content_json.get("warnings", [])
    return len(warnings) if isinstance(warnings, list) else 0


def _ranking_label(item: Any, overview: Any) -> str:
    state = "current" if item.roster_hash == overview.current_roster_hash else "stale"
    hash_prefix = item.output_hash[:10] if item.output_hash else "no hash"
    return (
        f"Run {item.run_number} · {item.algorithm_implementation_id} · "
        f"{item.completed_at.isoformat()} · {hash_prefix} · {state}"
    )
