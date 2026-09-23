"""End-to-end reporting against real calculations, migrations, and SQLite."""

import io
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from poli_insight.application.use_cases.close_session import CloseSessionCommand
from poli_insight.application.use_cases.create_ranking import CreateRankingCommand
from poli_insight.application.use_cases.create_result_package import (
    CreateResultPackageCommand,
)
from poli_insight.application.use_cases.enroll_participant import (
    EnrollParticipantCommand,
)
from poli_insight.application.use_cases.finalize_validation_bundle import (
    FinalizeValidationBundleCommand,
)
from poli_insight.application.use_cases.manual_report_exports import (
    report_html,
    report_zip,
)
from poli_insight.application.use_cases.manual_reporting import validate_document
from poli_insight.application.use_cases.run_selected_analyses import (
    AnalysisTestSpec,
    RunSelectedAnalysesCommand,
)
from poli_insight.application.use_cases.save_submission_draft import (
    SaveSubmissionDraftCommand,
)
from poli_insight.application.use_cases.submit_response import SubmitResponseCommand
from poli_insight.application.use_cases.validate_current_submissions import (
    ValidateCurrentSubmissionsCommand,
)
from poli_insight.domain.enum import (
    AnalysisMethod,
    BundleVariant,
    ResponseFormat,
    RunStatus,
)
from poli_insight.domain.reporting import NARRATIVE_SECTIONS, ReportingError
from poli_insight.presentation.streamlit.auth.models import Principal
from tests.integration.test_participation_flow import (
    _answer,
    _container,
    _open_questionnaire,
)

ADMIN = Principal("report-admin", "Report moderator", frozenset({"admin"}))


def seed_reporting(database_path: Path):
    container = _container(database_path)
    session_id, group_id = _open_questionnaire(
        container,
        slug="reporting-study",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
    )
    enrolled = []
    for index in range(3):
        enrollment = container.participation.enroll.execute(
            EnrollParticipantCommand(
                session_id=session_id,
                selected_group_id=group_id,
                alias=f"Private respondent {index + 1}",
            )
        )
        enrolled.append(enrollment)
        workspace = container.page_queries.get_participation_workspace(
            enrollment.participant_id
        )
        answers = tuple(
            _answer(q.question_definition_id, workspace.scale_options[2].scale_value_id)
            for q in workspace.questions
        )
        draft = container.submissions.save_draft.execute(
            SaveSubmissionDraftCommand(
                session_id=session_id,
                participant_id=enrollment.participant_id,
                actor_id=enrollment.participant_id,
                access_token=enrollment.access_token,
                answers=answers,
            )
        )
        container.submissions.submit.execute(
            SubmitResponseCommand(
                submission_id=draft.submission_id,
                session_id=session_id,
                participant_id=enrollment.participant_id,
                actor_id=enrollment.participant_id,
                access_token=enrollment.access_token,
            )
        )
    container.sessions.close.execute(
        CloseSessionCommand(session_id=session_id, actor_id=ADMIN.subject)
    )
    validation = container.validation.validate_current.execute(
        ValidateCurrentSubmissionsCommand(session_id, ADMIN.subject)
    )
    container.validation.finalize_bundle.execute(
        FinalizeValidationBundleCommand(validation.processing_run_id, ADMIN.subject)
    )
    ranking = container.ranking.create.execute(
        CreateRankingCommand(session_id, validation.processing_run_id, ADMIN.subject)
    )
    assert ranking.status == RunStatus.SUCCEEDED
    analyses = container.analysis.run_selected.execute(
        RunSelectedAnalysesCommand(
            session_id,
            ranking.ranking_run_id,
            (AnalysisTestSpec(AnalysisMethod.CRITERION_REMOVAL),),
            ADMIN.subject,
        )
    )
    analysis_id = container.analysis.list_runs.execute(session_id)[0].analysis_run_id
    assert analyses
    package = container.packages.create.execute(
        CreateResultPackageCommand(
            session_id,
            ranking.ranking_run_id,
            (analysis_id,),
            (BundleVariant.ANONYMOUS, BundleVariant.PUBLIC),
            ADMIN.subject,
        )
    )
    return container, session_id, package.package_run_id, enrolled


@pytest.fixture
def study(tmp_path):
    return seed_reporting(tmp_path / "reporting.sqlite")


def complete_revision(
    service, report, *, document_ids=(), text="Recorded interpretation."
):
    head = service.history(ADMIN, report.report_id)["revisions"][0]
    return service.save_revision(
        ADMIN,
        report_id=report.report_id,
        expected_revision_id=head.revision_id,
        sections=dict.fromkeys(NARRATIVE_SECTIONS, text),
        evidence_refs=("05_ranking",),
        document_ids=document_ids,
        change_summary="Reviewable narrative",
    )


def approve(service, revision):
    service.review(
        ADMIN,
        revision_id=revision.revision_id,
        status="submitted",
        warnings_acknowledged=True,
    )
    return service.review(
        ADMIN,
        revision_id=revision.revision_id,
        status="approved",
        warnings_acknowledged=True,
    )


def test_revision_review_publication_and_private_results(study):
    container, session_id, package_id, enrolled = study
    service = container.reporting
    report = service.create_report(
        ADMIN, package_run_id=package_id, title="Transit priorities"
    )
    initial = service.history(ADMIN, report.report_id)["revisions"][0]
    assert service.preview(ADMIN, initial.revision_id).draft
    with pytest.raises(ReportingError, match="Complete every"):
        service.review(
            ADMIN,
            revision_id=initial.revision_id,
            status="submitted",
            warnings_acknowledged=True,
        )
    revision = complete_revision(service, report)
    with pytest.raises(ReportingError, match="Acknowledge"):
        service.review(ADMIN, revision_id=revision.revision_id, status="submitted")
    with pytest.raises(ReportingError, match="Reload"):
        service.save_revision(
            ADMIN,
            report_id=report.report_id,
            expected_revision_id=initial.revision_id,
            sections=revision.sections,
            change_summary="Old editor",
        )
    with pytest.raises(ReportingError, match="Approve"):
        service.publish(ADMIN, revision_id=revision.revision_id, audience="public")
    approve(service, revision)
    public = service.publish(ADMIN, revision_id=revision.revision_id, audience="public")
    assert service.public_report(public.release_id).revision == revision
    assert service.participant_report(enrolled[0].access_token) is None
    participant = service.publish(
        ADMIN, revision_id=revision.revision_id, audience="participant"
    )
    assert (
        service.participant_report(enrolled[0].access_token).package_run_id
        == package_id
    )
    private = container.packages.participant_access.execute(enrolled[0].access_token)
    assert private.package_run_id == package_id
    assert private.alias == "Private respondent 1"
    with pytest.raises(ReportingError):
        service.public_report(participant.release_id)
    newer = complete_revision(service, report, text="Edited later.")
    assert service.preview(ADMIN, newer.revision_id).draft
    assert service.public_report(public.release_id).revision == revision
    approve(service, newer)
    replacement = service.publish(
        ADMIN, revision_id=newer.revision_id, audience="public"
    )
    with pytest.raises(ReportingError):
        service.public_report(public.release_id)
    assert service.participant_report(enrolled[0].access_token).revision == revision
    items, total = service.public_catalog("priorities")
    assert total == 1 and items[0]["release_id"] == replacement.release_id
    service.withdraw(
        ADMIN, release_id=replacement.release_id, reason="Correction needed"
    )
    assert service.public_catalog()[1] == 0
    with pytest.raises(ReportingError):
        service.public_report(replacement.release_id)
    assert service.participant_report(enrolled[1].access_token).revision == revision
    # One private participant projection never contains another participant's alias.
    assert "Private respondent 1" not in str(
        container.packages.participant_access.execute(enrolled[1].access_token).result
    )


def test_document_approval_versioning_export_privacy_and_authorization(study):
    container, session_id, package_id, _ = study
    service = container.reporting
    confidential = service.upload_document(
        ADMIN,
        session_id=session_id,
        title="PRIVATE-TITLE",
        source_reference="PRIVATE-SOURCE",
        classification="confidential",
        filename="secret.txt",
        content=b"PRIVATE-CONTENT",
    )
    shareable = service.upload_document(
        ADMIN,
        session_id=session_id,
        title="Policy brief",
        source_reference="Public source",
        classification="shareable",
        filename="../../brief.txt",
        content=b"Approved evidence",
    )
    assert shareable.filename == "brief.txt"
    report = service.create_report(
        ADMIN, package_run_id=package_id, title="<script>Title</script>"
    )
    for version in (confidential, shareable):
        with pytest.raises(ReportingError, match="approved shareable"):
            complete_revision(service, report, document_ids=(version.version_id,))
    with pytest.raises(ReportingError, match="Confidential"):
        service.approve_document(ADMIN, confidential.version_id)
    service.approve_document(ADMIN, shareable.version_id)
    revision = complete_revision(
        service,
        report,
        document_ids=(shareable.version_id,),
        text="<script>alert(1)</script>",
    )
    service.add_note(ADMIN, report_id=report.report_id, body="PRIVATE-NOTE")
    newer_doc = service.upload_document(
        ADMIN,
        session_id=session_id,
        title="Updated brief",
        source_reference="Updated",
        classification="shareable",
        filename="brief.txt",
        content=b"Updated content",
        document_id=shareable.document_id,
        expected_version=1,
    )
    assert newer_doc.number == 2
    with pytest.raises(ReportingError, match="Reload"):
        service.upload_document(
            ADMIN,
            session_id=session_id,
            title="Conflict",
            source_reference="",
            classification="shareable",
            filename="brief.txt",
            content=b"Conflict",
            document_id=shareable.document_id,
            expected_version=1,
        )
    projection = service.preview(ADMIN, revision.revision_id)
    assert projection.documents[0].content == b"Approved evidence"
    html = report_html(projection)
    assert b"&lt;script&gt;" in html and b"<script>" not in html
    assert b"DRAFT" in html
    with ZipFile(io.BytesIO(report_zip(projection))) as archive:
        output = b"\n".join(archive.read(name) for name in archive.namelist())
        for forbidden in (
            b"PRIVATE-TITLE",
            b"PRIVATE-SOURCE",
            b"PRIVATE-CONTENT",
            b"PRIVATE-NOTE",
            b"Private respondent",
            b"identity-map",
            b"Updated content",
        ):
            assert forbidden not in output
        assert b"Approved evidence" in output
    outsider = Principal("participant", "Participant", frozenset())
    for call in (
        lambda: service.document(outsider, confidential.version_id),
        lambda: service.workspace(outsider, session_id),
        lambda: service.preview(outsider, revision.revision_id),
        lambda: service.publish(
            outsider, revision_id=revision.revision_id, audience="public"
        ),
        lambda: service.approve_document(outsider, shareable.version_id),
    ):
        with pytest.raises(ReportingError, match="Administrator"):
            call()
    with pytest.raises(ReportingError):
        service.public_report(confidential.version_id)
    with pytest.raises(ReportingError):
        service.public_report("not-a-uuid")


def test_stale_package_and_atomic_participant_release(study):
    container, session_id, package_id, enrolled = study
    service = container.reporting
    report = service.create_report(
        ADMIN, package_run_id=package_id, title="Reviewed findings"
    )
    revision = complete_revision(service, report)
    approve(service, revision)
    # Force a failure after the composed private release has been prepared.
    with patch.object(
        service, "_audit", side_effect=RuntimeError("Transaction failure")
    ):
        with pytest.raises(RuntimeError):
            service.publish(
                ADMIN, revision_id=revision.revision_id, audience="participant"
            )
    assert container.packages.list_releases.execute(session_id) == ()
    assert service.workspace(ADMIN, session_id)["releases"] == ()
    release = service.publish(
        ADMIN, revision_id=revision.revision_id, audience="public"
    )
    from poli_insight.infrastructure.database.engine import build_session_factory
    from poli_insight.infrastructure.database.models.participation import ParticipantRow

    with build_session_factory(container.settings)() as db:
        participant = db.get(ParticipantRow, enrolled[0].participant_id)
        participant.access_status = "disabled"
        participant.disabled_at = service.clock()
        participant.updated_at = participant.disabled_at
        participant.disabled_by = ADMIN.subject
        participant.disable_reason = "Excluded for stale-package test"
        db.commit()
    assert service.public_catalog()[1] == 0
    with pytest.raises(ReportingError):
        service.public_report(release.release_id)
    with pytest.raises(ReportingError, match="stale"):
        service.publish(ADMIN, revision_id=revision.revision_id, audience="public")
    assert service.preview(ADMIN, revision.revision_id).revision == revision


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("bad.pdf", b"plain text"),
        ("bad.docx", b"not zip"),
        ("bad.txt", b"\xff"),
        ("bad.md", b"null\x00"),
        ("script.html", b"<script/>"),
        ("empty.txt", b""),
        ("huge.txt", b"a" * (20 * 1024 * 1024 + 1)),
    ],
)
def test_document_validation(filename, content):
    with pytest.raises(ReportingError):
        validate_document(filename, content)


def test_review_rejection_not_assessed_and_cross_session_sources(study):
    container, session_id, package_id, _ = study
    service = container.reporting
    report = service.create_report(ADMIN, package_run_id=package_id, title="Assessment")
    head = service.history(ADMIN, report.report_id)["revisions"][0]
    revision = service.save_revision(
        ADMIN,
        report_id=report.report_id,
        expected_revision_id=head.revision_id,
        sections=dict.fromkeys(NARRATIVE_SECTIONS, None),
        change_summary="Explicitly not assessed",
    )
    service.review(
        ADMIN,
        revision_id=revision.revision_id,
        status="submitted",
        warnings_acknowledged=True,
    )
    with pytest.raises(ReportingError, match="reason"):
        service.review(ADMIN, revision_id=revision.revision_id, status="rejected")
    service.review(
        ADMIN,
        revision_id=revision.revision_id,
        status="rejected",
        reason="Needs context",
    )
    approve(service, revision)
    with pytest.raises(ReportingError, match="transition"):
        service.review(
            ADMIN,
            revision_id=revision.revision_id,
            status="rejected",
            reason="Cannot rewrite approval",
        )
    assert b"Not assessed" in report_html(service.preview(ADMIN, revision.revision_id))
    other_session, _ = _open_questionnaire(
        container,
        slug="other-study",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
    )
    document = service.upload_document(
        ADMIN,
        session_id=other_session,
        title="Other session",
        source_reference="",
        classification="shareable",
        filename="notes.txt",
        content=b"Other session source",
    )
    service.approve_document(ADMIN, document.version_id)
    with pytest.raises(ReportingError, match="from this session"):
        complete_revision(service, report, document_ids=(document.version_id,))


def test_migration_preserves_packages_and_database_prevents_duplicate_active_release(
    study,
):
    import os
    import sqlite3
    from uuid import uuid4

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import IntegrityError

    from poli_insight.infrastructure.database.engine import build_session_factory
    from poli_insight.infrastructure.database.models.reporting import ReportReleaseRow

    container, session_id, package_id, _ = study
    url = container.settings.database_url
    database_path = url.split("///", 1)[1]
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    with sqlite3.connect(database_path) as db:
        before = db.execute(
            "SELECT package_run_id, output_hash FROM result_package_runs"
        ).fetchall()
        audit_before = db.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    with patch.dict(os.environ, {"DATABASE_URL": url}):
        command.downgrade(config, "0013")
        command.upgrade(config, "head")
    with sqlite3.connect(database_path) as db:
        assert (
            db.execute(
                "SELECT package_run_id, output_hash FROM result_package_runs"
            ).fetchall()
            == before
        )
        assert (
            db.execute("SELECT count(*) FROM audit_events").fetchone()[0]
            == audit_before
        )
    service = container.reporting
    report = service.create_report(
        ADMIN, package_run_id=package_id, title="Migrated package report"
    )
    revision = complete_revision(service, report)
    approve(service, revision)
    release = service.publish(
        ADMIN, revision_id=revision.revision_id, audience="public"
    )
    with build_session_factory(container.settings)() as db:
        db.add(
            ReportReleaseRow(
                release_id=str(uuid4()),
                session_id=session_id,
                revision_id=revision.revision_id,
                approval_id=release.approval_id,
                audience="public",
                number=2,
                status="active",
                created_at=service.clock(),
                created_by=ADMIN.subject,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    assert service.public_report(release.release_id).revision == revision


def test_existing_private_release_is_replaced_to_match_shared_package(study):
    from poli_insight.application.use_cases.participant_result_release import (
        ReleaseParticipantResultsCommand,
    )

    container, session_id, package_id, enrolled = study
    package = container.packages.list_runs.execute(session_id)[0]
    other = container.packages.create.execute(
        CreateResultPackageCommand(
            session_id,
            package.source_ranking_run_id,
            package.source_analysis_run_ids,
            (BundleVariant.PUBLIC,),
            ADMIN.subject,
        )
    )
    container.packages.release_participants.execute(
        ReleaseParticipantResultsCommand(
            session_id, other.package_run_id, ADMIN.subject
        )
    )
    service = container.reporting
    report = service.create_report(
        ADMIN, package_run_id=package_id, title="Matching package"
    )
    revision = complete_revision(service, report)
    approve(service, revision)
    service.publish(ADMIN, revision_id=revision.revision_id, audience="participant")
    private = container.packages.participant_access.execute(enrolled[0].access_token)
    shared = service.participant_report(enrolled[0].access_token)
    assert private.package_run_id == shared.package_run_id == package_id
    assert len(container.packages.list_releases.execute(session_id)) == 2


def test_valid_document_containers():
    assert validate_document("readme.md", b"# UTF-8 source")[1] == "text/markdown"
    assert validate_document("report.pdf", b"%PDF-1.7\n%%EOF")[1] == "application/pdf"
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    assert validate_document("report.docx", buffer.getvalue())[0] == "report.docx"


def test_reporting_overviews_and_previews_do_not_load_private_records_or_files(study):
    from sqlalchemy import event

    from poli_insight.application.use_cases.manual_reporting import ManualReporting
    from poli_insight.domain.reporting import DocumentSummary
    from poli_insight.infrastructure.database.engine import build_session_factory
    from poli_insight.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

    container, session_id, package_id, _ = study
    service = container.reporting
    document = service.upload_document(
        ADMIN,
        session_id=session_id,
        title="Evidence",
        source_reference="Source",
        classification="shareable",
        filename="brief.txt",
        content=b"Supporting text",
    )
    service.approve_document(ADMIN, document.version_id)
    report = service.create_report(
        ADMIN, package_run_id=package_id, title="Overview test"
    )
    revision = complete_revision(service, report, document_ids=(document.version_id,))
    factory = build_session_factory(container.settings)
    reader = ManualReporting(lambda: SqlAlchemyUnitOfWork(factory))
    statements = []

    def record_sql(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(factory.kw["bind"], "before_cursor_execute", record_sql)
    options = reader.package_options(ADMIN, session_id)
    assert options[0].package_run_id == package_id
    assert not options[0].artifacts
    assert not any(
        "result_package_artifacts" in sql or "result_package_subjects" in sql
        for sql in statements
    )
    statements.clear()
    workspace = reader.workspace(ADMIN, session_id, include_documents=False)
    assert workspace["reports"] and not workspace["versions"]
    assert not any("supporting_document" in sql for sql in statements)
    statements.clear()
    workspace = reader.workspace(ADMIN, session_id)
    assert isinstance(workspace["versions"][0], DocumentSummary)
    preview = reader.preview(ADMIN, revision.revision_id, include_files=False)
    assert isinstance(preview.documents[0], DocumentSummary)
    assert preview.evidence["05_ranking"]
    assert not any(
        "supporting_document_versions.content," in sql
        or "result_package_subjects" in sql
        for sql in statements
    )
    full = reader.preview(ADMIN, revision.revision_id)
    assert full.documents[0].content == b"Supporting text"
