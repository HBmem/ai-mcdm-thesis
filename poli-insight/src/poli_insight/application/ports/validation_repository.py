"""Persistence port for immutable submission-validation aggregates."""

from __future__ import annotations

from typing import Protocol, Sequence

from poli_insight.domain.validation import SubmissionValidation


class ValidationRepository(Protocol):
    """Persist and query complete validation attempts without committing."""

    def add(self, validation: SubmissionValidation) -> None:
        """Add a new validation attempt and its current output children."""
        ...

    def get(self, validation_id: str) -> SubmissionValidation | None:
        """Load one complete validation attempt by identity."""
        ...

    def get_for_update(
        self,
        validation_id: str,
    ) -> SubmissionValidation | None:
        """Load and lock an attempt before a lifecycle transition."""
        ...

    def list_for_submission(
        self,
        submission_id: str,
    ) -> Sequence[SubmissionValidation]:
        """Load all attempts for a submission in deterministic order."""
        ...

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
        """Find an attempt with the schema's immutable input identity."""
        ...

    def save(self, validation: SubmissionValidation) -> None:
        """Persist one legal lifecycle transition of an existing attempt."""
        ...
