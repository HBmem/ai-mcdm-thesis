"""Session lifecycle and immutable calculation configuration domain models.

The operational :class:`Session` is modeled as an immutable value: lifecycle
methods return a replacement instance instead of mutating the original.  Each
configuration version is also immutable and owns the stakeholder groups,
algorithm selections, and response questions used for that version.  This
keeps historical submissions pinned to an unchanged calculation contract.
"""

from __future__ import annotations

import re
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Self

from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    AccessCodeMode,
    AlgorithmRole,
    Discoverability,
    EnrollmentMode,
    MissingGroupPolicy,
    QuestionType,
    ResponseFormat,
    ResponseTargetType,
    ScenarioSnapshotStatus,
    SessionStatus,
    StakeholderSelectionMode,
)
from poli_insight.domain.scenario import ScenarioSnapshot


JsonObject = Mapping[str, Any]
DEFAULT_ALLOCATION_TOTAL_UNITS = 10_000
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class SessionRuleViolation(ValueError):
    """Raised when an operation violates a session business rule."""


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise SessionRuleViolation(f"{field_name} cannot be empty.")
    if value != value.strip():
        raise SessionRuleViolation(
            f"{field_name} cannot contain leading or trailing whitespace."
        )


def _require_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and (
        value.tzinfo is None or value.utcoffset() is None
    ):
        raise SessionRuleViolation(
            f"{field_name} must include timezone information."
        )


def _require_actor(actor_id: str) -> None:
    _require_text(actor_id, "Actor ID")


def _require_sha256(value: str, field_name: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise SessionRuleViolation(
            f"{field_name} must be a lowercase hexadecimal SHA-256 digest."
        )


def _require_nonnegative_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SessionRuleViolation(
            f"{field_name} must be a nonnegative integer."
        )


@dataclass(frozen=True, slots=True)
class SessionAlgorithmConfig:
    """One versioned algorithm selection within a session configuration."""

    session_algorithm_config_id: str
    configuration_version_id: str
    algorithm_implementation_id: str
    role: AlgorithmRole
    execution_order: int
    parameter_json: JsonObject
    parameter_schema_version: int
    parameter_hash: str

    def __post_init__(self) -> None:
        _require_text(
            self.session_algorithm_config_id,
            "Session algorithm configuration ID",
        )
        _require_text(
            self.configuration_version_id,
            "Configuration version ID",
        )
        _require_text(
            self.algorithm_implementation_id,
            "Algorithm implementation ID",
        )
        _require_nonnegative_integer(
            self.execution_order,
            "Algorithm execution order",
        )
        if self.parameter_schema_version < 1:
            raise SessionRuleViolation(
                "Algorithm parameter schema version must be at least 1."
            )
        self.validate_integrity()

    def validate_integrity(self) -> None:
        """Verify that parameters still match their immutable digest."""

        _require_sha256(self.parameter_hash, "Algorithm parameter hash")
        if hash_json(self.parameter_json) != self.parameter_hash:
            raise SessionRuleViolation(
                "Algorithm parameter JSON does not match parameter_hash."
            )


@dataclass(frozen=True, slots=True)
class SessionStakeholderGroup:
    """A stakeholder group and its exact allocation for one configuration."""

    session_stakeholder_group_id: str
    configuration_version_id: str
    group_key: str
    name: str
    description: str
    allocation_units: int
    display_order: int
    is_active: bool
    created_at: datetime
    created_by: str
    within_group_algorithm_config_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(
            self.session_stakeholder_group_id,
            "Session stakeholder group ID",
        )
        _require_text(
            self.configuration_version_id,
            "Configuration version ID",
        )
        _require_text(self.group_key, "Stakeholder group key")
        _require_text(self.name, "Stakeholder group name")
        _require_text(self.description, "Stakeholder group description")
        _require_optional_text(
            self.within_group_algorithm_config_id,
            "Within-group algorithm configuration ID",
        )
        _require_nonnegative_integer(
            self.allocation_units,
            "Stakeholder allocation units",
        )
        _require_nonnegative_integer(
            self.display_order,
            "Stakeholder display order",
        )
        _require_aware_datetime(self.created_at, "Stakeholder created_at")
        _require_text(self.created_by, "Stakeholder creator")


@dataclass(frozen=True, slots=True)
class ResponseQuestionDefinition:
    """The exact response unit expected from a participant."""

    question_definition_id: str
    configuration_version_id: str
    question_key: str
    question_type: QuestionType
    display_order: int
    required: bool
    prompt_snapshot: str
    metadata_json: JsonObject = field(default_factory=dict)
    criterion_id: str | None = None
    left_criterion_id: str | None = None
    right_criterion_id: str | None = None
    alternative_id: str | None = None
    scale_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.question_definition_id, "Question definition ID")
        _require_text(
            self.configuration_version_id,
            "Configuration version ID",
        )
        _require_text(self.question_key, "Question key")
        _require_text(self.prompt_snapshot, "Question prompt snapshot")
        _require_nonnegative_integer(
            self.display_order,
            "Question display order",
        )
        for field_name, value in (
            ("criterion_id", self.criterion_id),
            ("left_criterion_id", self.left_criterion_id),
            ("right_criterion_id", self.right_criterion_id),
            ("alternative_id", self.alternative_id),
            ("scale_id", self.scale_id),
        ):
            _require_optional_text(value, field_name)
        self._validate_targets()

    def _validate_targets(self) -> None:
        if self.question_type is QuestionType.CRITERION_PAIR:
            if (
                self.criterion_id is not None
                or self.alternative_id is not None
                or self.left_criterion_id is None
                or self.right_criterion_id is None
                or self.scale_id is None
            ):
                raise SessionRuleViolation(
                    "A criterion-pair question requires left criterion, right "
                    "criterion, and scale IDs, with no direct target."
                )
            if self.left_criterion_id == self.right_criterion_id:
                raise SessionRuleViolation(
                    "A criterion-pair question must reference two different "
                    "criteria."
                )
            if self.left_criterion_id > self.right_criterion_id:
                raise SessionRuleViolation(
                    "Criterion-pair targets must use canonical ascending ID "
                    "order."
                )
            return

        if self.question_type is QuestionType.CRITERION_RATING:
            if (
                self.criterion_id is None
                or self.left_criterion_id is not None
                or self.right_criterion_id is not None
                or self.alternative_id is not None
                or self.scale_id is None
            ):
                raise SessionRuleViolation(
                    "A criterion-rating question requires one criterion and "
                    "one scale, with no pair or alternative target."
                )
            return

        if self.question_type is QuestionType.ALTERNATIVE_RATING:
            if (
                self.alternative_id is None
                or self.criterion_id is not None
                or self.left_criterion_id is not None
                or self.right_criterion_id is not None
                or self.scale_id is None
            ):
                raise SessionRuleViolation(
                    "An alternative-rating question requires one alternative "
                    "and one scale, with no criterion target."
                )
            return

        if self.question_type is QuestionType.ALTERNATIVE_RANK:
            if (
                self.alternative_id is None
                or self.criterion_id is not None
                or self.left_criterion_id is not None
                or self.right_criterion_id is not None
                or self.scale_id is not None
            ):
                raise SessionRuleViolation(
                    "An alternative-rank question requires one alternative, "
                    "no criterion target, and no scale."
                )
            return

        raise SessionRuleViolation(
            f"Unsupported question type: {self.question_type!r}."
        )


@dataclass(frozen=True, slots=True)
class SessionConfigurationVersion:
    """A complete, immutable submission and calculation contract."""

    configuration_version_id: str
    session_id: str
    version_number: int
    scenario_snapshot_id: str

    response_format: ResponseFormat
    response_target_type: ResponseTargetType
    scale_id: str
    allow_resubmissions: bool
    max_submissions_per_participant: int
    allow_incomplete_submission: bool
    minimum_valid_submissions: int
    missing_group_policy: MissingGroupPolicy
    required_group_policy_json: JsonObject
    consistency_threshold: Decimal | None

    configuration_json: JsonObject
    schema_version: int
    config_hash: str

    created_at: datetime
    created_by: str
    stakeholder_groups: tuple[SessionStakeholderGroup, ...]
    algorithm_configs: tuple[SessionAlgorithmConfig, ...]
    question_definitions: tuple[ResponseQuestionDefinition, ...]

    activated_at: datetime | None = None
    activated_by: str | None = None
    allocation_total_units: int = DEFAULT_ALLOCATION_TOTAL_UNITS

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_submission_rules()
        self._validate_content_integrity()
        self._validate_activation_metadata()
        self._validate_children()

    @property
    def is_activated(self) -> bool:
        return self.activated_at is not None

    def activate(self, *, actor_id: str, at: datetime) -> Self:
        """Return this configuration finalized for use by its session."""

        _require_actor(actor_id)
        _require_aware_datetime(at, "Configuration activation time")
        if self.is_activated:
            raise SessionRuleViolation(
                f"Configuration version {self.version_number} is already "
                "activated."
            )
        if at < self.created_at:
            raise SessionRuleViolation(
                "Configuration activation cannot precede creation."
            )
        self.validate_for_activation()
        return replace(self, activated_at=at, activated_by=actor_id)

    def validate_for_activation(self) -> None:
        """Recheck all content used at the calculation boundary."""

        self._validate_content_integrity()
        self._validate_children()

    def _validate_identity(self) -> None:
        _require_text(
            self.configuration_version_id,
            "Configuration version ID",
        )
        _require_text(self.session_id, "Configuration session ID")
        _require_text(
            self.scenario_snapshot_id,
            "Configuration scenario snapshot ID",
        )
        _require_text(self.scale_id, "Configuration scale ID")
        _require_text(self.created_by, "Configuration creator")
        _require_aware_datetime(self.created_at, "Configuration created_at")
        if self.version_number < 1:
            raise SessionRuleViolation(
                "Configuration version number must be at least 1."
            )
        if self.schema_version < 1:
            raise SessionRuleViolation(
                "Configuration schema version must be at least 1."
            )

    def _validate_submission_rules(self) -> None:
        if self.max_submissions_per_participant < 1:
            raise SessionRuleViolation(
                "Maximum submissions per participant must be at least 1."
            )
        if (
            not self.allow_resubmissions
            and self.max_submissions_per_participant != 1
        ):
            raise SessionRuleViolation(
                "A configuration that disallows resubmission must allow "
                "exactly one submission per participant."
            )
        if (
            self.allow_resubmissions
            and self.max_submissions_per_participant < 2
        ):
            raise SessionRuleViolation(
                "A configuration that allows resubmission must allow at least "
                "two submissions per participant."
            )
        if self.minimum_valid_submissions < 1:
            raise SessionRuleViolation(
                "Minimum valid submissions must be at least 1."
            )
        if self.consistency_threshold is not None and not (
            Decimal("0") <= self.consistency_threshold <= Decimal("1")
        ):
            raise SessionRuleViolation(
                "Consistency threshold must be between 0 and 1."
            )
        _require_nonnegative_integer(
            self.allocation_total_units,
            "Allocation total units",
        )
        if self.allocation_total_units == 0:
            raise SessionRuleViolation(
                "Allocation total units must be greater than zero."
            )

    def _validate_content_integrity(self) -> None:
        _require_sha256(self.config_hash, "Configuration hash")
        if hash_json(self.configuration_json) != self.config_hash:
            raise SessionRuleViolation(
                "Configuration JSON does not match config_hash."
            )

    def _validate_activation_metadata(self) -> None:
        _require_aware_datetime(
            self.activated_at,
            "Configuration activated_at",
        )
        _require_optional_text(
            self.activated_by,
            "Configuration activator",
        )
        if (self.activated_at is None) != (self.activated_by is None):
            raise SessionRuleViolation(
                "Configuration activation time and actor must be set together."
            )
        if (
            self.activated_at is not None
            and self.activated_at < self.created_at
        ):
            raise SessionRuleViolation(
                "Configuration activation cannot precede creation."
            )

    def _validate_children(self) -> None:
        self._validate_child_ownership()
        self._validate_unique_children()
        self._validate_algorithms()
        self._validate_allocations()
        self._validate_questions()

    def _validate_child_ownership(self) -> None:
        for group in self.stakeholder_groups:
            if group.configuration_version_id != self.configuration_version_id:
                raise SessionRuleViolation(
                    f"Stakeholder group {group.group_key!r} belongs to a "
                    "different configuration version."
                )
        for algorithm in self.algorithm_configs:
            if (
                algorithm.configuration_version_id
                != self.configuration_version_id
            ):
                raise SessionRuleViolation(
                    "Algorithm configuration belongs to a different session "
                    "configuration version."
                )
        for question in self.question_definitions:
            if (
                question.configuration_version_id
                != self.configuration_version_id
            ):
                raise SessionRuleViolation(
                    f"Question {question.question_key!r} belongs to a "
                    "different configuration version."
                )

    def _validate_unique_children(self) -> None:
        _require_unique(
            (group.session_stakeholder_group_id for group in self.stakeholder_groups),
            "Stakeholder group IDs",
        )
        _require_unique(
            (group.group_key for group in self.stakeholder_groups),
            "Stakeholder group keys",
        )
        _require_unique(
            (group.display_order for group in self.stakeholder_groups),
            "Stakeholder group display orders",
        )
        _require_unique(
            (
                algorithm.session_algorithm_config_id
                for algorithm in self.algorithm_configs
            ),
            "Algorithm configuration IDs",
        )
        _require_unique(
            (
                (algorithm.role, algorithm.execution_order)
                for algorithm in self.algorithm_configs
            ),
            "Algorithm role and execution-order combinations",
        )
        _require_unique(
            (
                question.question_definition_id
                for question in self.question_definitions
            ),
            "Question definition IDs",
        )
        _require_unique(
            (question.question_key for question in self.question_definitions),
            "Question keys",
        )
        _require_unique(
            (question.display_order for question in self.question_definitions),
            "Question display orders",
        )

    def _validate_algorithms(self) -> None:
        if not self.algorithm_configs:
            raise SessionRuleViolation(
                "A configuration must select at least one algorithm."
            )
        for algorithm in self.algorithm_configs:
            algorithm.validate_integrity()

        roles = {algorithm.role for algorithm in self.algorithm_configs}
        required_roles = {
            AlgorithmRole.WEIGHTING,
            AlgorithmRole.RANKING,
        }
        missing_roles = required_roles.difference(roles)
        if missing_roles:
            missing = sorted(role.value for role in missing_roles)
            raise SessionRuleViolation(
                f"Configuration is missing required algorithm roles: {missing}."
            )

        algorithm_by_id = {
            algorithm.session_algorithm_config_id: algorithm
            for algorithm in self.algorithm_configs
        }
        for group in self.stakeholder_groups:
            algorithm_id = group.within_group_algorithm_config_id
            if algorithm_id is None:
                continue
            algorithm = algorithm_by_id.get(algorithm_id)
            if algorithm is None:
                raise SessionRuleViolation(
                    f"Stakeholder group {group.group_key!r} references an "
                    "unknown within-group algorithm configuration."
                )
            if algorithm.role is not AlgorithmRole.WITHIN_GROUP_AGGREGATION:
                raise SessionRuleViolation(
                    f"Stakeholder group {group.group_key!r} must reference an "
                    "algorithm with the within-group aggregation role."
                )

    def _validate_allocations(self) -> None:
        active_groups = [
            group for group in self.stakeholder_groups if group.is_active
        ]
        if not active_groups:
            raise SessionRuleViolation(
                "A configuration must contain at least one active stakeholder "
                "group."
            )
        if not any(group.allocation_units > 0 for group in active_groups):
            raise SessionRuleViolation(
                "At least one active stakeholder group must have a positive "
                "allocation."
            )
        actual_total = sum(group.allocation_units for group in active_groups)
        if actual_total != self.allocation_total_units:
            raise SessionRuleViolation(
                "Active stakeholder allocations must total exactly "
                f"{self.allocation_total_units}; got {actual_total}."
            )

    def _validate_questions(self) -> None:
        if not self.question_definitions:
            raise SessionRuleViolation(
                "A configuration must define at least one response question."
            )
        expected_question_type = self._expected_question_type()
        for question in self.question_definitions:
            if question.question_type is not expected_question_type:
                raise SessionRuleViolation(
                    f"Question {question.question_key!r} has type "
                    f"{question.question_type.value!r}; configuration requires "
                    f"{expected_question_type.value!r}."
                )
            if (
                question.scale_id is not None
                and question.scale_id != self.scale_id
            ):
                raise SessionRuleViolation(
                    f"Question {question.question_key!r} references a different "
                    "scale than its configuration."
                )

        pair_targets = [
            (question.left_criterion_id, question.right_criterion_id)
            for question in self.question_definitions
            if question.question_type is QuestionType.CRITERION_PAIR
        ]
        _require_unique(pair_targets, "Criterion-pair question targets")

    def _expected_question_type(self) -> QuestionType:
        if self.response_format is ResponseFormat.PAIRWISE:
            if self.response_target_type is not ResponseTargetType.CRITERION:
                raise SessionRuleViolation(
                    "Pairwise responses currently support criterion targets "
                    "only."
                )
            return QuestionType.CRITERION_PAIR
        if self.response_format is ResponseFormat.DIRECT_RATING:
            if self.response_target_type is ResponseTargetType.CRITERION:
                return QuestionType.CRITERION_RATING
            return QuestionType.ALTERNATIVE_RATING
        if self.response_format is ResponseFormat.DIRECT_RANKING:
            if self.response_target_type is not ResponseTargetType.ALTERNATIVE:
                raise SessionRuleViolation(
                    "Direct ranking requires alternative targets."
                )
            return QuestionType.ALTERNATIVE_RANK
        raise SessionRuleViolation(
            f"Unsupported response format: {self.response_format!r}."
        )


@dataclass(frozen=True, slots=True)
class Session:
    """Operational session shell and owner of configuration versions."""

    session_id: str
    scenario_snapshot_id: str
    public_slug: str
    title: str
    description: str | None
    admin_notes: str | None

    status: SessionStatus
    discoverability: Discoverability
    enrollment_mode: EnrollmentMode
    access_code_mode: AccessCodeMode
    identity_policy: str
    stakeholder_selection_mode: StakeholderSelectionMode

    opens_at: datetime | None
    closes_at: datetime | None
    opened_at: datetime | None
    paused_at: datetime | None
    closed_at: datetime | None
    canceled_at: datetime | None
    archived_at: datetime | None

    active_configuration_version_id: str | None
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str
    configurations: tuple[SessionConfigurationVersion, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_schedule()
        self._validate_access_configuration()
        self._validate_configurations()
        self._validate_status_timestamps()

    @property
    def active_configuration(self) -> SessionConfigurationVersion | None:
        if self.active_configuration_version_id is None:
            return None
        return self._find_configuration(self.active_configuration_version_id)

    def add_configuration(
        self,
        configuration: SessionConfigurationVersion,
        *,
        actor_id: str,
        at: datetime,
    ) -> Self:
        """Return the session with a new, unactivated configuration version."""

        self._require_configuration_editable()
        _require_actor(actor_id)
        _require_aware_datetime(at, "Configuration addition time")
        if configuration.is_activated:
            raise SessionRuleViolation(
                "Configurations must be activated through their owning session."
            )
        if configuration.session_id != self.session_id:
            raise SessionRuleViolation(
                "Configuration belongs to a different session."
            )
        if configuration.scenario_snapshot_id != self.scenario_snapshot_id:
            raise SessionRuleViolation(
                "Configuration references a different scenario snapshot."
            )
        if at < self.created_at:
            raise SessionRuleViolation(
                "Configuration addition cannot precede session creation."
            )
        self._require_not_before_last_update(at)
        candidate = replace(
            self,
            configurations=tuple(
                sorted(
                    (*self.configurations, configuration),
                    key=lambda item: item.version_number,
                )
            ),
            updated_at=at,
            updated_by=actor_id,
        )
        return candidate

    def activate_configuration(
        self,
        configuration_version_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> Self:
        """Activate one complete version before the session is opened."""

        self._require_configuration_editable()
        _require_actor(actor_id)
        _require_aware_datetime(at, "Configuration activation time")
        self._require_not_before_last_update(at)
        target = self._find_configuration(configuration_version_id)
        if self.active_configuration_version_id == configuration_version_id:
            raise SessionRuleViolation(
                "Configuration is already the active version."
            )
        activated = target.activate(actor_id=actor_id, at=at)
        configurations = tuple(
            activated if item.configuration_version_id == configuration_version_id
            else item
            for item in self.configurations
        )
        return replace(
            self,
            configurations=configurations,
            active_configuration_version_id=configuration_version_id,
            updated_at=at,
            updated_by=actor_id,
        )

    def schedule(self, *, actor_id: str, at: datetime) -> Self:
        """Move a draft session into its scheduled state."""

        _require_actor(actor_id)
        _require_aware_datetime(at, "Scheduling time")
        if self.status is not SessionStatus.DRAFT:
            raise SessionRuleViolation(
                "Only a draft session can be scheduled."
            )
        if self.opens_at is None:
            raise SessionRuleViolation(
                "A session requires opens_at before it can be scheduled."
            )
        if self.opens_at <= at:
            raise SessionRuleViolation(
                "A scheduled session must open in the future."
            )
        return self._transition(
            status=SessionStatus.SCHEDULED,
            actor_id=actor_id,
            at=at,
        )

    def open(
        self,
        *,
        scenario_snapshot: ScenarioSnapshot,
        actor_id: str,
        at: datetime,
    ) -> Self:
        """Open the session after scenario and configuration readiness checks."""

        _require_actor(actor_id)
        _require_aware_datetime(at, "Opening time")
        if self.status not in {SessionStatus.DRAFT, SessionStatus.SCHEDULED}:
            raise SessionRuleViolation(
                "Only a draft or scheduled session can be opened."
            )
        if scenario_snapshot.scenario_snapshot_id != self.scenario_snapshot_id:
            raise SessionRuleViolation(
                "Session cannot open with a different scenario snapshot."
            )
        if scenario_snapshot.status is not ScenarioSnapshotStatus.READY:
            raise SessionRuleViolation(
                "Session cannot open until its scenario snapshot is ready."
            )
        configuration = self._require_active_configuration()
        configuration.validate_for_activation()
        if self.opens_at is not None and at < self.opens_at:
            raise SessionRuleViolation(
                "Session cannot open before its configured opening time."
            )
        if self.closes_at is not None and at >= self.closes_at:
            raise SessionRuleViolation(
                "Session cannot open at or after its configured closing time."
            )
        return self._transition(
            status=SessionStatus.OPEN,
            actor_id=actor_id,
            at=at,
            opened_at=at,
        )

    def pause(self, *, actor_id: str, at: datetime) -> Self:
        _require_actor(actor_id)
        _require_aware_datetime(at, "Pause time")
        if self.status is not SessionStatus.OPEN:
            raise SessionRuleViolation("Only an open session can be paused.")
        return self._transition(
            status=SessionStatus.PAUSED,
            actor_id=actor_id,
            at=at,
            paused_at=at,
        )

    def resume(self, *, actor_id: str, at: datetime) -> Self:
        _require_actor(actor_id)
        _require_aware_datetime(at, "Resume time")
        if self.status is not SessionStatus.PAUSED:
            raise SessionRuleViolation("Only a paused session can be resumed.")
        if self.closes_at is not None and at >= self.closes_at:
            raise SessionRuleViolation(
                "Session cannot resume at or after its closing time."
            )
        return self._transition(
            status=SessionStatus.OPEN,
            actor_id=actor_id,
            at=at,
        )

    def close(self, *, actor_id: str, at: datetime) -> Self:
        _require_actor(actor_id)
        _require_aware_datetime(at, "Closing time")
        if self.status not in {SessionStatus.OPEN, SessionStatus.PAUSED}:
            raise SessionRuleViolation(
                "Only an open or paused session can be closed."
            )
        return self._transition(
            status=SessionStatus.CLOSED,
            actor_id=actor_id,
            at=at,
            closed_at=at,
        )

    def cancel(self, *, actor_id: str, at: datetime) -> Self:
        _require_actor(actor_id)
        _require_aware_datetime(at, "Cancellation time")
        if self.status not in {
            SessionStatus.DRAFT,
            SessionStatus.SCHEDULED,
            SessionStatus.OPEN,
            SessionStatus.PAUSED,
        }:
            raise SessionRuleViolation(
                f"A session in {self.status.value!r} status cannot be canceled."
            )
        return self._transition(
            status=SessionStatus.CANCELED,
            actor_id=actor_id,
            at=at,
            canceled_at=at,
        )

    def archive(self, *, actor_id: str, at: datetime) -> Self:
        _require_actor(actor_id)
        _require_aware_datetime(at, "Archive time")
        if self.status not in {SessionStatus.CLOSED, SessionStatus.CANCELED}:
            raise SessionRuleViolation(
                "Only a closed or canceled session can be archived."
            )
        return self._transition(
            status=SessionStatus.ARCHIVED,
            actor_id=actor_id,
            at=at,
            archived_at=at,
        )

    def can_accept_submissions(self, *, at: datetime) -> bool:
        _require_aware_datetime(at, "Submission eligibility time")
        if self.status is not SessionStatus.OPEN:
            return False
        if self.opens_at is not None and at < self.opens_at:
            return False
        if self.closes_at is not None and at >= self.closes_at:
            return False
        return True

    def _transition(
        self,
        *,
        status: SessionStatus,
        actor_id: str,
        at: datetime,
        opened_at: datetime | None = None,
        paused_at: datetime | None = None,
        closed_at: datetime | None = None,
        canceled_at: datetime | None = None,
        archived_at: datetime | None = None,
    ) -> Self:
        if at < self.updated_at:
            raise SessionRuleViolation(
                "Lifecycle transition cannot precede the last session update."
            )
        return replace(
            self,
            status=status,
            opened_at=opened_at or self.opened_at,
            paused_at=paused_at or self.paused_at,
            closed_at=closed_at or self.closed_at,
            canceled_at=canceled_at or self.canceled_at,
            archived_at=archived_at or self.archived_at,
            updated_at=at,
            updated_by=actor_id,
        )

    def _require_configuration_editable(self) -> None:
        if self.status not in {SessionStatus.DRAFT, SessionStatus.SCHEDULED}:
            raise SessionRuleViolation(
                "Calculation configuration cannot change after the session "
                "has opened. Create a new session instead."
            )

    def _require_not_before_last_update(self, at: datetime) -> None:
        if at < self.updated_at:
            raise SessionRuleViolation(
                "Session change cannot precede the last session update."
            )

    def _require_active_configuration(self) -> SessionConfigurationVersion:
        configuration = self.active_configuration
        if configuration is None:
            raise SessionRuleViolation(
                "Session requires an active configuration."
            )
        if not configuration.is_activated:
            raise SessionRuleViolation(
                "The active configuration must be activated."
            )
        return configuration

    def _find_configuration(
        self,
        configuration_version_id: str,
    ) -> SessionConfigurationVersion:
        _require_text(configuration_version_id, "Configuration version ID")
        for configuration in self.configurations:
            if (
                configuration.configuration_version_id
                == configuration_version_id
            ):
                return configuration
        raise SessionRuleViolation(
            f"Unknown configuration version: {configuration_version_id!r}."
        )

    def _validate_identity(self) -> None:
        _require_text(self.session_id, "Session ID")
        _require_text(self.scenario_snapshot_id, "Scenario snapshot ID")
        _require_text(self.public_slug, "Session public slug")
        _require_text(self.title, "Session title")
        _require_optional_text(self.description, "Session description")
        _require_optional_text(self.admin_notes, "Session admin notes")
        _require_text(self.identity_policy, "Session identity policy")
        _require_text(self.created_by, "Session creator")
        _require_text(self.updated_by, "Session updater")

    def _validate_schedule(self) -> None:
        timestamps = {
            "opens_at": self.opens_at,
            "closes_at": self.closes_at,
            "opened_at": self.opened_at,
            "paused_at": self.paused_at,
            "closed_at": self.closed_at,
            "canceled_at": self.canceled_at,
            "archived_at": self.archived_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        for field_name, value in timestamps.items():
            _require_aware_datetime(value, field_name)
        if self.opens_at is not None and self.closes_at is not None:
            if self.closes_at <= self.opens_at:
                raise SessionRuleViolation(
                    "Session closes_at must be later than opens_at."
                )
        if self.updated_at < self.created_at:
            raise SessionRuleViolation(
                "Session updated_at cannot precede created_at."
            )
        for field_name in (
            "opened_at",
            "paused_at",
            "closed_at",
            "canceled_at",
            "archived_at",
        ):
            value = timestamps[field_name]
            if value is not None and value < self.created_at:
                raise SessionRuleViolation(
                    f"Session {field_name} cannot precede created_at."
                )

    def _validate_access_configuration(self) -> None:
        if (
            self.access_code_mode is AccessCodeMode.PER_INVITATION_CODE
            and self.enrollment_mode is not EnrollmentMode.INVITATION_ONLY
        ):
            raise SessionRuleViolation(
                "Per-invitation access codes require invitation-only enrollment."
            )

    def _validate_configurations(self) -> None:
        _require_unique(
            (
                configuration.configuration_version_id
                for configuration in self.configurations
            ),
            "Configuration version IDs",
        )
        _require_unique(
            (
                configuration.version_number
                for configuration in self.configurations
            ),
            "Configuration version numbers",
        )
        _require_unique(
            (configuration.config_hash for configuration in self.configurations),
            "Configuration hashes",
        )
        for configuration in self.configurations:
            if configuration.session_id != self.session_id:
                raise SessionRuleViolation(
                    "Configuration belongs to a different session."
                )
            if configuration.scenario_snapshot_id != self.scenario_snapshot_id:
                raise SessionRuleViolation(
                    "Configuration references a different scenario snapshot."
                )
        if self.active_configuration_version_id is not None:
            active = self._find_configuration(
                self.active_configuration_version_id
            )
            if not active.is_activated:
                raise SessionRuleViolation(
                    "Active configuration version must be activated."
                )

    def _validate_status_timestamps(self) -> None:
        if self.status is SessionStatus.SCHEDULED and self.opens_at is None:
            raise SessionRuleViolation(
                "A scheduled session requires opens_at."
            )
        if self.status in {
            SessionStatus.OPEN,
            SessionStatus.PAUSED,
            SessionStatus.CLOSED,
        } and self.opened_at is None:
            raise SessionRuleViolation(
                f"A {self.status.value} session requires opened_at."
            )
        if self.status is SessionStatus.PAUSED and self.paused_at is None:
            raise SessionRuleViolation(
                "A paused session requires paused_at."
            )
        if self.status is SessionStatus.CLOSED and self.closed_at is None:
            raise SessionRuleViolation(
                "A closed session requires closed_at."
            )
        if self.status is SessionStatus.CANCELED and self.canceled_at is None:
            raise SessionRuleViolation(
                "A canceled session requires canceled_at."
            )
        if self.status is SessionStatus.ARCHIVED:
            if self.archived_at is None:
                raise SessionRuleViolation(
                    "An archived session requires archived_at."
                )
            if self.closed_at is None and self.canceled_at is None:
                raise SessionRuleViolation(
                    "An archived session must previously be closed or canceled."
                )
        if self.status in {SessionStatus.OPEN, SessionStatus.PAUSED} and (
            self.closed_at is not None
            or self.canceled_at is not None
            or self.archived_at is not None
        ):
            raise SessionRuleViolation(
                "An active session cannot have terminal lifecycle timestamps."
            )


def _require_unique(
    values: Iterable[Hashable],
    field_name: str,
) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise SessionRuleViolation(f"{field_name} must be unique.")
