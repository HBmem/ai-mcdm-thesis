"""SQLAlchemy repository for the session aggregate."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import and_, select
from sqlalchemy.orm import Load, Session as DatabaseSession, selectinload

from poli_insight.domain.session import (
    Session,
    SessionConfigurationVersion,
)
from poli_insight.infrastructure.database.mappers.session import (
    apply_session_operational_state,
    session_configuration_version_to_domain,
    session_configuration_version_to_row,
    session_to_domain,
    session_to_row,
)
from poli_insight.infrastructure.database.models.session import (
    SessionConfigurationVersionRow,
    SessionRow,
)


class SessionNotFoundError(LookupError):
    """Raised when an aggregate requested for persistence does not exist."""


class ImmutableSessionConfigurationError(RuntimeError):
    """Raised when a save would alter persisted configuration content."""


def _session_load_options() -> tuple[Load, ...]:
    """Eager-load every collection required to reconstruct a session."""

    return (
        selectinload(SessionRow.configurations).selectinload(
            SessionConfigurationVersionRow.stakeholder_groups
        ),
        selectinload(SessionRow.configurations).selectinload(
            SessionConfigurationVersionRow.algorithm_configs
        ),
        selectinload(SessionRow.configurations).selectinload(
            SessionConfigurationVersionRow.question_definitions
        ),
    )


def _configuration_load_options() -> tuple[Load, ...]:
    """Eager-load the immutable children of one configuration version."""

    return (
        selectinload(SessionConfigurationVersionRow.stakeholder_groups),
        selectinload(SessionConfigurationVersionRow.algorithm_configs),
        selectinload(SessionConfigurationVersionRow.question_definitions),
    )


def _canonical_configuration(
    configuration: SessionConfigurationVersion,
) -> SessionConfigurationVersion:
    """Normalize collection order before comparing immutable content."""

    return replace(
        configuration,
        stakeholder_groups=tuple(
            sorted(
                configuration.stakeholder_groups,
                key=lambda item: (
                    item.display_order,
                    item.group_key,
                    item.session_stakeholder_group_id,
                ),
            )
        ),
        algorithm_configs=tuple(
            sorted(
                configuration.algorithm_configs,
                key=lambda item: (
                    item.role.value,
                    item.execution_order,
                    item.session_algorithm_config_id,
                ),
            )
        ),
        question_definitions=tuple(
            sorted(
                configuration.question_definitions,
                key=lambda item: (
                    item.display_order,
                    item.question_key,
                    item.question_definition_id,
                ),
            )
        ),
    )


class SqlAlchemySessionRepository:
    """Persist sessions while keeping configuration versions append-only.

    The caller owns the transaction. Methods flush when ordering or immediate
    persistence is required, but this repository never commits or rolls back.
    """

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, session: Session) -> None:
        """Add a new aggregate without committing the caller's transaction."""

        row = session_to_row(session)
        active_configuration_id = row.active_configuration_version_id

        # The session row must exist before its configuration rows, while its
        # active-configuration FK can only be set after the target row exists.
        row.active_configuration_version_id = None
        self._database_session.add(row)
        self._database_session.flush()

        if active_configuration_id is not None:
            row.active_configuration_version_id = active_configuration_id
            self._database_session.flush()

    def get(self, session_id: str) -> Session | None:
        """Load a complete aggregate without taking a database row lock."""

        row = self._load_row(session_id, for_update=False)
        return None if row is None else session_to_domain(row)

    def get_for_update(self, session_id: str) -> Session | None:
        """Load an aggregate and lock its operational row on PostgreSQL."""

        row = self._load_row(session_id, for_update=True)
        return None if row is None else session_to_domain(row)

    def save(self, session: Session) -> None:
        """Persist lifecycle changes and append new configuration versions.

        Existing configuration content and child rows are never rewritten.
        The only permitted update to an existing version is its one-way
        activation metadata transition.
        """

        row = self._load_row(session.session_id, for_update=True)
        if row is None:
            raise SessionNotFoundError(
                f"Session {session.session_id!r} does not exist."
            )

        incoming_by_id = {
            configuration.configuration_version_id: configuration
            for configuration in session.configurations
        }
        existing_by_id = {
            str(configuration_row.configuration_version_id): configuration_row
            for configuration_row in row.configurations
        }

        removed_ids = sorted(existing_by_id.keys() - incoming_by_id.keys())
        if removed_ids:
            raise ImmutableSessionConfigurationError(
                "Persisted session configuration versions cannot be removed: "
                f"{removed_ids}."
            )

        activations: list[
            tuple[
                SessionConfigurationVersionRow,
                SessionConfigurationVersion,
            ]
        ] = []
        for configuration_id, configuration_row in existing_by_id.items():
            incoming = incoming_by_id[configuration_id]
            should_activate = self._validate_configuration_transition(
                configuration_row,
                incoming,
            )
            if should_activate:
                activations.append((configuration_row, incoming))

        # Apply state only after every immutable version has been validated, so
        # a rejected save does not leave earlier rows dirty in the identity map.
        for configuration_row, incoming in activations:
            configuration_row.activated_at = incoming.activated_at
            configuration_row.activated_by = incoming.activated_by

        new_configurations = sorted(
            (
                configuration
                for configuration_id, configuration in incoming_by_id.items()
                if configuration_id not in existing_by_id
            ),
            key=lambda item: (
                item.version_number,
                item.configuration_version_id,
            ),
        )
        row.configurations.extend(
            session_configuration_version_to_row(configuration)
            for configuration in new_configurations
        )

        # Insert new versions and record activation before the operational row
        # is allowed to reference a newly inserted active version.
        self._database_session.flush()
        apply_session_operational_state(row, session)
        self._database_session.flush()

    def get_active_configuration(
        self,
        session_id: str,
    ) -> SessionConfigurationVersion | None:
        """Load the active configuration directly by its persisted identity."""

        statement = (
            select(SessionConfigurationVersionRow)
            .join(
                SessionRow,
                and_(
                    SessionRow.session_id
                    == SessionConfigurationVersionRow.session_id,
                    SessionRow.active_configuration_version_id
                    == SessionConfigurationVersionRow.configuration_version_id,
                ),
            )
            .options(*_configuration_load_options())
            .where(SessionRow.session_id == session_id)
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return (
            None
            if row is None
            else session_configuration_version_to_domain(row)
        )

    def _load_row(
        self,
        session_id: str,
        *,
        for_update: bool,
    ) -> SessionRow | None:
        statement = (
            select(SessionRow)
            .options(*_session_load_options())
            .where(SessionRow.session_id == session_id)
        )
        if for_update and self._uses_postgresql():
            statement = statement.with_for_update()

        return self._database_session.execute(statement).scalar_one_or_none()

    def _uses_postgresql(self) -> bool:
        bind = self._database_session.get_bind()
        return bind.dialect.name == "postgresql"

    @staticmethod
    def _validate_configuration_transition(
        row: SessionConfigurationVersionRow,
        incoming: SessionConfigurationVersion,
    ) -> bool:
        persisted = _canonical_configuration(
            session_configuration_version_to_domain(row)
        )
        incoming = _canonical_configuration(incoming)

        if persisted.is_activated:
            if persisted != incoming:
                raise ImmutableSessionConfigurationError(
                    "Activated session configuration "
                    f"{persisted.configuration_version_id!r} is immutable."
                )
            return False

        expected = replace(
            persisted,
            activated_at=incoming.activated_at,
            activated_by=incoming.activated_by,
        )
        if expected != incoming:
            raise ImmutableSessionConfigurationError(
                "Persisted session configuration "
                f"{persisted.configuration_version_id!r} may only be "
                "activated; its content and children are immutable."
            )

        return incoming.is_activated
