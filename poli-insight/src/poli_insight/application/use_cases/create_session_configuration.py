"""Build and append one complete immutable session configuration."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import combinations
from typing import cast

from poli_insight.application.ports.algorithm_repository import (
    AlgorithmImplementation,
)
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AlgorithmRole,
    AuditAction,
    MissingGroupPolicy,
    QuestionType,
    ResponseFormat,
    ResponseTargetType,
    ScenarioSnapshotStatus,
    SessionStatus,
)
from poli_insight.domain.scenario import ScenarioSnapshot
from poli_insight.domain.session import (
    ResponseQuestionDefinition,
    SessionAlgorithmConfig,
    SessionConfigurationVersion,
    SessionRuleViolation,
    SessionStakeholderGroup,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
JsonObject = Mapping[str, object]
_GROUP_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_-]*")


class CreateSessionConfigurationError(ValueError):
    """Expected failure while building a session configuration."""


@dataclass(frozen=True, slots=True)
class StakeholderGroupInput:
    group_key: str
    name: str
    description: str
    allocation_units: int
    required: bool = False

    def __post_init__(self) -> None:
        if _GROUP_KEY_PATTERN.fullmatch(self.group_key) is None:
            raise CreateSessionConfigurationError(
                "Stakeholder group keys must start with a letter and contain "
                "only lowercase letters, numbers, underscores, or hyphens."
            )
        if not self.name.strip() or self.name != self.name.strip():
            raise CreateSessionConfigurationError(
                "Stakeholder group names cannot be empty or contain "
                "surrounding whitespace."
            )
        if not self.description.strip() or self.description != self.description.strip():
            raise CreateSessionConfigurationError(
                "Stakeholder group descriptions cannot be empty or contain "
                "surrounding whitespace."
            )
        if isinstance(self.allocation_units, bool) or not isinstance(
            self.allocation_units, int
        ):
            raise CreateSessionConfigurationError(
                "Stakeholder allocation units must be integers."
            )
        if self.allocation_units < 0:
            raise CreateSessionConfigurationError(
                "Stakeholder allocation units cannot be negative."
            )


@dataclass(frozen=True, slots=True)
class AlgorithmSelectionInput:
    algorithm_implementation_id: str
    role: AlgorithmRole
    parameter_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.algorithm_implementation_id.strip():
            raise CreateSessionConfigurationError(
                "Algorithm implementation ID cannot be empty."
            )
        object.__setattr__(self, "parameter_json", dict(self.parameter_json))


@dataclass(frozen=True, slots=True)
class CreateSessionConfigurationCommand:
    session_id: str
    actor_id: str
    response_format: ResponseFormat
    response_target_type: ResponseTargetType
    scale_id: str
    stakeholder_groups: tuple[StakeholderGroupInput, ...]
    algorithms: tuple[AlgorithmSelectionInput, ...]
    allow_resubmissions: bool = False
    max_submissions_per_participant: int = 1
    allow_incomplete_submission: bool = False
    minimum_valid_submissions: int = 1
    missing_group_policy: MissingGroupPolicy = MissingGroupPolicy.FAIL
    consistency_threshold: Decimal | None = Decimal("0.10")
    consent_required: bool = False
    consent_version: str = "1"
    consent_title: str = "Research participation consent"
    consent_statement: str = ""
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("actor_id", self.actor_id),
            ("scale_id", self.scale_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise CreateSessionConfigurationError(
                    f"{field_name} cannot be empty."
                )
        if self.consent_required:
            for field_name, value in (
                ("consent_version", self.consent_version),
                ("consent_title", self.consent_title),
                ("consent_statement", self.consent_statement),
            ):
                if not value.strip():
                    raise CreateSessionConfigurationError(
                        f"{field_name} is required when consent is enabled."
                    )


@dataclass(frozen=True, slots=True)
class CreateSessionConfigurationResult:
    session_id: str
    configuration_version_id: str
    version_number: int
    config_hash: str
    question_count: int
    stakeholder_group_count: int
    session_status: SessionStatus


class CreateSessionConfiguration:
    """Construct a complete version from administrator inputs and a snapshot."""

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
        command: CreateSessionConfigurationCommand,
    ) -> CreateSessionConfigurationResult:
        occurred_at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            if session is None:
                raise CreateSessionConfigurationError(
                    f"Session {command.session_id!r} does not exist."
                )
            snapshot = unit_of_work.scenarios.get_by_id(
                session.scenario_snapshot_id
            )
            if snapshot is None:
                raise CreateSessionConfigurationError(
                    "The session's scenario snapshot no longer exists."
                )
            if snapshot.status != ScenarioSnapshotStatus.READY:
                raise CreateSessionConfigurationError(
                    "Configurations require a ready scenario snapshot."
                )

            implementations = unit_of_work.algorithms.get_many(
                tuple(
                    selection.algorithm_implementation_id
                    for selection in command.algorithms
                )
            )
            _validate_algorithm_selections(command, implementations)
            configuration = self._build_configuration(
                session_id=session.session_id,
                scenario_snapshot=snapshot,
                version_number=max(
                    (item.version_number for item in session.configurations),
                    default=0,
                )
                + 1,
                command=command,
                implementations=implementations,
                occurred_at=occurred_at,
            )
            try:
                updated = session.add_configuration(
                    configuration,
                    actor_id=command.actor_id,
                    at=occurred_at,
                )
            except SessionRuleViolation as error:
                raise CreateSessionConfigurationError(str(error)) from error

            unit_of_work.session.save(updated)
            unit_of_work.audit_events.add(
                _configuration_created_event(
                    configuration,
                    command=command,
                    occurred_at=occurred_at,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()

        return CreateSessionConfigurationResult(
            session_id=updated.session_id,
            configuration_version_id=configuration.configuration_version_id,
            version_number=configuration.version_number,
            config_hash=configuration.config_hash,
            question_count=len(configuration.question_definitions),
            stakeholder_group_count=len(configuration.stakeholder_groups),
            session_status=updated.status,
        )

    def _build_configuration(
        self,
        *,
        session_id: str,
        scenario_snapshot: ScenarioSnapshot,
        version_number: int,
        command: CreateSessionConfigurationCommand,
        implementations: tuple[AlgorithmImplementation, ...],
        occurred_at: datetime,
    ) -> SessionConfigurationVersion:
        configuration_id = self._id_factory()
        algorithm_by_id = {
            item.algorithm_implementation_id: item
            for item in implementations
        }
        algorithms = tuple(
            SessionAlgorithmConfig(
                session_algorithm_config_id=self._id_factory(),
                configuration_version_id=configuration_id,
                algorithm_implementation_id=(
                    selection.algorithm_implementation_id
                ),
                role=selection.role,
                execution_order=0,
                parameter_json=dict(selection.parameter_json),
                parameter_schema_version=1,
                parameter_hash=hash_json(selection.parameter_json),
            )
            for selection in command.algorithms
        )
        groups = tuple(
            SessionStakeholderGroup(
                session_stakeholder_group_id=self._id_factory(),
                configuration_version_id=configuration_id,
                group_key=item.group_key,
                name=item.name,
                description=item.description,
                allocation_units=item.allocation_units,
                display_order=index,
                is_active=True,
                created_at=occurred_at,
                created_by=command.actor_id,
            )
            for index, item in enumerate(command.stakeholder_groups)
        )
        questions = _build_questions(
            scenario_snapshot,
            configuration_id=configuration_id,
            response_format=command.response_format,
            response_target_type=command.response_target_type,
            scale_id=command.scale_id,
            id_factory=self._id_factory,
        )
        configuration_json = {
            "schema_version": 1,
            "response_format": command.response_format.value,
            "response_target_type": command.response_target_type.value,
            "scale_id": command.scale_id,
            "allow_resubmissions": command.allow_resubmissions,
            "max_submissions_per_participant": (
                command.max_submissions_per_participant
            ),
            "allow_incomplete_submission": (
                command.allow_incomplete_submission
            ),
            "minimum_valid_submissions": command.minimum_valid_submissions,
            "missing_group_policy": command.missing_group_policy.value,
            "required_group_keys": sorted(
                item.group_key
                for item in command.stakeholder_groups
                if item.required
            ),
            "consistency_threshold": (
                None
                if command.consistency_threshold is None
                else str(command.consistency_threshold)
            ),
            "consent": {
                "required": command.consent_required,
                "version": command.consent_version.strip(),
                "title": command.consent_title.strip(),
                "statement": command.consent_statement.strip(),
            },
            "stakeholder_groups": [
                {
                    "group_key": item.group_key,
                    "name": item.name,
                    "description": item.description,
                    "allocation_units": item.allocation_units,
                    "required": item.required,
                }
                for item in command.stakeholder_groups
            ],
            "algorithms": [
                {
                    "implementation_id": selection.algorithm_implementation_id,
                    "stable_key": algorithm_by_id[
                        selection.algorithm_implementation_id
                    ].stable_key,
                    "role": selection.role.value,
                    "parameter_json": dict(selection.parameter_json),
                }
                for selection in command.algorithms
            ],
            "questions": [
                {
                    "question_key": item.question_key,
                    "question_type": item.question_type.value,
                    "criterion_id": item.criterion_id,
                    "left_criterion_id": item.left_criterion_id,
                    "right_criterion_id": item.right_criterion_id,
                    "alternative_id": item.alternative_id,
                    "scale_id": item.scale_id,
                    "required": item.required,
                    "prompt": item.prompt_snapshot,
                }
                for item in questions
            ],
        }
        return SessionConfigurationVersion(
            configuration_version_id=configuration_id,
            session_id=session_id,
            version_number=version_number,
            scenario_snapshot_id=scenario_snapshot.scenario_snapshot_id,
            response_format=command.response_format,
            response_target_type=command.response_target_type,
            scale_id=command.scale_id,
            allow_resubmissions=command.allow_resubmissions,
            max_submissions_per_participant=(
                command.max_submissions_per_participant
            ),
            allow_incomplete_submission=command.allow_incomplete_submission,
            minimum_valid_submissions=command.minimum_valid_submissions,
            missing_group_policy=command.missing_group_policy,
            required_group_policy_json={
                "required_group_keys": configuration_json[
                    "required_group_keys"
                ]
            },
            consistency_threshold=command.consistency_threshold,
            configuration_json=configuration_json,
            schema_version=1,
            config_hash=hash_json(configuration_json),
            created_at=occurred_at,
            created_by=command.actor_id,
            stakeholder_groups=groups,
            algorithm_configs=algorithms,
            question_definitions=questions,
        )


def _validate_algorithm_selections(
    command: CreateSessionConfigurationCommand,
    implementations: tuple[AlgorithmImplementation, ...],
) -> None:
    selected_ids = {
        item.algorithm_implementation_id for item in command.algorithms
    }
    if len(selected_ids) != len(command.algorithms):
        raise CreateSessionConfigurationError(
            "An algorithm implementation can only be selected once."
        )
    implementation_by_id = {
        item.algorithm_implementation_id: item for item in implementations
    }
    if selected_ids != set(implementation_by_id):
        raise CreateSessionConfigurationError(
            "One or more selected algorithm implementations do not exist."
        )
    for selection in command.algorithms:
        implementation = implementation_by_id[
            selection.algorithm_implementation_id
        ]
        if not implementation.active:
            raise CreateSessionConfigurationError(
                f"Algorithm {implementation.stable_key!r} is retired."
            )
        if implementation.role != selection.role:
            raise CreateSessionConfigurationError(
                f"Algorithm {implementation.stable_key!r} does not provide "
                f"the {selection.role.value!r} role."
            )
        supported_formats = implementation.capabilities_json.get(
            "response_formats"
        )
        if (
            isinstance(supported_formats, list)
            and command.response_format.value not in supported_formats
        ):
            raise CreateSessionConfigurationError(
                f"Algorithm {implementation.stable_key!r} does not support "
                f"{command.response_format.value!r} responses."
            )
        supported_targets = implementation.capabilities_json.get(
            "response_targets"
        )
        if (
            isinstance(supported_targets, list)
            and command.response_target_type.value not in supported_targets
        ):
            raise CreateSessionConfigurationError(
                f"Algorithm {implementation.stable_key!r} does not support "
                f"{command.response_target_type.value!r} response targets."
            )


def _build_questions(
    snapshot: ScenarioSnapshot,
    *,
    configuration_id: str,
    response_format: ResponseFormat,
    response_target_type: ResponseTargetType,
    scale_id: str,
    id_factory: IdFactory,
) -> tuple[ResponseQuestionDefinition, ...]:
    scale_by_id = {item.scale_id: item for item in snapshot.scales}
    if scale_id not in scale_by_id:
        raise CreateSessionConfigurationError(
            "The selected response scale is outside the scenario snapshot."
        )
    scale = scale_by_id[scale_id]
    if not scale.values:
        raise CreateSessionConfigurationError(
            "The selected response scale has no values. Choose an application "
            "scale or another complete scenario scale."
        )
    compatible_formats = {
        "pairwise": ResponseFormat.PAIRWISE,
        "pairwise_comparison": ResponseFormat.PAIRWISE,
        "direct_rating": ResponseFormat.DIRECT_RATING,
        "criterion_linguistic_rating": ResponseFormat.DIRECT_RATING,
    }
    expected_format = compatible_formats.get(scale.scale_type.strip().lower())
    if expected_format is not None and response_format != expected_format:
        raise CreateSessionConfigurationError(
            "The selected response scale is incompatible with the participant "
            "response method."
        )
    targets: list[dict[str, object]] = []
    if response_format == ResponseFormat.PAIRWISE:
        if response_target_type != ResponseTargetType.CRITERION:
            raise CreateSessionConfigurationError(
                "Pairwise responses currently require criterion targets."
            )
        criterion_by_id = {
            item.criterion_id: item for item in snapshot.criteria
        }
        for left_id, right_id in combinations(sorted(criterion_by_id), 2):
            left = criterion_by_id[left_id]
            right = criterion_by_id[right_id]
            targets.append(
                {
                    "key": f"criterion_pair.{left.criterion_key}.{right.criterion_key}",
                    "type": QuestionType.CRITERION_PAIR,
                    "prompt": f"Compare {left.name} with {right.name}.",
                    "left_criterion_id": left_id,
                    "right_criterion_id": right_id,
                    "scale_id": scale_id,
                }
            )
    elif response_format == ResponseFormat.DIRECT_RATING:
        if response_target_type == ResponseTargetType.CRITERION:
            for criterion in snapshot.criteria:
                targets.append(
                    {
                        "key": f"criterion_rating.{criterion.criterion_key}",
                        "type": QuestionType.CRITERION_RATING,
                        "prompt": f"Rate the importance of {criterion.name}.",
                        "criterion_id": criterion.criterion_id,
                        "scale_id": scale_id,
                    }
                )
        else:
            for alternative in snapshot.alternatives:
                targets.append(
                    {
                        "key": (
                            "alternative_rating."
                            f"{alternative.alternative_key}"
                        ),
                        "type": QuestionType.ALTERNATIVE_RATING,
                        "prompt": f"Rate {alternative.name}.",
                        "alternative_id": alternative.alternative_id,
                        "scale_id": scale_id,
                    }
                )
    elif response_format == ResponseFormat.DIRECT_RANKING:
        if response_target_type != ResponseTargetType.ALTERNATIVE:
            raise CreateSessionConfigurationError(
                "Direct ranking requires alternative targets."
            )
        for alternative in snapshot.alternatives:
            targets.append(
                {
                    "key": f"alternative_rank.{alternative.alternative_key}",
                    "type": QuestionType.ALTERNATIVE_RANK,
                    "prompt": f"Assign a rank to {alternative.name}.",
                    "alternative_id": alternative.alternative_id,
                }
            )
    else:
        raise CreateSessionConfigurationError(
            f"Unsupported response format {response_format.value!r}."
        )
    if not targets:
        raise CreateSessionConfigurationError(
            "The selected response contract did not produce any questions."
        )
    return tuple(
        ResponseQuestionDefinition(
            question_definition_id=id_factory(),
            configuration_version_id=configuration_id,
            question_key=str(target["key"]),
            question_type=cast(QuestionType, target["type"]),
            display_order=index,
            required=True,
            prompt_snapshot=str(target["prompt"]),
            criterion_id=cast(str | None, target.get("criterion_id")),
            left_criterion_id=cast(
                str | None, target.get("left_criterion_id")
            ),
            right_criterion_id=cast(
                str | None, target.get("right_criterion_id")
            ),
            alternative_id=cast(str | None, target.get("alternative_id")),
            scale_id=cast(str | None, target.get("scale_id")),
            metadata_json={"generated": True},
        )
        for index, target in enumerate(targets)
    )


def _configuration_created_event(
    configuration: SessionConfigurationVersion,
    *,
    command: CreateSessionConfigurationCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    after_json = {
        "schema_version": 1,
        "session_id": configuration.session_id,
        "configuration_version_id": configuration.configuration_version_id,
        "version_number": configuration.version_number,
        "config_hash": configuration.config_hash,
        "question_count": len(configuration.question_definitions),
        "stakeholder_group_count": len(configuration.stakeholder_groups),
    }
    source_metadata = {
        "schema_version": 1,
        "use_case": "create_session_configuration",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": configuration.session_id,
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
        session_id=configuration.session_id,
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
