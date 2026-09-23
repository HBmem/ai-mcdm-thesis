"""Authorized manual-report operations and strictly separated audience projections."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID
from zipfile import BadZipFile, ZipFile

from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.application.use_cases.participant_access import (
    ParticipantAccessError,
    authorize_participant_access,
)
from poli_insight.application.use_cases.participant_result_release import (
    ReleaseParticipantResults,
    ReleaseParticipantResultsCommand,
    _current_roster_hash,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.enum import (
    ActorType,
    AuditAction,
    PackageArtifactType,
    RunStatus,
    SessionStatus,
)
from poli_insight.domain.reporting import (
    EVIDENCE_SECTIONS,
    NARRATIVE_SECTIONS,
    DocumentApproval,
    DocumentSummary,
    DocumentVersion,
    ModeratorNote,
    Report,
    ReportingError,
    ReportRelease,
    ReportRevision,
    ReviewDecision,
    SharedReport,
    SupportingDocument,
)

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def validate_document(filename, content):
    """Validate the container without executing, rendering, or extracting it."""
    filename = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in MEDIA_TYPES or not filename or len(filename) > 255:
        raise ReportingError(
            "Upload a PDF, DOCX, TXT, or Markdown file with a short filename."
        )
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ReportingError("Documents must be nonempty and no larger than 20 MB.")
    if suffix in {".txt", ".md"}:
        try:
            value = content.decode("utf-8-sig")
            if "\x00" in value:
                raise ValueError()
        except (UnicodeDecodeError, ValueError) as error:
            raise ReportingError(
                "Text documents must contain UTF-8 text without null bytes."
            ) from error
    elif suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise ReportingError("The document is not a PDF file.")
    elif suffix == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
                if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                    raise ValueError()
                if any("vbaproject" in name.lower() for name in names):
                    raise ValueError()
        except (BadZipFile, ValueError) as error:
            raise ReportingError(
                "The document is not a supported macro-free DOCX file."
            ) from error
    return filename, MEDIA_TYPES[suffix]


def shared_evidence(package):
    """Only persisted aggregate common sections; no manifests, subjects, or environments."""
    evidence = {
        item.name: dict(item.content_json)
        for item in package.artifacts
        if item.artifact_type == PackageArtifactType.COMMON_SECTION
        and item.name in EVIDENCE_SECTIONS
    }
    provenance = evidence.get("07_provenance", {})
    evidence["07_provenance"] = {
        key: provenance[key]
        for key in (
            "schema_version",
            "source_processing_run_id",
            "source_ranking_run_id",
            "source_analysis_run_ids",
            "source_roster_hash",
            "lineage_state_at_packaging",
        )
        if key in provenance
    }
    return evidence


def package_warnings(package):
    warnings = set()
    for artifact in package.artifacts:
        if artifact.artifact_type == PackageArtifactType.VARIANT_MANIFEST:
            warnings.update(artifact.content_json.get("warnings", ()))
    evidence = shared_evidence(package)
    for item in evidence.get("06_analyses", {}).get("completeness", ()):
        if item.get("state") != "selected":
            warnings.add(f"{item.get('method')}: {item.get('state')}")
    return tuple(sorted(warnings))


class ManualReporting:
    def __init__(self, unit_of_work_factory, *, admin_role="admin", clock=utc_now):
        if not admin_role.strip():
            raise ValueError("Reporting administrator role is required.")
        self.uow = unit_of_work_factory
        self.admin_role = admin_role.strip()
        self.clock = clock

    def _authorize(self, actor):
        if not actor or not actor.subject or not actor.has_role(self.admin_role):
            raise ReportingError("Administrator access is required.")
        return actor.subject

    @contextmanager
    def _mutation(self, actor, session_id):
        self._authorize(actor)
        with self.uow() as uow:
            if uow.session.get(session_id) is None:
                raise ReportingError("Session unavailable.")
            uow.reporting.lock_session(session_id)
            yield uow
            uow.commit()

    def _audit(self, uow, actor, session_id, record, action):
        identity = getattr(record, next(iter(record.__dataclass_fields__)))
        uow.audit_events.add(
            operational_audit_event(
                event_id=str(new_id()),
                occurred_at=self.clock(),
                session_id=session_id,
                actor_id=actor.subject,
                actor_type=ActorType.USER,
                action=action,
                entity_type=type(record).__name__,
                entity_id=identity,
                correlation_id=str(new_id()),
                use_case="manual_reporting",
            )
        )

    @staticmethod
    def _get(uow, kind, identity):
        record = uow.reporting.get(kind, identity)
        if record is None:
            raise ReportingError("The requested reporting record is unavailable.")
        return record

    def _report_session(self, actor, report_id):
        self._authorize(actor)
        with self.uow() as uow:
            return self._get(uow, Report, report_id).session_id

    def package_options(self, actor, session_id):
        self._authorize(actor)
        with self.uow() as uow:
            return uow.result_packages.list_overviews(session_id)

    def package_evidence(self, actor, package_run_id):
        self._authorize(actor)
        with self.uow() as uow:
            package = uow.result_packages.get_overview(package_run_id)
            if package is None:
                raise ReportingError("Select a successful result package.")
            return package

    def workspace(self, actor, session_id, *, include_documents=True):
        self._authorize(actor)
        with self.uow() as uow:
            documents = (
                uow.reporting.list(SupportingDocument, session_id=session_id)
                if include_documents
                else ()
            )
            versions = (
                uow.reporting.document_summaries(session_id)
                if include_documents
                else ()
            )
            approved = {
                v.version_id
                for v in versions
                if uow.reporting.list(DocumentApproval, version_id=v.version_id)
            }
            return {
                "reports": uow.reporting.list(Report, session_id=session_id),
                "documents": documents,
                "versions": versions,
                "approved_documents": approved,
                "releases": uow.reporting.list(ReportRelease, session_id=session_id),
            }

    def history(self, actor, report_id):
        self._authorize(actor)
        with self.uow() as uow:
            self._get(uow, Report, report_id)
            revisions = uow.reporting.list(ReportRevision, report_id=report_id)
            return {
                "revisions": revisions,
                "reviews": {
                    r.revision_id: uow.reporting.list(
                        ReviewDecision, revision_id=r.revision_id
                    )
                    for r in revisions
                },
                "notes": uow.reporting.list(ModeratorNote, report_id=report_id),
            }

    def upload_document(
        self,
        actor,
        *,
        session_id,
        title,
        source_reference,
        classification,
        filename,
        content,
        document_id=None,
        expected_version=None,
    ):
        self._authorize(actor)
        filename, media_type = validate_document(filename, content)
        if classification not in {"shareable", "confidential"} or not title.strip():
            raise ReportingError(
                "A title and valid document classification are required."
            )
        with self._mutation(actor, session_id) as uow:
            now = self.clock()
            if document_id:
                doc = self._get(uow, SupportingDocument, document_id)
                if doc.session_id != session_id:
                    raise ReportingError("Document belongs to another session.")
                uow.reporting.advance_head(
                    SupportingDocument, document_id, expected_version
                )
                number = expected_version + 1
            else:
                document_id = str(new_id())
                uow.reporting.add(
                    SupportingDocument(document_id, session_id, 1, now, actor.subject)
                )
                number = 1
            version = DocumentVersion(
                str(new_id()),
                document_id,
                number,
                title.strip(),
                source_reference.strip(),
                classification,
                filename,
                media_type,
                sha256(content).hexdigest(),
                content,
                now,
                actor.subject,
            )
            uow.reporting.add(version)
            self._audit(uow, actor, session_id, version, AuditAction.CREATED)
            return version

    def approve_document(self, actor, version_id):
        version = self.document(actor, version_id)
        with self.uow() as uow:
            doc = self._get(uow, SupportingDocument, version.document_id)
        with self._mutation(actor, doc.session_id) as uow:
            if version.classification != "shareable":
                raise ReportingError(
                    "Confidential documents cannot be approved for shared reports."
                )
            approvals = uow.reporting.list(DocumentApproval, version_id=version_id)
            if approvals:
                return approvals[0]
            approval = DocumentApproval(
                str(new_id()), version_id, self.clock(), actor.subject
            )
            uow.reporting.add(approval)
            self._audit(uow, actor, doc.session_id, approval, AuditAction.APPROVED)
            return approval

    def document(self, actor, version_id):
        self._authorize(actor)
        with self.uow() as uow:
            return self._get(uow, DocumentVersion, version_id)

    def create_report(self, actor, *, package_run_id, title):
        self._authorize(actor)
        with self.uow() as uow:
            package = self._package(uow, package_run_id)
        if not title.strip():
            raise ReportingError("Enter a report title.")
        with self._mutation(actor, package.session_id) as uow:
            now = self.clock()
            report = Report(
                str(new_id()),
                package.session_id,
                package_run_id,
                title.strip(),
                1,
                now,
                actor.subject,
            )
            revision = ReportRevision(
                str(new_id()),
                report.report_id,
                1,
                None,
                dict.fromkeys(NARRATIVE_SECTIONS, ""),
                (),
                (),
                "Initial deterministic draft",
                now,
                actor.subject,
            )
            uow.reporting.add(report)
            uow.reporting.add(revision)
            self._audit(uow, actor, report.session_id, report, AuditAction.CREATED)
            return report

    def save_revision(
        self,
        actor,
        *,
        report_id,
        expected_revision_id,
        sections,
        evidence_refs=(),
        document_ids=(),
        change_summary,
    ):
        session_id = self._report_session(actor, report_id)
        with self._mutation(actor, session_id) as uow:
            report = self._get(uow, Report, report_id)
            head = uow.reporting.list(ReportRevision, report_id=report_id)[0]
            if head.revision_id != expected_revision_id:
                raise ReportingError(
                    "This report changed. Reload before saving your edits."
                )
            revision = ReportRevision(
                str(new_id()),
                report_id,
                head.number + 1,
                head.revision_id,
                dict(sections),
                tuple(dict.fromkeys(evidence_refs)),
                tuple(dict.fromkeys(document_ids)),
                change_summary.strip(),
                self.clock(),
                actor.subject,
            )
            self._sources(uow, report, revision)
            uow.reporting.advance_head(Report, report_id, head.number)
            uow.reporting.add(revision)
            self._audit(uow, actor, session_id, revision, AuditAction.UPDATED)
            return revision

    def add_note(self, actor, *, report_id, body):
        session_id = self._report_session(actor, report_id)
        if not body.strip():
            raise ReportingError("Enter a moderator note.")
        with self._mutation(actor, session_id) as uow:
            note = ModeratorNote(
                str(new_id()), report_id, body.strip(), self.clock(), actor.subject
            )
            uow.reporting.add(note)
            self._audit(uow, actor, session_id, note, AuditAction.CREATED)
            return note

    def review(
        self, actor, *, revision_id, status, reason="", warnings_acknowledged=False
    ):
        self._authorize(actor)
        with self.uow() as uow:
            revision = self._get(uow, ReportRevision, revision_id)
            report = self._get(uow, Report, revision.report_id)
        with self._mutation(actor, report.session_id) as uow:
            reviews = uow.reporting.list(ReviewDecision, revision_id=revision_id)
            current = reviews[0].status if reviews else "draft"
            allowed = {
                "draft": {"submitted"},
                "submitted": {"approved", "rejected"},
                "rejected": {"submitted"},
            }
            if status not in allowed.get(current, set()):
                raise ReportingError(
                    "This review changed or the requested transition is unavailable. Reload the report."
                )
            if status == "rejected" and not reason.strip():
                raise ReportingError("A rejection reason is required.")
            if status in {"submitted", "approved"}:
                revision.require_complete()
                self._sources(uow, report, revision)
                if (
                    package_warnings(self._package(uow, report.package_run_id))
                    and not warnings_acknowledged
                ):
                    raise ReportingError(
                        "Acknowledge the completeness and privacy warnings for this revision."
                    )
            decision = ReviewDecision(
                str(new_id()),
                revision_id,
                len(reviews) + 1,
                status,
                reason.strip(),
                warnings_acknowledged,
                self.clock(),
                actor.subject,
            )
            uow.reporting.add(decision)
            self._audit(
                uow,
                actor,
                report.session_id,
                decision,
                AuditAction.APPROVED if status == "approved" else AuditAction.UPDATED,
            )
            return decision

    def publish(self, actor, *, revision_id, audience):
        self._authorize(actor)
        if audience not in {"participant", "public"}:
            raise ReportingError("Choose participant or public publication.")
        with self.uow() as uow:
            revision = self._get(uow, ReportRevision, revision_id)
            report = self._get(uow, Report, revision.report_id)
        with self._mutation(actor, report.session_id) as uow:
            reviews = uow.reporting.list(ReviewDecision, revision_id=revision_id)
            if not reviews or reviews[0].status != "approved":
                raise ReportingError("Approve this exact revision before publication.")
            package = self._package(uow, report.package_run_id)
            self._eligible(uow, package)
            self._sources(uow, report, revision)
            history = uow.reporting.list(
                ReportRelease, session_id=report.session_id, audience=audience
            )
            if audience == "participant":
                previous = uow.participant_result_releases.get_active_for_session(
                    report.session_id, for_update=True
                )
                if (
                    previous is None
                    or previous.package_run_id != package.package_run_id
                ):
                    ReleaseParticipantResults(
                        self.uow, clock=self.clock
                    ).execute_in_unit_of_work(
                        uow,
                        ReleaseParticipantResultsCommand(
                            session_id=report.session_id,
                            package_run_id=package.package_run_id,
                            actor_id=actor.subject,
                        ),
                    )
                else:
                    session = uow.session.get(report.session_id)
                    if session.identity_policy.casefold() == "anonymous":
                        raise ReportingError(
                            "Anonymous sessions cannot release identity-linked participant results."
                        )
            for previous in history:
                if previous.status == "active":
                    self._withdraw(
                        uow, actor, previous, "Superseded by a new report release."
                    )
            release = ReportRelease(
                str(new_id()),
                report.session_id,
                revision_id,
                reviews[0].decision_id,
                audience,
                max((r.number for r in history), default=0) + 1,
                "active",
                self.clock(),
                actor.subject,
            )
            uow.reporting.add(release)
            self._audit(uow, actor, report.session_id, release, AuditAction.PUBLISHED)
            return release

    def withdraw(self, actor, *, release_id, reason):
        self._authorize(actor)
        if not reason.strip():
            raise ReportingError("A withdrawal reason is required.")
        with self.uow() as uow:
            release = self._get(uow, ReportRelease, release_id)
        with self._mutation(actor, release.session_id) as uow:
            release = self._get(uow, ReportRelease, release_id)
            if release.status != "active":
                raise ReportingError("This release is already withdrawn.")
            self._withdraw(uow, actor, release, reason.strip())

    def _withdraw(self, uow, actor, release, reason):
        uow.reporting.withdraw(
            replace(
                release,
                status="withdrawn",
                withdrawn_at=self.clock(),
                withdrawn_by=actor.subject,
                withdrawal_reason=reason,
            )
        )
        self._audit(uow, actor, release.session_id, release, AuditAction.WITHDRAWN)

    def preview(self, actor, revision_id, *, include_files=True):
        self._authorize(actor)
        with self.uow() as uow:
            return self._projection(uow, revision_id, include_files=include_files)

    def public_report(self, release_id):
        try:
            UUID(release_id)
            with self.uow() as uow:
                release = self._get(uow, ReportRelease, release_id)
                if release.audience != "public":
                    raise ReportingError("Unavailable")
                return self._released(uow, release)
        except (ReportingError, ValueError, TypeError) as error:
            raise ReportingError("This public report is unavailable.") from error

    def public_catalog(self, search="", *, page=1, page_size=20):
        if page < 1 or not 1 <= page_size <= 100:
            raise ReportingError("Invalid catalog page.")
        with self.uow() as uow:
            items = []
            for release in uow.reporting.list(
                ReportRelease, audience="public", status="active"
            ):
                try:
                    revision = self._get(uow, ReportRevision, release.revision_id)
                    report = self._get(uow, Report, revision.report_id)
                    self._eligible(uow, self._package(uow, report.package_run_id))
                    if search.casefold() in report.title.casefold():
                        items.append(
                            {
                                "release_id": release.release_id,
                                "title": report.title,
                                "released_at": release.created_at,
                                "revision": revision.number,
                            }
                        )
                except ReportingError:
                    continue
            items.sort(key=lambda item: item["released_at"], reverse=True)
            return tuple(items[(page - 1) * page_size : page * page_size]), len(items)

    def participant_report(self, access_token):
        with self.uow() as uow:
            try:
                participant = authorize_participant_access(
                    uow, access_token=access_token, at=self.clock()
                )
            except ParticipantAccessError as error:
                raise ReportingError("Participant report unavailable.") from error
            releases = uow.reporting.list(
                ReportRelease,
                session_id=participant.session_id,
                audience="participant",
                status="active",
            )
            session = uow.session.get(participant.session_id)
            if session is None or session.identity_policy.casefold() == "anonymous":
                raise ReportingError("Participant report unavailable.")
            if not releases:
                return None
            shared = self._released(uow, releases[0])
            private = uow.participant_result_releases.get_active_for_session(
                participant.session_id
            )
            package = self._package(uow, shared.package_run_id)
            if (
                private is None
                or private.package_run_id != shared.package_run_id
                or not any(
                    s.participant_id == participant.participant_id
                    for s in package.subjects
                )
            ):
                raise ReportingError(
                    "The shared report and private results are not currently released together."
                )
            uow.commit()
            return shared

    def _released(self, uow, release):
        if release.status != "active":
            raise ReportingError("Release unavailable.")
        approval = self._get(uow, ReviewDecision, release.approval_id)
        if approval.status != "approved" or approval.revision_id != release.revision_id:
            raise ReportingError("Approval unavailable.")
        revision = self._get(uow, ReportRevision, release.revision_id)
        report = self._get(uow, Report, revision.report_id)
        if report.session_id != release.session_id:
            raise ReportingError("Release unavailable.")
        self._eligible(uow, self._package(uow, report.package_run_id))
        return self._projection(uow, release.revision_id, release_id=release.release_id)

    def _projection(self, uow, revision_id, *, release_id=None, include_files=True):
        revision = self._get(uow, ReportRevision, revision_id)
        report = self._get(uow, Report, revision.report_id)
        package = self._evidence_package(uow, report.package_run_id)
        documents = self._sources(
            uow, report, revision, metadata_only=not include_files
        )
        reviews = uow.reporting.list(ReviewDecision, revision_id=revision_id)
        return SharedReport(
            report.title,
            revision,
            package.package_run_id,
            package.output_hash,
            shared_evidence(package),
            documents,
            not reviews or reviews[0].status != "approved",
            release_id,
        )

    def _sources(self, uow, report, revision, *, metadata_only=False):
        evidence = shared_evidence(self._evidence_package(uow, report.package_run_id))
        if any(key not in evidence for key in revision.evidence_refs):
            raise ReportingError(
                "An evidence reference is unavailable in this package."
            )
        documents = []
        for identity in revision.document_ids:
            version = self._get(
                uow, DocumentSummary if metadata_only else DocumentVersion, identity
            )
            doc = self._get(uow, SupportingDocument, version.document_id)
            if (
                doc.session_id != report.session_id
                or version.classification != "shareable"
                or not uow.reporting.list(DocumentApproval, version_id=identity)
            ):
                raise ReportingError(
                    "Only approved shareable document versions from this session may be cited or attached."
                )
            documents.append(version)
        return tuple(documents)

    @staticmethod
    def _evidence_package(uow, package_id):
        package = uow.result_packages.get_overview(package_id)
        if package is None:
            raise ReportingError("Select a successful result package.")
        return package

    @staticmethod
    def _package(uow, package_id):
        package = uow.result_packages.get(package_id)
        if package is None or package.status != RunStatus.SUCCEEDED:
            raise ReportingError("Select a successful result package.")
        return package

    @staticmethod
    def _eligible(uow, package):
        session = uow.session.get(package.session_id)
        source = uow.processing_runs.get(package.source_processing_run_id)
        if session is None or session.status != SessionStatus.CLOSED:
            raise ReportingError("Only closed sessions may publish reports.")
        if (
            source is None
            or _current_roster_hash(uow, source) != package.source_roster_hash
        ):
            raise ReportingError(
                "This package is stale. Process and package current results before publication."
            )
