from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st
from streamlit_extras.metric_cards import (  # type: ignore[import-untyped]
    style_metric_cards,
)
from streamlit_extras.pagination import pagination  # type: ignore[import-untyped]
from streamlit_extras.steps import steps  # type: ignore[import-untyped]

from poli_insight.application.ports.bundled_scenarios import (
    BundledScenarioCandidate,
    BundledScenarioSourceError,
)
from poli_insight.application.queries.page_queries import (
    AdminSessionDetail,
    AdminSessionSummary,
    PageQueryError,
    ScenarioSnapshotDetail,
    ScenarioSnapshotSummary,
)
from poli_insight.application.use_cases.activate_session_configuration import (
    ActivateSessionConfigurationCommand,
    ActivateSessionConfigurationError,
)
from poli_insight.application.use_cases.close_session import (
    CloseSessionCommand,
    CloseSessionError,
)
from poli_insight.application.use_cases.create_session import (
    CreateSessionCommand,
    CreateSessionError,
)
from poli_insight.application.use_cases.create_session_configuration import (
    AlgorithmSelectionInput,
    CreateSessionConfigurationCommand,
    CreateSessionConfigurationError,
    StakeholderGroupInput,
)
from poli_insight.application.use_cases.import_bundled_scenarios import (
    BundledScenarioDiscoveryResult,
    BundledScenarioOutcomeStatus,
    ImportBundledScenariosCommand,
    ImportBundledScenariosResult,
)
from poli_insight.application.use_cases.import_invitations import (
    ApplyInvitationImportCommand,
    ApplyInvitationImportResult,
    InvitationImportError,
    InvitationImportPreview,
    PreviewInvitationImportCommand,
)
from poli_insight.application.use_cases.import_scenario import (
    ImportScenarioCommand,
    ImportScenarioResult,
    ScenarioImportError,
)
from poli_insight.application.use_cases.manage_invitations import (
    ExpireInvitationsCommand,
    InvitationManagementError,
    IssuedInvitationResult,
    IssueInvitationCommand,
    ReplaceInvitationCommand,
    RevokeInvitationCommand,
)
from poli_insight.application.use_cases.open_session import (
    OpenSessionCommand,
    OpenSessionError,
)
from poli_insight.application.use_cases.participant_submission_import import (
    ApplyParticipantSubmissionImportCommand,
    GenerateImportedResumeLinksCommand,
    GenerateImportedResumeLinksResult,
    GenerateParticipantImportTemplateCommand,
    ImportRowStatus,
    ParticipantSubmissionImportError,
    ParticipantSubmissionImportPreview,
    PreviewParticipantSubmissionImportCommand,
    RedactExpiredImportedIdentityCommand,
)
from poli_insight.application.use_cases.replace_participant_access_grant import (
    ReplaceParticipantAccessGrantCommand,
    ReplaceParticipantAccessGrantError,
)
from poli_insight.application.use_cases.review_submission import (
    ReviewSubmissionCommand,
    ReviewSubmissionError,
)
from poli_insight.application.use_cases.transition_session import (
    SessionTransition,
    TransitionSessionCommand,
    TransitionSessionError,
)
from poli_insight.domain.enum import (
    AccessCodeMode,
    ActorType,
    AlgorithmRole,
    Discoverability,
    EnrollmentMode,
    InvitationStatus,
    MissingGroupPolicy,
    ParticipantAccessStatus,
    ResponseFormat,
    ResponseTargetType,
    ScenarioSnapshotStatus,
    SessionStatus,
    StakeholderSelectionMode,
    SubmissionReviewStatus,
    SubmissionStatus,
    ValidationStatus,
)
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    format_datetime,
    render_empty_state,
    render_page_header,
)
from poli_insight.presentation.streamlit.components.scenario_archive import (
    MAX_ARCHIVE_BYTES,
    ScenarioArchiveError,
    ScenarioArchiveInspection,
    extracted_scenario_directory,
    inspect_scenario_archive,
)
from poli_insight.presentation.streamlit.components.status import render_status
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.urls import (
    private_invitation_url,
    private_resume_url,
)

_PAGE_SIZE = 10
_SESSION_SELECTED_KEY = "sessions:selected_session_id"
_SESSION_PAGE_KEY = "sessions:page"
_SESSION_FILTER_KEY = "sessions:filter_fingerprint"
_CREATE_DIALOG_KEY = "session_create:dialog_open"
_CREATE_GENERATION_KEY = "session_create:generation"
_CONFIG_DIALOG_KEY = "session_config:dialog_open"
_CONFIG_GENERATION_KEY = "session_config:generation"
_ACCESS_REPLACE_DIALOG_KEY = "participant_access:replace_dialog"
_NEW_RESUME_LINK_KEY = "participant_access:new_resume_link"
_SESSION_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True, slots=True, repr=False)
class _OneTimeResumeLink:
    participant_id: str
    resume_url: str
    expires_at: datetime

    def __repr__(self) -> str:
        return "_OneTimeResumeLink(resume_url=<redacted>)"
_SELECTED_SNAPSHOT_KEY = "scenario_library:selected_snapshot_id"
_PAGE_KEY = "scenario_library:page"
_FILTER_KEY = "scenario_library:filter_fingerprint"
_IMPORT_DIALOG_OPEN_KEY = "scenario_import:dialog_open"
_IMPORT_RESULT_KEY = "scenario_import:result"
_IMPORT_GENERATION_KEY = "scenario_import:generation"
_BATCH_DIALOG_OPEN_KEY = "scenario_batch:dialog_open"
_BATCH_COMMAND_KEY = "scenario_batch:command"
_BATCH_DISCOVERY_KEY = "scenario_batch:discovery"
_BATCH_RESULT_KEY = "scenario_batch:result"
_BATCH_GENERATION_KEY = "scenario_batch:generation"
_INVITATION_RESULT_KEY = "operations:invitation_result"
_INVITATION_IMPORT_PREVIEW_KEY = "operations:invitation_import_preview"
_INVITATION_IMPORT_CONTENT_KEY = "operations:invitation_import_content"
_INVITATION_IMPORT_RESULT_KEY = "operations:invitation_import_result"
_PARTICIPANT_IMPORT_PREFIX = "participant_import:"
_PARTICIPANT_IMPORT_PREVIEW_KEY = f"{_PARTICIPANT_IMPORT_PREFIX}preview"
_PARTICIPANT_IMPORT_CONTENT_KEY = f"{_PARTICIPANT_IMPORT_PREFIX}content"
_PARTICIPANT_IMPORT_RESULT_KEY = f"{_PARTICIPANT_IMPORT_PREFIX}result"
_PARTICIPANT_IMPORT_CREDENTIALS_KEY = f"{_PARTICIPANT_IMPORT_PREFIX}credentials"


@dataclass(frozen=True, slots=True)
class _ConfigurationResponseDraft:
    response_format: ResponseFormat
    target_type: ResponseTargetType
    scale_id: str
    weighting_id: str
    ranking_id: str


@dataclass(frozen=True, slots=True)
class _ConfigurationRulesDraft:
    allow_resubmissions: bool
    max_submissions_per_participant: int
    allow_incomplete_submission: bool
    minimum_valid_submissions: int
    missing_group_policy: MissingGroupPolicy
    consistency_threshold: Decimal
    consent_required: bool
    consent_version: str
    consent_title: str
    consent_statement: str


def render(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="Administration",
            title="Manage Sessions",
            description=(
                "Create sessions from immutable scenario snapshots and manage "
                "their configuration, lifecycle, participants, and submissions."
            ),
        )
    )

    tabs = st.tabs(("Sessions", "Scenario Library", "Imports", "Audit"))
    with tabs[0]:
        _render_sessions(context)
    with tabs[1]:
        _render_scenario_library(context)
    with tabs[2]:
        _render_participant_submission_imports(context)
    with tabs[3]:
        _render_admin_audit(context)


def _render_participant_submission_imports(context: PageContext) -> None:
    if getattr(context.container, "participant_imports", None) is None:
        render_empty_state(
            "Participant imports unavailable",
            "The participant import services are not configured in this runtime.",
            icon=":material/upload_file:",
        )
        return
    maintenance_key = f"{_PARTICIPANT_IMPORT_PREFIX}retention_checked"
    if not st.session_state.get(maintenance_key, False):
        try:
            context.container.participant_imports.redact_expired_identity.execute(
                RedactExpiredImportedIdentityCommand(limit=25)
            )
        except ParticipantSubmissionImportError:
            st.warning(
                "Imported-identity retention maintenance could not run. "
                "No identity values were displayed."
            )
        except Exception:  # noqa: BLE001 - never render persistence details or PII.
            st.warning(
                "Imported-identity retention maintenance could not run. "
                "No identity values were displayed."
            )
        else:
            st.session_state[maintenance_key] = True
    st.subheader("Participant and submission imports", anchor=False)
    st.write(
        "Populate a frozen session configuration from a UTF-8 CSV or .xlsx "
        "workbook. Preview is read-only; apply is atomic and audited."
    )
    sessions = context.queries.list_admin_sessions(page=1, page_size=100).items
    eligible = tuple(
        item for item in sessions if item.active_configuration_version is not None
    )
    selected_id = st.selectbox(
        "1. Choose session",
        options=(None, *(item.session_id for item in eligible)),
        format_func=lambda value: (
            "Select a configured session"
            if value is None
            else next(
                f"{item.title} · {item.public_slug} · {item.status.value}"
                for item in eligible
                if item.session_id == value
            )
        ),
        key=f"{_PARTICIPANT_IMPORT_PREFIX}session",
    )
    if selected_id is None:
        render_empty_state(
            "Choose a session to begin",
            "Templates and validation are generated from its activated frozen configuration.",
            icon=":material/upload_file:",
        )
        return
    try:
        scope = context.container.participant_imports.get_session.execute(selected_id)
    except ParticipantSubmissionImportError as error:
        st.error(str(error), icon=":material/error:")
        return

    with st.container(border=True):
        st.markdown(f"#### {scope.session_title}")
        st.caption(
            f"/{scope.session_slug} · {scope.lifecycle_state.value.title()} · "
            f"{scope.scenario_title} {scope.scenario_version}"
        )
        facts = st.columns(4)
        facts[0].metric("Configuration", f"v{scope.configuration_version}")
        facts[1].metric("Required questions", scope.required_question_count)
        facts[2].metric("Response", scope.response_format.value.replace("_", " "))
        facts[3].metric("Target", scope.response_target_type.replace("_", " "))
        st.markdown(
            f"**Scale:** {scope.scale_name} v{scope.scale_version}  \n"
            f"**Groups:** {', '.join(f'{key} ({name})' for key, name in scope.groups)}  \n"
            f"**Incomplete submissions:** {'permitted' if scope.allow_incomplete_submission else 'not permitted'}  \n"
            f"**Resubmissions:** {'permitted' if scope.allow_resubmissions else 'not permitted'}  \n"
            f"**Consistency threshold:** {scope.consistency_threshold or 'not configured'}  \n"
            f"**Consent:** {scope.consent_policy}  \n"
            f"**Identity policy:** {scope.identity_policy}"
        )

    completed_result = st.session_state.get(_PARTICIPANT_IMPORT_RESULT_KEY)
    if completed_result is not None:
        _render_participant_import_result(context, scope, completed_result)
        return

    st.markdown("#### 2. Prepare template")
    template_columns = st.columns(4)
    template_specs = (
        ("Blank Excel", "xlsx", False),
        ("Blank CSV", "csv", False),
        ("Example Excel", "xlsx", True),
        ("Example CSV", "csv", True),
    )
    for column, (label, file_format, example) in zip(
        template_columns, template_specs, strict=True
    ):
        try:
            template = context.container.participant_imports.generate_template.execute(
                GenerateParticipantImportTemplateCommand(
                    session_id=selected_id,
                    file_format=file_format,
                    filled_example=example,
                )
            )
        except ParticipantSubmissionImportError as error:
            column.caption(str(error))
        else:
            column.download_button(
                label,
                data=template.content,
                file_name=template.filename,
                mime=template.media_type,
                icon=":material/download:",
                width="stretch",
                key=f"{_PARTICIPANT_IMPORT_PREFIX}template:{file_format}:{example}",
            )

    st.markdown("#### 3. Upload and preview")
    upload = st.file_uploader(
        "CSV or Excel workbook",
        type=("csv", "xlsx"),
        accept_multiple_files=False,
        key=f"{_PARTICIPANT_IMPORT_PREFIX}upload",
        help="The uploaded file is held only for this transient preview/apply workflow.",
    )
    preview_state = st.session_state.get(_PARTICIPANT_IMPORT_PREVIEW_KEY)
    current_preview = (
        preview_state
        if isinstance(preview_state, ParticipantSubmissionImportPreview)
        else None
    )
    conflict_rows = (
        tuple(
            row.row_number
            for row in current_preview.rows
            if row.status
            in {ImportRowStatus.SKIPPED_CONFLICT, ImportRowStatus.PLANNED_REPLACEMENT}
        )
        if current_preview is not None
        and current_preview.session_id == selected_id
        else ()
    )
    selected_replacement_rows = (
        tuple(
            row.row_number
            for row in current_preview.rows
            if row.status == ImportRowStatus.PLANNED_REPLACEMENT
        )
        if current_preview is not None
        else ()
    )
    replace_rows = frozenset(
        st.multiselect(
            "Replace existing submission (selected rows)",
            options=conflict_rows,
            default=selected_replacement_rows if conflict_rows else (),
            key=f"{_PARTICIPANT_IMPORT_PREFIX}replace_rows",
            help="A replacement creates a new attempt and preserves prior evidence.",
        )
    )
    preview_clicked = st.button(
        "Preview import" if current_preview is None else "Update preview plan",
        type="primary",
        disabled=upload is None,
        key=f"{_PARTICIPANT_IMPORT_PREFIX}preview_button",
    )
    if preview_clicked and upload is not None:
        try:
            content = upload.getvalue()
            generated_preview = context.container.participant_imports.preview.execute(
                PreviewParticipantSubmissionImportCommand(
                    session_id=selected_id,
                    filename=upload.name,
                    content=content,
                    replace_row_numbers=replace_rows,
                )
            )
        except ParticipantSubmissionImportError as error:
            st.error(str(error), icon=":material/error:")
        except Exception:  # noqa: BLE001 - uploaded values must not reach the page.
            st.error(
                "The file could not be previewed safely. Verify the template "
                "and try again.",
                icon=":material/error:",
            )
        else:
            st.session_state[_PARTICIPANT_IMPORT_PREVIEW_KEY] = generated_preview
            st.session_state[_PARTICIPANT_IMPORT_CONTENT_KEY] = content
            st.session_state.pop(_PARTICIPANT_IMPORT_RESULT_KEY, None)
            st.rerun()

    preview_state = st.session_state.get(_PARTICIPANT_IMPORT_PREVIEW_KEY)
    if not isinstance(preview_state, ParticipantSubmissionImportPreview):
        return
    preview = preview_state
    if preview.session_id != selected_id:
        return
    summary = preview.summary
    metrics = st.columns(5)
    metrics[0].metric("Rows", summary.total_rows)
    metrics[1].metric("New", summary.new_participants)
    metrics[2].metric("Submitted", summary.submitted)
    metrics[3].metric("Skipped", summary.skipped_conflicts)
    metrics[4].metric("Blocking", summary.blocking_error_count)
    status_filter = st.selectbox(
        "Row status",
        options=(None, *ImportRowStatus),
        format_func=lambda value: (
            "All rows" if value is None else value.value.replace("_", " ").title()
        ),
        key=f"{_PARTICIPANT_IMPORT_PREFIX}status_filter",
    )
    visible_rows = tuple(
        row for row in preview.rows
        if status_filter is None or row.status == status_filter
    )
    st.dataframe(
        [
            {
                "Row": row.row_number,
                "Participant reference": row.participant_ref,
                "Alias": row.participant_alias,
                "Group": row.group_name or "—",
                "State": row.record_state.value,
                "Answers": row.answer_count,
                "Status": row.status.value.replace("_", " ").title(),
            }
            for row in visible_rows
        ],
        hide_index=True,
        width="stretch",
    )
    for row in visible_rows:
        if row.issues:
            with st.expander(f"Row {row.row_number} diagnostics ({len(row.issues)})"):
                for issue in row.issues:
                    st.write(
                        f"{'Error' if issue.blocking else 'Warning'} · "
                        f"`{issue.column}` · {issue.message}"
                    )
    if any(row.issues for row in preview.rows):
        st.download_button(
            "Download diagnostics",
            data=preview.error_report_csv,
            file_name="participant-import-diagnostics.csv",
            mime="text/csv",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}diagnostics",
        )

    st.markdown("#### 4. Confirm and apply")
    if preview.has_blocking_errors:
        st.error("Resolve every blocking error and preview the file again.")
        return
    lifecycle_supported = scope.lifecycle_state in {
        SessionStatus.DRAFT,
        SessionStatus.OPEN,
        SessionStatus.PAUSED,
        SessionStatus.CLOSED,
    }
    if not lifecycle_supported:
        st.error(
            f"Sessions in {scope.lifecycle_state.value!r} state cannot be imported."
        )
    lifecycle_override = False
    lifecycle_reason = None
    if scope.lifecycle_state in {SessionStatus.PAUSED, SessionStatus.CLOSED}:
        st.warning(
            "This changes historical/session data in a paused or closed session "
            "and will be recorded in the audit log."
        )
        lifecycle_override = st.checkbox(
            "Override paused/closed session protection",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}lifecycle_override",
        )
        lifecycle_reason = st.text_input(
            "Lifecycle override reason",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}lifecycle_reason",
        )
    resub_override = False
    resub_reason = None
    if summary.planned_replacements and not scope.allow_resubmissions:
        resub_override = st.checkbox(
            "Override resubmission policy",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}resub_override",
        )
        resub_reason = st.text_input(
            "Resubmission override reason",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}resub_reason",
        )
    identity_attested = False
    identity_basis = None
    if summary.identity_rows:
        identity_attested = st.checkbox(
            "I confirm authorization to store the imported identity data",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}identity_attestation",
        )
        identity_basis = st.text_input(
            "Identity processing basis",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}identity_basis",
        )
        st.caption(
            "This administrator attestation is not participant questionnaire consent."
        )
    confirmed = st.checkbox(
        f"Confirm: create {summary.new_participants}, submit {summary.submitted}, "
        f"draft {summary.drafts}, replace {summary.planned_replacements}, "
        f"skip {summary.skipped_conflicts}",
        key=f"{_PARTICIPANT_IMPORT_PREFIX}confirmed",
    )
    actor_id = context.principal.subject
    apply_disabled = (
        not confirmed
        or not lifecycle_supported
        or actor_id is None
        or (scope.lifecycle_state in {SessionStatus.PAUSED, SessionStatus.CLOSED} and (not lifecycle_override or not (lifecycle_reason or "").strip()))
        or (summary.planned_replacements and not scope.allow_resubmissions and (not resub_override or not (resub_reason or "").strip()))
        or (summary.identity_rows > 0 and (not identity_attested or not (identity_basis or "").strip()))
    )
    if st.button(
        "Confirm and apply",
        type="primary",
        disabled=apply_disabled,
        key=f"{_PARTICIPANT_IMPORT_PREFIX}apply",
    ):
        transient_content = st.session_state.get(_PARTICIPANT_IMPORT_CONTENT_KEY)
        if not isinstance(transient_content, bytes):
            st.error("The transient upload expired. Upload and preview again.")
        else:
            try:
                with st.spinner("Applying the import atomically…"):
                    result = context.container.participant_imports.apply.execute(
                        ApplyParticipantSubmissionImportCommand(
                            session_id=selected_id,
                            filename=preview.filename,
                            content=transient_content,
                            expected_file_hash=preview.file_hash,
                            expected_plan_hash=preview.plan_hash,
                            actor_id=actor_id or "",
                            actor_roles=context.principal.roles,
                            replace_row_numbers=replace_rows,
                            lifecycle_override=lifecycle_override,
                            lifecycle_override_reason=lifecycle_reason,
                            resubmission_override=resub_override,
                            resubmission_override_reason=resub_reason,
                            identity_processing_attested=identity_attested,
                            identity_processing_basis=identity_basis,
                        )
                    )
            except ParticipantSubmissionImportError as error:
                st.error(str(error), icon=":material/error:")
            except Exception:  # noqa: BLE001 - uploaded values must not reach the page.
                st.error(
                    "The import could not be applied safely. No rows were committed.",
                    icon=":material/error:",
                )
            else:
                st.session_state[_PARTICIPANT_IMPORT_RESULT_KEY] = result
                st.session_state.pop(_PARTICIPANT_IMPORT_CONTENT_KEY, None)
                st.session_state.pop(_PARTICIPANT_IMPORT_PREVIEW_KEY, None)
                st.session_state.pop(
                    f"{_PARTICIPANT_IMPORT_PREFIX}upload", None
                )
                st.rerun()

def _render_participant_import_result(context: PageContext, scope: Any, result: Any) -> None:
    st.success(
        f"Import applied: {result.created_participant_count} participants, "
        f"{result.submitted_count} submissions, {result.replaced_count} replacements."
    )
    st.download_button(
        "Download import result",
        data=result.result_report_csv,
        file_name="participant-import-result.csv",
        mime="text/csv",
        key=f"{_PARTICIPANT_IMPORT_PREFIX}result_download",
    )
    eligible_ids = tuple(
        row.participant_id
        for row in result.rows
        if row.participant_id is not None and row.status != "skipped_conflict"
    )
    if eligible_ids and st.checkbox(
        "Generate resume links (optional separate action)",
        key=f"{_PARTICIPANT_IMPORT_PREFIX}resume_option",
    ):
        st.warning(
            "Plaintext links are shown once. They may not be usable until the session is open."
        )
        confirmed = st.checkbox(
            "Confirm resume-link generation",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}resume_confirm",
        )
        if st.button(
            "Generate resume links",
            disabled=not confirmed,
            key=f"{_PARTICIPANT_IMPORT_PREFIX}resume_generate",
        ):
            try:
                generated_credentials = context.container.participant_imports.generate_resume_links.execute(
                    GenerateImportedResumeLinksCommand(
                        session_id=scope.session_id,
                        participant_ids=eligible_ids,
                        actor_id=context.principal.subject or "",
                        actor_roles=context.principal.roles,
                        confirmed=confirmed,
                    )
                )
            except ParticipantSubmissionImportError as error:
                st.error(str(error))
            except Exception:  # noqa: BLE001 - credentials must not reach the page.
                st.error("Resume links could not be generated safely.")
            else:
                st.session_state[_PARTICIPANT_IMPORT_CREDENTIALS_KEY] = (
                    generated_credentials
                )
                st.rerun()
    credentials_state = st.session_state.get(_PARTICIPANT_IMPORT_CREDENTIALS_KEY)
    if isinstance(credentials_state, GenerateImportedResumeLinksResult):
        credentials = credentials_state
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("participant_alias", "resume_url", "expires_at"))
        for item in credentials.credentials:
            alias = item.participant_alias
            if alias.startswith(("=", "+", "-", "@")):
                alias = "'" + alias
            writer.writerow((
                alias,
                private_resume_url(
                    context.container.settings.public_base_url,
                    session_slug=credentials.session_slug,
                    access_token=item.access_token,
                ),
                item.expires_at.isoformat(),
            ))
        st.download_button(
            "Download one-time resume links",
            data=output.getvalue().encode("utf-8"),
            file_name="participant-resume-links.csv",
            mime="text/csv",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}credentials_download",
        )
        if st.button(
            "I saved the links — clear plaintext credentials",
            key=f"{_PARTICIPANT_IMPORT_PREFIX}credentials_clear",
        ):
            st.session_state.pop(_PARTICIPANT_IMPORT_CREDENTIALS_KEY, None)
            st.rerun()
    if st.button("Clear import workflow", key=f"{_PARTICIPANT_IMPORT_PREFIX}clear"):
        _clear_participant_import_state()
        st.rerun()


def _clear_participant_import_state() -> None:
    for key in tuple(st.session_state):
        if str(key).startswith(_PARTICIPANT_IMPORT_PREFIX):
            st.session_state.pop(key, None)


def _render_sessions(context: PageContext) -> None:
    if st.session_state.get(_CREATE_DIALOG_KEY, False):
        _render_create_session_dialog(context)
    if st.session_state.get(_CONFIG_DIALOG_KEY, False):
        _render_configuration_dialog(context)
    if st.session_state.get(_ACCESS_REPLACE_DIALOG_KEY, False):
        _render_replace_participant_access_dialog(context)

    selected_session_id = st.session_state.get(_SESSION_SELECTED_KEY)
    if selected_session_id:
        detail = context.queries.get_admin_session_detail(selected_session_id)
        if detail is None:
            st.session_state.pop(_SESSION_SELECTED_KEY, None)
            st.warning(
                "That session is no longer available. Return to the catalog "
                "and select another session.",
                icon=":material/warning:",
            )
        else:
            _render_session_detail(context, detail)
            return

    header_columns = st.columns([0.7, 0.3], vertical_alignment="center")
    with header_columns[0]:
        st.subheader("Sessions", anchor=False)
        st.write(
            "Create decision sessions and monitor their operational readiness, "
            "participation, and validation state."
        )
    with header_columns[1]:
        if st.button(
            "Create session",
            icon=":material/add:",
            type="primary",
            width="stretch",
            key="sessions:create",
        ):
            _begin_session_creation()

    filter_columns = st.columns([0.5, 0.25, 0.25])
    with filter_columns[0]:
        search = st.text_input(
            "Search sessions",
            placeholder="Title or public slug",
            icon=":material/search:",
            key="sessions:search",
        )
    with filter_columns[1]:
        status = st.selectbox(
            "Operational status",
            options=(None, *SessionStatus),
            format_func=lambda value: (
                "All statuses"
                if value is None
                else value.value.replace("_", " ").title()
            ),
            key="sessions:status",
        )
    scenario_options = context.queries.list_session_scenarios()
    scenario_by_key = {item.scenario_key: item for item in scenario_options}
    with filter_columns[2]:
        scenario_key = st.selectbox(
            "Scenario",
            options=(None, *scenario_by_key),
            format_func=lambda value: (
                "All scenarios" if value is None else scenario_by_key[value].title
            ),
            key="sessions:scenario",
        )

    fingerprint = (search.strip(), status, scenario_key)
    if st.session_state.get(_SESSION_FILTER_KEY) != fingerprint:
        st.session_state[_SESSION_FILTER_KEY] = fingerprint
        st.session_state[_SESSION_PAGE_KEY] = 1

    metrics = context.queries.get_session_catalog_metrics(
        search=search,
        status=status,
        scenario_key=scenario_key,
    )
    metric_columns = st.columns(3)
    metric_columns[0].metric("Sessions", metrics.total_count)
    metric_columns[1].metric("Open", metrics.open_count)
    metric_columns[2].metric("Needs attention", metrics.attention_count)
    style_metric_cards(
        border_left_color=st.get_option("theme.primaryColor") or "#C4932A",
        border_radius_px=8,
        box_shadow=False,
    )

    requested_page = max(1, int(st.session_state.get(_SESSION_PAGE_KEY, 1)))
    result = context.queries.list_admin_sessions(
        search=search,
        status=status,
        scenario_key=scenario_key,
        page=requested_page,
        page_size=_PAGE_SIZE,
    )
    if requested_page > max(result.page_count, 1):
        st.session_state[_SESSION_PAGE_KEY] = max(result.page_count, 1)
        st.rerun()
    if not result.items:
        filtered = bool(search.strip() or status is not None or scenario_key)
        render_empty_state(
            "No matching sessions" if filtered else "No sessions yet",
            (
                "Adjust the session filters to see other records."
                if filtered
                else "Create a draft from a ready scenario snapshot to begin."
            ),
            icon=":material/event_note:",
        )
        return

    st.caption(
        f"{result.total} session{'s' if result.total != 1 else ''} · "
        "Select a row to open its administrative workspace."
    )
    catalog_key = sha256(repr((fingerprint, result.page)).encode()).hexdigest()[:12]
    event = st.dataframe(
        [_session_table_row(context, item) for item in result.items],
        column_order=(
            "Session",
            "Status",
            "Participation",
            "Validation / next step",
            "Schedule",
        ),
        column_config={
            "Session": st.column_config.TextColumn(width="large"),
            "Status": st.column_config.TextColumn(width="small"),
            "Participation": st.column_config.TextColumn(width="medium"),
            "Validation / next step": st.column_config.TextColumn(width="large"),
            "Schedule": st.column_config.TextColumn(width="medium"),
        },
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"sessions:catalog:{catalog_key}",
    )
    selected_rows = getattr(getattr(event, "selection", None), "rows", ())
    if selected_rows:
        selected_index = int(selected_rows[0])
        if 0 <= selected_index < len(result.items):
            st.session_state[_SESSION_SELECTED_KEY] = result.items[
                selected_index
            ].session_id
            st.rerun()

    if result.page_count > 1:
        pagination_key = sha256(repr(fingerprint).encode()).hexdigest()[:12]
        selected_page = pagination(
            result.page_count,
            default=result.page,
            key=f"sessions:pagination:{pagination_key}",
            width="stretch",
        )
        if selected_page != result.page:
            st.session_state[_SESSION_PAGE_KEY] = selected_page
            st.rerun()


def _session_table_row(
    context: PageContext,
    item: AdminSessionSummary,
) -> dict[str, str]:
    configuration = (
        "configuration not active"
        if item.active_configuration_version is None
        else f"configuration v{item.active_configuration_version}"
    )
    return {
        "Session": (
            f"{item.title}\n{item.public_slug} · {item.scenario_title} "
            f"{item.scenario_version} · {configuration}"
        ),
        "Status": item.status.value.replace("_", " ").title(),
        "Participation": (
            f"{item.participant_count} enrolled · "
            f"{item.submitted_participant_count} submitted"
        ),
        "Validation / next step": _session_next_step(item),
        "Schedule": _session_schedule(context, item),
    }


def _session_next_step(item: AdminSessionSummary) -> str:
    if item.scenario_status != ScenarioSnapshotStatus.READY:
        return "Pinned scenario snapshot needs attention"
    if item.status == SessionStatus.PAUSED:
        return "Moderator action required"
    if item.validation_attention_count:
        return (
            f"{item.validation_attention_count} submission"
            f"{'s' if item.validation_attention_count != 1 else ''} need review"
        )
    if item.active_configuration_version is None and item.status in {
        SessionStatus.DRAFT,
        SessionStatus.SCHEDULED,
    }:
        return "Add and activate a configuration"
    if item.status == SessionStatus.CLOSED:
        return "Ready for processing"
    if item.status == SessionStatus.OPEN:
        return "Accepting responses"
    return "No immediate action"


def _session_schedule(context: PageContext, item: AdminSessionSummary) -> str:
    timezone_name = context.container.settings.app_timezone
    if item.status == SessionStatus.CLOSED and item.closed_at is not None:
        return "Closed " + format_datetime(item.closed_at, timezone_name=timezone_name)
    if item.status == SessionStatus.PAUSED and item.paused_at is not None:
        return "Paused " + format_datetime(item.paused_at, timezone_name=timezone_name)
    if item.closes_at is not None:
        return "Closes " + format_datetime(item.closes_at, timezone_name=timezone_name)
    if item.opens_at is not None:
        return "Opens " + format_datetime(item.opens_at, timezone_name=timezone_name)
    return "No schedule"


def _render_session_detail(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    summary = detail.summary
    if st.button(
        "All sessions",
        icon=":material/arrow_back:",
        key=f"session_detail:back:{summary.session_id}",
    ):
        st.session_state.pop(_SESSION_SELECTED_KEY, None)
        st.rerun()

    with st.container(border=True, height="stretch", vertical_alignment="distribute"):
        header_columns = st.columns([0.68, 0.32], vertical_alignment="center")
        with header_columns[0]:
            st.caption(
                f"{summary.status.value.upper()} SESSION · {summary.public_slug}"
            )
            st.subheader(summary.title, anchor=False)
            st.write(summary.description or "No public description has been added.")
        with header_columns[1]:
            _render_session_lifecycle_actions(context, detail)

        metadata = st.columns(4)
        metadata[0].markdown(
            f"**Scenario**  \n{summary.scenario_title} · {summary.scenario_version}"
        )
        metadata[1].markdown(
            "**Configuration**  \n"
            + (
                "Not active"
                if summary.active_configuration_version is None
                else f"Version {summary.active_configuration_version} active"
            )
        )
        metadata[2].markdown(
            "**Access**  \n"
            f"{detail.discoverability.value.title()} · "
            f"{detail.enrollment_mode.value.replace('_', ' ')}"
        )
        metadata[3].markdown(
            "**Closes**  \n"
            + format_datetime(
                summary.closes_at,
                timezone_name=context.container.settings.app_timezone,
                empty="Not scheduled",
            )
        )

        (
            overview,
            configuration,
            invitations,
            participants,
            submissions,
            validation,
            audit,
        ) = st.tabs(
            (
                "Overview",
                "Configuration",
                "Invitations",
                f"Participants ({detail.participant_total})",
                f"Submissions ({detail.submission_total})",
                "Validation queue",
                "Audit",
            )
        )
        with overview:
            _render_session_overview(detail)
        with configuration:
            _render_session_configuration(context, detail)
        with invitations:
            _render_session_invitations(context, detail)
        with participants:
            _render_session_participants(context, detail)
        with submissions:
            _render_session_submissions(context, detail)
        with validation:
            _render_validation_queue(context, detail)
        with audit:
            _render_session_audit(detail)


def _render_session_lifecycle_actions(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    summary = detail.summary
    actor_id = context.principal.subject
    if actor_id is None:
        st.error("Your administrator session has expired.", icon=":material/error:")
        return
    now = datetime.now(UTC)
    if summary.status == SessionStatus.DRAFT:
        future_open = summary.opens_at is not None and summary.opens_at > now
        if future_open:
            if st.button(
                "Schedule session",
                icon=":material/schedule:",
                type="primary",
                width="stretch",
                key=f"session_detail:schedule:{summary.session_id}",
            ):
                _execute_transition(
                    context,
                    summary.session_id,
                    SessionTransition.SCHEDULE,
                    actor_id,
                    success_message="Session scheduled.",
                )
        else:
            _render_open_action(context, detail, actor_id, now=now)
        _render_cancel_action(context, detail, actor_id)
    elif summary.status == SessionStatus.SCHEDULED:
        _render_open_action(context, detail, actor_id, now=now)
        _render_cancel_action(context, detail, actor_id)
    elif summary.status == SessionStatus.OPEN:
        if st.button(
            "Pause session",
            icon=":material/pause_circle:",
            width="stretch",
            key=f"session_detail:pause:{summary.session_id}",
        ):
            _execute_transition(
                context,
                summary.session_id,
                SessionTransition.PAUSE,
                actor_id,
                success_message="Session paused.",
            )
        _render_close_action(context, detail, actor_id)
        _render_cancel_action(context, detail, actor_id)
    elif summary.status == SessionStatus.PAUSED:
        if st.button(
            "Resume session",
            icon=":material/play_circle:",
            type="primary",
            width="stretch",
            key=f"session_detail:resume:{summary.session_id}",
        ):
            _execute_transition(
                context,
                summary.session_id,
                SessionTransition.RESUME,
                actor_id,
                success_message="Session resumed.",
            )
        _render_close_action(context, detail, actor_id)
        _render_cancel_action(context, detail, actor_id)
    elif summary.status in {SessionStatus.CLOSED, SessionStatus.CANCELED}:
        _render_archive_action(context, detail, actor_id)
    else:
        render_status(summary.status)


def _render_open_action(
    context: PageContext,
    detail: AdminSessionDetail,
    actor_id: str,
    *,
    now: datetime,
) -> None:
    summary = detail.summary
    before_schedule = summary.opens_at is not None and summary.opens_at > now
    disabled = summary.active_configuration_version is None or before_schedule
    if summary.active_configuration_version is None:
        help_text = "Activate an immutable configuration before opening."
    elif before_schedule:
        help_text = "The configured opening time has not arrived."
    else:
        help_text = None
    if st.button(
        "Open session",
        icon=":material/event_available:",
        type="primary",
        disabled=disabled,
        help=help_text,
        width="stretch",
        key=f"session_detail:open:{summary.session_id}",
    ):
        try:
            context.container.sessions.open.execute(
                OpenSessionCommand(
                    session_id=summary.session_id,
                    actor_id=actor_id,
                )
            )
        except OpenSessionError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.success("Session opened.", icon=":material/check_circle:")
            st.rerun()


def _render_close_action(
    context: PageContext,
    detail: AdminSessionDetail,
    actor_id: str,
) -> None:
    summary = detail.summary
    with st.popover(
        "Close session",
        icon=":material/lock:",
        width="stretch",
    ):
        st.warning(
            "Closing stops new submissions. The session can only be archived "
            "afterward.",
            icon=":material/warning:",
        )
        reason = st.text_area(
            "Reason",
            placeholder="Optional operational context for the audit log",
            key=f"session_detail:close_reason:{summary.session_id}",
        )
        confirmed = st.checkbox(
            f"Close {summary.title}",
            key=f"session_detail:close_confirm:{summary.session_id}",
        )
        if st.button(
            "Confirm close",
            icon=":material/lock:",
            type="primary",
            disabled=not confirmed,
            width="stretch",
            key=f"session_detail:close:{summary.session_id}",
        ):
            try:
                context.container.sessions.close.execute(
                    CloseSessionCommand(
                        session_id=summary.session_id,
                        actor_id=actor_id,
                        reason_code="manual_close",
                        reason_text=_optional_text(reason),
                    )
                )
            except CloseSessionError as error:
                st.error(str(error), icon=":material/error:")
            else:
                st.success("Session closed.", icon=":material/check_circle:")
                st.rerun()


def _render_cancel_action(
    context: PageContext,
    detail: AdminSessionDetail,
    actor_id: str,
) -> None:
    summary = detail.summary
    with st.popover(
        "Cancel session",
        icon=":material/cancel:",
        width="stretch",
    ):
        reason = st.text_area(
            "Cancellation reason",
            placeholder="Explain why this session is being canceled",
            key=f"session_detail:cancel_reason:{summary.session_id}",
        )
        confirmed = st.checkbox(
            f"Cancel {summary.title}",
            key=f"session_detail:cancel_confirm:{summary.session_id}",
        )
        if st.button(
            "Confirm cancellation",
            icon=":material/cancel:",
            disabled=not confirmed,
            width="stretch",
            key=f"session_detail:cancel:{summary.session_id}",
        ):
            _execute_transition(
                context,
                summary.session_id,
                SessionTransition.CANCEL,
                actor_id,
                reason_code="manual_cancel",
                reason_text=_optional_text(reason),
                success_message="Session canceled.",
            )


def _render_archive_action(
    context: PageContext,
    detail: AdminSessionDetail,
    actor_id: str,
) -> None:
    summary = detail.summary
    with st.popover(
        "Archive session",
        icon=":material/archive:",
        width="stretch",
    ):
        st.write(
            "Archiving removes the session from active administration while "
            "retaining its immutable records and audit history."
        )
        confirmed = st.checkbox(
            f"Archive {summary.title}",
            key=f"session_detail:archive_confirm:{summary.session_id}",
        )
        if st.button(
            "Confirm archive",
            icon=":material/archive:",
            disabled=not confirmed,
            width="stretch",
            key=f"session_detail:archive:{summary.session_id}",
        ):
            _execute_transition(
                context,
                summary.session_id,
                SessionTransition.ARCHIVE,
                actor_id,
                reason_code="manual_archive",
                success_message="Session archived.",
            )


def _execute_transition(
    context: PageContext,
    session_id: str,
    transition: SessionTransition,
    actor_id: str,
    *,
    reason_code: str | None = None,
    reason_text: str | None = None,
    success_message: str,
) -> None:
    try:
        context.container.sessions.transition.execute(
            TransitionSessionCommand(
                session_id=session_id,
                transition=transition,
                actor_id=actor_id,
                reason_code=reason_code,
                reason_text=reason_text,
            )
        )
    except TransitionSessionError as error:
        st.error(str(error), icon=":material/error:")
    else:
        st.success(success_message, icon=":material/check_circle:")
        st.rerun()


def _render_session_overview(detail: AdminSessionDetail) -> None:
    columns = st.columns([0.68, 0.32])
    with columns[0]:
        st.markdown("#### Session readiness")
        readiness = (
            (
                detail.summary.scenario_status == ScenarioSnapshotStatus.READY,
                "Ready scenario snapshot is pinned",
            ),
            (
                detail.configuration is not None,
                "An immutable configuration is active",
            ),
            (
                bool(detail.group_progress)
                and sum(item.allocation_units for item in detail.group_progress)
                == 10_000,
                "Active stakeholder allocations total 100%",
            ),
            (True, "Enrollment and access policy are configured"),
        )
        for ready, label in readiness:
            st.markdown(
                f"{':material/check_circle:' if ready else ':material/pending:'} "
                f"{label}"
            )

        st.markdown("#### Participation progress")
        if detail.group_progress:
            st.dataframe(
                [
                    {
                        "Group": item.group_name,
                        "Allocation": item.allocation_units / 100,
                        "Enrolled": item.enrolled_count,
                        "Submitted": item.submitted_count,
                        "Valid": item.valid_count,
                    }
                    for item in detail.group_progress
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "Allocation": st.column_config.NumberColumn(format="%.2f%%")
                },
            )
        else:
            render_empty_state(
                "No active stakeholder groups",
                "Add and activate a session configuration to define groups.",
                icon=":material/groups:",
            )
    with columns[1]:
        st.markdown("#### Needs attention")
        attention = {
            "Validation review": detail.summary.validation_attention_count,
            "Participants not submitted": max(
                detail.summary.participant_count
                - detail.summary.submitted_participant_count,
                0,
            ),
        }
        for label, value in attention.items():
            st.metric(label, value)
        if detail.admin_notes:
            st.markdown("#### Administrator notes")
            st.write(detail.admin_notes)


def _render_session_configuration(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    configuration = detail.configuration
    editable = detail.summary.status in {
        SessionStatus.DRAFT,
        SessionStatus.SCHEDULED,
    }
    heading_columns = st.columns([0.7, 0.3], vertical_alignment="center")
    with heading_columns[0]:
        st.markdown("#### Immutable configuration versions")
        st.caption("Create a complete version, review it, then activate it explicitly.")
    with heading_columns[1]:
        if st.button(
            "New configuration",
            icon=":material/add:",
            type="primary" if configuration is None else "secondary",
            disabled=not editable,
            help=(
                None if editable else "Configurations are locked after a session opens."
            ),
            width="stretch",
            key=f"session_config:new:{detail.summary.session_id}",
        ):
            _begin_configuration_creation(detail.summary.session_id)

    if configuration is None:
        render_empty_state(
            "No active configuration",
            "This draft has a pinned scenario, but cannot open until a complete "
            "response and calculation configuration is added and activated.",
            icon=":material/tune:",
        )
    else:
        st.markdown(
            f"##### Active configuration · version {configuration.version_number}"
        )
        st.caption(
            "Activated "
            + format_datetime(
                configuration.activated_at,
                timezone_name=context.container.settings.app_timezone,
            )
            + f" by {configuration.activated_by or 'Unknown actor'}"
        )
        rows = (
            ("Response method", configuration.response_format.value),
            ("Response target", configuration.response_target_type.value),
            ("Scale", configuration.scale_name),
            (
                "Minimum valid submissions",
                configuration.minimum_valid_submissions,
            ),
            (
                "Resubmissions",
                (
                    f"Allowed · maximum {configuration.max_submissions_per_participant}"
                    if configuration.allow_resubmissions
                    else "Not allowed"
                ),
            ),
            ("Missing group policy", configuration.missing_group_policy.value),
            (
                "Consistency threshold",
                configuration.consistency_threshold or "None",
            ),
            ("Stakeholder groups", configuration.stakeholder_group_count),
            ("Questions", configuration.question_count),
        )
        st.dataframe(
            [
                {"Setting": label, "Value": str(value).replace("_", " ")}
                for label, value in rows
            ],
            hide_index=True,
            width="stretch",
        )
        with st.expander("Configuration identity"):
            st.code(configuration.configuration_version_id, language=None)
            st.code(configuration.config_hash, language=None)

    st.markdown("##### Version history")
    if not detail.configurations:
        st.caption("No configuration versions have been created.")
        return
    st.dataframe(
        [
            {
                "Version": item.version_number,
                "State": (
                    "Active"
                    if item.is_active
                    else (
                        "Previously activated"
                        if item.activated_at is not None
                        else "Awaiting activation"
                    )
                ),
                "Response": item.response_format.value.replace("_", " ").title(),
                "Target": item.response_target_type.value.title(),
                "Questions": item.question_count,
                "Groups": item.stakeholder_group_count,
                "Created": item.created_at,
                "Created by": item.created_by,
            }
            for item in detail.configurations
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "Created": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a")
        },
    )
    activation_candidates = tuple(
        item
        for item in detail.configurations
        if not item.is_active and item.activated_at is None
    )
    if editable and activation_candidates:
        candidate_by_id = {
            item.configuration_version_id: item for item in activation_candidates
        }
        with st.popover(
            "Activate a reviewed version",
            icon=":material/check_circle:",
            width="stretch",
        ):
            selected_id = st.selectbox(
                "Configuration version",
                options=tuple(candidate_by_id),
                format_func=lambda value: (
                    f"Version {candidate_by_id[value].version_number} · "
                    f"{candidate_by_id[value].question_count} questions"
                ),
                key=f"session_config:activate_choice:{detail.summary.session_id}",
            )
            st.warning(
                "Activation changes which immutable contract participants will "
                "receive. Previously activated versions remain in history.",
                icon=":material/warning:",
            )
            confirmed = st.checkbox(
                "I reviewed this version and want to make it active.",
                key=f"session_config:activate_confirm:{detail.summary.session_id}",
            )
            if st.button(
                "Activate configuration",
                type="primary",
                icon=":material/check_circle:",
                disabled=not confirmed,
                width="stretch",
                key=f"session_config:activate:{detail.summary.session_id}",
            ):
                _activate_configuration(context, detail, selected_id)


def _begin_configuration_creation(session_id: str) -> None:
    generation = int(st.session_state.get(_CONFIG_GENERATION_KEY, 0)) + 1
    st.session_state[_CONFIG_GENERATION_KEY] = generation
    st.session_state["session_config:session_id"] = session_id
    st.session_state[_CONFIG_DIALOG_KEY] = True
    st.rerun()


def _on_configuration_dialog_dismissed() -> None:
    st.session_state[_CONFIG_DIALOG_KEY] = False


@st.dialog(
    "Create configuration version",
    width="large",
    on_dismiss=_on_configuration_dialog_dismissed,
)
def _render_configuration_dialog(context: PageContext) -> None:
    session_id = st.session_state.get("session_config:session_id")
    if not isinstance(session_id, str):
        st.error("The configuration workflow could not be initialized.")
        return
    detail = context.queries.get_admin_session_detail(session_id)
    if detail is None:
        st.error("The selected session is no longer available.")
        return
    if detail.summary.status not in {
        SessionStatus.DRAFT,
        SessionStatus.SCHEDULED,
    }:
        st.error("Configurations are locked after a session opens.")
        return
    scenario = context.queries.get_scenario_snapshot_detail(
        detail.summary.scenario_snapshot_id
    )
    if scenario is None:
        st.error("The pinned scenario snapshot could not be loaded.")
        return

    generation = int(st.session_state.get(_CONFIG_GENERATION_KEY, 0))
    prefix = f"session_config:{generation}"
    step_key = f"{prefix}:step"
    current_step = max(0, min(int(st.session_state.get(step_key, 0)), 3))
    st.session_state[step_key] = current_step
    steps(
        ("Response", "Stakeholders", "Rules", "Review"),
        current=current_step,
        icons=(
            ":material/quiz:",
            ":material/groups:",
            ":material/rule:",
            ":material/fact_check:",
        ),
        horizontal=True,
        key=f"{prefix}:steps:{current_step}",
    )

    if current_step == 0:
        _render_configuration_response_step(context, scenario, prefix, step_key)
    elif current_step == 1:
        _render_configuration_groups_step(scenario, prefix, step_key)
    elif current_step == 2:
        _render_configuration_rules_step(prefix, step_key)
    else:
        _render_configuration_review_step(
            context,
            detail,
            scenario,
            prefix,
            step_key,
        )


def _render_configuration_response_step(
    context: PageContext,
    scenario: ScenarioSnapshotDetail,
    prefix: str,
    step_key: str,
) -> None:
    st.markdown("#### Response and calculation contract")
    st.write(
        "Choose how participants answer and pin versioned algorithm "
        "implementations for weighting and ranking."
    )
    presets = {
        "Rate criteria": (
            ResponseFormat.DIRECT_RATING,
            ResponseTargetType.CRITERION,
        ),
        "Compare criteria in pairs": (
            ResponseFormat.PAIRWISE,
            ResponseTargetType.CRITERION,
        ),
    }
    weighting = context.queries.list_active_algorithm_implementations(
        role=AlgorithmRole.WEIGHTING
    )
    ranking = context.queries.list_active_algorithm_implementations(
        role=AlgorithmRole.RANKING
    )
    weighting_by_id = {item.algorithm_implementation_id: item for item in weighting}
    ranking_by_id = {item.algorithm_implementation_id: item for item in ranking}
    saved = st.session_state.get(f"{prefix}:response_draft")
    if not isinstance(saved, _ConfigurationResponseDraft):
        saved = None
    preset_options = tuple(presets)
    scenario_default_format = getattr(scenario, "default_response_format", None)
    scenario_default_preset = next(
        (
            label
            for label, values in presets.items()
            if values[0] == scenario_default_format
        ),
        preset_options[0],
    )
    saved_preset = next(
        (
            label
            for label, values in presets.items()
            if saved is not None
            and values == (saved.response_format, saved.target_type)
        ),
        scenario_default_preset,
    )
    default_scale_key = getattr(scenario, "default_scale_key", None)
    weighting_options = tuple(weighting_by_id)
    ranking_options = tuple(ranking_by_id)
    selected_preset = st.selectbox(
        "Participant response method",
        options=preset_options,
        index=preset_options.index(saved_preset),
        key=f"{prefix}:preset",
    )
    response_format, target_type = presets[selected_preset]
    compatible_scales = tuple(
        item
        for item in scenario.scales
        if _scale_supports_response_format(item, response_format)
        and (
            bool(getattr(item, "is_application_defined", False))
            or getattr(item, "scale_key", None) == default_scale_key
        )
    )
    compatible_scale_by_id = {item.scale_id: item for item in compatible_scales}
    scale_options = tuple(compatible_scale_by_id)
    default_scale_id = next(
        (
            item.scale_id
            for item in compatible_scales
            if getattr(item, "scale_key", None) == default_scale_key
        ),
        None,
    )
    selected_scale_id = st.selectbox(
        "Response scale",
        options=scale_options,
        index=(
            scale_options.index(saved.scale_id)
            if saved is not None and saved.scale_id in scale_options
            else (
                scale_options.index(default_scale_id)
                if default_scale_id in scale_options
                else (0 if scale_options else None)
            )
        ),
        format_func=lambda value: _configuration_scale_label(
            compatible_scale_by_id[value],
            default_scale_key=default_scale_key,
        ),
        key=f"{prefix}:scale_id:{response_format.value}",
    )
    algorithm_columns = st.columns(2)
    selected_weighting_id = algorithm_columns[0].selectbox(
        "Weighting algorithm",
        options=weighting_options,
        index=(
            weighting_options.index(saved.weighting_id)
            if saved is not None and saved.weighting_id in weighting_options
            else (0 if weighting_options else None)
        ),
        format_func=lambda value: _algorithm_label(weighting_by_id[value]),
        key=f"{prefix}:weighting_id",
    )
    selected_ranking_id = algorithm_columns[1].selectbox(
        "Ranking algorithm",
        options=ranking_options,
        index=(
            ranking_options.index(saved.ranking_id)
            if saved is not None and saved.ranking_id in ranking_options
            else (0 if ranking_options else None)
        ),
        format_func=lambda value: _algorithm_label(ranking_by_id[value]),
        key=f"{prefix}:ranking_id",
    )
    submitted = st.button(
        "Continue to stakeholders",
        icon=":material/arrow_forward:",
        type="primary",
        width="stretch",
        disabled=(not scale_options or not weighting_by_id or not ranking_by_id),
        key=f"{prefix}:response_next",
    )
    if not scale_options:
        st.error(
            "No application response scale supports the selected questioning "
            "method. Rescan the bundled scenarios to create an updated snapshot."
        )
    if not weighting_by_id or not ranking_by_id:
        st.error(
            "The algorithm registry is missing an active weighting or ranking "
            "implementation. Apply the latest database migration."
        )
    if submitted:
        if (
            not isinstance(selected_preset, str)
            or not isinstance(selected_scale_id, str)
            or not isinstance(selected_weighting_id, str)
            or not isinstance(selected_ranking_id, str)
        ):
            st.error(
                "Complete every response and algorithm selection before continuing.",
                icon=":material/error:",
            )
            return
        selected_scale = compatible_scale_by_id[selected_scale_id]
        if selected_scale.value_count < 1:
            st.error(
                "The selected response scale has no values. Choose a complete "
                "application scale.",
                icon=":material/error:",
            )
            return
        if not _scale_supports_response_format(selected_scale, response_format):
            st.error(
                "The selected scale does not support this participant response "
                "method. Choose a matching direct-rating or pairwise scale.",
                icon=":material/error:",
            )
            return
        st.session_state[f"{prefix}:response_draft"] = _ConfigurationResponseDraft(
            response_format=response_format,
            target_type=target_type,
            scale_id=selected_scale_id,
            weighting_id=selected_weighting_id,
            ranking_id=selected_ranking_id,
        )
        st.session_state[step_key] = 1
        st.rerun()


def _algorithm_label(item: Any) -> str:
    return f"{item.conceptual_method} · {item.library_name} {item.library_version}"


def _configuration_scale_label(
    item: Any,
    *,
    default_scale_key: str | None,
) -> str:
    labels: list[str] = []
    if (
        default_scale_key is not None
        and getattr(item, "scale_key", None) == default_scale_key
    ):
        labels.append("Scenario default")
    elif bool(getattr(item, "is_application_defined", False)):
        labels.append("Application")
    labels.append(str(item.name))
    labels.append(f"{item.value_count} values")
    return " · ".join(labels)


def _scale_supports_response_format(
    item: Any,
    response_format: ResponseFormat,
) -> bool:
    scale_type = str(getattr(item, "scale_type", "")).strip().lower()
    expected = {
        "pairwise": ResponseFormat.PAIRWISE,
        "pairwise_comparison": ResponseFormat.PAIRWISE,
        "direct_rating": ResponseFormat.DIRECT_RATING,
        "criterion_linguistic_rating": ResponseFormat.DIRECT_RATING,
    }.get(scale_type)
    return expected is None or response_format == expected


def _render_configuration_groups_step(
    scenario: ScenarioSnapshotDetail,
    prefix: str,
    step_key: str,
) -> None:
    st.markdown("#### Stakeholder allocations")
    st.write(
        "Define the groups used for aggregation. Active allocations must total "
        "exactly 100.00%."
    )
    stakeholder_defaults = getattr(scenario, "stakeholder_group_defaults", ())
    default_rows = (
        [
            {
                "Group key": item.group_key,
                "Name": item.name,
                "Description": item.description,
                "Allocation %": item.allocation_units / 100,
                "Required": item.required,
            }
            for item in stakeholder_defaults
        ]
        if stakeholder_defaults
        else [
            {
                "Group key": "all_participants",
                "Name": "All participants",
                "Description": "All eligible session participants.",
                "Allocation %": 100.0,
                "Required": True,
            }
        ]
    )
    if stakeholder_defaults:
        st.caption(
            "Loaded from the scenario defaults. Edit, add, or remove groups "
            "before saving this configuration version."
        )
    else:
        st.caption(
            "This scenario has no stakeholder defaults, so all eligible "
            "participants begin in one group."
        )
    rows = st.data_editor(
        st.session_state.get(f"{prefix}:groups", default_rows),
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key=f"{prefix}:groups_editor",
        column_config={
            "Group key": st.column_config.TextColumn(required=True),
            "Name": st.column_config.TextColumn(required=True),
            "Description": st.column_config.TextColumn(required=True),
            "Allocation %": st.column_config.NumberColumn(
                min_value=0.0,
                max_value=100.0,
                step=0.01,
                format="%.2f%%",
                required=True,
            ),
            "Required": st.column_config.CheckboxColumn(),
        },
    )
    navigation = st.columns(2)
    if navigation[0].button(
        "Back",
        icon=":material/arrow_back:",
        width="stretch",
        key=f"{prefix}:groups_back",
    ):
        st.session_state[step_key] = 0
        st.rerun()
    if navigation[1].button(
        "Continue to rules",
        icon=":material/arrow_forward:",
        type="primary",
        width="stretch",
        key=f"{prefix}:groups_next",
    ):
        try:
            normalized = _normalize_group_rows(rows)
        except CreateSessionConfigurationError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.session_state[f"{prefix}:groups"] = normalized
            st.session_state[step_key] = 2
            st.rerun()


def _normalize_group_rows(rows: Any) -> list[dict[str, object]]:
    records = rows.to_dict("records") if hasattr(rows, "to_dict") else list(rows)
    if not records:
        raise CreateSessionConfigurationError("Add at least one stakeholder group.")
    normalized: list[dict[str, object]] = []
    total_units = 0
    for row in records:
        try:
            percent = Decimal(str(row.get("Allocation %", "")))
            units_value = percent * 100
        except (InvalidOperation, TypeError) as error:
            raise CreateSessionConfigurationError(
                "Every stakeholder allocation must be a percentage."
            ) from error
        if units_value != units_value.to_integral_value():
            raise CreateSessionConfigurationError(
                "Stakeholder allocations support at most two decimal places."
            )
        units = int(units_value)
        item = StakeholderGroupInput(
            group_key=str(row.get("Group key", "")).strip(),
            name=str(row.get("Name", "")).strip(),
            description=str(row.get("Description", "")).strip(),
            allocation_units=units,
            required=bool(row.get("Required", False)),
        )
        total_units += units
        normalized.append(
            {
                "Group key": item.group_key,
                "Name": item.name,
                "Description": item.description,
                "Allocation %": float(percent),
                "Required": item.required,
            }
        )
    if total_units != 10_000:
        raise CreateSessionConfigurationError(
            "Stakeholder allocations must total exactly 100.00%; "
            f"got {Decimal(total_units) / 100}%."
        )
    return normalized


def _render_configuration_rules_step(prefix: str, step_key: str) -> None:
    st.markdown("#### Submission and validation rules")
    saved = st.session_state.get(f"{prefix}:rules_draft")
    if not isinstance(saved, _ConfigurationRulesDraft):
        saved = None
    policy_options = tuple(MissingGroupPolicy)
    with st.form(f"{prefix}:rules_form", border=False):
        allow_resubmissions = st.checkbox(
            "Allow resubmissions",
            value=(False if saved is None else saved.allow_resubmissions),
            key=f"{prefix}:allow_resubmissions",
        )
        max_submissions = st.number_input(
            "Maximum submissions per participant",
            min_value=1,
            value=(2 if saved is None else saved.max_submissions_per_participant),
            step=1,
            help=(
                "Used only when resubmissions are allowed. Otherwise the saved "
                "maximum is one."
            ),
            key=f"{prefix}:max_submissions",
        )
        allow_incomplete = st.checkbox(
            "Allow incomplete submissions",
            value=(False if saved is None else saved.allow_incomplete_submission),
            key=f"{prefix}:allow_incomplete",
        )
        minimum_valid = st.number_input(
            "Minimum valid submissions",
            min_value=1,
            value=(1 if saved is None else saved.minimum_valid_submissions),
            step=1,
            key=f"{prefix}:minimum_valid",
        )
        missing_group_policy = st.selectbox(
            "Missing stakeholder group policy",
            options=policy_options,
            index=(
                0 if saved is None else policy_options.index(saved.missing_group_policy)
            ),
            format_func=_enum_label,
            key=f"{prefix}:missing_group_policy",
        )
        consistency_threshold = st.number_input(
            "Consistency threshold",
            min_value=0.0,
            max_value=1.0,
            value=(0.1 if saved is None else float(saved.consistency_threshold)),
            step=0.01,
            help="Used by consistency-aware weighting methods; 0 to 1.",
            key=f"{prefix}:consistency_threshold",
        )
        st.markdown("##### Participant consent")
        consent_required = st.checkbox(
            "Require consent before questionnaire participation",
            value=(True if saved is None else saved.consent_required),
            key=f"{prefix}:consent_required",
        )
        consent_version = st.text_input(
            "Consent version",
            value=("1" if saved is None else saved.consent_version),
            help="Used only when participant consent is required.",
            key=f"{prefix}:consent_version",
        )
        consent_title = st.text_input(
            "Consent title",
            value=(
                "Research participation consent"
                if saved is None
                else saved.consent_title
            ),
            help="Used only when participant consent is required.",
            key=f"{prefix}:consent_title",
        )
        consent_statement = st.text_area(
            "Consent statement",
            value=(
                "I have read the study information, understand that participation "
                "is voluntary, and consent to the use of my questionnaire responses "
                "for this research."
                if saved is None
                else saved.consent_statement
            ),
            help="Used only when participant consent is required.",
            key=f"{prefix}:consent_statement",
        )
        navigation = st.columns(2)
        back = navigation[0].form_submit_button(
            "Back",
            icon=":material/arrow_back:",
            width="stretch",
        )
        review = navigation[1].form_submit_button(
            "Review configuration",
            icon=":material/arrow_forward:",
            type="primary",
            width="stretch",
        )
    if back:
        st.session_state[step_key] = 1
        st.rerun()
    if review:
        st.session_state[f"{prefix}:rules_draft"] = _ConfigurationRulesDraft(
            allow_resubmissions=bool(allow_resubmissions),
            max_submissions_per_participant=(
                int(max_submissions) if allow_resubmissions else 1
            ),
            allow_incomplete_submission=bool(allow_incomplete),
            minimum_valid_submissions=int(minimum_valid),
            missing_group_policy=missing_group_policy,
            consistency_threshold=Decimal(str(consistency_threshold)),
            consent_required=bool(consent_required),
            consent_version=str(consent_version).strip(),
            consent_title=str(consent_title).strip(),
            consent_statement=str(consent_statement).strip(),
        )
        st.session_state[step_key] = 3
        st.rerun()


def _render_configuration_review_step(
    context: PageContext,
    detail: AdminSessionDetail,
    scenario: ScenarioSnapshotDetail,
    prefix: str,
    step_key: str,
) -> None:
    st.markdown("#### Review immutable version")
    response_draft = st.session_state.get(f"{prefix}:response_draft")
    groups = st.session_state.get(f"{prefix}:groups")
    rules_draft = st.session_state.get(f"{prefix}:rules_draft")
    if not isinstance(response_draft, _ConfigurationResponseDraft):
        _render_incomplete_configuration_draft(
            "Response selections are incomplete or expired.",
            step_key=step_key,
            target_step=0,
            button_label="Return to Response",
            button_key=f"{prefix}:review_missing_response",
        )
        return
    if not isinstance(groups, list) or not groups:
        _render_incomplete_configuration_draft(
            "Stakeholder allocations are incomplete or expired.",
            step_key=step_key,
            target_step=1,
            button_label="Return to Stakeholders",
            button_key=f"{prefix}:review_missing_groups",
        )
        return
    if not isinstance(rules_draft, _ConfigurationRulesDraft):
        _render_incomplete_configuration_draft(
            "Submission and validation rules are incomplete or expired.",
            step_key=step_key,
            target_step=2,
            button_label="Return to Rules",
            button_key=f"{prefix}:review_missing_rules",
        )
        return
    scale = next(
        (item for item in scenario.scales if item.scale_id == response_draft.scale_id),
        None,
    )
    if scale is None:
        _render_incomplete_configuration_draft(
            "The selected response scale is no longer available.",
            step_key=step_key,
            target_step=0,
            button_label="Return to Response",
            button_key=f"{prefix}:review_invalid_scale",
        )
        return
    st.dataframe(
        [
            {
                "Setting": "Response",
                "Value": _enum_label(response_draft.response_format),
            },
            {
                "Setting": "Target",
                "Value": _enum_label(response_draft.target_type),
            },
            {"Setting": "Scale", "Value": scale.name},
            {"Setting": "Stakeholder groups", "Value": str(len(groups))},
            {
                "Setting": "Minimum valid submissions",
                "Value": str(rules_draft.minimum_valid_submissions),
            },
            {
                "Setting": "Resubmissions",
                "Value": (
                    "Allowed" if rules_draft.allow_resubmissions else "Not allowed"
                ),
            },
            {
                "Setting": "Participant consent",
                "Value": (
                    f"Required ({rules_draft.consent_version})"
                    if rules_draft.consent_required
                    else "Not required"
                ),
            },
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "This creates a new unactivated version. Activation remains a separate "
        "reviewed and audited action."
    )
    confirmed = st.checkbox(
        "Create this immutable configuration version.",
        key=f"{prefix}:confirm_create",
    )
    navigation = st.columns(2)
    if navigation[0].button(
        "Back",
        icon=":material/arrow_back:",
        width="stretch",
        key=f"{prefix}:review_back",
    ):
        st.session_state[step_key] = 2
        st.rerun()
    if navigation[1].button(
        "Create version",
        icon=":material/add_circle:",
        type="primary",
        disabled=not confirmed,
        width="stretch",
        key=f"{prefix}:create_version",
    ):
        actor_id = context.principal.subject
        if actor_id is None:
            st.error("Your administrator session has expired.")
            return
        try:
            result = context.container.sessions.create_configuration.execute(
                CreateSessionConfigurationCommand(
                    session_id=detail.summary.session_id,
                    actor_id=actor_id,
                    response_format=response_draft.response_format,
                    response_target_type=response_draft.target_type,
                    scale_id=response_draft.scale_id,
                    stakeholder_groups=tuple(
                        StakeholderGroupInput(
                            group_key=str(item["Group key"]),
                            name=str(item["Name"]),
                            description=str(item["Description"]),
                            allocation_units=int(
                                Decimal(str(item["Allocation %"])) * 100
                            ),
                            required=bool(item["Required"]),
                        )
                        for item in groups
                    ),
                    algorithms=(
                        AlgorithmSelectionInput(
                            response_draft.weighting_id,
                            AlgorithmRole.WEIGHTING,
                        ),
                        AlgorithmSelectionInput(
                            response_draft.ranking_id,
                            AlgorithmRole.RANKING,
                        ),
                    ),
                    allow_resubmissions=rules_draft.allow_resubmissions,
                    max_submissions_per_participant=(
                        rules_draft.max_submissions_per_participant
                    ),
                    allow_incomplete_submission=(
                        rules_draft.allow_incomplete_submission
                    ),
                    minimum_valid_submissions=(rules_draft.minimum_valid_submissions),
                    missing_group_policy=rules_draft.missing_group_policy,
                    consistency_threshold=rules_draft.consistency_threshold,
                    consent_required=rules_draft.consent_required,
                    consent_version=rules_draft.consent_version,
                    consent_title=rules_draft.consent_title,
                    consent_statement=rules_draft.consent_statement,
                )
            )
        except CreateSessionConfigurationError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.session_state[_CONFIG_DIALOG_KEY] = False
            st.success(
                f"Configuration version {result.version_number} created. "
                "Review and activate it before opening the session.",
                icon=":material/check_circle:",
            )
            st.rerun()


def _render_incomplete_configuration_draft(
    message: str,
    *,
    step_key: str,
    target_step: int,
    button_label: str,
    button_key: str,
) -> None:
    st.error(
        message + " Return to that step and confirm the values again.",
        icon=":material/error:",
    )
    if st.button(
        button_label,
        icon=":material/arrow_back:",
        type="primary",
        width="stretch",
        key=button_key,
    ):
        st.session_state[step_key] = target_step
        st.rerun()


def _activate_configuration(
    context: PageContext,
    detail: AdminSessionDetail,
    configuration_version_id: str,
) -> None:
    actor_id = context.principal.subject
    if actor_id is None:
        st.error("Your administrator session has expired.")
        return
    try:
        result = context.container.sessions.activate_configuration.execute(
            ActivateSessionConfigurationCommand(
                session_id=detail.summary.session_id,
                configuration_version_id=configuration_version_id,
                actor_id=actor_id,
            )
        )
    except ActivateSessionConfigurationError as error:
        st.error(str(error), icon=":material/error:")
    else:
        st.success(
            f"Configuration version {result.version_number} activated.",
            icon=":material/check_circle:",
        )
        st.rerun()


def _render_session_invitations(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    if isinstance(
        st.session_state.get(_INVITATION_RESULT_KEY),
        IssuedInvitationResult,
    ):
        _render_issued_invitation_dialog(context, detail)
    st.markdown("#### Invitation management")
    st.caption(
        "Credentials are shown only when issued. Resending securely replaces the "
        "old unused token instead of storing recoverable secrets."
    )
    actor_id = context.principal.subject
    action_columns = st.columns([0.34, 0.33, 0.33])
    with (
        action_columns[0],
        st.popover(
            "Create invitation",
            icon=":material/person_add:",
            use_container_width=True,
        ),
    ):
        _render_issue_invitation_form(context, detail, actor_id)
    with (
        action_columns[1],
        st.popover(
            "Import CSV",
            icon=":material/upload_file:",
            use_container_width=True,
        ),
    ):
        _render_invitation_import(context, detail, actor_id)
    with action_columns[2]:
        expire = st.button(
            "Expire due",
            icon=":material/event_busy:",
            use_container_width=True,
            disabled=actor_id is None,
            key=f"invitations:expire:{detail.summary.session_id}",
        )
    if expire and actor_id is not None:
        try:
            count = context.container.operations.invitations.expire.execute(
                ExpireInvitationsCommand(
                    session_id=detail.summary.session_id,
                    actor_id=actor_id,
                )
            )
        except InvitationManagementError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.success(
                f"Expired {count} due invitation{'s' if count != 1 else ''}.",
                icon=":material/check_circle:",
            )
            st.rerun()

    filters = st.columns([0.55, 0.25, 0.2])
    with filters[0]:
        search = st.text_input(
            "Search invitations",
            placeholder="Token hint, group, or participant label",
            icon=":material/search:",
            key=f"invitations:search:{detail.summary.session_id}",
        )
    with filters[1]:
        status = st.selectbox(
            "Status",
            options=(None, *InvitationStatus),
            format_func=_optional_status_label,
            key=f"invitations:status:{detail.summary.session_id}",
        )
    page = _operational_page(
        f"invitations:{detail.summary.session_id}",
        fingerprint=(search.strip(), status),
    )
    try:
        with st.spinner("Loading invitations…", show_time=False):
            result = context.queries.list_session_invitations(
                detail.summary.session_id,
                search=search,
                status=status,
                page=page,
                page_size=10,
            )
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
        return
    _normalize_operational_page(f"invitations:{detail.summary.session_id}", result)
    if not result.items:
        render_empty_state(
            "No matching invitations" if search.strip() or status else "No invitations",
            "Create an invitation or adjust the filters.",
            icon=":material/mail:",
        )
        return
    event = st.dataframe(
        [
            {
                "ID": item.invitation_id,
                "Token": item.token_hint or "—",
                "Group": item.group_name or "Participant selects",
                "Status": item.status.value.replace("_", " ").title(),
                "Sends": item.send_count,
                "Expires": item.expires_at,
                "Participant": item.participant_label or "—",
            }
            for item in result.items
        ],
        hide_index=True,
        width="stretch",
        selection_mode="single-row",
        on_select="rerun",
        key=f"invitations:table:{detail.summary.session_id}:{page}",
        column_config={
            "ID": None,
            "Expires": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a"),
        },
    )
    _render_page_picker(f"invitations:{detail.summary.session_id}", result)
    selected = _selected_rows(event)
    if selected:
        _render_invitation_actions(
            context,
            detail,
            result.items[selected[0]],
            actor_id,
        )


def _render_issue_invitation_form(
    context: PageContext,
    detail: AdminSessionDetail,
    actor_id: str | None,
) -> None:
    if detail.configuration is None:
        st.warning("Activate a configuration before issuing invitations.")
        return
    groups = {item.group_name: item.group_id for item in detail.group_progress}
    selected_group = st.selectbox(
        "Assigned group",
        options=tuple(groups),
        index=None,
        placeholder="Choose a participant group",
        key=f"invitation:create:group:{detail.summary.session_id}",
    )
    expires_date = st.date_input(
        "Expires on",
        value=(
            datetime.now(ZoneInfo(context.container.settings.app_timezone)).date()
            + timedelta(days=7)
        ),
        key=f"invitation:create:date:{detail.summary.session_id}",
    )
    expires_time = st.time_input(
        "Expiration time",
        value=time(23, 59),
        key=f"invitation:create:time:{detail.summary.session_id}",
    )
    create = st.button(
        "Issue secure invitation",
        type="primary",
        use_container_width=True,
        disabled=actor_id is None or selected_group is None,
        key=f"invitation:create:submit:{detail.summary.session_id}",
    )
    if not create or actor_id is None or selected_group is None:
        return
    expires_at = _admin_datetime(context, expires_date, expires_time)
    try:
        result = context.container.operations.invitations.issue.execute(
            IssueInvitationCommand(
                session_id=detail.summary.session_id,
                assigned_group_id=groups[selected_group],
                expires_at=expires_at,
                actor_id=actor_id,
            )
        )
    except InvitationManagementError as error:
        st.error(str(error), icon=":material/error:")
    else:
        st.session_state[_INVITATION_RESULT_KEY] = result
        st.rerun()


@st.dialog("Save the private invitation link", width="large", dismissible=False)
def _render_issued_invitation_dialog(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    result = st.session_state.get(_INVITATION_RESULT_KEY)
    if not isinstance(result, IssuedInvitationResult):
        st.error("The one-time invitation credential is no longer available.")
        return
    invitation_url = private_invitation_url(
        context.container.settings.public_base_url,
        session_slug=detail.summary.public_slug,
        invitation_token=result.token,
    )
    st.warning(
        "This private invitation is shown only once. Copy or download it before "
        "continuing; the token is not stored in recoverable form.",
        icon=":material/key:",
    )
    st.markdown("**Complete invitation URL**")
    st.code(invitation_url, language=None, wrap_lines=True)
    st.caption(
        "Expires "
        + format_datetime(
            result.expires_at,
            timezone_name=context.container.settings.app_timezone,
        )
    )
    download_lines = [
        "Poli Insight private invitation",
        "",
        invitation_url,
        "",
        f"Expires: {result.expires_at.isoformat()}",
    ]
    if result.access_code is not None:
        st.markdown("**Access code**")
        st.code(
            result.access_code,
            language=None,
        )
        download_lines.extend(("", f"Access code: {result.access_code}"))
    st.download_button(
        "Download invitation details",
        data="\n".join(download_lines) + "\n",
        file_name="poli-insight-private-invitation.txt",
        mime="text/plain",
        key=f"invitation:issued:download:{result.invitation_id}",
    )
    acknowledged = st.checkbox(
        "I have saved the complete invitation link privately.",
        key=f"invitation:issued:acknowledged:{result.invitation_id}",
    )
    if st.button(
        "Done",
        type="primary",
        disabled=not acknowledged,
        key=f"invitation:issued:done:{result.invitation_id}",
    ):
        st.session_state.pop(_INVITATION_RESULT_KEY, None)
        st.rerun()


def _render_invitation_actions(
    context: PageContext,
    detail: AdminSessionDetail,
    invitation: Any,
    actor_id: str | None,
) -> None:
    with st.container(border=True):
        st.markdown(
            f"##### Invitation {invitation.token_hint or invitation.invitation_id}"
        )
        st.write(
            f"Status: **{invitation.status.value.replace('_', ' ').title()}** · "
            f"expires {format_datetime(invitation.expires_at, timezone_name=context.container.settings.app_timezone)}"
        )
        if invitation.status in {
            InvitationStatus.REDEEMED,
            InvitationStatus.EXPIRED,
            InvitationStatus.REVOKED,
        }:
            st.caption("Terminal invitations cannot be resent or revoked.")
            return
        reason = st.text_input(
            "Reason for revocation or replacement",
            value="Replaced for secure redelivery",
            key=f"invitation:reason:{invitation.invitation_id}",
        )
        confirm = st.checkbox(
            "I understand the existing invitation link will stop working.",
            key=f"invitation:confirm:{invitation.invitation_id}",
        )
        actions = st.columns(2)
        replace_clicked = actions[0].button(
            "Resend with new link",
            type="primary",
            disabled=actor_id is None or not confirm or not reason.strip(),
            key=f"invitation:replace:{invitation.invitation_id}",
        )
        revoke_clicked = actions[1].button(
            "Revoke",
            disabled=actor_id is None or not confirm or not reason.strip(),
            key=f"invitation:revoke:{invitation.invitation_id}",
        )
    try:
        if replace_clicked and actor_id is not None:
            result = context.container.operations.invitations.replace.execute(
                ReplaceInvitationCommand(
                    invitation_id=invitation.invitation_id,
                    actor_id=actor_id,
                    reason=reason.strip(),
                )
            )
            st.session_state[_INVITATION_RESULT_KEY] = result
            st.rerun()
        if revoke_clicked and actor_id is not None:
            context.container.operations.invitations.revoke.execute(
                RevokeInvitationCommand(
                    invitation_id=invitation.invitation_id,
                    actor_id=actor_id,
                    reason=reason.strip(),
                )
            )
            st.success("Invitation revoked.")
            st.rerun()
    except InvitationManagementError as error:
        st.error(str(error), icon=":material/error:")


def _render_invitation_import(
    context: PageContext,
    detail: AdminSessionDetail,
    actor_id: str | None,
) -> None:
    st.caption(
        "CSV columns: reference, group, expires_at. Use opaque references, not names "
        "or email addresses. Expiration values require an ISO-8601 timezone."
    )
    uploaded = st.file_uploader(
        "Invitation CSV",
        type=("csv",),
        key=f"invitation:import:file:{detail.summary.session_id}",
    )
    if uploaded is not None and st.button(
        "Preview import",
        key=f"invitation:import:preview:{detail.summary.session_id}",
        use_container_width=True,
    ):
        uploaded_content = uploaded.getvalue()
        try:
            preview_result = (
                context.container.operations.invitations.preview_import.execute(
                    PreviewInvitationImportCommand(
                        session_id=detail.summary.session_id,
                        filename=uploaded.name,
                        content=uploaded_content,
                    )
                )
            )
        except InvitationImportError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.session_state[_INVITATION_IMPORT_PREVIEW_KEY] = preview_result
            st.session_state[_INVITATION_IMPORT_CONTENT_KEY] = uploaded_content

    preview = st.session_state.get(_INVITATION_IMPORT_PREVIEW_KEY)
    if not isinstance(preview, InvitationImportPreview):
        return
    metrics = st.columns(4)
    metrics[0].metric("Rows", len(preview.rows))
    metrics[1].metric("Inserts", preview.expected_inserts)
    metrics[2].metric("Duplicates", preview.duplicate_count)
    metrics[3].metric("Invalid", preview.invalid_count)
    st.dataframe(
        [
            {
                "Row": row.row_number,
                "Reference": row.reference,
                "Group": row.group,
                "Expires": row.expires_at,
                "Outcome": row.status.value.title(),
                "Issues": " ".join(row.issues) or "—",
            }
            for row in preview.rows
        ],
        hide_index=True,
        width="stretch",
    )
    confirm = st.checkbox(
        "Apply the ready rows. Invalid and duplicate rows will be skipped.",
        key=f"invitation:import:confirm:{detail.summary.session_id}",
    )
    apply_clicked = st.button(
        "Apply invitation import",
        type="primary",
        disabled=actor_id is None or not confirm or preview.expected_inserts == 0,
        key=f"invitation:import:apply:{detail.summary.session_id}",
        use_container_width=True,
    )
    if apply_clicked and actor_id is not None:
        apply_content = st.session_state.get(_INVITATION_IMPORT_CONTENT_KEY)
        if not isinstance(apply_content, bytes):
            st.error("The preview file is no longer available. Preview it again.")
            return
        try:
            result = context.container.operations.invitations.apply_import.execute(
                ApplyInvitationImportCommand(
                    session_id=detail.summary.session_id,
                    filename=preview.filename,
                    content=apply_content,
                    expected_file_hash=preview.file_hash,
                    actor_id=actor_id,
                )
            )
        except InvitationImportError as error:
            st.error(str(error), icon=":material/error:")
        else:
            st.session_state[_INVITATION_IMPORT_RESULT_KEY] = result
            st.session_state.pop(_INVITATION_IMPORT_PREVIEW_KEY, None)
            st.session_state.pop(_INVITATION_IMPORT_CONTENT_KEY, None)
            st.success(f"Imported {result.imported_count} invitations.")

    import_result = st.session_state.get(_INVITATION_IMPORT_RESULT_KEY)
    if isinstance(import_result, ApplyInvitationImportResult):
        st.download_button(
            "Download issued credentials",
            data=_invitation_credentials_csv(
                import_result,
                context.container.settings.public_base_url,
                detail.summary.public_slug,
            ),
            file_name=f"{detail.summary.public_slug}-invitation-credentials.csv",
            mime="text/csv",
            key=f"invitation:import:download:{import_result.batch_id}",
            use_container_width=True,
        )


def _render_session_participants(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    st.markdown("#### Participants")
    st.caption("Analytical labels are shown without decrypted identity data.")
    try:
        participant_metrics = context.queries.get_session_participant_metrics(
            detail.summary.session_id
        )
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
        return
    metric_columns = st.columns(4)
    metric_columns[0].metric("Enrolled", participant_metrics.total_enrolled)
    metric_columns[1].metric("Never started", participant_metrics.never_started)
    metric_columns[2].metric("Active drafts", participant_metrics.active_drafts)
    metric_columns[3].metric(
        "Completion rate",
        f"{participant_metrics.completion_rate:.0f}%",
    )
    if participant_metrics.stale_drafts:
        st.warning(
            f"{participant_metrics.stale_drafts} draft(s) have not been saved in 7 days."
        )
    if participant_metrics.resume_links_expiring_soon:
        st.warning(
            f"{participant_metrics.resume_links_expiring_soon} resume link(s) expire within 7 days."
        )
    filters = st.columns([0.4, 0.2, 0.2, 0.2])
    search = filters[0].text_input(
        "Search participants",
        placeholder="Alias or group",
        icon=":material/search:",
        key=f"participants:search:{detail.summary.session_id}",
    )
    access_status = filters[1].selectbox(
        "Access",
        options=(None, *ParticipantAccessStatus),
        format_func=_optional_status_label,
        key=f"participants:access:{detail.summary.session_id}",
    )
    progress_label = filters[2].selectbox(
        "Progress",
        options=(None, "enrolled", "joined", "started", "submitted", "completed"),
        format_func=_optional_status_label,
        key=f"participants:progress:{detail.summary.session_id}",
    )
    sort = filters[3].selectbox(
        "Sort",
        options=("newest", "oldest", "name"),
        format_func=lambda value: value.title(),
        key=f"participants:sort:{detail.summary.session_id}",
    )
    prefix = f"participants:{detail.summary.session_id}"
    page = _operational_page(
        prefix,
        fingerprint=(search.strip(), access_status, progress_label, sort),
    )
    try:
        with st.spinner("Loading participants…", show_time=False):
            result = context.queries.list_session_participants(
                detail.summary.session_id,
                search=search,
                access_status=access_status,
                progress=progress_label,
                sort=sort,
                page=page,
                page_size=10,
            )
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
        return
    _normalize_operational_page(prefix, result)
    if not result.items:
        render_empty_state(
            "No matching participants"
            if any((search, access_status, progress_label))
            else "No participants enrolled",
            "Adjust the filters or issue invitations to eligible participants.",
            icon=":material/person_off:",
        )
        return
    event = st.dataframe(
        [
            {
                "ID": item.participant_id,
                "Participant": item.display_label,
                "Group": item.group_name,
                "Access": item.access_status.value.title(),
                "Progress": item.progress,
                "Answers": item.answer_progress,
                "Attempt": item.current_attempt or "—",
                "Last activity": item.last_activity_at,
                "Resume access": item.resume_access_status.replace("_", " ").title(),
                "Enrolled": item.enrolled_at,
            }
            for item in result.items
        ],
        hide_index=True,
        width="stretch",
        selection_mode="single-row",
        on_select="rerun",
        key=f"participants:table:{detail.summary.session_id}:{page}",
        column_config={
            "ID": None,
            "Last activity": st.column_config.DatetimeColumn(
                format="MMM D, YYYY, h:mm a"
            ),
            "Enrolled": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a"),
        },
    )
    _render_page_picker(prefix, result)
    selected_rows = _selected_rows(event)
    if selected_rows:
        selected = result.items[selected_rows[0]]
        participant = context.queries.get_session_participant_detail(
            detail.summary.session_id,
            selected.participant_id,
        )
        if participant is not None:
            _render_participant_detail(context, detail, participant)


def _render_participant_detail(
    context: PageContext,
    session: AdminSessionDetail,
    participant: Any,
) -> None:
    with st.container(border=True):
        st.markdown(f"##### {participant.summary.display_label}")
        tabs = st.tabs(
            ("Overview", "Timeline", "Draft progress", "Attempts", "Resume access", "Consent")
        )
        with tabs[0]:
            st.dataframe(
                [
                    {"Field": "Participant", "Value": participant.summary.display_label},
                    {"Field": "Participant ID", "Value": participant.summary.participant_id},
                    {"Field": "Group", "Value": participant.summary.group_name},
                    {"Field": "Configuration version", "Value": participant.configuration_version},
                    {"Field": "Enrollment source", "Value": participant.invitation_id or "Direct enrollment"},
                    {"Field": "Overall progress", "Value": participant.summary.progress},
                ],
                hide_index=True,
                width="stretch",
            )
        with tabs[1]:
            timeline = (
                ("Enrolled", participant.summary.enrolled_at),
                ("Joined", participant.joined_at),
                ("Started", participant.started_at),
                ("Last draft save", None if participant.draft is None else participant.draft.last_saved_at),
                ("Submitted", participant.submitted_at),
                ("Completed", participant.completed_at),
                ("Last updated", participant.updated_at),
            )
            st.dataframe(
                [{"Milestone": label, "Time": value} for label, value in timeline],
                hide_index=True,
                width="stretch",
                column_config={"Time": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a")},
            )
        with tabs[2]:
            if participant.draft is None:
                st.info("Enrolled but never saved: no draft exists for this participant.")
            else:
                draft = participant.draft
                st.progress(
                    draft.completion_percentage / 100,
                    text=(
                        f"{draft.answered_count} of {draft.required_answer_count} required "
                        f"answers ({draft.completion_percentage:.0f}%)"
                    ),
                )
                st.dataframe(
                    [{
                        "Draft ID": draft.submission_id,
                        "Attempt": draft.attempt_number,
                        "Last saved": draft.last_saved_at,
                    }],
                    hide_index=True,
                    width="stretch",
                )
        with tabs[3]:
            if not participant.attempts:
                st.info("No submission attempts exist.")
            else:
                st.dataframe(
                    [{
                        "Attempt": item.attempt_number,
                        "Status": item.status.value.replace("_", " ").title(),
                        "Submitted": item.submitted_at,
                        "Validation": _validation_label(item.validation_status),
                        "Review": item.review_status.value.replace("_", " ").title(),
                        "Predecessor": item.previous_submission_id or "—",
                    } for item in participant.attempts],
                    hide_index=True,
                    width="stretch",
                )
        with tabs[4]:
            one_time = st.session_state.get(_NEW_RESUME_LINK_KEY)
            if (
                isinstance(one_time, _OneTimeResumeLink)
                and one_time.participant_id == participant.summary.participant_id
            ):
                st.success("New private resume link generated. This is the only display.")
                st.code(one_time.resume_url, language=None, wrap_lines=True)
                st.download_button(
                    "Download new link",
                    data=(f"{one_time.resume_url}\nExpires: {one_time.expires_at.isoformat()}\n"),
                    file_name="poli-insight-replacement-resume-link.txt",
                    mime="text/plain",
                    key=f"participant_access:download:{participant.summary.participant_id}",
                )
                if st.button(
                    "I saved the new link",
                    key=f"participant_access:clear:{participant.summary.participant_id}",
                ):
                    st.session_state.pop(_NEW_RESUME_LINK_KEY, None)
                    st.rerun()
            access = participant.access
            if access is None:
                st.warning("No access grant exists. Replacement is unavailable.")
            else:
                remaining = access.expires_at - datetime.now(tz=UTC)
                if access.status != "active":
                    st.warning(f"Resume access is {access.status}.")
                elif remaining <= timedelta(days=3):
                    st.warning("Resume access expires soon.")
                st.dataframe(
                    [{
                        "Status": access.status.replace("_", " ").title(),
                        "Issued": access.issued_at,
                        "Expires": access.expires_at,
                        "Last used": access.last_used_at,
                        "Time remaining": str(max(remaining, timedelta(0))).split(".")[0],
                        "Replacement exists": "Yes" if access.has_replacement else "No",
                    }],
                    hide_index=True,
                    width="stretch",
                )
                if st.button(
                    "Generate replacement resume link",
                    disabled=access.status != "active",
                    key=f"participant_access:begin:{participant.summary.participant_id}",
                ):
                    st.session_state[_ACCESS_REPLACE_DIALOG_KEY] = {
                        "session_id": session.summary.session_id,
                        "public_slug": session.summary.public_slug,
                        "participant_id": participant.summary.participant_id,
                        "participant_label": participant.summary.display_label,
                    }
                    st.rerun()
        with tabs[5]:
            consent = participant.consent
            if consent.required and not consent.completed:
                st.warning("Required consent has not been completed.")
            st.dataframe(
                [{
                    "Required": "Yes" if consent.required else "No",
                    "Complete": "Yes" if consent.completed else "No",
                    "Version": consent.consent_version,
                    "Accepted": consent.accepted_at,
                }],
                hide_index=True,
                width="stretch",
            )


def _dismiss_replace_participant_access_dialog() -> None:
    st.session_state.pop(_ACCESS_REPLACE_DIALOG_KEY, None)


@st.dialog(
    "Generate replacement resume link",
    width="large",
    on_dismiss=_dismiss_replace_participant_access_dialog,
)
def _render_replace_participant_access_dialog(context: PageContext) -> None:
    state = st.session_state.get(_ACCESS_REPLACE_DIALOG_KEY)
    if not isinstance(state, dict):
        st.error("The replacement workflow is no longer available.")
        return
    st.warning(
        "Generating a replacement immediately invalidates the participant's old link. "
        "Their group, configuration, draft, and submissions are unchanged."
    )
    confirmed = st.checkbox(
        f"Invalidate the old link for {state.get('participant_label', 'this participant')}",
        key="participant_access:replace:confirmed",
    )
    if st.button(
        "Generate and invalidate old link",
        type="primary",
        disabled=not confirmed,
        key="participant_access:replace:submit",
    ):
        actor_id = context.principal.subject
        if actor_id is None:
            st.error("Your administrator session has expired.")
            return
        try:
            result = context.container.operations.replace_participant_access.execute(
                ReplaceParticipantAccessGrantCommand(
                    session_id=str(state["session_id"]),
                    participant_id=str(state["participant_id"]),
                    actor_id=actor_id,
                    actor_roles=context.principal.roles,
                )
            )
        except (ReplaceParticipantAccessGrantError, KeyError):
            st.error("The resume link could not be replaced. Refresh and try again.")
            return
        st.session_state[_NEW_RESUME_LINK_KEY] = _OneTimeResumeLink(
            participant_id=result.participant_id,
            resume_url=private_resume_url(
                context.container.settings.public_base_url,
                session_slug=str(state["public_slug"]),
                access_token=result.access_token,
            ),
            expires_at=result.expires_at,
        )
        st.session_state.pop(_ACCESS_REPLACE_DIALOG_KEY, None)
        st.session_state.pop("participant_access:replace:confirmed", None)
        st.rerun()


def _render_session_submissions(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    st.markdown("#### Submissions")
    st.caption("Finalized answers remain immutable; corrections are separate attempts.")
    filters = st.columns([0.34, 0.18, 0.2, 0.18, 0.1])
    search = filters[0].text_input(
        "Search submissions",
        placeholder="Participant or group",
        icon=":material/search:",
        key=f"submissions:search:{detail.summary.session_id}",
    )
    status = filters[1].selectbox(
        "Submission",
        options=(None, *SubmissionStatus),
        format_func=_optional_status_label,
        key=f"submissions:status:{detail.summary.session_id}",
    )
    validation_status = filters[2].selectbox(
        "Validation",
        options=(None, *ValidationStatus),
        format_func=_optional_status_label,
        key=f"submissions:validation:{detail.summary.session_id}",
    )
    review_status = filters[3].selectbox(
        "Review",
        options=(None, *SubmissionReviewStatus),
        format_func=_optional_status_label,
        key=f"submissions:review:{detail.summary.session_id}",
    )
    sort = filters[4].selectbox(
        "Sort",
        options=("newest", "oldest", "participant"),
        format_func=lambda value: value.title(),
        key=f"submissions:sort:{detail.summary.session_id}",
    )
    prefix = f"submissions:{detail.summary.session_id}"
    page = _operational_page(
        prefix,
        fingerprint=(search.strip(), status, validation_status, review_status, sort),
    )
    try:
        with st.spinner("Loading submissions…", show_time=False):
            result = context.queries.list_session_submissions(
                detail.summary.session_id,
                search=search,
                status=status,
                validation_status=validation_status,
                review_status=review_status,
                sort=sort,
                page=page,
                page_size=10,
            )
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
        return
    _normalize_operational_page(prefix, result)
    if not result.items:
        render_empty_state(
            "No matching submissions"
            if any((search, status, validation_status, review_status))
            else "No submissions",
            "No response attempts match the current filters.",
            icon=":material/inbox:",
        )
        return
    event = st.dataframe(
        [
            {
                "ID": item.submission_id,
                "Participant": item.participant_label,
                "Group": item.group_name,
                "Attempt": item.attempt_number,
                "Submission": item.status.value.title(),
                "Validation": _validation_label(item.validation_status),
                "Review": item.review_status.value.replace("_", " ").title(),
                "Consistency": item.consistency_ratio or "—",
                "Submitted": item.submitted_at,
            }
            for item in result.items
        ],
        hide_index=True,
        width="stretch",
        selection_mode="single-row",
        on_select="rerun",
        key=f"submissions:table:{detail.summary.session_id}:{page}",
        column_config={
            "ID": None,
            "Submitted": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a"),
        },
    )
    _render_page_picker(prefix, result)
    selected_rows = _selected_rows(event)
    if selected_rows:
        selected = result.items[selected_rows[0]]
        submission = context.queries.get_session_submission_detail(
            detail.summary.session_id,
            selected.submission_id,
        )
        if submission is not None:
            _render_submission_detail(context, submission)


def _render_validation_queue(
    context: PageContext,
    detail: AdminSessionDetail,
) -> None:
    st.markdown("#### Validation review queue")
    st.caption(
        "Automated validation remains reproducible; operator decisions are separate, "
        "append-only records. Accepted and rejected decisions are final."
    )
    filters = st.columns([0.7, 0.3])
    search = filters[0].text_input(
        "Search queue",
        placeholder="Participant or group",
        icon=":material/search:",
        key=f"validation_queue:search:{detail.summary.session_id}",
    )
    review_status = filters[1].selectbox(
        "Review status",
        options=(None, *SubmissionReviewStatus),
        format_func=_optional_status_label,
        key=f"validation_queue:status:{detail.summary.session_id}",
    )
    prefix = f"validation_queue:{detail.summary.session_id}"
    page = _operational_page(
        prefix,
        fingerprint=(search.strip(), review_status),
    )
    try:
        with st.spinner("Loading validation queue…", show_time=False):
            result = context.queries.list_validation_queue(
                detail.summary.session_id,
                search=search,
                review_status=review_status,
                page=page,
                page_size=10,
            )
    except PageQueryError as error:
        st.error(str(error), icon=":material/error:")
        return
    _normalize_operational_page(prefix, result)
    if not result.items:
        render_empty_state(
            "No matching validation reviews"
            if search or review_status
            else "Validation queue is empty",
            "Submitted attempts will appear here for operator review.",
            icon=":material/fact_check:",
        )
        return
    event = st.dataframe(
        [
            {
                "ID": item.submission_id,
                "Participant": item.participant_label,
                "Group": item.group_name,
                "Attempt": item.attempt_number,
                "Validation": _validation_label(item.validation_status),
                "Findings": item.validation_message_count,
                "Review": item.review_status.value.replace("_", " ").title(),
                "Submitted": item.submitted_at,
            }
            for item in result.items
        ],
        hide_index=True,
        width="stretch",
        selection_mode="single-row",
        on_select="rerun",
        key=f"validation_queue:table:{detail.summary.session_id}:{page}",
        column_config={
            "ID": None,
            "Submitted": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a"),
        },
    )
    _render_page_picker(prefix, result)
    selected_rows = _selected_rows(event)
    if not selected_rows:
        return
    item = result.items[selected_rows[0]]
    submission = context.queries.get_session_submission_detail(
        detail.summary.session_id,
        item.submission_id,
    )
    if submission is not None:
        _render_submission_detail(context, submission)
        _render_review_form(context, detail, submission)


def _render_submission_detail(context: PageContext, submission: Any) -> None:
    with st.container(border=True):
        st.markdown(
            f"##### {submission.summary.participant_label} · attempt {submission.summary.attempt_number}"
        )
        tabs = st.tabs(("Overview", "Responses", "Matrix / weights", "Validation", "Integrity / audit"))
        completion = (
            100.0
            if submission.required_answer_count == 0
            else min(
                100.0,
                submission.answer_count / submission.required_answer_count * 100,
            )
        )
        response_rows = _submission_response_rows(submission)
        matrix_rows, matrix_note = _submission_matrix_rows(submission)
        with tabs[0]:
            metrics = st.columns(3)
            metrics[0].metric("Progress", f"{completion:.0f}%")
            metrics[1].metric("Answers", f"{submission.answer_count} / {submission.required_answer_count}")
            metrics[2].metric("Attempt", submission.summary.attempt_number)
            st.dataframe(
                [{
                    "Participant": submission.summary.participant_label,
                    "Group": submission.summary.group_name,
                    "Status": submission.summary.status.value.replace("_", " ").title(),
                    "Started": submission.started_at,
                    "Last saved": submission.last_saved_at,
                    "Submitted": submission.submitted_at,
                    "Validation": _validation_label(submission.summary.validation_status),
                    "Review": submission.review_status.value.replace("_", " ").title(),
                }],
                hide_index=True,
                width="stretch",
            )
            if submission.answer_count < submission.required_answer_count:
                st.warning("This attempt has incomplete required responses.")
            if submission.summary.status == SubmissionStatus.SUPERSEDED:
                st.info("This attempt has been superseded by a later submission.")
        with tabs[1]:
            if not response_rows:
                st.info("No authored responses have been saved.")
            else:
                st.caption("Authored values are shown separately from validator-derived values.")
                st.dataframe(response_rows, hide_index=True, width="stretch")
                with st.expander("Raw authored JSON"):
                    st.json(
                        [
                            {
                                "question_id": item.question_definition_id,
                                "raw_value": dict(item.raw_value),
                            }
                            for item in submission.authored_answers
                        ]
                    )
                st.download_button(
                    "Download authored responses CSV",
                    data=_rows_csv(response_rows),
                    file_name=f"submission-{submission.summary.attempt_number}-responses.csv",
                    mime="text/csv",
                    key=f"submission:responses:csv:{submission.summary.submission_id}",
                )
        with tabs[2]:
            st.caption(matrix_note)
            if matrix_rows:
                st.dataframe(matrix_rows, hide_index=True, width="stretch")
                st.download_button(
                    "Download displayed matrix / weights CSV",
                    data=_rows_csv(matrix_rows),
                    file_name=f"submission-{submission.summary.attempt_number}-matrix.csv",
                    mime="text/csv",
                    key=f"submission:matrix:csv:{submission.summary.submission_id}",
                )
                if submission.response_format == ResponseFormat.DIRECT_RATING:
                    chart_values = {
                        str(row["Criterion"]): float(str(row["Derived weight"]))
                        for row in matrix_rows
                        if row.get("Derived weight") not in {None, "—"}
                    }
                    if chart_values:
                        st.bar_chart(chart_values, horizontal=True)
            else:
                st.info("Matrix not applicable for the available authored targets.")
        with tabs[3]:
            st.dataframe(
                [{
                    "Status": _validation_label(submission.summary.validation_status),
                    "Completion ratio": submission.completion_ratio or "—",
                    "Consistency ratio": submission.summary.consistency_ratio or "—",
                    "Configured threshold": submission.consistency_threshold or "—",
                    "Validator version": submission.validator_version or "—",
                    "Completed": submission.validation_completed_at,
                }],
                hide_index=True,
                width="stretch",
            )
            if (
                submission.summary.consistency_ratio is not None
                and submission.consistency_threshold is not None
                and Decimal(submission.summary.consistency_ratio)
                > Decimal(submission.consistency_threshold)
            ):
                st.warning("Consistency ratio exceeds the configured threshold.")
            for message in submission.validation_messages:
                st.warning(message)
            if not submission.criterion_weights:
                st.info("Derived criterion weights are unavailable until validation succeeds.")
        with tabs[4]:
            st.dataframe(
                [{
                    "Submission ID": submission.summary.submission_id,
                    "Answer hash": submission.answers_hash or "Draft — not finalized",
                    "Schema version": submission.answer_schema_version or "Draft",
                    "Previous submission": submission.previous_submission_id or "—",
                    "Superseded at": submission.superseded_at,
                    "Withdrawn at": submission.withdrawn_at,
                }],
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Download safe structured JSON",
                data=_safe_submission_json(submission),
                file_name=f"submission-{submission.summary.attempt_number}.json",
                mime="application/json",
                key=f"submission:json:{submission.summary.submission_id}",
            )
            if submission.review_notes:
                st.markdown(f"**Reviewer notes:** {submission.review_notes}")


def _submission_response_rows(submission: Any) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for answer in submission.authored_answers:
        target = (
            answer.criterion_label
            or (
                f"{answer.left_criterion_label} ↔ {answer.right_criterion_label}"
                if answer.left_criterion_label and answer.right_criterion_label
                else answer.alternative_label
            )
            or "—"
        )
        authored = (
            answer.selected_scale_label
            or answer.numeric_value
            or (str(answer.rank_value) if answer.rank_value is not None else "—")
        )
        rows.append(
            {
                "Order": answer.display_order + 1,
                "Question": answer.prompt,
                "Target": target,
                "Authored response": authored,
                "Scale numeric value": answer.selected_scale_numeric_value or "—",
                "Derived normalized value": answer.normalized_crisp_value or "—",
                "Answered": answer.answered_at,
                "Response time (ms)": answer.response_time_ms or "—",
            }
        )
    return rows


def _submission_matrix_rows(
    submission: Any,
) -> tuple[list[dict[str, object]], str]:
    if submission.response_format == ResponseFormat.PAIRWISE:
        labels: list[str] = []
        for answer in submission.authored_answers:
            for label in (answer.left_criterion_label, answer.right_criterion_label):
                if label and label not in labels:
                    labels.append(label)
        values = {
            (answer.left_criterion_label, answer.right_criterion_label): (
                answer.normalized_crisp_value
            )
            for answer in submission.authored_answers
            if answer.left_criterion_label and answer.right_criterion_label
        }
        rows = []
        for left in labels:
            matrix_row: dict[str, object] = {"Criterion": left}
            for right in labels:
                matrix_row[right] = "1" if left == right else values.get((left, right), "—") or "—"
            rows.append(matrix_row)
        note = (
            "Criteria comparison matrix in frozen criterion order. Cells use validated "
            "numeric interpretations; reciprocal cells remain blank because the read "
            "model does not assert a reciprocity contract."
        )
        if not any(answer.normalized_crisp_value for answer in submission.authored_answers):
            note = "Authored pairwise responses are available, but derived matrix values are unavailable until successful validation."
        return rows, note
    if submission.response_format == ResponseFormat.DIRECT_RATING:
        weights = {item.criterion_id: item for item in submission.criterion_weights}
        rows = []
        for answer in submission.authored_answers:
            if not answer.criterion_label:
                continue
            weight = weights.get(answer.criterion_id or "")
            rows.append(
                {
                    "Criterion": answer.criterion_label,
                    "Authored scale label": answer.selected_scale_label or "—",
                    "Authored numeric value": answer.selected_scale_numeric_value or "—",
                    "Derived normalized value": answer.normalized_crisp_value or "—",
                    "Derived weight": (
                        "—" if weight is None else weight.crisp_weight or (
                            f"({weight.fuzzy_lower}, {weight.fuzzy_middle}, {weight.fuzzy_upper})"
                        )
                    ),
                }
            )
        return rows, "Criterion rating and weight table; authored and derived columns are explicitly labeled."
    return [], "This response format does not define a supported matrix for these question targets; use the authored responses table."


def _rows_csv(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _safe_submission_json(submission: Any) -> str:
    payload = {
        "schema_version": 1,
        "submission": {
            "submission_id": submission.summary.submission_id,
            "participant_id": submission.participant_id,
            "participant_label": submission.summary.participant_label,
            "group": submission.summary.group_name,
            "attempt": submission.summary.attempt_number,
            "status": submission.summary.status.value,
            "response_format": submission.response_format.value,
            "answer_hash": submission.answers_hash,
            "answer_schema_version": submission.answer_schema_version,
            "previous_submission_id": submission.previous_submission_id,
        },
        "responses": [
            {
                "question_id": item.question_definition_id,
                "display_order": item.display_order,
                "prompt": item.prompt,
                "selected_scale_label": item.selected_scale_label,
                "raw_value": dict(item.raw_value),
                "normalized_value": (
                    None if item.normalized_value is None else dict(item.normalized_value)
                ),
                "normalizer_version": item.normalizer_version,
            }
            for item in submission.authored_answers
        ],
        "validation": {
            "status": (
                None
                if submission.summary.validation_status is None
                else submission.summary.validation_status.value
            ),
            "completion_ratio": submission.completion_ratio,
            "consistency_ratio": submission.summary.consistency_ratio,
            "consistency_threshold": submission.consistency_threshold,
            "validator_version": submission.validator_version,
            "findings": list(submission.validation_messages),
            "criterion_weights": [
                {
                    "criterion_id": item.criterion_id,
                    "criterion_label": item.criterion_label,
                    "crisp_weight": item.crisp_weight,
                    "fuzzy": [item.fuzzy_lower, item.fuzzy_middle, item.fuzzy_upper],
                }
                for item in submission.criterion_weights
            ],
        },
    }
    return json.dumps(payload, indent=2, default=str)


def _render_review_form(
    context: PageContext,
    detail: AdminSessionDetail,
    submission: Any,
) -> None:
    if submission.review_status in {
        SubmissionReviewStatus.ACCEPTED,
        SubmissionReviewStatus.REJECTED,
    }:
        st.info("This review decision is final and cannot be overwritten.")
        return
    actor_id = context.principal.subject
    prefix = f"validation_review:{submission.summary.submission_id}"
    with st.container(border=True):
        decision = st.radio(
            "Decision",
            options=(
                SubmissionReviewStatus.NEEDS_REVIEW,
                SubmissionReviewStatus.ACCEPTED,
                SubmissionReviewStatus.REJECTED,
            ),
            format_func=lambda value: value.value.replace("_", " ").title(),
            horizontal=True,
            key=f"{prefix}:decision",
        )
        notes = st.text_area(
            "Reviewer notes",
            help="Required for needs-review and rejected decisions.",
            key=f"{prefix}:notes",
        )
        confirmed = st.checkbox(
            "I confirm this review decision and understand that accepted or "
            "rejected decisions are final.",
            key=f"{prefix}:confirmed",
        )
        submitted = st.button(
            "Record decision",
            type="primary",
            disabled=actor_id is None or not confirmed,
            key=f"{prefix}:submit",
        )
    if not submitted or actor_id is None:
        return
    try:
        context.container.operations.review_submission.execute(
            ReviewSubmissionCommand(
                session_id=detail.summary.session_id,
                submission_id=submission.summary.submission_id,
                status=decision,
                actor_id=actor_id,
                reviewer_notes=notes.strip() or None,
                validation_id=submission.validation_id,
            )
        )
    except ReviewSubmissionError as error:
        st.error(str(error), icon=":material/error:")
    else:
        st.success("Review decision recorded.", icon=":material/check_circle:")
        st.rerun()


def _operational_page(prefix: str, *, fingerprint: tuple[Any, ...]) -> int:
    fingerprint_key = f"{prefix}:fingerprint"
    page_key = f"{prefix}:page"
    if st.session_state.get(fingerprint_key) != fingerprint:
        st.session_state[fingerprint_key] = fingerprint
        st.session_state[page_key] = 1
    return max(1, int(st.session_state.get(page_key, 1)))


def _render_page_picker(prefix: str, result: Any) -> None:
    if result.page_count <= 1:
        st.caption(f"{result.total} result{'s' if result.total != 1 else ''}")
        return
    selected = st.number_input(
        "Page",
        min_value=1,
        max_value=result.page_count,
        value=min(result.page, result.page_count),
        step=1,
        key=f"{prefix}:page_picker",
    )
    if int(selected) != result.page:
        st.session_state[f"{prefix}:page"] = int(selected)
        st.rerun()
    st.caption(f"{result.total} results · page {result.page} of {result.page_count}")


def _normalize_operational_page(prefix: str, result: Any) -> None:
    last_page = max(result.page_count, 1)
    if result.page <= last_page:
        return
    st.session_state[f"{prefix}:page"] = last_page
    st.rerun()


def _optional_status_label(value: Any) -> str:
    if value is None:
        return "All"
    raw = value.value if hasattr(value, "value") else str(value)
    return raw.replace("_", " ").title()


def _selected_rows(event: Any) -> list[int]:
    selection = getattr(event, "selection", None)
    rows = getattr(selection, "rows", ())
    return [int(row) for row in rows]


def _validation_label(value: ValidationStatus | None) -> str:
    return "Not run" if value is None else value.value.replace("_", " ").title()


def _admin_datetime(
    context: PageContext, selected_date: date, selected_time: time
) -> datetime:
    timezone = ZoneInfo(context.container.settings.app_timezone)
    return datetime.combine(selected_date, selected_time, tzinfo=timezone).astimezone(
        UTC
    )


def _invitation_credentials_csv(
    result: ApplyInvitationImportResult,
    public_base_url: str,
    public_slug: str,
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("reference", "invitation", "access_code", "expires_at"))
    for item in result.invitations:
        writer.writerow(
            (
                item.reference,
                private_invitation_url(
                    public_base_url,
                    session_slug=public_slug,
                    invitation_token=item.invitation.token,
                ),
                item.invitation.access_code or "",
                item.invitation.expires_at.isoformat(),
            )
        )
    return output.getvalue().encode("utf-8")


def _render_session_audit(detail: AdminSessionDetail) -> None:
    st.markdown("#### Session audit")
    if not detail.audit_events:
        render_empty_state(
            "No audit events",
            "No administrative events are available for this session.",
            icon=":material/history:",
        )
        return
    st.dataframe(
        [
            {
                "Occurred": item.occurred_at,
                "Action": item.action,
                "Entity": item.entity_type,
                "Actor": item.actor_display,
                "Reason": item.reason or "—",
                "Reference": item.correlation_id,
            }
            for item in detail.audit_events
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "Occurred": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a")
        },
    )


def _render_admin_audit(context: PageContext) -> None:
    st.subheader("Administrative audit", anchor=False)
    st.write(
        "Review immutable administrative events across sessions and scenario "
        "imports. Technical payloads and sensitive identity data are excluded."
    )
    filter_columns = st.columns([0.7, 0.3])
    with filter_columns[0]:
        search = st.text_input(
            "Search audit events",
            placeholder="Session, actor, entity, or correlation reference",
            icon=":material/search:",
            key="admin_audit:search",
        )
    actions = context.queries.list_audit_actions()
    with filter_columns[1]:
        action = st.selectbox(
            "Action",
            options=(None, *actions),
            format_func=lambda value: (
                "All actions" if value is None else value.replace("_", " ").title()
            ),
            key="admin_audit:action",
        )
    fingerprint = (search.strip(), action)
    if st.session_state.get("admin_audit:fingerprint") != fingerprint:
        st.session_state["admin_audit:fingerprint"] = fingerprint
        st.session_state["admin_audit:page"] = 1
    requested_page = max(1, int(st.session_state.get("admin_audit:page", 1)))
    result = context.queries.list_admin_audit_events(
        search=search,
        action=action,
        page=requested_page,
        page_size=25,
    )
    if requested_page > max(result.page_count, 1):
        st.session_state["admin_audit:page"] = max(result.page_count, 1)
        st.rerun()
    if not result.items:
        render_empty_state(
            "No matching audit events"
            if search.strip() or action
            else "No audit events",
            (
                "Adjust the filters to inspect other administrative activity."
                if search.strip() or action
                else "Administrative actions will appear here after they occur."
            ),
            icon=":material/history:",
        )
        return
    st.caption(f"{result.total} event{'s' if result.total != 1 else ''} · newest first")
    st.dataframe(
        [
            {
                "Occurred": item.occurred_at,
                "Action": item.action,
                "Session": (
                    item.session_title or item.public_slug or "Application-wide"
                ),
                "Entity": f"{item.entity_type} · {item.entity_id}",
                "Actor": item.actor_display,
                "Reason": item.reason or "—",
                "Reference": item.correlation_id,
            }
            for item in result.items
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "Occurred": st.column_config.DatetimeColumn(format="MMM D, YYYY, h:mm a"),
            "Entity": st.column_config.TextColumn(width="large"),
            "Reference": st.column_config.TextColumn(width="large"),
        },
    )
    if result.page_count > 1:
        selected_page = pagination(
            result.page_count,
            default=result.page,
            key="admin_audit:pagination",
            width="stretch",
        )
        if selected_page != result.page:
            st.session_state["admin_audit:page"] = selected_page
            st.rerun()


def _begin_session_creation() -> None:
    generation = int(st.session_state.get(_CREATE_GENERATION_KEY, 0)) + 1
    st.session_state[_CREATE_GENERATION_KEY] = generation
    st.session_state[_CREATE_DIALOG_KEY] = True
    st.rerun()


def _on_create_session_dismissed() -> None:
    st.session_state[_CREATE_DIALOG_KEY] = False


@st.dialog(
    "Create session",
    width="large",
    on_dismiss=_on_create_session_dismissed,
)
def _render_create_session_dialog(context: PageContext) -> None:
    generation = int(st.session_state.get(_CREATE_GENERATION_KEY, 0))
    prefix = f"session_create:{generation}"
    step_key = f"{prefix}:current_step"
    current_step = max(0, min(int(st.session_state.get(step_key, 0)), 3))
    st.session_state[step_key] = current_step
    steps(
        ("Scenario", "Details", "Access", "Review"),
        current=current_step,
        icons=(
            ":material/library_books:",
            ":material/description:",
            ":material/lock_open:",
            ":material/fact_check:",
        ),
        horizontal=True,
        key=f"{prefix}:steps:{current_step}",
    )
    ready_scenarios = context.queries.list_scenario_snapshots(
        status=ScenarioSnapshotStatus.READY,
        page=1,
        page_size=100,
    )
    scenario_by_id = {item.scenario_snapshot_id: item for item in ready_scenarios.items}
    draft = _creation_draft(prefix)

    if current_step == 0:
        st.markdown("#### Choose a ready scenario snapshot")
        st.write(
            "Alternatives, criteria, scales, and source data are pinned to the "
            "new session and cannot be edited in place."
        )
        snapshot_options = tuple(scenario_by_id)
        saved_snapshot_id = draft.get("scenario_snapshot_id")
        selected_index = (
            snapshot_options.index(saved_snapshot_id)
            if saved_snapshot_id in snapshot_options
            else (0 if snapshot_options else None)
        )
        selected_snapshot_id = st.selectbox(
            "Scenario snapshot",
            options=snapshot_options,
            index=selected_index,
            format_func=lambda value: _scenario_choice_label(scenario_by_id[value]),
            placeholder="Choose a ready scenario",
            key=f"{prefix}:snapshot_id",
        )
        if not scenario_by_id:
            render_empty_state(
                "No ready scenarios",
                "Import and validate a scenario in the Scenario Library first.",
                icon=":material/library_add:",
            )
        elif selected_snapshot_id is not None:
            detail = context.queries.get_scenario_snapshot_detail(selected_snapshot_id)
            if detail is None:
                st.warning(
                    "The selected snapshot is no longer available. Choose "
                    "another ready snapshot.",
                    icon=":material/warning:",
                )
            else:
                _render_creation_scenario_preview(detail)
        st.button(
            "Continue to details",
            icon=":material/arrow_forward:",
            type="primary",
            disabled=selected_snapshot_id is None,
            width="stretch",
            key=f"{prefix}:scenario_next",
            on_click=_save_scenario_and_set_step,
            args=(prefix, step_key, 1),
        )
        return

    if current_step == 1:
        st.markdown("#### Session details")
        st.caption(
            "Changes in this step are submitted together, avoiding a modal "
            "refresh after each text field."
        )
        with st.form(f"{prefix}:details_form", border=False):
            st.text_input(
                "Session title",
                value=str(draft.get("title", "")),
                placeholder="Seattle School Closure 2026",
                max_chars=200,
                key=f"{prefix}:title",
            )
            st.text_input(
                "Public slug",
                value=str(draft.get("public_slug", "")),
                placeholder="seattle-schools-2026",
                max_chars=160,
                help="Lowercase letters, numbers, and single hyphens only.",
                key=f"{prefix}:slug",
            )
            st.text_area(
                "Public description",
                value=str(draft.get("description", "")),
                placeholder=(
                    "Briefly explain the decision participants will evaluate."
                ),
                key=f"{prefix}:description",
            )
            st.text_area(
                "Administrator notes",
                value=str(draft.get("admin_notes", "")),
                placeholder="Optional internal context; never shown publicly.",
                key=f"{prefix}:admin_notes",
            )
            navigation_columns = st.columns(2)
            navigation_columns[0].form_submit_button(
                "Back",
                icon=":material/arrow_back:",
                width="stretch",
                on_click=_save_details_and_set_step,
                args=(prefix, step_key, 0),
            )
            navigation_columns[1].form_submit_button(
                "Continue to access",
                icon=":material/arrow_forward:",
                type="primary",
                width="stretch",
                on_click=_continue_from_details,
                args=(prefix, step_key),
            )
        if st.session_state.get(f"{prefix}:details_error", False):
            st.warning(
                "Enter a title and a slug containing only lowercase letters, "
                "numbers, and single hyphens.",
                icon=":material/warning:",
            )
        return

    if current_step == 2:
        st.markdown("#### Access and schedule")
        access_columns = st.columns(2)
        with access_columns[0]:
            discoverability_options = (
                Discoverability.UNLISTED,
                Discoverability.LISTED,
            )
            saved_discoverability = draft.get(
                "discoverability", Discoverability.UNLISTED
            )
            st.selectbox(
                "Discoverability",
                options=discoverability_options,
                index=discoverability_options.index(saved_discoverability),
                format_func=_enum_label,
                key=f"{prefix}:discoverability",
            )
            enrollment_options = tuple(EnrollmentMode)
            saved_enrollment = draft.get("enrollment_mode", EnrollmentMode.OPEN)
            enrollment_mode = st.selectbox(
                "Enrollment",
                options=enrollment_options,
                index=enrollment_options.index(saved_enrollment),
                format_func=_enum_label,
                key=f"{prefix}:enrollment_mode",
            )
            access_options = (
                (AccessCodeMode.NONE, AccessCodeMode.SHARED_SESSION_CODE)
                if enrollment_mode == EnrollmentMode.OPEN
                else tuple(AccessCodeMode)
            )
            saved_access_code = draft.get("access_code_mode", AccessCodeMode.NONE)
            access_code_index = (
                access_options.index(saved_access_code)
                if saved_access_code in access_options
                else 0
            )
            access_code_mode = st.selectbox(
                "Access codes",
                options=access_options,
                index=access_code_index,
                format_func=_enum_label,
                key=f"{prefix}:access_code_mode",
            )
            if access_code_mode == AccessCodeMode.SHARED_SESSION_CODE:
                st.text_input(
                    "Shared session code",
                    value=str(draft.get("shared_access_code", "")),
                    type="password",
                    help="6 to 128 characters. Stored only as a slow hash.",
                    key=f"{prefix}:shared_access_code",
                )
        with access_columns[1]:
            identity_options = (
                "pseudonymous",
                "anonymous",
                "authenticated",
            )
            saved_identity = str(draft.get("identity_policy", "pseudonymous"))
            st.selectbox(
                "Identity policy",
                options=identity_options,
                index=(
                    identity_options.index(saved_identity)
                    if saved_identity in identity_options
                    else 0
                ),
                format_func=lambda value: value.title(),
                key=f"{prefix}:identity_policy",
            )
            selection_options = tuple(StakeholderSelectionMode)
            saved_selection = draft.get(
                "stakeholder_selection_mode",
                StakeholderSelectionMode.SELF_SELECT,
            )
            st.selectbox(
                "Stakeholder selection",
                options=selection_options,
                index=selection_options.index(saved_selection),
                format_func=_enum_label,
                key=f"{prefix}:stakeholder_selection_mode",
            )
        schedule_columns = st.columns(2)
        with schedule_columns[0]:
            has_open = st.checkbox(
                "Schedule opening",
                value=bool(draft.get("has_opens_at", False)),
                key=f"{prefix}:has_opens_at",
            )
            if has_open:
                _render_datetime_fields(
                    prefix,
                    "opens",
                    days_from_now=1,
                    draft=draft,
                )
        with schedule_columns[1]:
            has_close = st.checkbox(
                "Schedule closing",
                value=bool(draft.get("has_closes_at", False)),
                key=f"{prefix}:has_closes_at",
            )
            if has_close:
                _render_datetime_fields(
                    prefix,
                    "closes",
                    days_from_now=14,
                    draft=draft,
                )
        schedule_valid, schedule_message = _validate_schedule(context, prefix)
        if not schedule_valid:
            st.warning(schedule_message, icon=":material/warning:")
        code_valid = (
            access_code_mode != AccessCodeMode.SHARED_SESSION_CODE
            or len(str(st.session_state.get(f"{prefix}:shared_access_code", ""))) >= 6
        )
        if not code_valid:
            st.warning(
                "Enter a shared session code containing at least 6 characters.",
                icon=":material/warning:",
            )
        _wizard_navigation(
            prefix=prefix,
            step_key=step_key,
            current_step=current_step,
            step="access",
            next_label="Review draft",
            can_continue=schedule_valid and code_valid,
        )
        return

    _render_create_session_review(
        context,
        prefix,
        scenario_by_id,
        step_key=step_key,
        current_step=current_step,
    )


def _render_creation_scenario_preview(
    detail: ScenarioSnapshotDetail,
) -> None:
    summary = detail.summary
    with st.container(border=True):
        st.markdown(f"#### {summary.title}")
        st.caption(
            f"{summary.scenario_key} · version {summary.declared_version} · "
            f"{summary.domain}"
        )
        st.write(summary.summary)
        st.info(detail.policy_question, icon=":material/help:")
        preview_columns = st.columns(4)
        preview_columns[0].metric("Alternatives", summary.alternative_count)
        preview_columns[1].metric("Criteria", summary.criterion_count)
        preview_columns[2].metric("Scales", summary.scale_count)
        preview_columns[3].metric("Files", summary.file_count)

        with st.expander("Inspect scenario contents"):
            alternatives, criteria, scales = st.tabs(
                ("Alternatives", "Criteria", "Scales")
            )
            with alternatives:
                st.dataframe(
                    [
                        {
                            "Alternative": item.name,
                            "Key": item.alternative_key,
                            "Description": item.description or "—",
                        }
                        for item in detail.alternatives
                    ],
                    hide_index=True,
                    width="stretch",
                )
            with criteria:
                st.dataframe(
                    [
                        {
                            "Criterion": item.name,
                            "Key": item.criterion_key,
                            "Direction": item.direction.value.title(),
                            "Required": item.required,
                        }
                        for item in detail.criteria
                    ],
                    hide_index=True,
                    width="stretch",
                )
            with scales:
                st.dataframe(
                    [
                        {
                            "Scale": item.name,
                            "Key": item.scale_key,
                            "Type": item.scale_type,
                            "Values": item.value_count,
                        }
                        for item in detail.scales
                    ],
                    hide_index=True,
                    width="stretch",
                )


def _render_create_session_review(
    context: PageContext,
    prefix: str,
    scenario_by_id: dict[str, ScenarioSnapshotSummary],
    *,
    step_key: str,
    current_step: int,
) -> None:
    st.markdown("#### Review draft session")
    draft = _creation_draft(prefix)
    selected = _selected_wizard_scenario(prefix, scenario_by_id)
    title = str(draft.get("title", "")).strip()
    slug = str(draft.get("public_slug", "")).strip()
    discoverability = draft.get("discoverability", Discoverability.UNLISTED)
    enrollment_mode = draft.get("enrollment_mode", EnrollmentMode.OPEN)
    review_rows = (
        ("Scenario", "—" if selected is None else _scenario_choice_label(selected)),
        ("Title", title or "—"),
        ("Public slug", slug or "—"),
        ("Discoverability", _enum_label(discoverability)),
        ("Enrollment", _enum_label(enrollment_mode)),
        ("Opening", _wizard_schedule_label(context, prefix, "opens")),
        ("Closing", _wizard_schedule_label(context, prefix, "closes")),
        ("Initial status", "Draft"),
        ("Active configuration", "Not yet configured"),
    )
    st.dataframe(
        [{"Setting": label, "Value": value} for label, value in review_rows],
        hide_index=True,
        width="stretch",
    )
    confirmed = st.checkbox(
        "Create this draft. I understand it cannot open until an immutable "
        "configuration is added and activated.",
        key=f"{prefix}:confirmed",
    )
    navigation_columns = st.columns(2)
    with navigation_columns[0]:
        st.button(
            "Back",
            icon=":material/arrow_back:",
            width="stretch",
            key=f"{prefix}:review_back",
            on_click=_set_create_step,
            args=(step_key, current_step - 1),
        )
    with navigation_columns[1]:
        if (
            st.button(
                "Create draft session",
                icon=":material/add_circle:",
                type="primary",
                width="stretch",
                disabled=(
                    not confirmed
                    or selected is None
                    or not _valid_session_details(prefix)
                ),
                key=f"{prefix}:create",
            )
            and selected is not None
        ):
            _create_draft_session(context, prefix, selected)


def _create_draft_session(
    context: PageContext,
    prefix: str,
    selected: ScenarioSnapshotSummary,
) -> None:
    actor_id = context.principal.subject
    if actor_id is None:
        st.error(
            "Your administrator session has expired. Sign in again before creating.",
            icon=":material/error:",
        )
        return
    draft = _creation_draft(prefix)
    slug = str(draft.get("public_slug", "")).strip()
    if not context.queries.is_public_slug_available(slug):
        st.error(
            "That public slug is already in use. Choose another slug.",
            icon=":material/error:",
        )
        return
    opens_at = _wizard_datetime(context, prefix, "opens")
    closes_at = _wizard_datetime(context, prefix, "closes")
    try:
        result = context.container.sessions.create.execute(
            CreateSessionCommand(
                scenario_snapshot_id=selected.scenario_snapshot_id,
                public_slug=slug,
                title=str(draft.get("title", "")).strip(),
                description=_optional_text(draft.get("description")),
                admin_notes=_optional_text(draft.get("admin_notes")),
                discoverability=draft.get("discoverability", Discoverability.UNLISTED),
                enrollment_mode=draft.get("enrollment_mode", EnrollmentMode.OPEN),
                access_code_mode=draft.get("access_code_mode", AccessCodeMode.NONE),
                shared_access_code=(
                    str(draft.get("shared_access_code", ""))
                    if draft.get("access_code_mode")
                    == AccessCodeMode.SHARED_SESSION_CODE
                    else None
                ),
                identity_policy=str(draft.get("identity_policy", "pseudonymous")),
                stakeholder_selection_mode=draft.get(
                    "stakeholder_selection_mode",
                    StakeholderSelectionMode.SELF_SELECT,
                ),
                opens_at=opens_at,
                closes_at=closes_at,
                actor_id=actor_id,
            )
        )
    except CreateSessionError as error:
        st.error(str(error), icon=":material/error:")
        return
    st.session_state[_SESSION_SELECTED_KEY] = result.session_id
    st.session_state[_CREATE_DIALOG_KEY] = False
    st.session_state[_SESSION_PAGE_KEY] = 1
    st.session_state.pop(f"{prefix}:shared_access_code", None)
    st.session_state.pop(f"{prefix}:draft", None)
    st.rerun()


def _wizard_navigation(
    *,
    prefix: str,
    step_key: str,
    current_step: int,
    step: str,
    next_label: str,
    can_continue: bool = True,
) -> None:
    callback = _save_access_and_set_step if step == "access" else _set_create_step
    callback_prefix = (prefix,) if step == "access" else ()
    columns = st.columns(2)
    with columns[0]:
        st.button(
            "Back",
            icon=":material/arrow_back:",
            width="stretch",
            key=f"{prefix}:{step}_back",
            on_click=callback,
            args=(*callback_prefix, step_key, current_step - 1),
        )
    with columns[1]:
        st.button(
            next_label,
            icon=":material/arrow_forward:",
            type="primary",
            width="stretch",
            disabled=not can_continue,
            key=f"{prefix}:{step}_next",
            on_click=callback,
            args=(*callback_prefix, step_key, current_step + 1),
        )


def _set_create_step(step_key: str, step: int) -> None:
    st.session_state[step_key] = max(0, min(step, 5))


def _creation_draft(prefix: str) -> dict[str, Any]:
    draft = st.session_state.get(f"{prefix}:draft")
    return dict(draft) if isinstance(draft, dict) else {}


def _update_creation_draft(prefix: str, **values: Any) -> None:
    draft = _creation_draft(prefix)
    draft.update(values)
    st.session_state[f"{prefix}:draft"] = draft


def _save_scenario_and_set_step(
    prefix: str,
    step_key: str,
    step: int,
) -> None:
    _update_creation_draft(
        prefix,
        scenario_snapshot_id=st.session_state.get(f"{prefix}:snapshot_id"),
    )
    _set_create_step(step_key, step)


def _save_details(prefix: str) -> None:
    _update_creation_draft(
        prefix,
        title=str(st.session_state.get(f"{prefix}:title", "")).strip(),
        public_slug=str(st.session_state.get(f"{prefix}:slug", "")).strip(),
        description=str(st.session_state.get(f"{prefix}:description", "")),
        admin_notes=str(st.session_state.get(f"{prefix}:admin_notes", "")),
    )


def _save_details_and_set_step(
    prefix: str,
    step_key: str,
    step: int,
) -> None:
    _save_details(prefix)
    _set_create_step(step_key, step)


def _save_access_and_set_step(
    prefix: str,
    step_key: str,
    step: int,
) -> None:
    values: dict[str, Any] = {
        "discoverability": st.session_state.get(
            f"{prefix}:discoverability", Discoverability.UNLISTED
        ),
        "enrollment_mode": st.session_state.get(
            f"{prefix}:enrollment_mode", EnrollmentMode.OPEN
        ),
        "access_code_mode": st.session_state.get(
            f"{prefix}:access_code_mode", AccessCodeMode.NONE
        ),
        "shared_access_code": st.session_state.get(f"{prefix}:shared_access_code", ""),
        "identity_policy": st.session_state.get(
            f"{prefix}:identity_policy", "pseudonymous"
        ),
        "stakeholder_selection_mode": st.session_state.get(
            f"{prefix}:stakeholder_selection_mode",
            StakeholderSelectionMode.SELF_SELECT,
        ),
        "has_opens_at": bool(st.session_state.get(f"{prefix}:has_opens_at", False)),
        "has_closes_at": bool(st.session_state.get(f"{prefix}:has_closes_at", False)),
    }
    for field in ("opens", "closes"):
        if values[f"has_{field}_at"]:
            values[f"{field}_date"] = st.session_state.get(f"{prefix}:{field}_date")
            values[f"{field}_time"] = st.session_state.get(f"{prefix}:{field}_time")
    _update_creation_draft(prefix, **values)
    _set_create_step(step_key, step)


def _continue_from_details(prefix: str, step_key: str) -> None:
    if _valid_session_details(prefix):
        _save_details(prefix)
        st.session_state[f"{prefix}:details_error"] = False
        _set_create_step(step_key, 2)
        return
    st.session_state[f"{prefix}:details_error"] = True


def _render_datetime_fields(
    prefix: str,
    field: str,
    *,
    days_from_now: int,
    draft: dict[str, Any],
) -> None:
    default = datetime.now(tz=UTC) + timedelta(days=days_from_now)
    saved_date = draft.get(f"{field}_date", default.date())
    saved_time = draft.get(f"{field}_time", time(default.hour, default.minute))
    st.date_input(
        f"{field.title()} date",
        value=saved_date if isinstance(saved_date, date) else default.date(),
        min_value=datetime.now(tz=UTC).date(),
        key=f"{prefix}:{field}_date",
    )
    st.time_input(
        f"{field.title()} time",
        value=(
            saved_time
            if isinstance(saved_time, time)
            else time(default.hour, default.minute)
        ),
        step=900,
        key=f"{prefix}:{field}_time",
    )


def _wizard_datetime(
    context: PageContext,
    prefix: str,
    field: str,
) -> datetime | None:
    draft = _creation_draft(prefix)
    if not st.session_state.get(
        f"{prefix}:has_{field}_at",
        draft.get(f"has_{field}_at", False),
    ):
        return None
    selected_date = st.session_state.get(
        f"{prefix}:{field}_date", draft.get(f"{field}_date")
    )
    selected_time = st.session_state.get(
        f"{prefix}:{field}_time", draft.get(f"{field}_time")
    )
    if not isinstance(selected_date, date) or not isinstance(selected_time, time):
        return None
    try:
        timezone = ZoneInfo(context.container.settings.app_timezone)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.combine(selected_date, selected_time, tzinfo=timezone).astimezone(
        UTC
    )


def _validate_schedule(
    context: PageContext,
    prefix: str,
) -> tuple[bool, str]:
    opens_at = _wizard_datetime(context, prefix, "opens")
    closes_at = _wizard_datetime(context, prefix, "closes")
    if st.session_state.get(f"{prefix}:has_opens_at", False) and opens_at is None:
        return False, "Choose a complete opening date and time."
    if st.session_state.get(f"{prefix}:has_closes_at", False) and closes_at is None:
        return False, "Choose a complete closing date and time."
    if opens_at is not None and closes_at is not None and closes_at <= opens_at:
        return False, "The closing time must be later than the opening time."
    return True, ""


def _wizard_schedule_label(
    context: PageContext,
    prefix: str,
    field: str,
) -> str:
    return format_datetime(
        _wizard_datetime(context, prefix, field),
        timezone_name=context.container.settings.app_timezone,
        empty="Not scheduled",
    )


def _valid_session_details(prefix: str) -> bool:
    draft = _creation_draft(prefix)
    title = str(st.session_state.get(f"{prefix}:title", draft.get("title", ""))).strip()
    slug = str(
        st.session_state.get(f"{prefix}:slug", draft.get("public_slug", ""))
    ).strip()
    return bool(title) and _SESSION_SLUG_PATTERN.fullmatch(slug) is not None


def _selected_wizard_scenario(
    prefix: str,
    scenario_by_id: dict[str, ScenarioSnapshotSummary],
) -> ScenarioSnapshotSummary | None:
    snapshot_id = st.session_state.get(f"{prefix}:snapshot_id")
    if snapshot_id is None:
        snapshot_id = _creation_draft(prefix).get("scenario_snapshot_id")
    return scenario_by_id.get(snapshot_id) if isinstance(snapshot_id, str) else None


def _scenario_choice_label(item: ScenarioSnapshotSummary) -> str:
    return (
        f"{item.title} · {item.declared_version} · "
        f"{item.alternative_count} alternatives · {item.criterion_count} criteria"
    )


def _enum_label(value: Any) -> str:
    return value.value.replace("_", " ").title()


def _optional_text(value: Any) -> str | None:
    normalized = "" if value is None else str(value).strip()
    return normalized or None


def _render_scenario_library(context: PageContext) -> None:
    header_columns = st.columns([0.45, 0.55], vertical_alignment="center")
    with header_columns[0]:
        st.subheader("Scenario Library", anchor=False)
        st.markdown(
            "Browse the immutable, versioned source packages available to new sessions."
        )
    with header_columns[1]:
        actions = st.columns([1, 1.35, 1.05])
        with actions[0]:
            if st.button(
                "Upload ZIP",
                icon=":material/upload:",
                type="primary",
                width="stretch",
            ):
                st.session_state[_BATCH_DIALOG_OPEN_KEY] = False
                st.session_state[_IMPORT_DIALOG_OPEN_KEY] = True
        with actions[1]:
            if st.button(
                "Scan bundled scenarios",
                icon=":material/folder_open:",
                width="stretch",
            ):
                _begin_bundled_scan(context)
        with actions[2]:
            _render_template_popover(context)

    if st.session_state.get(_IMPORT_DIALOG_OPEN_KEY, False):
        _render_import_dialog(context)
    if st.session_state.get(_BATCH_DIALOG_OPEN_KEY, False):
        _render_bundled_scan_dialog(context)

    metrics = context.queries.get_scenario_library_metrics()
    metric_columns = st.columns(4)
    metric_columns[0].metric("Definitions", metrics.definition_count)
    metric_columns[1].metric("Snapshots", metrics.snapshot_count)
    metric_columns[2].metric("Ready", metrics.ready_count)
    metric_columns[3].metric("Needs attention", metrics.attention_count)
    style_metric_cards(
        border_left_color=st.get_option("theme.primaryColor") or "#C4932A",
        border_radius_px=8,
        box_shadow=False,
    )

    st.markdown("#### Catalog")
    filter_columns = st.columns([0.5, 0.25, 0.25])
    with filter_columns[0]:
        search = st.text_input(
            "Search scenarios",
            placeholder="Title, scenario key, or domain",
            icon=":material/search:",
            key="scenario_library:search",
        )
    with filter_columns[1]:
        status = st.selectbox(
            "Snapshot status",
            options=(None, *ScenarioSnapshotStatus),
            format_func=_status_filter_label,
            key="scenario_library:status",
        )
    with filter_columns[2]:
        domain = st.selectbox(
            "Domain",
            options=(None, *context.queries.list_scenario_domains()),
            format_func=lambda value: value or "All domains",
            key="scenario_library:domain",
        )

    fingerprint = (search.strip(), status, domain)
    if st.session_state.get(_FILTER_KEY) != fingerprint:
        st.session_state[_FILTER_KEY] = fingerprint
        st.session_state[_PAGE_KEY] = 1
        st.session_state.pop(_SELECTED_SNAPSHOT_KEY, None)

    requested_page = max(1, int(st.session_state.get(_PAGE_KEY, 1)))
    result = context.queries.list_scenario_snapshots(
        search=search,
        status=status,
        domain=domain,
        page=requested_page,
        page_size=_PAGE_SIZE,
    )

    if requested_page > max(result.page_count, 1):
        st.session_state[_PAGE_KEY] = max(result.page_count, 1)
        st.rerun()

    if not result.items:
        title = "No matching scenarios" if any(fingerprint) else "No scenarios yet"
        message = (
            "Adjust the catalog filters to see other snapshots."
            if any(fingerprint)
            else "Import a validated scenario ZIP package to start the library."
        )
        render_empty_state(title, message, icon=":material/library_books:")
        return

    st.caption(
        f"{result.total} snapshot{'s' if result.total != 1 else ''} · "
        "Select a row to inspect its immutable contents and provenance."
    )
    catalog_key = sha256(repr((fingerprint, result.page)).encode()).hexdigest()[:12]
    event = st.dataframe(
        [_scenario_table_row(item) for item in result.items],
        column_order=(
            "Scenario",
            "Version",
            "Domain",
            "Status",
            "Alternatives",
            "Criteria",
            "Imported",
        ),
        column_config={
            "Scenario": st.column_config.TextColumn(width="large"),
            "Version": st.column_config.TextColumn(width="small"),
            "Domain": st.column_config.TextColumn(width="medium"),
            "Status": st.column_config.TextColumn(width="small"),
            "Alternatives": st.column_config.NumberColumn(width="small"),
            "Criteria": st.column_config.NumberColumn(width="small"),
            "Imported": st.column_config.DatetimeColumn(
                format="MMM D, YYYY, h:mm a",
                width="medium",
            ),
        },
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"scenario_library:catalog:{catalog_key}",
    )

    selected_rows = getattr(getattr(event, "selection", None), "rows", ())
    if selected_rows:
        selected_index = int(selected_rows[0])
        if 0 <= selected_index < len(result.items):
            st.session_state[_SELECTED_SNAPSHOT_KEY] = result.items[
                selected_index
            ].scenario_snapshot_id

    if result.page_count > 1:
        pagination_key = sha256(repr(fingerprint).encode()).hexdigest()[:12]
        selected_page = pagination(
            result.page_count,
            default=result.page,
            key=f"scenario_library:pagination:{pagination_key}",
            width="stretch",
        )
        if selected_page != result.page:
            st.session_state[_PAGE_KEY] = selected_page
            st.session_state.pop(_SELECTED_SNAPSHOT_KEY, None)
            st.rerun()

    selected_snapshot_id = st.session_state.get(_SELECTED_SNAPSHOT_KEY)
    if selected_snapshot_id:
        detail = context.queries.get_scenario_snapshot_detail(selected_snapshot_id)
        if detail is None:
            st.session_state.pop(_SELECTED_SNAPSHOT_KEY, None)
            st.warning(
                "That snapshot is no longer available. Refresh the catalog and "
                "select another row.",
                icon=":material/warning:",
            )
        else:
            st.divider()
            _render_snapshot_detail(context, detail)


def _scenario_table_row(item: ScenarioSnapshotSummary) -> dict[str, object]:
    return {
        "Scenario": item.title,
        "Version": item.declared_version,
        "Domain": item.domain,
        "Status": item.snapshot_status.value.replace("_", " ").title(),
        "Alternatives": item.alternative_count,
        "Criteria": item.criterion_count,
        "Imported": item.created_at,
    }


def _render_snapshot_detail(
    context: PageContext,
    detail: ScenarioSnapshotDetail,
) -> None:
    summary = detail.summary
    imported_at = format_datetime(
        summary.created_at,
        timezone_name=context.container.settings.app_timezone,
    )
    with st.container(border=True):
        heading_columns = st.columns([0.8, 0.2], vertical_alignment="center")
        with heading_columns[0]:
            st.subheader(
                f"{summary.title} · v{summary.declared_version}",
                anchor=False,
            )
            st.caption(
                f"{summary.scenario_key} · {summary.domain} · "
                f"{summary.scenario_type.value.title()}"
            )
        with heading_columns[1]:
            render_status(summary.snapshot_status)

        st.write(summary.summary)
        st.markdown(f"**Policy question:** {detail.policy_question}")

        content_columns = st.columns(4)
        content_columns[0].metric("Alternatives", summary.alternative_count)
        content_columns[1].metric("Criteria", summary.criterion_count)
        content_columns[2].metric("Scales", summary.scale_count)
        content_columns[3].metric("Matrix values", detail.matrix_value_count)

        overview, alternatives, criteria, scales, provenance = st.tabs(
            ("Overview", "Alternatives", "Criteria", "Scales", "Provenance")
        )
        with overview:
            left, right = st.columns(2)
            with left:
                st.markdown("**Snapshot ID**")
                st.code(summary.scenario_snapshot_id, language=None)
                st.markdown("**Root hash**")
                st.code(summary.root_hash, language=None)
            with right:
                st.markdown("**Definition ID**")
                st.code(summary.scenario_definition_id, language=None)
                st.markdown("**Materialized input hash**")
                st.code(detail.materialized_input_hash, language=None)
            st.caption(
                f"Imported {imported_at} by {detail.created_by}. Definition status: "
                f"{summary.definition_status.value}."
            )

        with alternatives:
            if detail.alternatives:
                st.dataframe(
                    [
                        {
                            "Key": item.alternative_key,
                            "Alternative": item.name,
                            "Description": item.description or "—",
                        }
                        for item in detail.alternatives
                    ],
                    hide_index=True,
                    width="stretch",
                )
            else:
                render_empty_state(
                    "No alternatives",
                    "This snapshot does not declare alternatives.",
                )

        with criteria:
            if detail.criteria:
                st.dataframe(
                    [
                        {
                            "Key": item.criterion_key,
                            "Criterion": item.name,
                            "Direction": item.direction.value.title(),
                            "Data type": item.data_type.value.title(),
                            "Unit": item.unit or "—",
                            "Required": item.required,
                        }
                        for item in detail.criteria
                    ],
                    hide_index=True,
                    width="stretch",
                )
            else:
                render_empty_state(
                    "No criteria",
                    "This snapshot does not declare criteria.",
                )

        with scales:
            if detail.scales:
                st.dataframe(
                    [
                        {
                            "Key": item.scale_key,
                            "Scale": item.name,
                            "Type": item.scale_type.replace("_", " ").title(),
                            "Ordered": item.ordered,
                            "Version": item.definition_version,
                            "Values": item.value_count,
                        }
                        for item in detail.scales
                    ],
                    hide_index=True,
                    width="stretch",
                )
            else:
                render_empty_state(
                    "No scales",
                    "This snapshot does not declare response scales.",
                )

        with provenance:
            provenance_columns = st.columns(2)
            provenance_columns[0].markdown(f"**Importer**  \n{detail.importer_version}")
            provenance_columns[1].markdown(
                f"**Schema versions**  \nScenario {detail.schema_version}; "
                f"manifest {detail.manifest_schema_version}"
            )
            st.markdown(f"**Source URI:** `{detail.source_uri or 'Not recorded'}`")
            st.dataframe(
                [
                    {
                        "Path": item.logical_path,
                        "Role": item.file_role.value.replace("_", " ").title(),
                        "Media type": item.media_type,
                        "Size": _format_bytes(item.byte_size),
                        "SHA-256": item.content_hash,
                    }
                    for item in detail.files
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "Path": st.column_config.TextColumn(width="large"),
                    "SHA-256": st.column_config.TextColumn(width="large"),
                },
            )
            with st.expander("Canonical manifest"):
                st.json(dict(detail.manifest_json), expanded=False)


def _render_template_popover(context: PageContext) -> None:
    with st.popover(
        "Scenario template",
        icon=":material/download:",
        width="stretch",
    ):
        st.markdown("#### Scenario authoring template")
        st.write(
            "The template uses JSONC so explanatory comments can be included "
            "while authoring."
        )
        st.markdown(
            "- Completed production scenarios should normally use "
            "`scenario.json`.\n"
            "- Remove comments before converting a JSONC document to JSON.\n"
            "- ZIP upload retains JSONC support for transitional authoring.\n"
            "- The template directory is never imported into the library."
        )
        try:
            archive = context.container.import_bundled_scenarios.template_archive()
        except BundledScenarioSourceError as error:
            st.error(str(error), icon=":material/error:")
            return
        st.download_button(
            "Download scenario template",
            data=archive.content,
            file_name=archive.filename,
            mime="application/zip",
            icon=":material/download:",
            width="stretch",
        )
        with st.expander(f"Inspect included files ({len(archive.file_paths)})"):
            st.code("\n".join(archive.file_paths), language=None)


def _begin_bundled_scan(context: PageContext) -> None:
    actor_id = context.principal.subject
    if actor_id is None:
        st.error(
            "Your administrator session has expired. Sign in again before "
            "scanning bundled scenarios.",
            icon=":material/error:",
        )
        return
    generation = int(st.session_state.get(_BATCH_GENERATION_KEY, 0)) + 1
    st.session_state[_BATCH_GENERATION_KEY] = generation
    st.session_state[_BATCH_COMMAND_KEY] = ImportBundledScenariosCommand(
        actor_id=actor_id,
        actor_type=ActorType.USER,
    )
    st.session_state.pop(_BATCH_DISCOVERY_KEY, None)
    st.session_state.pop(_BATCH_RESULT_KEY, None)
    st.session_state[_IMPORT_DIALOG_OPEN_KEY] = False
    st.session_state[_BATCH_DIALOG_OPEN_KEY] = True


def _on_batch_dialog_dismissed() -> None:
    st.session_state[_BATCH_DIALOG_OPEN_KEY] = False


@st.dialog(
    "Scan bundled scenarios",
    width="large",
    on_dismiss=_on_batch_dialog_dismissed,
)
def _render_bundled_scan_dialog(context: PageContext) -> None:
    generation = int(st.session_state.get(_BATCH_GENERATION_KEY, 0))
    command = st.session_state.get(_BATCH_COMMAND_KEY)
    if not isinstance(command, ImportBundledScenariosCommand):
        st.error(
            "The bundled scan could not be initialized. Close this dialog and "
            "try again.",
            icon=":material/error:",
        )
        return

    wizard = steps(
        ("Discover", "Import", "Results"),
        icons=(
            ":material/search:",
            ":material/input:",
            ":material/checklist:",
        ),
        horizontal=True,
        key=f"scenario_batch:{generation}",
    )
    discovery = st.session_state.get(_BATCH_DISCOVERY_KEY)
    if not isinstance(discovery, BundledScenarioDiscoveryResult):
        with st.spinner("Inspecting configured scenario packages…"):
            discovery = context.container.import_bundled_scenarios.discover(
                correlation_id=command.correlation_id
            )
        st.session_state[_BATCH_DISCOVERY_KEY] = discovery

    with wizard[0]:
        st.markdown("#### Discovered packages")
        if discovery.error_message is not None:
            st.error(discovery.error_message, icon=":material/error:")
            st.caption(f"Batch reference: `{discovery.correlation_id}`")
        elif not discovery.candidates:
            st.info(
                "No production scenario packages were found. JSONC-only "
                "templates and unrelated directories are excluded.",
                icon=":material/folder_off:",
            )
        else:
            discovery_metrics = st.columns(3)
            discovery_metrics[0].metric("Discovered", len(discovery.candidates))
            discovery_metrics[1].metric("Ready", discovery.ready_count)
            discovery_metrics[2].metric(
                "Invalid",
                len(discovery.candidates) - discovery.ready_count,
            )
            st.dataframe(
                [
                    {
                        "Package": candidate.display_name,
                        "Directory": candidate.relative_directory,
                        "Version": candidate.declared_version or "—",
                        "Configuration": candidate.configuration_type.value.replace(
                            "_", " "
                        ).title(),
                        "Discovery": candidate.discovery_status.value.title(),
                        "Details": candidate.error_message or "Ready to import",
                    }
                    for candidate in discovery.candidates
                ],
                hide_index=True,
                width="stretch",
            )
            confirmed = st.checkbox(
                "Import ready packages and record invalid packages as failures. "
                "Snapshots with identical canonical content will be skipped.",
                key=f"scenario_batch:confirm:{generation}",
            )
            if st.button(
                "Continue to import",
                icon=":material/arrow_forward:",
                type="primary",
                disabled=not confirmed or discovery.ready_count == 0,
                width="stretch",
            ):
                wizard.next()

    with wizard[1]:
        st.markdown("#### Import bundled scenarios")
        st.write(
            "Each package is processed in its own transaction. A failed package "
            "will not roll back successful imports."
        )
        navigation_columns = st.columns(2)
        with navigation_columns[0]:
            if st.button(
                "Back",
                icon=":material/arrow_back:",
                width="stretch",
                key=f"scenario_batch:back:{generation}",
            ):
                wizard.previous()
        with navigation_columns[1]:
            if st.button(
                "Import packages",
                icon=":material/input:",
                type="primary",
                width="stretch",
                key=f"scenario_batch:execute:{generation}",
            ):
                progress_bar = st.progress(0.0)
                progress_label = st.empty()

                def update_progress(
                    completed: int,
                    total: int,
                    candidate: BundledScenarioCandidate,
                ) -> None:
                    progress_bar.progress(completed / max(total, 1))
                    progress_label.caption(
                        f"Processed {candidate.display_name} ({completed} of {total})"
                    )

                with st.status(
                    "Importing bundled scenarios…",
                    expanded=True,
                ) as import_status:
                    result = context.container.import_bundled_scenarios.execute(
                        command,
                        candidates=discovery.candidates,
                        on_progress=update_progress,
                    )
                    import_status.update(
                        label="Bundled scenario scan complete",
                        state="error" if result.failed_count else "complete",
                    )
                st.session_state[_BATCH_RESULT_KEY] = result
                imported_snapshot_ids = tuple(
                    outcome.snapshot_id
                    for outcome in result.outcomes
                    if outcome.status == BundledScenarioOutcomeStatus.IMPORTED
                    and outcome.snapshot_id is not None
                )
                if imported_snapshot_ids:
                    st.session_state[_SELECTED_SNAPSHOT_KEY] = imported_snapshot_ids[-1]
                wizard.next()

    with wizard[2]:
        batch_result = st.session_state.get(_BATCH_RESULT_KEY)
        if isinstance(batch_result, ImportBundledScenariosResult):
            _render_batch_result(batch_result)
        else:
            st.warning(
                "No completed batch result is available.",
                icon=":material/warning:",
            )
        if st.button(
            "Done",
            icon=":material/done:",
            type="primary",
            width="stretch",
            key=f"scenario_batch:done:{generation}",
        ):
            st.session_state[_BATCH_DIALOG_OPEN_KEY] = False
            st.session_state[_PAGE_KEY] = 1
            wizard.reset()


def _render_batch_result(result: ImportBundledScenariosResult) -> None:
    if result.discovery_error is not None:
        st.error(result.discovery_error, icon=":material/error:")
    elif result.failed_count:
        st.warning(
            "The scan completed, but one or more packages need attention.",
            icon=":material/warning:",
        )
    elif result.imported_count:
        st.success(
            "Bundled scenarios were imported successfully.",
            icon=":material/check_circle:",
        )
    else:
        st.info(
            "All discovered scenarios already exist in the library.",
            icon=":material/content_copy:",
        )

    summary_columns = st.columns(4)
    summary_columns[0].metric("Discovered", result.discovered_count)
    summary_columns[1].metric("Imported", result.imported_count)
    summary_columns[2].metric("Skipped", result.skipped_duplicate_count)
    summary_columns[3].metric("Failed", result.failed_count)
    if result.outcomes:
        st.dataframe(
            [
                {
                    "Package": outcome.display_name,
                    "Directory": outcome.relative_directory,
                    "Version": outcome.declared_version or "—",
                    "Outcome": outcome.status.value.title(),
                    "Snapshot ID": outcome.snapshot_id or "—",
                    "Details": outcome.error_message or _outcome_detail(outcome.status),
                }
                for outcome in result.outcomes
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "Package": st.column_config.TextColumn(width="large"),
                "Details": st.column_config.TextColumn(width="large"),
            },
        )
    st.caption(f"Batch reference: `{result.correlation_id}`")


def _outcome_detail(status: BundledScenarioOutcomeStatus) -> str:
    if status == BundledScenarioOutcomeStatus.IMPORTED:
        return "New immutable snapshot created"
    if status == BundledScenarioOutcomeStatus.SKIPPED:
        return "Identical canonical snapshot already exists"
    return "Import failed"


def _on_import_dialog_dismissed() -> None:
    st.session_state[_IMPORT_DIALOG_OPEN_KEY] = False


@st.dialog(
    "Import scenario package",
    width="large",
    on_dismiss=_on_import_dialog_dismissed,
)
def _render_import_dialog(context: PageContext) -> None:
    wizard = steps(
        ("Upload", "Review", "Import"),
        current=0,
        icons=(
            ":material/upload_file:",
            ":material/fact_check:",
            ":material/library_add_check:",
        ),
        horizontal=True,
        key="scenario_import",
    )
    generation = int(st.session_state.get(_IMPORT_GENERATION_KEY, 0))

    with wizard[0]:
        st.write(
            "Upload one scenario package as a ZIP archive. The package is "
            "validated before any data is written."
        )
        uploaded_file = st.file_uploader(
            "Scenario ZIP",
            type=("zip",),
            max_upload_size=MAX_ARCHIVE_BYTES // (1024 * 1024),
            help=(
                "The archive must contain exactly one scenario.json or "
                "scenario.jsonc file, either at its root or in one folder."
            ),
            key=f"scenario_import:archive:{generation}",
        )
        inspection = _inspect_upload(uploaded_file)
        if inspection is not None:
            st.success(
                f"Found a scenario package in {inspection.package_label}.",
                icon=":material/check_circle:",
            )
            st.caption(
                f"{inspection.file_count} files · "
                f"{_format_bytes(inspection.total_uncompressed_bytes)} extracted"
            )
        if st.button(
            "Continue to review",
            icon=":material/arrow_forward:",
            type="primary",
            disabled=inspection is None,
            width="stretch",
        ):
            wizard.next()

    with wizard[1]:
        inspection = _inspect_upload(uploaded_file)
        if inspection is None:
            st.warning(
                "The uploaded package is no longer available. Return to the "
                "upload step and select it again.",
                icon=":material/warning:",
            )
        else:
            st.markdown("#### Review package")
            review_columns = st.columns(3)
            review_columns[0].metric("Files", inspection.file_count)
            review_columns[1].metric(
                "Compressed", _format_bytes(len(inspection.archive_bytes))
            )
            review_columns[2].metric(
                "Extracted",
                _format_bytes(inspection.total_uncompressed_bytes),
            )
            st.markdown(f"**Archive:** `{inspection.filename}`")
            st.markdown(f"**Package root:** `{inspection.package_label}`")
            st.info(
                "Import creates a content-addressed snapshot. Re-uploading "
                "identical content reuses the existing snapshot.",
                icon=":material/fingerprint:",
            )

        navigation_columns = st.columns(2)
        with navigation_columns[0]:
            if st.button(
                "Back",
                icon=":material/arrow_back:",
                width="stretch",
            ):
                wizard.previous()
        with navigation_columns[1]:
            if (
                st.button(
                    "Import snapshot",
                    icon=":material/library_add:",
                    type="primary",
                    disabled=inspection is None,
                    width="stretch",
                )
                and inspection is not None
            ):
                result = _import_scenario(context, inspection)
                if result is not None:
                    st.session_state[_IMPORT_RESULT_KEY] = result
                    st.session_state[_SELECTED_SNAPSHOT_KEY] = (
                        result.scenario_snapshot_id
                    )
                    wizard.next()

    with wizard[2]:
        result = st.session_state.get(_IMPORT_RESULT_KEY)
        if isinstance(result, ImportScenarioResult):
            action = "imported" if result.created else "already in the library"
            st.success(
                f"The scenario snapshot was {action} and is ready to use.",
                icon=":material/check_circle:",
            )
            render_status(result.status)
            st.markdown("**Snapshot ID**")
            st.code(result.scenario_snapshot_id, language=None)
            st.markdown("**Root hash**")
            st.code(result.root_hash, language=None)
        else:
            st.warning(
                "No completed import result is available.",
                icon=":material/warning:",
            )

        if st.button(
            "Done",
            icon=":material/done:",
            type="primary",
            width="stretch",
        ):
            st.session_state.pop(_IMPORT_RESULT_KEY, None)
            st.session_state[_IMPORT_GENERATION_KEY] = generation + 1
            st.session_state[_IMPORT_DIALOG_OPEN_KEY] = False
            wizard.reset()


def _inspect_upload(uploaded_file: Any) -> ScenarioArchiveInspection | None:
    if uploaded_file is None:
        return None
    try:
        return inspect_scenario_archive(
            uploaded_file.getvalue(),
            filename=uploaded_file.name,
        )
    except ScenarioArchiveError as error:
        st.error(str(error), icon=":material/error:")
        return None


def _import_scenario(
    context: PageContext,
    inspection: ScenarioArchiveInspection,
) -> ImportScenarioResult | None:
    actor_id = context.principal.subject
    if actor_id is None:
        st.error(
            "Your administrator session has expired. Sign in again before importing.",
            icon=":material/error:",
        )
        return None

    source_digest = sha256(inspection.archive_bytes).hexdigest()
    try:
        with (
            st.spinner("Validating and materializing scenario data…"),
            extracted_scenario_directory(inspection) as source_directory,
        ):
            return context.container.import_scenario.execute(
                ImportScenarioCommand(
                    source_directory=source_directory,
                    actor_id=actor_id,
                    source_uri=f"urn:poli-insight:scenario-upload:{source_digest}",
                    actor_type=ActorType.USER,
                )
            )
    except (ScenarioArchiveError, ScenarioImportError) as error:
        st.error(str(error), icon=":material/error:")
        return None


def _status_filter_label(status: ScenarioSnapshotStatus | None) -> str:
    if status is None:
        return "All statuses"
    return status.value.replace("_", " ").title()


def _format_bytes(byte_count: int) -> str:
    value = float(byte_count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            precision = 0 if unit == "B" else 1
            return f"{value:.{precision}f} {unit}"
        value /= 1024
    return f"{byte_count} B"
