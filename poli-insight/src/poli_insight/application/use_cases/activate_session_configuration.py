"""Activate a reviewed immutable session configuration."""

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
from poli_insight.domain.session import SessionRuleViolation

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class ActivateSessionConfigurationError(ValueError):
    """Expected failure while activating a configuration."""


@dataclass(frozen=True, slots=True)
class ActivateSessionConfigurationCommand:
    session_id: str
    configuration_version_id: str
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("configuration_version_id", self.configuration_version_id),
            ("actor_id", self.actor_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise ActivateSessionConfigurationError(
                    f"{field_name} cannot be empty."
                )


@dataclass(frozen=True, slots=True)
class ActivateSessionConfigurationResult:
    session_id: str
    configuration_version_id: str
    version_number: int
    config_hash: str
    activated_at: datetime
    session_status: SessionStatus


class ActivateSessionConfiguration:
    """Activate one version while the session is still configurable."""

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

    def execute(
        self,
        command: ActivateSessionConfigurationCommand,
    ) -> ActivateSessionConfigurationResult:
        occurred_at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            if session is None:
                raise ActivateSessionConfigurationError(
                    f"Session {command.session_id!r} does not exist."
                )
            try:
                updated = session.activate_configuration(
                    command.configuration_version_id,
                    actor_id=command.actor_id,
                    at=occurred_at,
                )
            except SessionRuleViolation as error:
                raise ActivateSessionConfigurationError(str(error)) from error
            configuration = updated.active_configuration
            if configuration is None:
                raise AssertionError(
                    "Configuration activation did not set an active version."
                )
            unit_of_work.session.save(updated)
            unit_of_work.audit_events.add(
                _activation_event(
                    updated.session_id,
                    configuration.configuration_version_id,
                    version_number=configuration.version_number,
                    config_hash=configuration.config_hash,
                    previous_configuration_id=(
                        session.active_configuration_version_id
                    ),
                    command=command,
                    occurred_at=occurred_at,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()
        return ActivateSessionConfigurationResult(
            session_id=updated.session_id,
            configuration_version_id=configuration.configuration_version_id,
            version_number=configuration.version_number,
            config_hash=configuration.config_hash,
            activated_at=occurred_at,
            session_status=updated.status,
        )


def _activation_event(
    session_id: str,
    configuration_id: str,
    *,
    version_number: int,
    config_hash: str,
    previous_configuration_id: str | None,
    command: ActivateSessionConfigurationCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    before_json = {
        "schema_version": 1,
        "active_configuration_version_id": previous_configuration_id,
    }
    after_json = {
        "schema_version": 1,
        "active_configuration_version_id": configuration_id,
        "version_number": version_number,
        "config_hash": config_hash,
    }
    source_metadata = {
        "schema_version": 1,
        "use_case": "activate_session_configuration",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.ACTIVATED.value,
        "entity_type": "session_configuration_version",
        "entity_id": configuration_id,
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
        session_id=session_id,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=AuditAction.ACTIVATED,
        entity_type="session_configuration_version",
        entity_id=configuration_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        before_json=before_json,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
