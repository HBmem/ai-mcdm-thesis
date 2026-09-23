"""Explicit row mappings with append-only content and atomic head advancement."""

from dataclasses import fields
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import defer

from poli_insight.domain import reporting as domain
from poli_insight.infrastructure.database.models import reporting as rows
from poli_insight.infrastructure.database.repositories.result_package_repository import (
    _lock_session,
)

MODELS = {
    domain.Report: rows.ReportRow,
    domain.ReportRevision: rows.ReportRevisionRow,
    domain.ReviewDecision: rows.ReviewDecisionRow,
    domain.ReportRelease: rows.ReportReleaseRow,
    domain.SupportingDocument: rows.SupportingDocumentRow,
    domain.DocumentVersion: rows.DocumentVersionRow,
    domain.DocumentApproval: rows.DocumentApprovalRow,
    domain.ModeratorNote: rows.ModeratorNoteRow,
}


def to_domain(record_type, row):
    values = {f.name: getattr(row, f.name) for f in fields(record_type)}
    values = {
        key: str(value) if isinstance(value, UUID) else value
        for key, value in values.items()
    }
    for key in ("evidence_refs", "document_ids"):
        if key in values:
            values[key] = tuple(values[key])
    return record_type(**values)


class SqlAlchemyReportingRepository:
    def __init__(self, database_session):
        self.db = database_session

    def get(self, record_type, identity):
        if record_type == domain.DocumentSummary:
            row = self.db.scalar(
                select(rows.DocumentVersionRow)
                .where(rows.DocumentVersionRow.version_id == identity)
                .options(defer(rows.DocumentVersionRow.content, raiseload=True))
            )
            return None if row is None else to_domain(record_type, row)
        row = self.db.get(MODELS[record_type], identity)
        return None if row is None else to_domain(record_type, row)

    def document_summaries(self, session_id):
        statement = (
            select(rows.DocumentVersionRow)
            .join(rows.SupportingDocumentRow)
            .where(rows.SupportingDocumentRow.session_id == session_id)
            .options(defer(rows.DocumentVersionRow.content, raiseload=True))
            .order_by(rows.DocumentVersionRow.created_at.desc())
        )
        return tuple(
            to_domain(domain.DocumentSummary, row) for row in self.db.scalars(statement)
        )

    def list(self, record_type, **filters):
        model = MODELS[record_type]
        statement = select(model).filter_by(**filters)
        if hasattr(model, "number"):
            statement = statement.order_by(model.number.desc())
        else:
            statement = statement.order_by(model.created_at.desc())
        return tuple(to_domain(record_type, row) for row in self.db.scalars(statement))

    def add(self, record):
        values = {f.name: getattr(record, f.name) for f in fields(record)}
        self.db.add(MODELS[type(record)](**values))
        self.db.flush()

    def lock_session(self, session_id):
        _lock_session(self.db, session_id)
        self.db.expire_all()

    def advance_head(self, record_type, identity, expected):
        model = MODELS[record_type]
        pk = model.__mapper__.primary_key[0]
        result = self.db.execute(
            update(model)
            .where(pk == identity, model.head_number == expected)
            .values(head_number=expected + 1)
        )
        if result.rowcount != 1:
            raise domain.ReportingError(
                "This record changed. Reload before saving your edits."
            )

    def withdraw(self, release):
        row = self.db.get(rows.ReportReleaseRow, release.release_id)
        for name in ("status", "withdrawn_at", "withdrawn_by", "withdrawal_reason"):
            setattr(row, name, getattr(release, name))
        self.db.flush()
