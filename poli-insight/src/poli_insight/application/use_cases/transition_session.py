"""Application service for audited session lifecycle transitions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import ActorType, AuditAction, SessionStatus
from poli_insight.domain.session import Session, SessionRuleViolation

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class SessionTransition(StrEnum):
    SCHEDULE = "schedule"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    ARCHIVE = "archive"


_AUDIT_ACTION = {
    SessionTransition.SCHEDULE: AuditAction.SCHEDULED,
    SessionTransition.PAUSE: AuditAction.PAUSED,
    SessionTransition.RESUME: AuditAction.RESUMED,
    SessionTransition.CANCEL: AuditAction.CANCELED,
    SessionTransition.ARCHIVE: AuditAction.ARCHIVED,
}


class TransitionSessionError(ValueError):
    """Expected application failure during a lifecycle transition."""


@dataclass(frozen=True, slots=True)
class TransitionSessionCommand:
    session_id: str
    transition: SessionTransition
    actor_id: str
    reason_code: str | None = None
    reason_text: str | None = None
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("actor_id", self.actor_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise TransitionSessionError(f"{field_name} cannot be empty.")
        for field_name, optional_value in (
            ("reason_code", self.reason_code),
            ("reason_text", self.reason_text),
        ):
            if optional_value is not None and not optional_value.strip():
                raise TransitionSessionError(
                    f"{field_name} cannot be blank when provided."
                )


@dataclass(frozen=True, slots=True)
class TransitionSessionResult:
    session_id: str
    status: SessionStatus
    transitioned_at: datetime


class TransitionSession:
    """Apply one domain transition in a locked transaction and audit it."""

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

    def execute(self, command: TransitionSessionCommand) -> TransitionSessionResult:
        occurred_at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            if session is None:
                raise TransitionSessionError(
                    f"Session {command.session_id!r} does not exist."
                )
            before_json = _lifecycle_projection(session)
            try:
                transition = getattr(session, command.transition.value)
                updated = transition(actor_id=command.actor_id, at=occurred_at)
            except SessionRuleViolation as error:
                raise TransitionSessionError(str(error)) from error

            after_json = _lifecycle_projection(updated)
            unit_of_work.session.save(updated)
            unit_of_work.audit_events.add(
                _transition_event(
                    updated,
                    before_json=before_json,
                    after_json=after_json,
                    command=command,
                    occurred_at=occurred_at,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()
        return TransitionSessionResult(
            session_id=updated.session_id,
            status=updated.status,
            transitioned_at=occurred_at,
        )


def _lifecycle_projection(session: Session) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session.session_id,
        "status": session.status.value,
        "active_configuration_version_id": session.active_configuration_version_id,
        "opens_at": session.opens_at,
        "closes_at": session.closes_at,
        "opened_at": session.opened_at,
        "paused_at": session.paused_at,
        "closed_at": session.closed_at,
        "canceled_at": session.canceled_at,
        "archived_at": session.archived_at,
    }


def _transition_event(
    session: Session,
    *,
    before_json: dict[str, object],
    after_json: dict[str, object],
    command: TransitionSessionCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    action = _AUDIT_ACTION[command.transition]
    source_metadata = {
        "schema_version": 1,
        "use_case": f"{command.transition.value}_session",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": session.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": action.value,
        "entity_type": "session",
        "entity_id": session.session_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "causation_event_id": command.causation_event_id,
        "reason_code": command.reason_code,
        "reason_text": command.reason_text,
        "before_json": before_json,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        session_id=session.session_id,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=action,
        entity_type="session",
        entity_id=session.session_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        reason_code=command.reason_code,
        reason_text=command.reason_text,
        before_json=before_json,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
