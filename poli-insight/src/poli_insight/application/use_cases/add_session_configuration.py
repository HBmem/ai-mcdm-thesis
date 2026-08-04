"""Application use case for appending a session configuration version."""

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
    ActorType,
    AuditAction,
    ScenarioSnapshotStatus,
    SessionStatus,
)
from poli_insight.domain.scenario import ScenarioSnapshot
from poli_insight.domain.session import (
    Session,
    SessionConfigurationVersion,
    SessionRuleViolation,
)


UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class AddSessionConfigurationError(ValueError):
    """Expected application failure while adding a configuration version."""


@dataclass(frozen=True, slots=True)
class AddSessionConfigurationCommand:
    """Input for appending and optionally activating one configuration."""

    session_id: str
    configuration: SessionConfigurationVersion
    actor_id: str
    activate: bool = False
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
                raise AddSessionConfigurationError(
                    f"{field_name} cannot be empty."
                )


@dataclass(frozen=True, slots=True)
class AddSessionConfigurationResult:
    """Identity and activation state of the appended configuration."""

    session_id: str
    configuration_version_id: str
    version_number: int
    config_hash: str
    activated: bool
    active_configuration_version_id: str | None
    session_status: SessionStatus


class AddSessionConfiguration:
    """Append an immutable configuration while holding the session lock."""

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
        command: AddSessionConfigurationCommand,
    ) -> AddSessionConfigurationResult:
        occurred_at = self._clock()

        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            if session is None:
                raise AddSessionConfigurationError(
                    f"Session {command.session_id!r} does not exist."
                )

            snapshot = unit_of_work.scenarios.get_by_id(
                session.scenario_snapshot_id
            )
            if snapshot is None:
                raise AddSessionConfigurationError(
                    "The session's scenario snapshot no longer exists."
                )
            if snapshot.status != ScenarioSnapshotStatus.READY:
                raise AddSessionConfigurationError(
                    "Configurations can only reference a ready scenario "
                    "snapshot."
                )
            _validate_snapshot_references(command.configuration, snapshot)

            try:
                updated = session.add_configuration(
                    command.configuration,
                    actor_id=command.actor_id,
                    at=occurred_at,
                )
                if command.activate:
                    updated = updated.activate_configuration(
                        command.configuration.configuration_version_id,
                        actor_id=command.actor_id,
                        at=occurred_at,
                    )
            except SessionRuleViolation as error:
                raise AddSessionConfigurationError(str(error)) from error

            stored_configuration = next(
                configuration
                for configuration in updated.configurations
                if configuration.configuration_version_id
                == command.configuration.configuration_version_id
            )
            unit_of_work.session.save(updated)
            unit_of_work.audit_events.add(
                _build_configuration_event(
                    updated,
                    stored_configuration,
                    command=command,
                    occurred_at=occurred_at,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()

        return AddSessionConfigurationResult(
            session_id=updated.session_id,
            configuration_version_id=(
                stored_configuration.configuration_version_id
            ),
            version_number=stored_configuration.version_number,
            config_hash=stored_configuration.config_hash,
            activated=stored_configuration.is_activated,
            active_configuration_version_id=(
                updated.active_configuration_version_id
            ),
            session_status=updated.status,
        )


def _validate_snapshot_references(
    configuration: SessionConfigurationVersion,
    snapshot: ScenarioSnapshot,
) -> None:
    if configuration.scenario_snapshot_id != snapshot.scenario_snapshot_id:
        raise AddSessionConfigurationError(
            "Configuration references a different scenario snapshot."
        )

    criterion_ids = {item.criterion_id for item in snapshot.criteria}
    alternative_ids = {item.alternative_id for item in snapshot.alternatives}
    scale_ids = {item.scale_id for item in snapshot.scales}
    if configuration.scale_id not in scale_ids:
        raise AddSessionConfigurationError(
            "Configuration references a scale outside its scenario snapshot."
        )

    for question in configuration.question_definitions:
        referenced_criteria = (
            question.criterion_id,
            question.left_criterion_id,
            question.right_criterion_id,
        )
        if any(
            value is not None and value not in criterion_ids
            for value in referenced_criteria
        ):
            raise AddSessionConfigurationError(
                f"Question {question.question_key!r} references a criterion "
                "outside the scenario snapshot."
            )
        if (
            question.alternative_id is not None
            and question.alternative_id not in alternative_ids
        ):
            raise AddSessionConfigurationError(
                f"Question {question.question_key!r} references an "
                "alternative outside the scenario snapshot."
            )
        if question.scale_id is not None and question.scale_id not in scale_ids:
            raise AddSessionConfigurationError(
                f"Question {question.question_key!r} references a scale "
                "outside the scenario snapshot."
            )


def _build_configuration_event(
    session: Session,
    configuration: SessionConfigurationVersion,
    *,
    command: AddSessionConfigurationCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    after_json = {
        "schema_version": 1,
        "session_id": session.session_id,
        "configuration_version_id": configuration.configuration_version_id,
        "version_number": configuration.version_number,
        "scenario_snapshot_id": configuration.scenario_snapshot_id,
        "config_hash": configuration.config_hash,
        "activated": configuration.is_activated,
        "activated_at": configuration.activated_at,
        "active_configuration_version_id": (
            session.active_configuration_version_id
        ),
    }
    source_metadata = {
        "schema_version": 1,
        "use_case": "add_session_configuration",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": session.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.CREATED.value,
        "entity_type": "session_configuration_version",
        "entity_id": configuration.configuration_version_id,
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
        entity_type="session_configuration_version",
        entity_id=configuration.configuration_version_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
