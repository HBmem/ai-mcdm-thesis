"""SQLAlchemy repository for immutable, versioned validation aggregates.

The repository persists messages, normalized answers, and criterion weights
through their owning validation attempt. The caller owns the transaction;
this adapter may flush changes but never commits or rolls back.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from poli_insight.domain.validation import SubmissionValidation
from poli_insight.infrastructure.database.mappers.validation import (
    apply_validation_aggregate,
    validation_to_domain,
    validation_to_row,
)
from poli_insight.infrastructure.database.models.validation import (
    SubmissionValidationRow,
)


class ValidationNotFoundError(LookupError):
    """Raised when a validation requested for persistence does not exist."""


def _validation_load_options() -> tuple[ExecutableOption, ...]:
    """Eager-load every child required to reconstruct a validation."""

    return (
        selectinload(SubmissionValidationRow.messages),
        selectinload(SubmissionValidationRow.normalized_answers),
        selectinload(SubmissionValidationRow.prepared_matrix),
        selectinload(SubmissionValidationRow.criterion_weights),
    )


class SqlAlchemyValidationRepository:
    """Persist complete validation aggregates without transaction control."""

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, validation: SubmissionValidation) -> None:
        """Add a validation and all current output children without committing."""

        self._database_session.add(validation_to_row(validation))

    def get(self, validation_id: str) -> SubmissionValidation | None:
        """Load one complete validation without taking a write lock."""

        row = self._load_by_id(validation_id, for_update=False)
        return None if row is None else validation_to_domain(row)

    def get_for_update(
        self,
        validation_id: str,
    ) -> SubmissionValidation | None:
        """Load and lock an attempt for a lifecycle-changing operation."""

        row = self._load_by_id(validation_id, for_update=True)
        return None if row is None else validation_to_domain(row)

    def list_for_submission(
        self,
        submission_id: str,
    ) -> tuple[SubmissionValidation, ...]:
        """Load all validation attempts for a submission deterministically."""

        statement = (
            select(SubmissionValidationRow)
            .options(*_validation_load_options())
            .where(SubmissionValidationRow.submission_id == submission_id)
            .order_by(SubmissionValidationRow.validation_id)
        )
        rows = self._database_session.scalars(statement).all()
        return tuple(validation_to_domain(row) for row in rows)

    def get_by_input_identity(
        self,
        *,
        submission_id: str,
        answers_hash: str,
        configuration_hash: str,
        validator_implementation_id: str,
        validator_version: str,
        parameter_hash: str,
    ) -> SubmissionValidation | None:
        """Find an existing attempt with the schema's unique input identity."""

        statement = (
            select(SubmissionValidationRow)
            .options(*_validation_load_options())
            .where(
                SubmissionValidationRow.submission_id == submission_id,
                SubmissionValidationRow.answers_hash == answers_hash,
                SubmissionValidationRow.configuration_hash
                == configuration_hash,
                SubmissionValidationRow.validator_implementation_id
                == validator_implementation_id,
                SubmissionValidationRow.validator_version
                == validator_version,
                SubmissionValidationRow.parameter_hash == parameter_hash,
            )
        )
        statement = statement.order_by(
            SubmissionValidationRow.attempt_number.desc()
        ).limit(1)
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else validation_to_domain(row)

    def list_by_input_identity(
        self,
        *,
        submission_id: str,
        answers_hash: str,
        configuration_hash: str,
        validator_implementation_id: str,
        validator_version: str,
        parameter_hash: str,
    ) -> tuple[SubmissionValidation, ...]:
        statement = (
            select(SubmissionValidationRow)
            .options(*_validation_load_options())
            .where(
                SubmissionValidationRow.submission_id == submission_id,
                SubmissionValidationRow.answers_hash == answers_hash,
                SubmissionValidationRow.configuration_hash == configuration_hash,
                SubmissionValidationRow.validator_implementation_id
                == validator_implementation_id,
                SubmissionValidationRow.validator_version == validator_version,
                SubmissionValidationRow.parameter_hash == parameter_hash,
            )
            .order_by(SubmissionValidationRow.attempt_number)
        )
        return tuple(
            validation_to_domain(row)
            for row in self._database_session.scalars(statement).all()
        )

    def save(self, validation: SubmissionValidation) -> None:
        """Persist one allowed lifecycle transition without committing."""

        row = self._load_by_id(validation.validation_id, for_update=True)
        if row is None:
            raise ValidationNotFoundError(
                f"Validation {validation.validation_id!r} does not exist."
            )
        apply_validation_aggregate(row, validation)
        self._database_session.flush()

    def _load_by_id(
        self,
        validation_id: str,
        *,
        for_update: bool,
    ) -> SubmissionValidationRow | None:
        if for_update and self._uses_sqlite():
            # SQLite has no row-level FOR UPDATE. A no-op update obtains the
            # database write reservation before state is inspected, preventing
            # competing writers from both completing the same running attempt.
            reservation = (
                update(SubmissionValidationRow)
                .where(
                    SubmissionValidationRow.validation_id == validation_id
                )
                .values(
                    validation_id=SubmissionValidationRow.validation_id
                )
            )
            result = self._database_session.execute(reservation)
            if getattr(result, "rowcount", 0) == 0:
                return None

        statement = (
            select(SubmissionValidationRow)
            .options(*_validation_load_options())
            .where(SubmissionValidationRow.validation_id == validation_id)
        )
        if for_update and self._uses_postgresql():
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()

    def _uses_postgresql(self) -> bool:
        bind = self._database_session.get_bind()
        return bind.dialect.name == "postgresql"

    def _uses_sqlite(self) -> bool:
        bind = self._database_session.get_bind()
        return bind.dialect.name == "sqlite"
