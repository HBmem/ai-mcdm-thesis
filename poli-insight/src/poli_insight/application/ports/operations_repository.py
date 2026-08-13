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


@dataclass(frozen=True, slots=True)
class ParticipantSubmissionImportBatch:
    """Safe, secret-free metadata for one atomic participant import."""

    batch_id: str
    session_id: str
    scenario_snapshot_id: str
    configuration_version_id: str
    file_hash: str
    plan_hash: str
    filename: str
    row_count: int
    created_participant_count: int
    enrolled_count: int
    draft_count: int
    submitted_count: int
    skipped_count: int
    replaced_count: int
    identity_count: int
    lifecycle_override: bool
    resubmission_override: bool
    identity_attested: bool
    terminal_status: str
    imported_at: datetime
    imported_by: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ParticipantImportReference:
    reference_mapping_id: str
    session_id: str
    participant_id: str
    reference_digest: str
    first_batch_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ParticipantSubmissionImportRecord:
    import_record_id: str
    batch_id: str
    reference_mapping_id: str
    participant_id: str
    submission_id: str | None
    predecessor_submission_id: str | None
    source_row_number: int
    record_state: str
    recorded_at: datetime
    imported_at: datetime


@dataclass(frozen=True, slots=True)
class AdminImportConsentDisposition:
    disposition_id: str
    participant_id: str
    submission_id: str | None
    configuration_version_id: str
    batch_id: str
    administrator_id: str
    reason_code: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ImportedIdentityAuthority:
    authority_id: str
    participant_id: str
    batch_id: str
    administrator_id: str
    processing_basis: str
    attested_at: datetime
    retention_until: datetime


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


class ParticipantSubmissionImportRepository(Protocol):
    """Persistence for import provenance and keyed reference mappings."""

    def get_batch(
        self, session_id: str, file_hash: str, plan_hash: str
    ) -> ParticipantSubmissionImportBatch | None: ...

    def participants_by_reference_digests(
        self, session_id: str, reference_digests: tuple[str, ...]
    ) -> dict[str, str]: ...

    def get_reference(
        self, session_id: str, reference_digest: str
    ) -> ParticipantImportReference | None: ...

    def get_reference_for_participant(
        self, session_id: str, participant_id: str
    ) -> ParticipantImportReference | None: ...

    def add_batch(self, batch: ParticipantSubmissionImportBatch) -> None: ...

    def add_reference(self, reference: ParticipantImportReference) -> None: ...

    def add_record(self, record: ParticipantSubmissionImportRecord) -> None: ...

    def add_consent_disposition(
        self, disposition: AdminImportConsentDisposition
    ) -> None: ...

    def add_identity_authority(
        self, authority: ImportedIdentityAuthority
    ) -> None: ...
