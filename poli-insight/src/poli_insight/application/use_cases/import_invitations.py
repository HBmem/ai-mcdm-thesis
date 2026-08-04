"""Preview-first, idempotent CSV import for session invitations."""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

from poli_insight.application.ports.operations_repository import (
    InvitationImportBatch,
    InvitationImportRecord,
)
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.application.use_cases.manage_invitations import (
    InvitationManagementError,
    IssuedInvitationResult,
    IssueInvitation,
    _add_invitation_code,
    _invitation_event,
    _load_invitation_scope,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.content_hash import hash_json, sha256_digest
from poli_insight.domain.enum import ActorType, AuditAction

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_ROWS = 2_000
REQUIRED_COLUMNS = ("reference", "group", "expires_at")


class InvitationImportError(ValueError):
    """Safe import parse or application failure."""


class ImportPreviewStatus(StrEnum):
    READY = "ready"
    DUPLICATE = "duplicate"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class InvitationImportPreviewRow:
    row_number: int
    reference: str
    group: str
    expires_at: datetime | None
    status: ImportPreviewStatus
    issues: tuple[str, ...]
    reference_hash: str | None = field(default=None, repr=False)
    row_hash: str | None = field(default=None, repr=False)
    assigned_group_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class InvitationImportPreview:
    session_id: str
    filename: str
    file_hash: str
    rows: tuple[InvitationImportPreviewRow, ...]
    expected_inserts: int
    expected_updates: int
    duplicate_count: int
    invalid_count: int


@dataclass(frozen=True, slots=True)
class PreviewInvitationImportCommand:
    session_id: str
    filename: str
    content: bytes


class PreviewInvitationImport:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def execute(
        self,
        command: PreviewInvitationImportCommand,
    ) -> InvitationImportPreview:
        if not command.session_id.strip():
            raise InvitationImportError("Session ID cannot be empty.")
        filename = command.filename.strip()
        if not filename or not filename.lower().endswith(".csv"):
            raise InvitationImportError("Upload a CSV file.")
        if not command.content:
            raise InvitationImportError("The CSV file is empty.")
        if len(command.content) > MAX_IMPORT_BYTES:
            raise InvitationImportError("The CSV file exceeds the 1 MB limit.")
        try:
            text = command.content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise InvitationImportError(
                "The CSV file must use UTF-8 encoding."
            ) from error

        try:
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            headers = tuple(reader.fieldnames or ())
            if headers != REQUIRED_COLUMNS:
                raise InvitationImportError(
                    "CSV columns must be exactly: reference, group, expires_at."
                )
            source_rows = list(reader)
        except csv.Error as error:
            raise InvitationImportError("The CSV file is malformed.") from error
        if len(source_rows) > MAX_IMPORT_ROWS:
            raise InvitationImportError("The CSV file exceeds the 2,000 row limit.")

        now = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            try:
                _session, configuration = _load_invitation_scope(
                    unit_of_work, command.session_id
                )
            except InvitationManagementError as error:
                raise InvitationImportError(str(error)) from error
            groups: dict[str, tuple[str, str]] = {}
            for group in configuration.stakeholder_groups:
                if group.is_active:
                    value = (group.session_stakeholder_group_id, group.name)
                    groups[group.group_key.casefold()] = value
                    groups[group.name.casefold()] = value

            parsed = tuple(
                _parse_row(index, row, groups=groups, now=now)
                for index, row in enumerate(source_rows, start=2)
            )
            reference_counts = Counter(
                row.reference_hash for row in parsed if row.reference_hash is not None
            )
            hashes = tuple(
                row.reference_hash for row in parsed if row.reference_hash is not None
            )
            existing = unit_of_work.invitation_imports.existing_reference_hashes(
                command.session_id,
                hashes,
            )

        rows = tuple(
            _classify_duplicate(
                row,
                duplicate_in_file=(
                    row.reference_hash is not None
                    and reference_counts[row.reference_hash] > 1
                ),
                duplicate_in_database=row.reference_hash in existing,
            )
            for row in parsed
        )
        return InvitationImportPreview(
            session_id=command.session_id,
            filename=filename,
            file_hash=sha256_digest(command.content),
            rows=rows,
            expected_inserts=sum(
                row.status == ImportPreviewStatus.READY for row in rows
            ),
            expected_updates=0,
            duplicate_count=sum(
                row.status == ImportPreviewStatus.DUPLICATE for row in rows
            ),
            invalid_count=sum(
                row.status == ImportPreviewStatus.INVALID for row in rows
            ),
        )


@dataclass(frozen=True, slots=True)
class ApplyInvitationImportCommand:
    session_id: str
    filename: str
    content: bytes = field(repr=False)
    expected_file_hash: str
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))


@dataclass(frozen=True, slots=True, repr=False)
class AppliedInvitation:
    reference: str
    invitation: IssuedInvitationResult


@dataclass(frozen=True, slots=True, repr=False)
class ApplyInvitationImportResult:
    batch_id: str
    file_hash: str
    imported_count: int
    duplicate_count: int
    invalid_count: int
    invitations: tuple[AppliedInvitation, ...]
    already_applied: bool = False


class ApplyInvitationImport:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory
        self._preview = PreviewInvitationImport(
            unit_of_work_factory,
            clock=clock,
        )

    def execute(
        self,
        command: ApplyInvitationImportCommand,
    ) -> ApplyInvitationImportResult:
        preview = self._preview.execute(
            PreviewInvitationImportCommand(
                session_id=command.session_id,
                filename=command.filename,
                content=command.content,
            )
        )
        if preview.file_hash != command.expected_file_hash:
            raise InvitationImportError(
                "The uploaded file changed after preview. Preview it again."
            )
        at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            try:
                session, configuration = _load_invitation_scope(
                    unit_of_work,
                    command.session_id,
                    for_update=True,
                )
            except InvitationManagementError as error:
                raise InvitationImportError(str(error)) from error
            existing_batch = unit_of_work.invitation_imports.get_batch_by_file_hash(
                command.session_id,
                preview.file_hash,
            )
            if existing_batch is not None:
                return ApplyInvitationImportResult(
                    batch_id=existing_batch.batch_id,
                    file_hash=existing_batch.file_hash,
                    imported_count=0,
                    duplicate_count=(
                        existing_batch.imported_count + existing_batch.duplicate_count
                    ),
                    invalid_count=existing_batch.invalid_count,
                    invitations=(),
                    already_applied=True,
                )
            issuer = IssueInvitation(
                self._unit_of_work_factory,
                clock=self._clock,
                id_factory=self._id_factory,
            )
            batch_id = self._id_factory()
            applied: list[AppliedInvitation] = []
            candidate_rows = tuple(
                row for row in preview.rows if row.status == ImportPreviewStatus.READY
            )
            newly_existing = unit_of_work.invitation_imports.existing_reference_hashes(
                command.session_id,
                tuple(
                    row.reference_hash
                    for row in candidate_rows
                    if row.reference_hash is not None
                ),
            )
            ready_rows = tuple(
                row
                for row in candidate_rows
                if row.reference_hash not in newly_existing
            )
            duplicate_count = preview.duplicate_count + (
                len(candidate_rows) - len(ready_rows)
            )
            unit_of_work.invitation_imports.add_batch(
                InvitationImportBatch(
                    batch_id=batch_id,
                    session_id=command.session_id,
                    file_hash=preview.file_hash,
                    filename=preview.filename,
                    row_count=len(preview.rows),
                    imported_count=len(ready_rows),
                    duplicate_count=duplicate_count,
                    invalid_count=preview.invalid_count,
                    applied_at=at,
                    applied_by=command.actor_id,
                    correlation_id=command.correlation_id,
                )
            )
            for row in ready_rows:
                if (
                    row.expires_at is None
                    or row.assigned_group_id is None
                    or row.reference_hash is None
                    or row.row_hash is None
                ):
                    raise AssertionError("Ready import row is incomplete.")
                invitation, token, access_code = issuer._build_invitation(
                    session=session,
                    configuration=configuration,
                    assigned_group_id=row.assigned_group_id,
                    expires_at=row.expires_at,
                    actor_id=command.actor_id,
                    at=at,
                )
                unit_of_work.invitations.add(invitation)
                _add_invitation_code(
                    unit_of_work,
                    session=session,
                    invitation=invitation,
                    access_code=access_code,
                    actor_id=command.actor_id,
                    at=at,
                    id_factory=self._id_factory,
                )
                unit_of_work.invitation_imports.add_record(
                    InvitationImportRecord(
                        record_id=self._id_factory(),
                        batch_id=batch_id,
                        session_id=command.session_id,
                        invitation_id=invitation.invitation_id,
                        reference_hash=row.reference_hash,
                        row_hash=row.row_hash,
                        source_row_number=row.row_number,
                    )
                )
                unit_of_work.audit_events.add(
                    _invitation_event(
                        invitation,
                        event_id=self._id_factory(),
                        actor_id=command.actor_id,
                        actor_type=ActorType.IMPORT_PROCESS,
                        correlation_id=command.correlation_id,
                        occurred_at=at,
                        use_case="apply_invitation_import",
                    )
                )
                applied.append(
                    AppliedInvitation(
                        reference=row.reference,
                        invitation=IssuedInvitationResult(
                            invitation_id=invitation.invitation_id,
                            token=token.plaintext,
                            token_hint=token.token_hint,
                            access_code=access_code,
                            expires_at=invitation.expires_at,
                        ),
                    )
                )
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=at,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.CREATED,
                    entity_type="invitation_import_batch",
                    entity_id=batch_id,
                    correlation_id=command.correlation_id,
                    use_case="apply_invitation_import",
                    after_json={
                        "file_hash": preview.file_hash,
                        "row_count": len(preview.rows),
                        "imported_count": len(applied),
                        "duplicate_count": duplicate_count,
                        "invalid_count": preview.invalid_count,
                    },
                )
            )
            unit_of_work.commit()
        return ApplyInvitationImportResult(
            batch_id=batch_id,
            file_hash=preview.file_hash,
            imported_count=len(applied),
            duplicate_count=duplicate_count,
            invalid_count=preview.invalid_count,
            invitations=tuple(applied),
        )


def _parse_row(
    row_number: int,
    source: dict[str, str | None],
    *,
    groups: dict[str, tuple[str, str]],
    now: datetime,
) -> InvitationImportPreviewRow:
    reference = (source.get("reference") or "").strip()
    group_input = (source.get("group") or "").strip()
    expires_input = (source.get("expires_at") or "").strip()
    issues: list[str] = []
    reference_hash = None
    if not reference:
        issues.append("Reference is required.")
    elif len(reference) > 160:
        issues.append("Reference must be 160 characters or fewer.")
    else:
        reference_hash = sha256_digest(reference.casefold().encode("utf-8"))

    group_match = groups.get(group_input.casefold()) if group_input else None
    if not group_input:
        issues.append("Group is required.")
    elif group_match is None:
        issues.append("Group does not match an active session group.")

    expires_at = _parse_datetime(expires_input)
    if expires_at is None:
        issues.append("Expiration must be an ISO-8601 date and time with timezone.")
    elif expires_at <= now:
        issues.append("Expiration must be in the future.")

    assigned_group_id = None if group_match is None else group_match[0]
    canonical_group = group_input if group_match is None else group_match[1]
    row_hash = None
    if not issues and reference_hash is not None and expires_at is not None:
        row_hash = hash_json(
            {
                "reference_hash": reference_hash,
                "assigned_group_id": assigned_group_id,
                "expires_at": expires_at,
            }
        )
    return InvitationImportPreviewRow(
        row_number=row_number,
        reference=reference,
        group=canonical_group,
        expires_at=expires_at,
        status=(ImportPreviewStatus.INVALID if issues else ImportPreviewStatus.READY),
        issues=tuple(issues),
        reference_hash=reference_hash,
        row_hash=row_hash,
        assigned_group_id=assigned_group_id,
    )


def _classify_duplicate(
    row: InvitationImportPreviewRow,
    *,
    duplicate_in_file: bool,
    duplicate_in_database: bool,
) -> InvitationImportPreviewRow:
    if row.status == ImportPreviewStatus.INVALID:
        return row
    issues: list[str] = []
    if duplicate_in_file:
        issues.append("Reference is duplicated in this file.")
    if duplicate_in_database:
        issues.append("Reference was imported previously for this session.")
    if not issues:
        return row
    return replace(
        row,
        status=ImportPreviewStatus.DUPLICATE,
        issues=tuple(issues),
    )


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)
