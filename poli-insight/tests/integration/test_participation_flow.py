from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from poli_insight.application.use_cases.activate_session_configuration import (
    ActivateSessionConfigurationCommand,
)
from poli_insight.application.use_cases.create_session import CreateSessionCommand
from poli_insight.application.use_cases.create_session_configuration import (
    AlgorithmSelectionInput,
    CreateSessionConfigurationCommand,
    StakeholderGroupInput,
)
from poli_insight.application.use_cases.enroll_participant import (
    EnrollmentRejectedError,
    EnrollParticipantCommand,
)
from poli_insight.application.use_cases.import_bundled_scenarios import (
    ImportBundledScenariosCommand,
)
from poli_insight.application.use_cases.import_invitations import (
    ApplyInvitationImportCommand,
    InvitationImportError,
    PreviewInvitationImportCommand,
)
from poli_insight.application.use_cases.manage_invitations import (
    ExpireInvitations,
    ExpireInvitationsCommand,
    IssueInvitationCommand,
    ReplaceInvitationCommand,
    RevokeInvitationCommand,
)
from poli_insight.application.use_cases.open_session import OpenSessionCommand
from poli_insight.application.use_cases.participant_access import (
    ParticipantAccessError,
)
from poli_insight.application.use_cases.replace_participant_access_grant import (
    ReplaceParticipantAccessGrantCommand,
)
from poli_insight.application.use_cases.review_submission import (
    ReviewSubmissionCommand,
    ReviewSubmissionError,
)
from poli_insight.application.use_cases.save_submission_draft import (
    DraftAnswerInput,
    SaveSubmissionDraftCommand,
    SaveSubmissionDraftError,
)
from poli_insight.application.use_cases.submit_response import (
    SubmitResponseCommand,
    SubmitResponseError,
)
from poli_insight.bootstrap import ApplicationContainer, create_container
from poli_insight.config import Settings
from poli_insight.domain.enum import (
    AccessCodeMode,
    ActorType,
    AlgorithmRole,
    Discoverability,
    EnrollmentMode,
    InvitationStatus,
    ResponseFormat,
    ResponseTargetType,
    ScenarioSnapshotStatus,
    StakeholderSelectionMode,
    SubmissionReviewStatus,
    SubmissionStatus,
)
from poli_insight.domain.validation import SubmissionValidation
from poli_insight.infrastructure.auth.tokens import digest_token
from poli_insight.infrastructure.database.engine import build_session_factory
from poli_insight.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

PROJECT_ROOT = Path(__file__).parents[2]


def _container(database_path: Path) -> ApplicationContainer:
    database_url = f"sqlite+pysqlite:///{database_path}"
    with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
        alembic_command.upgrade(
            AlembicConfig(str(PROJECT_ROOT / "alembic.ini")), "head"
        )
    container = create_container(
        Settings(
            database_url=database_url,
            app_timezone="UTC",
            scenario_source_root=PROJECT_ROOT / "scenarios",
            scenario_template_directory="_template",
        )
    )
    result = container.import_bundled_scenarios.execute(
        ImportBundledScenariosCommand(actor_id="participation-admin")
    )
    assert result.imported_count == 2
    return container


def _open_questionnaire(
    container: ApplicationContainer,
    *,
    slug: str,
    response_format: ResponseFormat,
    consent_required: bool,
    access_code: str | None = None,
    enrollment_mode: EnrollmentMode = EnrollmentMode.OPEN,
    stakeholder_selection_mode: StakeholderSelectionMode = (
        StakeholderSelectionMode.SELF_SELECT
    ),
) -> tuple[str, str]:
    snapshot = container.page_queries.list_scenario_snapshots(
        status=ScenarioSnapshotStatus.READY,
        page_size=10,
    ).items[0]
    scenario = container.page_queries.get_scenario_snapshot_detail(
        snapshot.scenario_snapshot_id
    )
    assert scenario is not None
    expected_scale_type = (
        "pairwise" if response_format == ResponseFormat.PAIRWISE else "direct_rating"
    )
    scale = next(
        item for item in scenario.scales if expected_scale_type in item.scale_type
    )
    weighting = container.page_queries.list_active_algorithm_implementations(
        role=AlgorithmRole.WEIGHTING
    )[0]
    ranking = container.page_queries.list_active_algorithm_implementations(
        role=AlgorithmRole.RANKING
    )[0]
    created = container.sessions.create.execute(
        CreateSessionCommand(
            scenario_snapshot_id=snapshot.scenario_snapshot_id,
            public_slug=slug,
            title=f"{response_format.value} participation",
            discoverability=Discoverability.LISTED,
            enrollment_mode=enrollment_mode,
            access_code_mode=(
                AccessCodeMode.SHARED_SESSION_CODE
                if access_code is not None
                else AccessCodeMode.NONE
            ),
            shared_access_code=access_code,
            stakeholder_selection_mode=stakeholder_selection_mode,
            actor_id="participation-admin",
        )
    )
    configured = container.sessions.create_configuration.execute(
        CreateSessionConfigurationCommand(
            session_id=created.session_id,
            actor_id="participation-admin",
            response_format=response_format,
            response_target_type=ResponseTargetType.CRITERION,
            scale_id=scale.scale_id,
            stakeholder_groups=(
                StakeholderGroupInput(
                    group_key="community",
                    name="Community members",
                    description="People participating from the community.",
                    allocation_units=10_000,
                    required=True,
                ),
            ),
            algorithms=(
                AlgorithmSelectionInput(
                    weighting.algorithm_implementation_id,
                    AlgorithmRole.WEIGHTING,
                ),
                AlgorithmSelectionInput(
                    ranking.algorithm_implementation_id,
                    AlgorithmRole.RANKING,
                ),
            ),
            consent_required=consent_required,
            consent_version="thesis-v1",
            consent_title="Thesis research consent",
            consent_statement="I voluntarily consent to this research questionnaire.",
        )
    )
    container.sessions.activate_configuration.execute(
        ActivateSessionConfigurationCommand(
            session_id=created.session_id,
            configuration_version_id=configured.configuration_version_id,
            actor_id="participation-admin",
        )
    )
    container.sessions.open.execute(
        OpenSessionCommand(
            session_id=created.session_id,
            actor_id="participation-admin",
        )
    )
    public = container.page_queries.get_public_participation_session(slug)
    assert public is not None
    return created.session_id, public.groups[0].group_id


def _answer(question_id: str, scale_value_id: str) -> DraftAnswerInput:
    return DraftAnswerInput(
        question_definition_id=question_id,
        raw_value_json={"selected_scale_value_id": scale_value_id},
    )


def test_admin_replacement_invalidates_old_link_and_preserves_work(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "replace-participant-access.sqlite"
    container = _container(database_path)
    session_id, group_id = _open_questionnaire(
        container,
        slug="replace-access-study",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
    )
    enrollment = container.participation.enroll.execute(
        EnrollParticipantCommand(
            session_id=session_id,
            selected_group_id=group_id,
            alias="rotation-participant",
        )
    )
    workspace = container.page_queries.get_participation_workspace(
        enrollment.participant_id
    )
    assert workspace is not None
    saved = container.submissions.save_draft.execute(
        SaveSubmissionDraftCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
            answers=(
                _answer(
                    workspace.questions[0].question_definition_id,
                    workspace.scale_options[0].scale_value_id,
                ),
            ),
        )
    )
    before = container.page_queries.get_session_participant_detail(
        session_id, enrollment.participant_id
    )
    assert before is not None and before.draft is not None
    metrics = container.page_queries.get_session_participant_metrics(session_id)
    assert metrics.total_enrolled == 1
    assert metrics.never_started == 0
    assert metrics.active_drafts == 1
    assert metrics.submitted_or_completed == 0
    participant_rows = container.page_queries.list_session_participants(session_id)
    assert participant_rows.total == 1
    assert participant_rows.items[0].answer_progress.startswith("1 / ")
    assert participant_rows.items[0].current_attempt == 1
    assert participant_rows.items[0].resume_access_status == "active"

    replaced = container.operations.replace_participant_access.execute(
        ReplaceParticipantAccessGrantCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id="operations-admin",
            actor_roles=frozenset({"admin"}),
        )
    )

    with pytest.raises(ParticipantAccessError):
        container.participation.resume.execute(enrollment.access_token)
    resumed = container.participation.resume.execute(replaced.access_token)
    assert resumed.participant_id == enrollment.participant_id
    after = container.page_queries.get_session_participant_detail(
        session_id, enrollment.participant_id
    )
    assert after is not None and after.draft is not None
    assert after.configuration_version == before.configuration_version
    assert after.summary.group_name == before.summary.group_name
    assert after.draft.submission_id == saved.submission_id
    assert after.draft.answered_count == before.draft.answered_count
    assert after.access is not None
    assert after.access.access_grant_id == replaced.access_grant_id
    assert after.access.status == "active"

    with sqlite3.connect(database_path) as connection:
        grants = connection.execute(
            """
            SELECT access_grant_id, token_digest, revoked_at,
                   replaced_by_grant_id
            FROM participant_access_grants
            WHERE participant_id = ? ORDER BY issued_at
            """,
            (enrollment.participant_id,),
        ).fetchall()
        event = connection.execute(
            """
            SELECT before_json, after_json, source_metadata_json
            FROM audit_events
            WHERE entity_type = 'participant_access_grant'
            ORDER BY occurred_at DESC LIMIT 1
            """
        ).fetchone()
    assert len(grants) == 2
    assert grants[0][2] is not None
    assert grants[0][3] == replaced.access_grant_id
    assert grants[1][1] == digest_token(replaced.access_token)
    assert all(enrollment.access_token not in str(value) for row in grants for value in row)
    assert event is not None
    assert replaced.access_token not in "".join(str(value) for value in event)
    assert digest_token(replaced.access_token) not in "".join(
        str(value) for value in event
    )


def test_direct_catalog_consent_draft_resume_review_and_submit(tmp_path: Path) -> None:
    database_path = tmp_path / "direct-participation.sqlite"
    container = _container(database_path)
    session_id, group_id = _open_questionnaire(
        container,
        slug="direct-study",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=True,
    )
    assert container.page_queries.list_open_public_sessions().total == 1
    enrollment = container.participation.enroll.execute(
        EnrollParticipantCommand(
            session_id=session_id,
            selected_group_id=group_id,
            alias="participant-one",
        )
    )
    workspace = container.page_queries.get_participation_workspace(
        enrollment.participant_id
    )
    assert workspace is not None
    assert workspace.consent_required
    assert not workspace.consent_completed
    first = _answer(
        workspace.questions[0].question_definition_id,
        workspace.scale_options[0].scale_value_id,
    )
    with pytest.raises(SaveSubmissionDraftError, match="Consent"):
        container.submissions.save_draft.execute(
            SaveSubmissionDraftCommand(
                session_id=session_id,
                participant_id=enrollment.participant_id,
                actor_id=enrollment.participant_id,
                access_token=enrollment.access_token,
                answers=(first,),
            )
        )
    consent = container.participation.capture_consent.execute(
        access_token=enrollment.access_token,
        accepted=True,
    )
    assert consent.consent_version == "thesis-v1"
    with pytest.raises(SaveSubmissionDraftError, match="outside the configured"):
        container.submissions.save_draft.execute(
            SaveSubmissionDraftCommand(
                session_id=session_id,
                participant_id=enrollment.participant_id,
                actor_id=enrollment.participant_id,
                access_token=enrollment.access_token,
                answers=(
                    _answer(
                        workspace.questions[0].question_definition_id,
                        "00000000-0000-4000-8000-000000000000",
                    ),
                ),
            )
        )
    saved = container.submissions.save_draft.execute(
        SaveSubmissionDraftCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
            answers=(first,),
        )
    )
    assert saved.created
    resumed = container.participation.resume.execute(enrollment.access_token)
    assert resumed.participant_id == enrollment.participant_id
    with pytest.raises(ParticipantAccessError):
        container.participation.resume.execute("not-a-valid-resume-token")
    workspace = container.page_queries.get_participation_workspace(
        enrollment.participant_id
    )
    assert workspace is not None
    assert len(workspace.answers) == 1
    all_answers = tuple(
        _answer(
            question.question_definition_id, workspace.scale_options[-1].scale_value_id
        )
        for question in workspace.questions
    )
    saved = container.submissions.save_draft.execute(
        SaveSubmissionDraftCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
            answers=all_answers,
        )
    )
    submitted = container.submissions.submit.execute(
        SubmitResponseCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            submission_id=saved.submission_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
        )
    )
    assert submitted.status == SubmissionStatus.SUBMITTED
    completed = container.page_queries.get_participation_workspace(
        enrollment.participant_id
    )
    assert completed is not None
    assert completed.submission_status == SubmissionStatus.SUBMITTED
    with pytest.raises(SaveSubmissionDraftError):
        container.submissions.save_draft.execute(
            SaveSubmissionDraftCommand(
                session_id=session_id,
                participant_id=enrollment.participant_id,
                actor_id=enrollment.participant_id,
                access_token=enrollment.access_token,
                answers=(first,),
            )
        )
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM participant_consents"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM submissions WHERE status='submitted'"
        ).fetchone() == (1,)


def test_pairwise_access_code_missing_duplicate_and_complete(tmp_path: Path) -> None:
    database_path = tmp_path / "pairwise-participation.sqlite"
    container = _container(database_path)
    session_id, group_id = _open_questionnaire(
        container,
        slug="pairwise-study",
        response_format=ResponseFormat.PAIRWISE,
        consent_required=False,
        access_code="research-code-2026",
    )
    with pytest.raises(EnrollmentRejectedError):
        container.participation.enroll.execute(
            EnrollParticipantCommand(
                session_id=session_id,
                selected_group_id=group_id,
                access_code="incorrect-code",
            )
        )
    enrollment = container.participation.enroll.execute(
        EnrollParticipantCommand(
            session_id=session_id,
            selected_group_id=group_id,
            access_code="research-code-2026",
        )
    )
    workspace = container.page_queries.get_participation_workspace(
        enrollment.participant_id
    )
    assert workspace is not None
    assert workspace.response_format == ResponseFormat.PAIRWISE
    pairs = {(item.left_name, item.right_name) for item in workspace.questions}
    assert len(pairs) == len(workspace.questions)
    criteria = {name for pair in pairs for name in pair}
    assert len(workspace.questions) == len(criteria) * (len(criteria) - 1) // 2
    with pytest.raises(SaveSubmissionDraftError, match="same question"):
        SaveSubmissionDraftCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
            answers=(
                _answer(
                    workspace.questions[0].question_definition_id,
                    workspace.scale_options[0].scale_value_id,
                ),
            )
            * 2,
        )
    first_save = container.submissions.save_draft.execute(
        SaveSubmissionDraftCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
            answers=(
                _answer(
                    workspace.questions[0].question_definition_id,
                    workspace.scale_options[0].scale_value_id,
                ),
            ),
        )
    )
    with pytest.raises(SubmitResponseError, match="missing required questions"):
        container.submissions.submit.execute(
            SubmitResponseCommand(
                session_id=session_id,
                participant_id=enrollment.participant_id,
                submission_id=first_save.submission_id,
                actor_id=enrollment.participant_id,
                access_token=enrollment.access_token,
            )
        )
    final_save = container.submissions.save_draft.execute(
        SaveSubmissionDraftCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
            answers=tuple(
                _answer(
                    question.question_definition_id,
                    workspace.scale_options[0].scale_value_id,
                )
                for question in workspace.questions
            ),
        )
    )
    result = container.submissions.submit.execute(
        SubmitResponseCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            submission_id=final_save.submission_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
        )
    )
    assert result.answer_count == len(workspace.questions)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT use_count FROM session_access_codes"
        ).fetchone() == (1,)
        outcomes = connection.execute(
            "SELECT outcome FROM participant_access_attempts ORDER BY attempted_at"
        ).fetchall()
    assert outcomes == [("rejected",), ("accepted",)]


def test_invitation_only_enrollment_assigns_group_and_redeems_once(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invitation-participation.sqlite"
    container = _container(database_path)
    session_id, group_id = _open_questionnaire(
        container,
        slug="invitation-study",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
        enrollment_mode=EnrollmentMode.INVITATION_ONLY,
        stakeholder_selection_mode=StakeholderSelectionMode.INVITATION_ASSIGNED,
    )
    assert container.page_queries.list_open_public_sessions().total == 0
    direct = container.page_queries.get_public_participation_session("invitation-study")
    assert direct is not None
    with pytest.raises(EnrollmentRejectedError):
        container.participation.enroll.execute(
            EnrollParticipantCommand(session_id=session_id)
        )

    detail = container.page_queries.get_admin_session_detail(session_id)
    assert detail is not None
    assert detail.configuration is not None
    invitation_id = str(uuid4())
    invitation_token = (
        "invitation-token-with-at-least-256-bits-of-randomness-placeholder"
    )
    created_at = datetime.now(tz=UTC)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO session_invitations (
                invitation_id, session_id, configuration_version_id,
                assigned_group_id, token_digest, status, expires_at,
                max_redemptions, sent_at, send_count, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, 'sent', ?, 1, ?, 1, ?, ?)
            """,
            (
                invitation_id,
                session_id,
                detail.configuration.configuration_version_id,
                group_id,
                digest_token(invitation_token),
                (created_at + timedelta(days=2)).isoformat(sep=" "),
                created_at.isoformat(sep=" "),
                created_at.isoformat(sep=" "),
                "participation-admin",
            ),
        )
    enrolled = container.participation.enroll.execute(
        EnrollParticipantCommand(
            session_id=session_id,
            invitation_token=invitation_token,
        )
    )
    assert enrolled.session_stakeholder_group_id == group_id
    with pytest.raises(EnrollmentRejectedError):
        container.participation.enroll.execute(
            EnrollParticipantCommand(
                session_id=session_id,
                invitation_token=invitation_token,
            )
        )
    with sqlite3.connect(database_path) as connection:
        invitation_state = connection.execute(
            "SELECT status, redeemed_participant_id FROM session_invitations"
        ).fetchone()
    assert invitation_state == ("redeemed", enrolled.participant_id)


def test_operational_invitation_issue_replace_revoke_and_query(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operational-invitations.sqlite"
    container = _container(database_path)
    session_id, group_id = _open_questionnaire(
        container,
        slug="managed-invitations",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
        enrollment_mode=EnrollmentMode.INVITATION_ONLY,
        stakeholder_selection_mode=StakeholderSelectionMode.INVITATION_ASSIGNED,
    )
    expiration = datetime.now(tz=UTC) + timedelta(days=2)
    issued = container.operations.invitations.issue.execute(
        IssueInvitationCommand(
            session_id=session_id,
            assigned_group_id=group_id,
            expires_at=expiration,
            actor_id="operations-admin",
        )
    )
    first_page = container.page_queries.list_session_invitations(session_id)
    assert first_page.total == 1
    assert first_page.items[0].token_hint == issued.token_hint

    replacement = container.operations.invitations.replace.execute(
        ReplaceInvitationCommand(
            invitation_id=issued.invitation_id,
            actor_id="operations-admin",
            reason="Credential delivery retry",
        )
    )
    assert replacement.token != issued.token
    container.operations.invitations.revoke.execute(
        RevokeInvitationCommand(
            invitation_id=replacement.invitation_id,
            actor_id="operations-admin",
            reason="Participant no longer eligible",
        )
    )
    page = container.page_queries.list_session_invitations(session_id)
    assert {item.status.value for item in page.items} == {"revoked"}
    assert page.total == 2

    due_at = datetime.now(tz=UTC) + timedelta(hours=1)
    due = container.operations.invitations.issue.execute(
        IssueInvitationCommand(
            session_id=session_id,
            assigned_group_id=group_id,
            expires_at=due_at,
            actor_id="operations-admin",
        )
    )
    factory = build_session_factory(container.settings)
    expired_count = ExpireInvitations(
        lambda: SqlAlchemyUnitOfWork(factory),
        clock=lambda: due_at + timedelta(seconds=1),
    ).execute(
        ExpireInvitationsCommand(
            session_id=session_id,
            actor_id="operations-admin",
        )
    )
    assert expired_count == 1
    expired = container.page_queries.list_session_invitations(
        session_id,
        status=InvitationStatus.EXPIRED,
    )
    assert expired.items[0].invitation_id == due.invitation_id


def test_invitation_import_preview_apply_and_duplicate_detection(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operational-import.sqlite"
    container = _container(database_path)
    session_id, _group_id = _open_questionnaire(
        container,
        slug="invitation-import",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
        enrollment_mode=EnrollmentMode.INVITATION_ONLY,
        stakeholder_selection_mode=StakeholderSelectionMode.INVITATION_ASSIGNED,
    )
    detail = container.page_queries.get_admin_session_detail(session_id)
    assert detail is not None
    group_name = detail.group_progress[0].group_name
    expiration = (datetime.now(tz=UTC) + timedelta(days=3)).isoformat()
    content = (
        "reference,group,expires_at\n"
        f"opaque-001,{group_name},{expiration}\n"
        f"opaque-002,{group_name},{expiration}\n"
    ).encode()
    preview = container.operations.invitations.preview_import.execute(
        PreviewInvitationImportCommand(
            session_id=session_id,
            filename="invitations.csv",
            content=content,
        )
    )
    assert preview.expected_inserts == 2
    assert preview.expected_updates == 0
    applied = container.operations.invitations.apply_import.execute(
        ApplyInvitationImportCommand(
            session_id=session_id,
            filename="invitations.csv",
            content=content,
            expected_file_hash=preview.file_hash,
            actor_id="operations-admin",
        )
    )
    assert applied.imported_count == 2
    assert len(applied.invitations) == 2
    duplicate_preview = container.operations.invitations.preview_import.execute(
        PreviewInvitationImportCommand(
            session_id=session_id,
            filename="invitations.csv",
            content=content,
        )
    )
    assert duplicate_preview.duplicate_count == 2
    repeated = container.operations.invitations.apply_import.execute(
        ApplyInvitationImportCommand(
            session_id=session_id,
            filename="invitations.csv",
            content=content,
            expected_file_hash=preview.file_hash,
            actor_id="operations-admin",
        )
    )
    assert repeated.already_applied
    assert container.page_queries.list_session_invitations(session_id).total == 2

    duplicate_content = (
        "reference,group,expires_at\n"
        f"opaque-003,{group_name},{expiration}\n"
        f"opaque-003,{group_name},{expiration}\n"
    ).encode()
    duplicate_file = container.operations.invitations.preview_import.execute(
        PreviewInvitationImportCommand(
            session_id=session_id,
            filename="duplicate.csv",
            content=duplicate_content,
        )
    )
    assert duplicate_file.duplicate_count == 2
    assert duplicate_file.expected_inserts == 0
    with pytest.raises(InvitationImportError, match="columns must be exactly"):
        container.operations.invitations.preview_import.execute(
            PreviewInvitationImportCommand(
                session_id=session_id,
                filename="invalid.csv",
                content=b"email,group\nprivate@example.test,group\n",
            )
        )


def test_participant_submission_queries_and_review_transition(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operational-review.sqlite"
    container = _container(database_path)
    session_id, group_id = _open_questionnaire(
        container,
        slug="operational-review",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
    )
    enrollment = container.participation.enroll.execute(
        EnrollParticipantCommand(
            session_id=session_id,
            selected_group_id=group_id,
            alias="Reviewer sample",
        )
    )
    workspace = container.page_queries.get_participation_workspace(
        enrollment.participant_id
    )
    assert workspace is not None
    draft = container.submissions.save_draft.execute(
        SaveSubmissionDraftCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
            answers=tuple(
                _answer(
                    question.question_definition_id,
                    workspace.scale_options[0].scale_value_id,
                )
                for question in workspace.questions
            ),
        )
    )
    submitted = container.submissions.submit.execute(
        SubmitResponseCommand(
            session_id=session_id,
            participant_id=enrollment.participant_id,
            submission_id=draft.submission_id,
            actor_id=enrollment.participant_id,
            access_token=enrollment.access_token,
        )
    )
    participants = container.page_queries.list_session_participants(
        session_id,
        search="reviewer",
    )
    assert participants.total == 1
    participant_detail = container.page_queries.get_session_participant_detail(
        session_id,
        enrollment.participant_id,
    )
    assert participant_detail is not None
    assert participant_detail.submission_count == 1
    submissions = container.page_queries.list_session_submissions(
        session_id,
        status=SubmissionStatus.SUBMITTED,
    )
    assert submissions.total == 1
    queue = container.page_queries.list_validation_queue(
        session_id,
        review_status=SubmissionReviewStatus.PENDING,
    )
    assert queue.total == 1
    pending_detail = container.page_queries.get_session_submission_detail(
        session_id,
        submitted.submission_id,
    )
    assert pending_detail is not None
    assert pending_detail.validation_id is None
    assert pending_detail.review_status == SubmissionReviewStatus.PENDING

    with pytest.raises(ReviewSubmissionError, match="valid completed validation"):
        container.operations.review_submission.execute(
            ReviewSubmissionCommand(
                session_id=session_id,
                submission_id=submitted.submission_id,
                status=SubmissionReviewStatus.ACCEPTED,
                actor_id="operations-admin",
            )
        )

    weighting = container.page_queries.list_active_algorithm_implementations(
        role=AlgorithmRole.WEIGHTING
    )[0]
    factory = build_session_factory(container.settings)
    validation_id = str(uuid4())
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        submission = unit_of_work.submissions.get(submitted.submission_id)
        configuration = unit_of_work.session.get_active_configuration(session_id)
        assert submission is not None
        assert configuration is not None
        started_at = datetime.now(tz=UTC)
        validation = (
            SubmissionValidation.for_submission(
                validation_id=validation_id,
                submission=submission,
                configuration=configuration,
                validator_implementation_id=weighting.algorithm_implementation_id,
                validator_version="test-validator-1",
                parameter_json={},
            )
            .start(at=started_at)
            .complete(
                completion_ratio=Decimal(1),
                actor_type=ActorType.SYSTEM,
                actor_id="test-validator",
                at=started_at + timedelta(seconds=1),
            )
        )
        unit_of_work.validations.add(validation)
        unit_of_work.commit()

    decision = container.operations.review_submission.execute(
        ReviewSubmissionCommand(
            session_id=session_id,
            submission_id=submitted.submission_id,
            status=SubmissionReviewStatus.ACCEPTED,
            actor_id="operations-admin",
            validation_id=validation_id,
        )
    )
    assert decision.status == SubmissionReviewStatus.ACCEPTED
    submission_detail = container.page_queries.get_session_submission_detail(
        session_id,
        submitted.submission_id,
    )
    assert submission_detail is not None
    assert submission_detail.review_status == SubmissionReviewStatus.ACCEPTED
    accepted_queue = container.page_queries.list_validation_queue(
        session_id,
        review_status=SubmissionReviewStatus.ACCEPTED,
    )
    assert accepted_queue.total == 1
    with pytest.raises(ReviewSubmissionError, match="final"):
        container.operations.review_submission.execute(
            ReviewSubmissionCommand(
                session_id=session_id,
                submission_id=submitted.submission_id,
                status=SubmissionReviewStatus.REJECTED,
                actor_id="operations-admin",
                reviewer_notes="Late rejection",
            )
        )
