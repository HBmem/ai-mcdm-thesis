"""Application use case for opening a configured decision session."""

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


class OpenSessionError(ValueError):
    """Expected application failure while opening a session."""


@dataclass(frozen=True, slots=True)
class OpenSessionCommand:
    session_id: str
    actor_id: str
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
                raise OpenSessionError(f"{field_name} cannot be empty.")


@dataclass(frozen=True, slots=True)
class OpenSessionResult:
    session_id: str
    status: SessionStatus
    active_configuration_version_id: str
    opened_at: datetime


class OpenSession:
    """Open a locked session after loading its referenced snapshot."""

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

    def execute(self, command: OpenSessionCommand) -> OpenSessionResult:
        occurred_at = self._clock()

        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            if session is None:
                raise OpenSessionError(
                    f"Session {command.session_id!r} does not exist."
                )
            snapshot = unit_of_work.scenarios.get_by_id(
                session.scenario_snapshot_id
            )
            if snapshot is None:
                raise OpenSessionError(
                    "The session's scenario snapshot no longer exists."
                )

            before_json = _lifecycle_projection(session)
            try:
                updated = session.open(
                    scenario_snapshot=snapshot,
                    actor_id=command.actor_id,
                    at=occurred_at,
                )
            except SessionRuleViolation as error:
                raise OpenSessionError(str(error)) from error

            after_json = _lifecycle_projection(updated)
            unit_of_work.session.save(updated)
            unit_of_work.audit_events.add(
                _build_opened_event(
                    updated,
                    before_json=before_json,
                    after_json=after_json,
                    command=command,
                    occurred_at=occurred_at,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()

        if updated.active_configuration_version_id is None:
            raise AssertionError("An opened session must have an active config.")
        if updated.opened_at is None:
            raise AssertionError("An opened session must have opened_at.")
        return OpenSessionResult(
            session_id=updated.session_id,
            status=updated.status,
            active_configuration_version_id=(
                updated.active_configuration_version_id
            ),
            opened_at=updated.opened_at,
        )


def _lifecycle_projection(session: Session) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session.session_id,
        "status": session.status.value,
        "active_configuration_version_id": (
            session.active_configuration_version_id
        ),
        "opens_at": session.opens_at,
        "closes_at": session.closes_at,
        "opened_at": session.opened_at,
        "closed_at": session.closed_at,
    }


def _build_opened_event(
    session: Session,
    *,
    before_json: dict[str, object],
    after_json: dict[str, object],
    command: OpenSessionCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    source_metadata = {"schema_version": 1, "use_case": "open_session"}
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": session.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.OPENED.value,
        "entity_type": "session",
        "entity_id": session.session_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "causation_event_id": command.causation_event_id,
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
        action=AuditAction.OPENED,
        entity_type="session",
        entity_id=session.session_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        before_json=before_json,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
