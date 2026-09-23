"""Persistence for manual reports; content versions are append-only."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


class Authored:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)


class ReportRow(Authored, Base):
    __tablename__ = "manual_reports"
    __table_args__ = (
        CheckConstraint("head_number >= 1", name="ck_manual_report_head"),
    )
    report_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("sessions.session_id", ondelete="RESTRICT"), index=True
    )
    package_run_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("result_package_runs.package_run_id", ondelete="RESTRICT"),
    )
    title: Mapped[str] = mapped_column(Text())
    head_number: Mapped[int] = mapped_column(Integer)


class ReportRevisionRow(Authored, Base):
    __tablename__ = "report_revisions"
    __table_args__ = (
        UniqueConstraint("report_id", "number", name="uq_report_revision_number"),
        CheckConstraint("number >= 1", name="ck_report_revision_number"),
    )
    revision_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("manual_reports.report_id", ondelete="RESTRICT")
    )
    number: Mapped[int] = mapped_column(Integer)
    parent_revision_id: Mapped[str | None] = mapped_column(
        UUIDString(), ForeignKey("report_revisions.revision_id", ondelete="RESTRICT")
    )
    sections: Mapped[dict] = mapped_column(JSON)
    evidence_refs: Mapped[list] = mapped_column(JSON)
    document_ids: Mapped[list] = mapped_column(JSON)
    change_summary: Mapped[str] = mapped_column(Text())


class ReviewDecisionRow(Authored, Base):
    __tablename__ = "report_review_decisions"
    __table_args__ = (
        UniqueConstraint("revision_id", "number", name="uq_report_review_number"),
        CheckConstraint(
            "status IN ('submitted', 'approved', 'rejected')",
            name="ck_report_review_status",
        ),
    )
    decision_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("report_revisions.revision_id", ondelete="RESTRICT")
    )
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text())
    warnings_acknowledged: Mapped[bool] = mapped_column(Boolean)


class ReportReleaseRow(Authored, Base):
    __tablename__ = "report_releases"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "audience", "number", name="uq_report_release_number"
        ),
        Index(
            "uq_report_release_active",
            "session_id",
            "audience",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "audience IN ('participant', 'public')", name="ck_report_release_audience"
        ),
        CheckConstraint(
            "status IN ('active', 'withdrawn')", name="ck_report_release_status"
        ),
        CheckConstraint("number >= 1", name="ck_report_release_number"),
        CheckConstraint(
            "(status = 'active' AND withdrawn_at IS NULL AND withdrawn_by IS NULL AND withdrawal_reason IS NULL) OR (status = 'withdrawn' AND withdrawn_at IS NOT NULL AND withdrawn_by IS NOT NULL AND withdrawal_reason IS NOT NULL)",
            name="ck_report_release_withdrawal",
        ),
    )
    release_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("sessions.session_id", ondelete="RESTRICT")
    )
    revision_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("report_revisions.revision_id", ondelete="RESTRICT")
    )
    approval_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("report_review_decisions.decision_id", ondelete="RESTRICT"),
    )
    audience: Mapped[str] = mapped_column(String(20))
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    withdrawn_by: Mapped[str | None] = mapped_column(String(100))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text())


class SupportingDocumentRow(Authored, Base):
    __tablename__ = "supporting_documents"
    __table_args__ = (
        CheckConstraint("head_number >= 1", name="ck_supporting_document_head"),
    )
    document_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        UUIDString(), ForeignKey("sessions.session_id", ondelete="RESTRICT"), index=True
    )
    head_number: Mapped[int] = mapped_column(Integer)


class DocumentVersionRow(Authored, Base):
    __tablename__ = "supporting_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "number", name="uq_supporting_document_version"
        ),
        CheckConstraint(
            "classification IN ('shareable', 'confidential')",
            name="ck_supporting_document_class",
        ),
        CheckConstraint("number >= 1", name="ck_supporting_document_version"),
    )
    version_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("supporting_documents.document_id", ondelete="RESTRICT"),
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text())
    source_reference: Mapped[str] = mapped_column(Text())
    classification: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)


class DocumentApprovalRow(Authored, Base):
    __tablename__ = "supporting_document_approvals"
    approval_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("supporting_document_versions.version_id", ondelete="RESTRICT"),
        unique=True,
    )


class ModeratorNoteRow(Authored, Base):
    __tablename__ = "report_moderator_notes"
    note_id: Mapped[str] = mapped_column(UUIDString(), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        UUIDString(),
        ForeignKey("manual_reports.report_id", ondelete="RESTRICT"),
        index=True,
    )
    body: Mapped[str] = mapped_column(Text())
