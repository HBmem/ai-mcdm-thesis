"""Persistence ports for operational review and idempotent imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from poli_insight.domain.operations import SubmissionReviewDecision


@dataclass(frozen=True, slots=True)
class InvitationImportBatch:
    batch_id: str
    session_id: str
    file_hash: str
    filename: str
    row_count: int
    imported_count: int
    duplicate_count: int
    invalid_count: int
    applied_at: datetime
    applied_by: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class InvitationImportRecord:
    record_id: str
    batch_id: str
    session_id: str
    invitation_id: str
    reference_hash: str
    row_hash: str
    source_row_number: int


class SubmissionReviewRepository(Protocol):
    def get_latest(
        self,
        submission_id: str,
        *,
        for_update: bool = False,
    ) -> SubmissionReviewDecision | None:
        """Return the latest immutable decision for one submission."""
        ...

    def add(self, decision: SubmissionReviewDecision) -> None:
        """Append a review decision to the current transaction."""
        ...


class InvitationImportRepository(Protocol):
    def get_batch_by_file_hash(
        self,
        session_id: str,
        file_hash: str,
    ) -> InvitationImportBatch | None:
        ...

    def existing_reference_hashes(
        self,
        session_id: str,
        reference_hashes: tuple[str, ...],
    ) -> frozenset[str]:
        ...

    def add_batch(self, batch: InvitationImportBatch) -> None:
        ...

    def add_record(self, record: InvitationImportRecord) -> None:
        ...
