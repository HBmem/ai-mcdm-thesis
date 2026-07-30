"""Bidirectional mappings between session domain objects and ORM rows.

Session lifecycle fields belong to the mutable operational shell, while each
configuration version and its children are immutable calculation inputs.  The
separate mapper functions below preserve that boundary and let repositories
update operational state without replacing historical configuration content.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from poli_insight.core.time import as_utc
from poli_insight.domain.enum import (
    AccessCodeMode,
    AlgorithmRole,
    Discoverability,
    EnrollmentMode,
    MissingGroupPolicy,
    QuestionType,
    ResponseFormat,
    ResponseTargetType,
    SessionStatus,
    StakeholderSelectionMode,
)
from poli_insight.domain.session import (
    ResponseQuestionDefinition,
    Session,
    SessionAlgorithmConfig,
    SessionConfigurationVersion,
    SessionStakeholderGroup,
)
from poli_insight.infrastructure.database.models.session import (
    ResponseQuestionDefinitionRow,
    SessionAlgorithmConfigRow,
    SessionConfigurationVersionRow,
    SessionRow,
    SessionStakeholderGroupRow,
)


def _required_utc(value: datetime, field_name: str) -> datetime:
    utc_value = as_utc(value)
    if utc_value is None:
        raise ValueError(f"Persisted session is missing {field_name}.")
    return utc_value


def _optional_utc(value: datetime | None) -> datetime | None:
    return as_utc(value) if value is not None else None


def _optional_id(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _copy_json(value: Mapping[str, Any]) -> dict[str, Any]:
    """Detach nested JSON values from the source object being mapped."""

    return deepcopy(dict(value))


def session_algorithm_config_to_row(
    config: SessionAlgorithmConfig,
) -> SessionAlgorithmConfigRow:
    """Map one immutable algorithm selection to its persistence row."""

    return SessionAlgorithmConfigRow(
        session_algorithm_config_id=config.session_algorithm_config_id,
        configuration_version_id=config.configuration_version_id,
        algorithm_implementation_id=config.algorithm_implementation_id,
        role=config.role.value,
        execution_order=config.execution_order,
        parameter_json=_copy_json(config.parameter_json),
        parameter_schema_version=config.parameter_schema_version,
        parameter_hash=config.parameter_hash,
    )


def session_algorithm_config_to_domain(
    row: SessionAlgorithmConfigRow,
) -> SessionAlgorithmConfig:
    """Reconstruct one algorithm selection from a persistence row."""

    return SessionAlgorithmConfig(
        session_algorithm_config_id=str(row.session_algorithm_config_id),
        configuration_version_id=str(row.configuration_version_id),
        algorithm_implementation_id=str(row.algorithm_implementation_id),
        role=AlgorithmRole(row.role),
        execution_order=row.execution_order,
        parameter_json=_copy_json(row.parameter_json),
        parameter_schema_version=row.parameter_schema_version,
        parameter_hash=row.parameter_hash,
    )


def session_stakeholder_group_to_row(
    group: SessionStakeholderGroup,
) -> SessionStakeholderGroupRow:
    """Map a stakeholder group without converting its exact allocation."""

    return SessionStakeholderGroupRow(
        session_stakeholder_group_id=group.session_stakeholder_group_id,
        configuration_version_id=group.configuration_version_id,
        group_key=group.group_key,
        name=group.name,
        description=group.description,
        allocation_units=group.allocation_units,
        display_order=group.display_order,
        is_active=group.is_active,
        within_group_algorithm_config_id=(
            group.within_group_algorithm_config_id
        ),
        created_at=group.created_at,
        created_by=group.created_by,
    )


def session_stakeholder_group_to_domain(
    row: SessionStakeholderGroupRow,
) -> SessionStakeholderGroup:
    """Reconstruct a stakeholder group using exact integer allocation units."""

    return SessionStakeholderGroup(
        session_stakeholder_group_id=str(
            row.session_stakeholder_group_id
        ),
        configuration_version_id=str(row.configuration_version_id),
        group_key=row.group_key,
        name=row.name,
        description=row.description,
        allocation_units=row.allocation_units,
        display_order=row.display_order,
        is_active=row.is_active,
        within_group_algorithm_config_id=_optional_id(
            row.within_group_algorithm_config_id
        ),
        created_at=_required_utc(row.created_at, "group created_at"),
        created_by=row.created_by,
    )


def response_question_definition_to_row(
    question: ResponseQuestionDefinition,
) -> ResponseQuestionDefinitionRow:
    """Map one versioned participant response definition to a row."""

    return ResponseQuestionDefinitionRow(
        question_definition_id=question.question_definition_id,
        configuration_version_id=question.configuration_version_id,
        question_key=question.question_key,
        question_type=question.question_type.value,
        display_order=question.display_order,
        required=question.required,
        criterion_id=question.criterion_id,
        left_criterion_id=question.left_criterion_id,
        right_criterion_id=question.right_criterion_id,
        alternative_id=question.alternative_id,
        scale_id=question.scale_id,
        prompt_snapshot=question.prompt_snapshot,
        metadata_json=_copy_json(question.metadata_json),
    )


def response_question_definition_to_domain(
    row: ResponseQuestionDefinitionRow,
) -> ResponseQuestionDefinition:
    """Reconstruct one participant response definition from a row."""

    return ResponseQuestionDefinition(
        question_definition_id=str(row.question_definition_id),
        configuration_version_id=str(row.configuration_version_id),
        question_key=row.question_key,
        question_type=QuestionType(row.question_type),
        display_order=row.display_order,
        required=row.required,
        criterion_id=_optional_id(row.criterion_id),
        left_criterion_id=_optional_id(row.left_criterion_id),
        right_criterion_id=_optional_id(row.right_criterion_id),
        alternative_id=_optional_id(row.alternative_id),
        scale_id=_optional_id(row.scale_id),
        prompt_snapshot=row.prompt_snapshot,
        metadata_json=_copy_json(row.metadata_json),
    )


def session_configuration_version_to_row(
    configuration: SessionConfigurationVersion,
) -> SessionConfigurationVersionRow:
    """Map a complete immutable configuration aggregate to ORM rows."""

    return SessionConfigurationVersionRow(
        configuration_version_id=configuration.configuration_version_id,
        session_id=configuration.session_id,
        version_number=configuration.version_number,
        scenario_snapshot_id=configuration.scenario_snapshot_id,
        response_format=configuration.response_format.value,
        response_target_type=configuration.response_target_type.value,
        scale_id=configuration.scale_id,
        allow_resubmissions=configuration.allow_resubmissions,
        max_submissions_per_participant=(
            configuration.max_submissions_per_participant
        ),
        allow_incomplete_submission=(
            configuration.allow_incomplete_submission
        ),
        minimum_valid_submissions=configuration.minimum_valid_submissions,
        missing_group_policy=configuration.missing_group_policy.value,
        required_group_policy_json=_copy_json(
            configuration.required_group_policy_json
        ),
        consistency_threshold=configuration.consistency_threshold,
        configuration_json=_copy_json(configuration.configuration_json),
        schema_version=configuration.schema_version,
        config_hash=configuration.config_hash,
        allocation_total_units=configuration.allocation_total_units,
        created_at=configuration.created_at,
        created_by=configuration.created_by,
        activated_at=configuration.activated_at,
        activated_by=configuration.activated_by,
        stakeholder_groups=[
            session_stakeholder_group_to_row(group)
            for group in sorted(
                configuration.stakeholder_groups,
                key=lambda item: (
                    item.display_order,
                    item.group_key,
                    item.session_stakeholder_group_id,
                ),
            )
        ],
        algorithm_configs=[
            session_algorithm_config_to_row(config)
            for config in sorted(
                configuration.algorithm_configs,
                key=lambda item: (
                    item.role.value,
                    item.execution_order,
                    item.session_algorithm_config_id,
                ),
            )
        ],
        question_definitions=[
            response_question_definition_to_row(question)
            for question in sorted(
                configuration.question_definitions,
                key=lambda item: (
                    item.display_order,
                    item.question_key,
                    item.question_definition_id,
                ),
            )
        ],
    )


def session_configuration_version_to_domain(
    row: SessionConfigurationVersionRow,
) -> SessionConfigurationVersion:
    """Reconstruct a detached, deterministically ordered configuration."""

    return SessionConfigurationVersion(
        configuration_version_id=str(row.configuration_version_id),
        session_id=str(row.session_id),
        version_number=row.version_number,
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        response_format=ResponseFormat(row.response_format),
        response_target_type=ResponseTargetType(row.response_target_type),
        scale_id=str(row.scale_id),
        allow_resubmissions=row.allow_resubmissions,
        max_submissions_per_participant=(
            row.max_submissions_per_participant
        ),
        allow_incomplete_submission=row.allow_incomplete_submission,
        minimum_valid_submissions=row.minimum_valid_submissions,
        missing_group_policy=MissingGroupPolicy(row.missing_group_policy),
        required_group_policy_json=_copy_json(
            row.required_group_policy_json
        ),
        consistency_threshold=(
            Decimal(row.consistency_threshold)
            if row.consistency_threshold is not None
            else None
        ),
        configuration_json=_copy_json(row.configuration_json),
        schema_version=row.schema_version,
        config_hash=row.config_hash,
        allocation_total_units=row.allocation_total_units,
        created_at=_required_utc(
            row.created_at,
            "configuration created_at",
        ),
        created_by=row.created_by,
        activated_at=_optional_utc(row.activated_at),
        activated_by=row.activated_by,
        stakeholder_groups=tuple(
            session_stakeholder_group_to_domain(group_row)
            for group_row in sorted(
                row.stakeholder_groups,
                key=lambda item: (
                    item.display_order,
                    item.group_key,
                    str(item.session_stakeholder_group_id),
                ),
            )
        ),
        algorithm_configs=tuple(
            session_algorithm_config_to_domain(config_row)
            for config_row in sorted(
                row.algorithm_configs,
                key=lambda item: (
                    item.role,
                    item.execution_order,
                    str(item.session_algorithm_config_id),
                ),
            )
        ),
        question_definitions=tuple(
            response_question_definition_to_domain(question_row)
            for question_row in sorted(
                row.question_definitions,
                key=lambda item: (
                    item.display_order,
                    item.question_key,
                    str(item.question_definition_id),
                ),
            )
        ),
    )


def session_operational_state_to_row(session: Session) -> SessionRow:
    """Map only the mutable operational state of a session."""

    return SessionRow(
        session_id=session.session_id,
        scenario_snapshot_id=session.scenario_snapshot_id,
        public_slug=session.public_slug,
        title=session.title,
        description=session.description,
        admin_notes=session.admin_notes,
        status=session.status.value,
        discoverability=session.discoverability.value,
        enrollment_mode=session.enrollment_mode.value,
        access_code_mode=session.access_code_mode.value,
        identity_policy=session.identity_policy,
        stakeholder_selection_mode=(
            session.stakeholder_selection_mode.value
        ),
        opens_at=session.opens_at,
        closes_at=session.closes_at,
        opened_at=session.opened_at,
        paused_at=session.paused_at,
        closed_at=session.closed_at,
        canceled_at=session.canceled_at,
        archived_at=session.archived_at,
        active_configuration_version_id=(
            session.active_configuration_version_id
        ),
        created_at=session.created_at,
        created_by=session.created_by,
        updated_at=session.updated_at,
        updated_by=session.updated_by,
    )


def apply_session_operational_state(
    row: SessionRow,
    session: Session,
) -> None:
    """Apply lifecycle state to an existing row without touching versions."""

    if str(row.session_id) != session.session_id:
        raise ValueError("Cannot map operational state to another session.")
    if str(row.scenario_snapshot_id) != session.scenario_snapshot_id:
        raise ValueError("A session's scenario snapshot cannot be replaced.")

    row.public_slug = session.public_slug
    row.title = session.title
    row.description = session.description
    row.admin_notes = session.admin_notes
    row.status = session.status.value
    row.discoverability = session.discoverability.value
    row.enrollment_mode = session.enrollment_mode.value
    row.access_code_mode = session.access_code_mode.value
    row.identity_policy = session.identity_policy
    row.stakeholder_selection_mode = session.stakeholder_selection_mode.value
    row.opens_at = session.opens_at
    row.closes_at = session.closes_at
    row.opened_at = session.opened_at
    row.paused_at = session.paused_at
    row.closed_at = session.closed_at
    row.canceled_at = session.canceled_at
    row.archived_at = session.archived_at
    row.active_configuration_version_id = (
        session.active_configuration_version_id
    )
    row.updated_at = session.updated_at
    row.updated_by = session.updated_by


def session_operational_state_to_domain(
    row: SessionRow,
    *,
    configurations: tuple[SessionConfigurationVersion, ...],
) -> Session:
    """Compose a domain session from operational state and detached versions."""

    ordered_configurations = tuple(
        sorted(
            configurations,
            key=lambda item: (
                item.version_number,
                item.configuration_version_id,
            ),
        )
    )
    active_configuration_version_id = _optional_id(
        row.active_configuration_version_id
    )
    if active_configuration_version_id is not None:
        matches = tuple(
            configuration
            for configuration in ordered_configurations
            if configuration.configuration_version_id
            == active_configuration_version_id
        )
        if len(matches) != 1:
            raise ValueError(
                "Persisted session active configuration must resolve to "
                "exactly one loaded configuration version."
            )

    return Session(
        session_id=str(row.session_id),
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        public_slug=row.public_slug,
        title=row.title,
        description=row.description,
        admin_notes=row.admin_notes,
        status=SessionStatus(row.status),
        discoverability=Discoverability(row.discoverability),
        enrollment_mode=EnrollmentMode(row.enrollment_mode),
        access_code_mode=AccessCodeMode(row.access_code_mode),
        identity_policy=row.identity_policy,
        stakeholder_selection_mode=StakeholderSelectionMode(
            row.stakeholder_selection_mode
        ),
        opens_at=_optional_utc(row.opens_at),
        closes_at=_optional_utc(row.closes_at),
        opened_at=_optional_utc(row.opened_at),
        paused_at=_optional_utc(row.paused_at),
        closed_at=_optional_utc(row.closed_at),
        canceled_at=_optional_utc(row.canceled_at),
        archived_at=_optional_utc(row.archived_at),
        active_configuration_version_id=active_configuration_version_id,
        created_at=_required_utc(row.created_at, "created_at"),
        created_by=row.created_by,
        updated_at=_required_utc(row.updated_at, "updated_at"),
        updated_by=row.updated_by,
        configurations=ordered_configurations,
    )


def active_session_configuration_to_domain(
    row: SessionRow,
) -> SessionConfigurationVersion | None:
    """Resolve the active version by identity, never by collection order."""

    active_id = _optional_id(row.active_configuration_version_id)
    if active_id is None:
        return None

    matching_rows = tuple(
        configuration_row
        for configuration_row in row.configurations
        if str(configuration_row.configuration_version_id) == active_id
    )
    if len(matching_rows) != 1:
        raise ValueError(
            "Persisted session active configuration must resolve to exactly "
            "one loaded configuration version."
        )
    return session_configuration_version_to_domain(matching_rows[0])


def session_to_row(session: Session) -> SessionRow:
    """Map a complete session aggregate while retaining state boundaries."""

    row = session_operational_state_to_row(session)
    row.configurations = [
        session_configuration_version_to_row(configuration)
        for configuration in sorted(
            session.configurations,
            key=lambda item: (
                item.version_number,
                item.configuration_version_id,
            ),
        )
    ]
    return row


def session_to_domain(row: SessionRow) -> Session:
    """Reconstruct a complete, detached session aggregate."""

    configurations = tuple(
        session_configuration_version_to_domain(configuration_row)
        for configuration_row in sorted(
            row.configurations,
            key=lambda item: (
                item.version_number,
                str(item.configuration_version_id),
            ),
        )
    )
    return session_operational_state_to_domain(
        row,
        configurations=configurations,
    )
