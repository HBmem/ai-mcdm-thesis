"""Read models used by the Streamlit page layer.

Page queries deliberately return small immutable projections rather than domain
aggregates or ORM rows.  They are read-only and do not share a transaction with
commands.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Protocol

from poli_insight.domain.enum import (
    AccessCodeMode,
    AlgorithmRole,
    CriterionDataType,
    CriterionDirection,
    Discoverability,
    EnrollmentMode,
    InvitationStatus,
    MissingGroupPolicy,
    ParticipantAccessStatus,
    QuestionType,
    ResponseFormat,
    ResponseTargetType,
    ScenarioDefinitionStatus,
    ScenarioFileRole,
    ScenarioSnapshotStatus,
    ScenarioType,
    SessionStatus,
    StakeholderSelectionMode,
    SubmissionReviewStatus,
    SubmissionStatus,
    ValidationStatus,
)


class PageQueryError(RuntimeError):
    """Safe application-level failure raised by page query adapters."""


@dataclass(frozen=True, slots=True)
class PageResult[ItemT]:
    """One validated page of query results."""

    items: tuple[ItemT, ...]
    page: int
    page_size: int
    total: int

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be at least 1.")
        if self.page_size < 1:
            raise ValueError("page_size must be at least 1.")
        if self.total < 0:
            raise ValueError("total cannot be negative.")
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size.")
        if len(self.items) > self.total:
            raise ValueError("items cannot exceed total.")

    @property
    def page_count(self) -> int:
        if self.total == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


@dataclass(frozen=True, slots=True)
class PublicSessionSummary:
    session_id: str
    public_slug: str
    title: str
    description: str | None
    closes_at: datetime | None
    enrollment_mode: EnrollmentMode
    access_code_mode: AccessCodeMode


@dataclass(frozen=True, slots=True)
class ParticipationGroupOption:
    group_id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ParticipationScaleOption:
    scale_value_id: str
    label: str
    ordinal: int
    numeric_value: str | None


@dataclass(frozen=True, slots=True)
class ParticipationQuestion:
    question_definition_id: str
    question_type: QuestionType
    prompt: str
    required: bool
    display_order: int
    target_name: str | None
    target_description: str | None
    left_name: str | None
    right_name: str | None


@dataclass(frozen=True, slots=True)
class PublicParticipationSession:
    session_id: str
    public_slug: str
    title: str
    description: str | None
    enrollment_mode: EnrollmentMode
    access_code_mode: AccessCodeMode
    stakeholder_selection_mode: StakeholderSelectionMode
    identity_policy: str
    groups: tuple[ParticipationGroupOption, ...]


@dataclass(frozen=True, slots=True)
class ParticipationWorkspace:
    participant_id: str
    session: PublicParticipationSession
    response_format: ResponseFormat
    questions: tuple[ParticipationQuestion, ...]
    scale_name: str
    scale_options: tuple[ParticipationScaleOption, ...]
    consent_required: bool
    consent_version: str
    consent_title: str
    consent_statement: str
    consent_completed: bool
    submission_id: str | None
    submission_status: SubmissionStatus | None
    attempt_number: int | None
    answers: Mapping[str, Mapping[str, object]]
    last_saved_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "answers",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(value))
                    for key, value in self.answers.items()
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class AdminDashboardSnapshot:
    generated_at: datetime
    session_status_counts: Mapping[SessionStatus, int]

    def __post_init__(self) -> None:
        counts = {
            status: int(self.session_status_counts.get(status, 0))
            for status in SessionStatus
        }
        if any(count < 0 for count in counts.values()):
            raise ValueError("Session status counts cannot be negative.")
        object.__setattr__(
            self,
            "session_status_counts",
            MappingProxyType(counts),
        )

    def count(self, status: SessionStatus) -> int:
        return self.session_status_counts[status]


@dataclass(frozen=True, slots=True)
class HomeActiveSessionSummary:
    total_active_sessions: int
    total_participants_today: int


@dataclass(frozen=True, slots=True)
class SessionCatalogMetrics:
    total_count: int
    open_count: int
    attention_count: int

    def __post_init__(self) -> None:
        if min(self.total_count, self.open_count, self.attention_count) < 0:
            raise ValueError("Session catalog metrics cannot be negative.")
        if self.open_count > self.total_count:
            raise ValueError("Open session count cannot exceed total count.")
        if self.attention_count > self.total_count:
            raise ValueError("Attention count cannot exceed total count.")


@dataclass(frozen=True, slots=True)
class SessionScenarioOption:
    scenario_key: str
    title: str


@dataclass(frozen=True, slots=True)
class AdminSessionSummary:
    session_id: str
    scenario_snapshot_id: str
    public_slug: str
    title: str
    description: str | None
    status: SessionStatus
    scenario_key: str
    scenario_title: str
    scenario_version: str
    scenario_status: ScenarioSnapshotStatus
    active_configuration_version: int | None
    participant_count: int
    submitted_participant_count: int
    validation_attention_count: int
    needs_attention: bool
    opens_at: datetime | None
    closes_at: datetime | None
    paused_at: datetime | None
    closed_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SessionConfigurationSummary:
    configuration_version_id: str
    version_number: int
    response_format: ResponseFormat
    response_target_type: ResponseTargetType
    scale_name: str
    allow_resubmissions: bool
    max_submissions_per_participant: int
    allow_incomplete_submission: bool
    minimum_valid_submissions: int
    missing_group_policy: MissingGroupPolicy
    consistency_threshold: str | None
    config_hash: str
    activated_at: datetime | None
    activated_by: str | None
    created_at: datetime
    created_by: str
    is_active: bool
    question_count: int
    stakeholder_group_count: int


@dataclass(frozen=True, slots=True)
class SessionGroupProgress:
    group_id: str
    group_name: str
    allocation_units: int
    enrolled_count: int
    submitted_count: int
    valid_count: int


@dataclass(frozen=True, slots=True)
class SessionParticipantSummary:
    participant_id: str
    display_label: str
    group_name: str
    access_status: ParticipantAccessStatus
    progress: str
    enrolled_at: datetime


@dataclass(frozen=True, slots=True)
class SessionSubmissionSummary:
    submission_id: str
    participant_label: str
    group_name: str
    attempt_number: int
    status: SubmissionStatus
    validation_status: ValidationStatus | None
    consistency_ratio: str | None
    submitted_at: datetime | None
    review_status: SubmissionReviewStatus = SubmissionReviewStatus.PENDING


@dataclass(frozen=True, slots=True)
class SessionInvitationSummary:
    invitation_id: str
    token_hint: str | None
    group_name: str | None
    status: InvitationStatus
    expires_at: datetime
    sent_at: datetime | None
    send_count: int
    redeemed_at: datetime | None
    participant_label: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionParticipantDetail:
    summary: SessionParticipantSummary
    configuration_version: int
    invitation_id: str | None
    joined_at: datetime | None
    started_at: datetime | None
    submitted_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    submission_count: int


@dataclass(frozen=True, slots=True)
class SessionSubmissionDetail:
    summary: SessionSubmissionSummary
    participant_id: str
    response_format: ResponseFormat
    answer_count: int
    required_answer_count: int
    last_saved_at: datetime
    answers_hash: str | None
    validation_id: str | None
    validation_completed_at: datetime | None
    validation_messages: tuple[str, ...]
    review_status: SubmissionReviewStatus
    review_notes: str | None
    reviewed_at: datetime | None
    reviewed_by: str | None


@dataclass(frozen=True, slots=True)
class ValidationQueueItem:
    submission_id: str
    participant_label: str
    group_name: str
    attempt_number: int
    submitted_at: datetime
    validation_status: ValidationStatus | None
    consistency_ratio: str | None
    validation_message_count: int
    review_status: SubmissionReviewStatus
    reviewed_at: datetime | None
    reviewed_by: str | None


@dataclass(frozen=True, slots=True)
class SessionAuditEventSummary:
    audit_event_id: str
    occurred_at: datetime
    actor_display: str
    action: str
    entity_type: str
    reason: str | None
    correlation_id: str


@dataclass(frozen=True, slots=True)
class AdminSessionDetail:
    summary: AdminSessionSummary
    admin_notes: str | None
    discoverability: Discoverability
    enrollment_mode: EnrollmentMode
    access_code_mode: AccessCodeMode
    identity_policy: str
    stakeholder_selection_mode: StakeholderSelectionMode
    created_at: datetime
    created_by: str
    configuration: SessionConfigurationSummary | None
    configurations: tuple[SessionConfigurationSummary, ...]
    group_progress: tuple[SessionGroupProgress, ...]
    participants: tuple[SessionParticipantSummary, ...]
    participant_total: int
    submissions: tuple[SessionSubmissionSummary, ...]
    submission_total: int
    audit_events: tuple[SessionAuditEventSummary, ...]


@dataclass(frozen=True, slots=True)
class ScenarioLibraryMetrics:
    definition_count: int
    snapshot_count: int
    ready_count: int
    attention_count: int

    def __post_init__(self) -> None:
        values = (
            self.definition_count,
            self.snapshot_count,
            self.ready_count,
            self.attention_count,
        )
        if any(value < 0 for value in values):
            raise ValueError("Scenario library metrics cannot be negative.")


@dataclass(frozen=True, slots=True)
class ScenarioSnapshotSummary:
    scenario_snapshot_id: str
    scenario_definition_id: str
    scenario_key: str
    title: str
    domain: str
    summary: str
    declared_version: str
    scenario_type: ScenarioType
    snapshot_status: ScenarioSnapshotStatus
    definition_status: ScenarioDefinitionStatus
    alternative_count: int
    criterion_count: int
    scale_count: int
    file_count: int
    created_at: datetime
    ready_at: datetime | None
    root_hash: str


@dataclass(frozen=True, slots=True)
class ScenarioCriterionPreview:
    criterion_key: str
    name: str
    description: str | None
    direction: CriterionDirection
    data_type: CriterionDataType
    unit: str | None
    required: bool
    display_order: int


@dataclass(frozen=True, slots=True)
class ScenarioAlternativePreview:
    alternative_key: str
    name: str
    description: str | None
    display_order: int


@dataclass(frozen=True, slots=True)
class ScenarioScalePreview:
    scale_id: str
    scale_key: str
    name: str
    scale_type: str
    ordered: bool
    definition_version: int
    value_count: int
    is_application_defined: bool


@dataclass(frozen=True, slots=True)
class ScenarioStakeholderDefault:
    group_key: str
    name: str
    description: str
    allocation_units: int
    required: bool


@dataclass(frozen=True, slots=True)
class ScenarioFilePreview:
    logical_path: str
    file_role: ScenarioFileRole
    media_type: str
    byte_size: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class ScenarioSnapshotDetail:
    summary: ScenarioSnapshotSummary
    policy_question: str
    schema_version: int
    manifest_schema_version: int
    manifest_json: Mapping[str, object]
    materialized_input_hash: str
    source_uri: str | None
    importer_version: str
    created_by: str
    matrix_value_count: int
    criteria: tuple[ScenarioCriterionPreview, ...]
    alternatives: tuple[ScenarioAlternativePreview, ...]
    scales: tuple[ScenarioScalePreview, ...]
    default_response_format: ResponseFormat | None
    default_scale_key: str | None
    stakeholder_group_defaults: tuple[ScenarioStakeholderDefault, ...]
    files: tuple[ScenarioFilePreview, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "manifest_json",
            MappingProxyType(dict(self.manifest_json)),
        )


@dataclass(frozen=True, slots=True)
class AlgorithmImplementationOption:
    algorithm_implementation_id: str
    stable_key: str
    role: AlgorithmRole
    conceptual_method: str
    provider: str
    library_name: str
    library_version: str


@dataclass(frozen=True, slots=True)
class AdminAuditEventSummary:
    audit_event_id: str
    occurred_at: datetime
    session_id: str | None
    session_title: str | None
    public_slug: str | None
    actor_display: str
    action: str
    entity_type: str
    entity_id: str
    reason: str | None
    correlation_id: str


class PageQueries(Protocol):
    """Read-only interface tailored to current page requirements."""

    def list_open_public_sessions(
        self,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = 10,
        at: datetime | None = None,
    ) -> PageResult[PublicSessionSummary]:
        """Return listed sessions that can currently accept submissions."""
        ...

    def get_public_participation_session(
        self,
        public_slug: str,
        *,
        at: datetime | None = None,
    ) -> PublicParticipationSession | None:
        """Return an open session for direct or catalog-based enrollment."""
        ...

    def get_participation_workspace(
        self,
        participant_id: str,
    ) -> ParticipationWorkspace | None:
        """Return the participant's immutable questionnaire and current attempt."""
        ...

    def get_admin_dashboard(
        self,
        *,
        at: datetime | None = None,
    ) -> AdminDashboardSnapshot:
        """Return the operational dashboard projection."""
        ...

    def get_home_metrics(
        self,
        *,
        at: datetime | None = None,
    ) -> HomeActiveSessionSummary:
        """Return the home active session metics."""
        ...

    def get_session_catalog_metrics(
        self,
        *,
        search: str | None = None,
        status: SessionStatus | None = None,
        scenario_key: str | None = None,
    ) -> SessionCatalogMetrics:
        """Return counts for the filtered administrator session catalog."""
        ...

    def list_session_scenarios(self) -> tuple[SessionScenarioOption, ...]:
        """Return scenarios currently referenced by sessions."""
        ...

    def list_admin_sessions(
        self,
        *,
        search: str | None = None,
        status: SessionStatus | None = None,
        scenario_key: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PageResult[AdminSessionSummary]:
        """Return disclosure-safe operational session rows."""
        ...

    def get_admin_session_detail(
        self,
        session_id: str,
    ) -> AdminSessionDetail | None:
        """Return one session workspace projection."""
        ...

    def list_session_invitations(
        self,
        session_id: str,
        *,
        search: str | None = None,
        status: InvitationStatus | None = None,
        page: int = 1,
        page_size: int = 10,
        at: datetime | None = None,
    ) -> PageResult[SessionInvitationSummary]:
        """Return invitation lifecycle rows without credential material."""
        ...

    def list_session_participants(
        self,
        session_id: str,
        *,
        search: str | None = None,
        access_status: ParticipantAccessStatus | None = None,
        progress: str | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 10,
    ) -> PageResult[SessionParticipantSummary]: ...

    def get_session_participant_detail(
        self,
        session_id: str,
        participant_id: str,
    ) -> SessionParticipantDetail | None: ...

    def list_session_submissions(
        self,
        session_id: str,
        *,
        search: str | None = None,
        status: SubmissionStatus | None = None,
        validation_status: ValidationStatus | None = None,
        review_status: SubmissionReviewStatus | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 10,
    ) -> PageResult[SessionSubmissionSummary]: ...

    def get_session_submission_detail(
        self,
        session_id: str,
        submission_id: str,
    ) -> SessionSubmissionDetail | None: ...

    def list_validation_queue(
        self,
        session_id: str,
        *,
        search: str | None = None,
        review_status: SubmissionReviewStatus | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PageResult[ValidationQueueItem]: ...

    def list_active_algorithm_implementations(
        self,
        *,
        role: AlgorithmRole | None = None,
    ) -> tuple[AlgorithmImplementationOption, ...]:
        """Return active, version-pinned algorithm choices."""
        ...

    def list_admin_audit_events(
        self,
        *,
        search: str | None = None,
        action: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> PageResult[AdminAuditEventSummary]:
        """Return disclosure-safe audit events across administered sessions."""
        ...

    def list_audit_actions(self) -> tuple[str, ...]:
        """Return distinct persisted audit actions for filtering."""
        ...

    def is_public_slug_available(self, public_slug: str) -> bool:
        """Return whether a normalized public slug can be created."""
        ...

    def get_scenario_library_metrics(self) -> ScenarioLibraryMetrics:
        """Return high-level counts for scenario definitions and snapshots."""
        ...

    def list_scenario_domains(self) -> tuple[str, ...]:
        """Return distinct scenario domains available to catalog filters."""
        ...

    def list_scenario_snapshots(
        self,
        *,
        search: str | None = None,
        status: ScenarioSnapshotStatus | None = None,
        domain: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> PageResult[ScenarioSnapshotSummary]:
        """Return scenario snapshot catalog projections."""
        ...

    def get_scenario_snapshot_detail(
        self,
        scenario_snapshot_id: str,
    ) -> ScenarioSnapshotDetail | None:
        """Return an immutable scenario preview without source file bytes."""
        ...
