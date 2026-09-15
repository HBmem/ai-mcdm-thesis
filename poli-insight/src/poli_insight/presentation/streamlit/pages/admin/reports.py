"""Deterministic package exports and controlled participant-result releases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import streamlit as st

from poli_insight.application.queries.page_queries import (
    ProcessingQueueMode,
    SessionSearchFilters,
)
from poli_insight.application.use_cases.participant_result_release import (
    ParticipantResultReleaseError,
    ReleaseParticipantResultsCommand,
    WithdrawParticipantResultsCommand,
)
from poli_insight.application.use_cases.result_package_exports import (
    ResultPackageExportError,
)
from poli_insight.domain.enum import (
    BundleVariant,
    ParticipantReleaseStatus,
    RunStatus,
)
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    format_datetime,
    render_admin_surface_styles,
    render_capability_notice,
    render_empty_state,
    render_page_header,
)
from poli_insight.presentation.streamlit.context import PageContext


def render(context: PageContext) -> None:
    render_admin_surface_styles()
    render_page_header(
        PageHeader(
            eyebrow="Administration",
            title="AI Reports & Publication",
            description=(
                "Inspect immutable result packages, export deterministic bundles "
                "and reports, and control participant access to identity-linked results."
            ),
        )
    )
    render_capability_notice(
        "Deterministic reporting is available",
        "Exports and participant previews use only persisted package evidence. "
        "AI drafting, editorial review, and general publication are future functionality.",
        available=True,
    )
    if context.principal.subject is None:
        st.error("Your administrator session has expired.")
        return

    sessions = context.queries.list_processing_sessions(
        filters=SessionSearchFilters(),
        mode=ProcessingQueueMode.PROCESSED,
        page=1,
        page_size=100,
    ).items
    if not sessions:
        render_empty_state(
            "No packaged sessions",
            "Create a successful package in Session Processing before using this workspace.",
            icon=":material/package_2:",
        )
        return

    by_id = {item.session_id: item for item in sessions}
    requested = st.session_state.get("reports:session_id")
    default_index = list(by_id).index(requested) if requested in by_id else 0
    session_id = st.selectbox(
        "Session",
        options=tuple(by_id),
        index=default_index,
        format_func=lambda value: by_id[value].title,
        key="reports:session",
    )
    st.session_state["reports:session_id"] = session_id
    summary = by_id[session_id]
    package_runs = tuple(
        item
        for item in context.container.packages.list_runs.execute(session_id)
        if item.status == RunStatus.SUCCEEDED
    )
    if not package_runs:
        render_empty_state(
            "No successful package",
            "The session has no complete downloadable package.",
        )
        return

    package_labels = {
        item.package_run_id: _package_label(item, context) for item in package_runs
    }
    package_id = st.selectbox(
        "Package run",
        options=tuple(package_labels),
        format_func=package_labels.__getitem__,
        key=f"reports:package:{session_id}",
    )
    package = next(item for item in package_runs if item.package_run_id == package_id)
    packaged_configuration_id = _package_configuration_id(package)
    stale = (
        package.source_roster_hash != summary.current_roster_hash
        or packaged_configuration_id != summary.active_configuration_version_id
    )
    _package_overview(package, stale=stale)

    anonymous_tab, public_tab = st.tabs(
        ("Anonymous aggregate bundle", "Public / identity-linked bundle")
    )
    with anonymous_tab:
        _variant_workspace(context, package, BundleVariant.ANONYMOUS)
    with public_tab:
        _variant_workspace(context, package, BundleVariant.PUBLIC)
        if BundleVariant.PUBLIC in package.variants:
            _participant_directory(package)
            _participant_release_controls(
                context,
                package,
                session_id=session_id,
                stale=stale,
            )


def _package_label(package: Any, context: PageContext) -> str:
    return (
        f"Run {package.run_number} · "
        f"{format_datetime(package.completed_at, timezone_name=context.container.settings.app_timezone)} "
        f"· {(package.output_hash or 'no hash')[:10]}"
    )


def _package_overview(package: Any, *, stale: bool) -> None:
    st.markdown("### Package evidence")
    columns = st.columns(4)
    columns[0].metric("Package run", package.run_number)
    columns[1].metric("Versions", len(package.variants))
    columns[2].metric("Selected analyses", len(package.source_analysis_run_ids))
    columns[3].metric("Lineage", "Stale" if stale else "Current")
    if stale:
        st.warning(
            "This historical package remains available for moderator inspection and "
            "export, but it cannot be released to participants."
        )
    manifest = _variant_manifest(package, package.variants[0])
    completeness = manifest.get("completeness", {}) if manifest else {}
    warnings = manifest.get("warnings", []) if manifest else []
    with st.expander("Completeness, warnings, and hashes"):
        st.markdown("#### Completeness")
        st.json(completeness)
        st.markdown("#### Privacy and processing warnings")
        st.json(warnings)
        st.markdown("#### Lineage and hashes")
        st.json(
            {
                "package_run_id": package.package_run_id,
                "source_processing_run_id": package.source_processing_run_id,
                "source_ranking_run_id": package.source_ranking_run_id,
                "source_analysis_run_ids": package.source_analysis_run_ids,
                "input_hash": package.input_hash,
                "output_hash": package.output_hash,
                "source_processing_output_hash": package.source_processing_output_hash,
                "source_ranking_output_hash": package.source_ranking_output_hash,
            }
        )


def _variant_workspace(
    context: PageContext,
    package: Any,
    variant: BundleVariant,
) -> None:
    if variant not in package.variants:
        render_empty_state(
            f"{variant.value.title()} bundle not created",
            "Return to Package Results to create this immutable bundle version.",
        )
        return
    if variant == BundleVariant.ANONYMOUS:
        st.info(
            "Aggregate-only: participant identifiers, aliases, individual matrices, "
            "rankings, and influence cases are excluded."
        )
    else:
        st.warning(
            "Identity-linked moderator data. This bundle contains package-scoped subject "
            "files and one identity map; handle it according to the session privacy policy."
        )
    manifest = _variant_manifest(package, variant)
    st.caption(
        f"Schema version {manifest.get('schema_version', '—')} · "
        f"privacy label: {manifest.get('privacy_label', variant.value)}"
    )
    export_col, report_col = st.columns(2)
    try:
        bundle = context.container.packages.export.execute(
            package.package_run_id, variant
        )
        report = context.container.packages.render_report.execute(
            package.package_run_id, variant
        )
    except ResultPackageExportError as error:
        st.error(str(error))
        return
    export_col.download_button(
        "Export complete bundle",
        data=bundle.content,
        file_name=bundle.filename,
        mime=bundle.media_type,
        icon=":material/archive:",
        key=f"reports:bundle:{package.package_run_id}:{variant.value}",
        use_container_width=True,
    )
    report_col.download_button(
        "Generate readable report",
        data=report.content,
        file_name=report.filename,
        mime=report.media_type,
        icon=":material/description:",
        key=f"reports:html:{package.package_run_id}:{variant.value}",
        use_container_width=True,
    )
    with st.expander("Variant manifest"):
        st.json(manifest)


def _participant_directory(package: Any) -> None:
    st.markdown("### Moderator-only participant directory")
    st.caption(
        "Personalized previews show one participant at a time. Packaging never decrypts "
        "or exposes names, email addresses, invitations, access tokens, or credentials."
    )
    if not package.subjects:
        st.info("No participant records were represented in this package.")
        return
    labels = {
        item.package_subject_id: (
            f"{item.alias_snapshot} · {item.stakeholder_group_label} · "
            f"{item.inclusion_status.value.replace('_', ' ')}"
        )
        for item in package.subjects
    }
    subject_id = st.selectbox(
        "Participant result",
        options=tuple(labels),
        format_func=labels.__getitem__,
        key=f"reports:participant:{package.package_run_id}",
    )
    subject = next(
        item for item in package.subjects if item.package_subject_id == subject_id
    )
    result = subject.result_json
    sections = (
        ("What the participant submitted", result.get("preferences")),
        ("Criterion weights and comparisons", result.get("weights")),
        ("Rankings and comparisons", result.get("rankings")),
        ("Stakeholder allocation", result.get("stakeholder_representation")),
        ("Participant-influence testing", result.get("participant_influence")),
        ("Inclusion in the collective result", result.get("inclusion")),
    )
    for label, value in sections:
        with st.expander(label, expanded=label == "Inclusion in the collective result"):
            st.json(value)
    st.caption(
        "Leave-one-out influence is counterfactual sensitivity evidence. It does not "
        "establish that the participant caused a collective outcome."
    )


def _participant_release_controls(
    context: PageContext,
    package: Any,
    *,
    session_id: str,
    stale: bool,
) -> None:
    st.markdown("### Participant access")
    releases = context.container.packages.list_releases.execute(session_id)
    active = next(
        (item for item in releases if item.status == ParticipantReleaseStatus.ACTIVE),
        None,
    )
    if active is None:
        st.info(
            "Packaging does not expose results automatically. Confirm a release to make "
            "each participant's own breakdown available through their private link."
        )
    else:
        st.success(
            f"Release version {active.version_number} is active for package "
            f"{active.package_run_id[:10]}."
        )
    actor_id = context.principal.subject
    release_confirmed = st.checkbox(
        "I confirm that this current public package may be released to its participants.",
        key=f"reports:release:confirm:{package.package_run_id}",
    )
    if st.button(
        "Release this package to participants",
        type="primary",
        disabled=stale or not release_confirmed or actor_id is None,
        key=f"reports:release:{package.package_run_id}",
    ):
        try:
            release = context.container.packages.release_participants.execute(
                ReleaseParticipantResultsCommand(
                    session_id=session_id,
                    package_run_id=package.package_run_id,
                    actor_id=actor_id or "",
                )
            )
        except ParticipantResultReleaseError as error:
            st.error(str(error))
        else:
            st.success(
                f"Participant release version {release.version_number} activated."
            )
            st.rerun()
    if active is not None:
        reason = st.text_input(
            "Required withdrawal reason",
            key=f"reports:withdraw:reason:{active.release_id}",
        )
        if st.button(
            "Withdraw active participant release",
            disabled=not reason.strip() or actor_id is None,
            key=f"reports:withdraw:{active.release_id}",
        ):
            try:
                context.container.packages.withdraw_participants.execute(
                    WithdrawParticipantResultsCommand(
                        session_id=session_id,
                        actor_id=actor_id or "",
                        reason=reason,
                    )
                )
            except ParticipantResultReleaseError as error:
                st.error(str(error))
            else:
                st.success("Participant access withdrawn.")
                st.rerun()
    with st.expander("Participant release history"):
        if not releases:
            st.caption("No participant result release has been created.")
        else:
            st.dataframe(
                [
                    {
                        "Version": item.version_number,
                        "Status": item.status.value.title(),
                        "Package": item.package_run_id,
                        "Released": item.released_at.isoformat(),
                        "Withdrawn": (
                            item.withdrawn_at.isoformat() if item.withdrawn_at else "—"
                        ),
                        "Reason": item.withdrawal_reason or "—",
                    }
                    for item in releases
                ],
                hide_index=True,
                width="stretch",
            )


def _variant_manifest(package: Any, variant: BundleVariant) -> Mapping[str, Any]:
    for artifact in package.artifacts:
        if artifact.variant == variant:
            return artifact.content_json
    return {}


def _package_configuration_id(package: Any) -> str | None:
    for artifact in package.artifacts:
        if getattr(artifact, "name", None) == "02_configuration":
            value = artifact.content_json.get("configuration_version_id")
            return None if value is None else str(value)
    return None
