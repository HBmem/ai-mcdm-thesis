"""Manual report content, review history, and audience-specific releases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class ReportingError(ValueError):
    """Safe, user-facing reporting validation failure."""


class ReportingActor(Protocol):
    subject: str | None

    def has_role(self, role: str) -> bool: ...


NARRATIVE_SECTIONS = (
    "Executive summary",
    "Interpretation",
    "Stakeholder tradeoffs",
    "Recommendations",
    "Limitations",
    "Next steps",
)
EVIDENCE_SECTIONS = (
    "01_context",
    "02_configuration",
    "03_validation",
    "04_weighting",
    "05_ranking",
    "06_analyses",
    "07_provenance",
)


@dataclass(frozen=True, slots=True)
class Report:
    report_id: str
    session_id: str
    package_run_id: str
    title: str
    head_number: int
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class ReportRevision:
    revision_id: str
    report_id: str
    number: int
    parent_revision_id: str | None
    sections: dict[str, str | None]
    evidence_refs: tuple[str, ...]
    document_ids: tuple[str, ...]
    change_summary: str
    created_at: datetime
    created_by: str

    def __post_init__(self) -> None:
        if set(self.sections) != set(NARRATIVE_SECTIONS):
            raise ReportingError("Include all six narrative sections.")
        if any(
            value is not None and not isinstance(value, str)
            for value in self.sections.values()
        ):
            raise ReportingError(
                "Narratives must be plain text or explicitly not assessed."
            )
        if not set(self.evidence_refs).issubset(EVIDENCE_SECTIONS):
            raise ReportingError("An evidence reference is invalid.")
        if self.number < 1 or not self.change_summary.strip():
            raise ReportingError("A revision number and change summary are required.")

    def require_complete(self) -> None:
        if any(
            value is not None and not value.strip() for value in self.sections.values()
        ):
            raise ReportingError(
                "Complete every narrative section or mark it Not assessed."
            )


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision_id: str
    revision_id: str
    number: int
    status: str
    reason: str
    warnings_acknowledged: bool
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class ReportRelease:
    release_id: str
    session_id: str
    revision_id: str
    approval_id: str
    audience: str
    number: int
    status: str
    created_at: datetime
    created_by: str
    withdrawn_at: datetime | None = None
    withdrawn_by: str | None = None
    withdrawal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SupportingDocument:
    document_id: str
    session_id: str
    head_number: int
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    version_id: str
    document_id: str
    number: int
    title: str
    source_reference: str
    classification: str
    filename: str
    media_type: str
    content_hash: str
    content: bytes = field(repr=False)
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class DocumentApproval:
    approval_id: str
    version_id: str
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    """Document-version metadata without its potentially large file payload."""

    version_id: str
    document_id: str
    number: int
    title: str
    source_reference: str
    classification: str
    filename: str
    media_type: str
    content_hash: str
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class ModeratorNote:
    note_id: str
    report_id: str
    body: str
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class SharedReport:
    """The only projection accepted by shared renderers and exports."""

    title: str
    revision: ReportRevision
    package_run_id: str
    package_hash: str
    evidence: dict
    documents: tuple[DocumentVersion | DocumentSummary, ...]
    draft: bool
    release_id: str | None = None
