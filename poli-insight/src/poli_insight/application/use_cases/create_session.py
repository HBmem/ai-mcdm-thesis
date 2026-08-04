"""Application use case for creating a draft decision session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    AccessCodeMode,
    ActorType,
    AuditAction,
    Discoverability,
    EnrollmentMode,
    ScenarioSnapshotStatus,
    SessionStatus,
    StakeholderSelectionMode,
)
from poli_insight.domain.session import Session, SessionRuleViolation

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class CreateSessionError(ValueError):
    """Expected application failure while creating a session."""


@dataclass(frozen=True, slots=True, repr=False)
class CreateSessionCommand:
    """Validated input needed to create one draft session."""

    scenario_snapshot_id: str
    public_slug: str
    title: str
    actor_id: str
    description: str | None = None
    admin_notes: str | None = None
    discoverability: Discoverability = Discoverability.UNLISTED
    enrollment_mode: EnrollmentMode = EnrollmentMode.OPEN
    access_code_mode: AccessCodeMode = AccessCodeMode.NONE
    shared_access_code: str | None = None
    identity_policy: str = "pseudonymous"
    stakeholder_selection_mode: StakeholderSelectionMode = (
        StakeholderSelectionMode.SELF_SELECT
    )
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("scenario_snapshot_id", self.scenario_snapshot_id),
            ("public_slug", self.public_slug),
            ("title", self.title),
            ("actor_id", self.actor_id),
            ("identity_policy", self.identity_policy),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise CreateSessionError(f"{field_name} cannot be empty.")
        if self.access_code_mode == AccessCodeMode.SHARED_SESSION_CODE:
            if self.shared_access_code is None or len(self.shared_access_code) < 6:
                raise CreateSessionError(
                    "A shared session code of at least 6 characters is required."
                )
        elif self.shared_access_code is not None:
            raise CreateSessionError(
                "A shared access code can only be set for shared-code sessions."
            )

    def __repr__(self) -> str:
        return (
            "CreateSessionCommand("
            f"scenario_snapshot_id={self.scenario_snapshot_id!r}, "
            f"public_slug={self.public_slug!r}, title={self.title!r}, "
            "shared_access_code=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class CreateSessionResult:
    """Application-facing identity and initial state of a created session."""

    session_id: str
    scenario_snapshot_id: str
    public_slug: str
    status: SessionStatus
    created_at: datetime


class CreateSession:
    """Create a draft session against a ready scenario snapshot."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory

    def execute(self, command: CreateSessionCommand) -> CreateSessionResult:
        occurred_at = self._clock()
        session_id = self._id_factory()

        with self._unit_of_work_factory() as unit_of_work:
            snapshot = unit_of_work.scenarios.get_by_id(
                command.scenario_snapshot_id
            )
            if snapshot is None:
                raise CreateSessionError(
                    "Scenario snapshot "
                    f"{command.scenario_snapshot_id!r} does not exist."
                )
            if snapshot.status != ScenarioSnapshotStatus.READY:
                raise CreateSessionError(
                    "A session can only be created from a ready scenario "
                    "snapshot."
                )

            try:
                session = Session(
                    session_id=session_id,
                    scenario_snapshot_id=snapshot.scenario_snapshot_id,
                    public_slug=command.public_slug,
                    title=command.title,
                    description=command.description,
                    admin_notes=command.admin_notes,
                    status=SessionStatus.DRAFT,
                    discoverability=command.discoverability,
                    enrollment_mode=command.enrollment_mode,
                    access_code_mode=command.access_code_mode,
                    identity_policy=command.identity_policy,
                    stakeholder_selection_mode=(
                        command.stakeholder_selection_mode
                    ),
                    opens_at=command.opens_at,
                    closes_at=command.closes_at,
                    opened_at=None,
                    paused_at=None,
                    closed_at=None,
                    canceled_at=None,
                    archived_at=None,
                    active_configuration_version_id=None,
                    created_at=occurred_at,
                    created_by=command.actor_id,
                    updated_at=occurred_at,
                    updated_by=command.actor_id,
                )
            except SessionRuleViolation as error:
                raise CreateSessionError(str(error)) from error

            unit_of_work.session.add(session)
            if command.access_code_mode == AccessCodeMode.SHARED_SESSION_CODE:
                unit_of_work.access_codes.add_shared_code(
                    access_code_id=self._id_factory(),
                    session_id=session.session_id,
                    plaintext_code=command.shared_access_code or "",
                    created_at=occurred_at,
                    created_by=command.actor_id,
                )
            unit_of_work.audit_events.add(
                _build_created_event(
                    session,
                    command=command,
                    occurred_at=occurred_at,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()

        return CreateSessionResult(
            session_id=session.session_id,
            scenario_snapshot_id=session.scenario_snapshot_id,
            public_slug=session.public_slug,
            status=session.status,
            created_at=session.created_at,
        )


def _build_created_event(
    session: Session,
    *,
    command: CreateSessionCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    after_json = {
        "schema_version": 1,
        "session_id": session.session_id,
        "scenario_snapshot_id": session.scenario_snapshot_id,
        "public_slug": session.public_slug,
        "status": session.status.value,
        "discoverability": session.discoverability.value,
        "enrollment_mode": session.enrollment_mode.value,
        "access_code_mode": session.access_code_mode.value,
        "stakeholder_selection_mode": (
            session.stakeholder_selection_mode.value
        ),
        "opens_at": session.opens_at,
        "closes_at": session.closes_at,
    }
    source_metadata = {
        "schema_version": 1,
        "use_case": "create_session",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": session.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.CREATED.value,
        "entity_type": "session",
        "entity_id": session.session_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "causation_event_id": command.causation_event_id,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        session_id=session.session_id,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=AuditAction.CREATED,
        entity_type="session",
        entity_id=session.session_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
