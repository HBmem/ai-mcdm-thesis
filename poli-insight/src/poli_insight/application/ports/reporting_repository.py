"""Repository boundary for the manual reporting aggregate."""

from typing import Protocol, TypeVar

from poli_insight.domain.reporting import (
    DocumentApproval,
    DocumentSummary,
    DocumentVersion,
    ModeratorNote,
    Report,
    ReportRelease,
    ReportRevision,
    ReviewDecision,
    SupportingDocument,
)

Record = (
    Report
    | ReportRevision
    | ReviewDecision
    | ReportRelease
    | SupportingDocument
    | DocumentVersion
    | DocumentSummary
    | DocumentApproval
    | ModeratorNote
)
T = TypeVar("T", bound=Record)


class ReportingRepository(Protocol):
    def document_summaries(self, session_id: str) -> tuple[DocumentSummary, ...]: ...
    def get(self, record_type: type[T], identity: str) -> T | None: ...
    def list(self, record_type: type[T], **filters: object) -> tuple[T, ...]: ...
    def add(self, record: Record) -> None: ...
    def lock_session(self, session_id: str) -> None: ...
    def advance_head(
        self,
        record_type: type[Report] | type[SupportingDocument],
        identity: str,
        expected: int,
    ) -> None: ...
    def withdraw(self, release: ReportRelease) -> None: ...
