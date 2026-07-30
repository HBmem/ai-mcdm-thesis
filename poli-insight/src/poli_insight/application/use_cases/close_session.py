"""Application use case for closing an open or paused decision session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

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


class CloseSessionError(ValueError):
    """Expected application failure while closing a session."""


@dataclass(frozen=True, slots=True)
class CloseSessionCommand:
    session_id: str
    actor_id: str
    reason_code: str = "manual_close"
    reason_text: str | None = None
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("actor_id", self.actor_id),
            ("reason_code", self.reason_code),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise CloseSessionError(f"{field_name} cannot be empty.")
        if self.reason_text is not None and not self.reason_text.strip():
            raise CloseSessionError(
                "reason_text cannot be blank when provided."
            )


@dataclass(frozen=True, slots=True)
class CloseSessionResult:
    session_id: str
    status: SessionStatus
    closed_at: datetime


class CloseSession:
    """Close a locked session and audit the moderator's reason."""

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

    def execute(self, command: CloseSessionCommand) -> CloseSessionResult:
        occurred_at = self._clock()

        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            if session is None:
                raise CloseSessionError(
                    f"Session {command.session_id!r} does not exist."
                )

            before_json = _lifecycle_projection(session)
            try:
                updated = session.close(
                    actor_id=command.actor_id,
                    at=occurred_at,
                )
            except SessionRuleViolation as error:
                raise CloseSessionError(str(error)) from error

            after_json = _lifecycle_projection(updated)
            unit_of_work.session.save(updated)
            unit_of_work.audit_events.add(
                _build_closed_event(
                    updated,
                    before_json=before_json,
                    after_json=after_json,
                    command=command,
                    occurred_at=occurred_at,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()

        if updated.closed_at is None:
            raise AssertionError("A closed session must have closed_at.")
        return CloseSessionResult(
            session_id=updated.session_id,
            status=updated.status,
            closed_at=updated.closed_at,
        )


def _lifecycle_projection(session: Session) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session.session_id,
        "status": session.status.value,
        "active_configuration_version_id": (
            session.active_configuration_version_id
        ),
        "opened_at": session.opened_at,
        "paused_at": session.paused_at,
        "closed_at": session.closed_at,
    }


def _build_closed_event(
    session: Session,
    *,
    before_json: dict[str, object],
    after_json: dict[str, object],
    command: CloseSessionCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    source_metadata = {"schema_version": 1, "use_case": "close_session"}
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": session.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.CLOSED.value,
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
        action=AuditAction.CLOSED,
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
