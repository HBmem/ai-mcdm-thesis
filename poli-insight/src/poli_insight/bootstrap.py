from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.queries.page_queries import PageQueries
from poli_insight.application.use_cases.activate_session_configuration import (
    ActivateSessionConfiguration,
)
from poli_insight.application.use_cases.add_session_configuration import (
    AddSessionConfiguration,
)
from poli_insight.application.use_cases.close_session import CloseSession
from poli_insight.application.use_cases.create_ranking import CreateRanking
from poli_insight.application.use_cases.create_session import CreateSession
from poli_insight.application.use_cases.create_session_configuration import (
    CreateSessionConfiguration,
)
from poli_insight.application.use_cases.enroll_participant import (
    EnrollmentUnitOfWork,
    EnrollParticipant,
)
from poli_insight.application.use_cases.finalize_validation_bundle import (
    FinalizeValidationBundle,
)
from poli_insight.application.use_cases.import_bundled_scenarios import (
    ImportBundledScenarios,
)
from poli_insight.application.use_cases.import_invitations import (
    ApplyInvitationImport,
    PreviewInvitationImport,
)
from poli_insight.application.use_cases.import_scenario import ImportScenario
from poli_insight.application.use_cases.list_ranking_runs import ListRankingRuns
from poli_insight.application.use_cases.list_validation_bundles import (
    ListValidationBundles,
)
from poli_insight.application.use_cases.manage_invitations import (
    ExpireInvitations,
    IssueInvitation,
    ReplaceInvitation,
    RevokeInvitation,
)
from poli_insight.application.use_cases.open_session import OpenSession
from poli_insight.application.use_cases.participant_access import (
    CaptureParticipantConsent,
    ResumeParticipant,
)
from poli_insight.application.use_cases.participant_submission_import import (
    ApplyParticipantSubmissionImport,
    GenerateImportedResumeLinks,
    GenerateParticipantImportTemplate,
    GetParticipantImportSession,
    PreviewParticipantSubmissionImport,
    RedactExpiredImportedIdentity,
)
from poli_insight.application.use_cases.replace_participant_access_grant import (
    ReplaceParticipantAccessGrant,
)
from poli_insight.application.use_cases.review_submission import ReviewSubmission
from poli_insight.application.use_cases.save_submission_draft import (
    SaveSubmissionDraft,
)
from poli_insight.application.use_cases.submit_response import SubmitResponse
from poli_insight.application.use_cases.transition_session import TransitionSession
from poli_insight.application.use_cases.validate_current_submissions import (
    ValidateCurrentSubmissions,
)
from poli_insight.application.use_cases.validate_submission import ValidateSubmission
from poli_insight.application.validation.preparation import CrispSubmissionInputPreparer
from poli_insight.application.validation.service import SubmissionValidationRegistry
from poli_insight.config import Settings, resolve_scenario_paths
from poli_insight.infrastructure.database.engine import build_session_factory
from poli_insight.infrastructure.database.queries.page_queries import (
    SqlAlchemyPageQueries,
)
from poli_insight.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from poli_insight.infrastructure.ranking.pydecision_topsis import (
    PyDecisionTopsisRunner,
    StaticRankingRunnerRegistry,
)
from poli_insight.infrastructure.scenarios.bundled_source import (
    FilesystemBundledScenarioSource,
)
from poli_insight.infrastructure.scenarios.subprocess_function_runner import (
    BundledScenarioSubprocessRunner,
)
from poli_insight.infrastructure.security.identity_protection import (
    AesGcmIdentityProtector,
)
from poli_insight.infrastructure.weighting.pydecision_ahp import (
    PyDecisionAhpRunner,
    StaticWeightingRunnerRegistry,
)


@dataclass(frozen=True, slots=True)
class SessionUseCases:
    create: CreateSession
    add_configuration: AddSessionConfiguration
    create_configuration: CreateSessionConfiguration
    activate_configuration: ActivateSessionConfiguration
    open: OpenSession
    close: CloseSession
    transition: TransitionSession


@dataclass(frozen=True, slots=True)
class SubmissionUseCases:
    save_draft: SaveSubmissionDraft
    submit: SubmitResponse


@dataclass(frozen=True, slots=True)
class ValidationUseCases:
    validate_submission: ValidateSubmission
    validate_current: ValidateCurrentSubmissions
    finalize_bundle: FinalizeValidationBundle
    list_bundles: ListValidationBundles


@dataclass(frozen=True, slots=True)
class RankingUseCases:
    create: CreateRanking
    list_runs: ListRankingRuns


@dataclass(frozen=True, slots=True)
class ParticipationUseCases:
    enroll: EnrollParticipant
    resume: ResumeParticipant
    capture_consent: CaptureParticipantConsent


@dataclass(frozen=True, slots=True)
class InvitationUseCases:
    issue: IssueInvitation
    replace: ReplaceInvitation
    revoke: RevokeInvitation
    expire: ExpireInvitations
    preview_import: PreviewInvitationImport
    apply_import: ApplyInvitationImport


@dataclass(frozen=True, slots=True)
class OperationalUseCases:
    invitations: InvitationUseCases
    review_submission: ReviewSubmission
    replace_participant_access: ReplaceParticipantAccessGrant


@dataclass(frozen=True, slots=True)
class ParticipantImportUseCases:
    get_session: GetParticipantImportSession
    generate_template: GenerateParticipantImportTemplate
    preview: PreviewParticipantSubmissionImport
    apply: ApplyParticipantSubmissionImport
    redact_expired_identity: RedactExpiredImportedIdentity
    generate_resume_links: GenerateImportedResumeLinks


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    settings: Settings
    page_queries: PageQueries
    import_scenario: ImportScenario
    import_bundled_scenarios: ImportBundledScenarios
    sessions: SessionUseCases
    submissions: SubmissionUseCases
    validation: ValidationUseCases
    ranking: RankingUseCases
    participation: ParticipationUseCases
    operations: OperationalUseCases
    participant_imports: ParticipantImportUseCases


def create_container(
    settings: Settings | None = None,
) -> ApplicationContainer:
    resolved_settings = settings or Settings.from_environment()
    scenario_paths = resolve_scenario_paths(resolved_settings)
    session_factory = build_session_factory(resolved_settings)

    def unit_of_work_factory() -> UnitOfWork:
        return cast(UnitOfWork, SqlAlchemyUnitOfWork(session_factory))

    def enrollment_unit_of_work_factory() -> EnrollmentUnitOfWork:
        return cast(EnrollmentUnitOfWork, SqlAlchemyUnitOfWork(session_factory))

    upload_importer = ImportScenario(unit_of_work_factory)
    bundled_source = FilesystemBundledScenarioSource(
        scenario_paths.source_root,
        scenario_paths.template_directory,
    )
    bundled_importer = ImportScenario(
        unit_of_work_factory,
        approved_function_runner=BundledScenarioSubprocessRunner(
            scenario_paths.source_root,
            scenario_paths.template_directory,
        ),
    )
    identity_protector = AesGcmIdentityProtector(
        hmac_secret=resolved_settings.participant_import_hmac_secret,
        encryption_secret=resolved_settings.participant_identity_encryption_key,
    )
    ahp_runner = PyDecisionAhpRunner()
    weighting_registry = StaticWeightingRunnerRegistry(ahp_runner)
    ranking_registry = StaticRankingRunnerRegistry(PyDecisionTopsisRunner())
    submission_validator = ValidateSubmission(
        unit_of_work_factory,
        SubmissionValidationRegistry(
            CrispSubmissionInputPreparer(),
            weighting_registry,
        ),
    )

    return ApplicationContainer(
        settings=resolved_settings,
        page_queries=SqlAlchemyPageQueries(
            session_factory,
            resolved_settings.app_timezone,
        ),
        import_scenario=upload_importer,
        import_bundled_scenarios=ImportBundledScenarios(
            bundled_source,
            bundled_importer,
        ),
        sessions=SessionUseCases(
            create=CreateSession(unit_of_work_factory),
            add_configuration=AddSessionConfiguration(
                unit_of_work_factory
            ),
            create_configuration=CreateSessionConfiguration(
                unit_of_work_factory
            ),
            activate_configuration=ActivateSessionConfiguration(
                unit_of_work_factory
            ),
            open=OpenSession(unit_of_work_factory),
            close=CloseSession(unit_of_work_factory),
            transition=TransitionSession(unit_of_work_factory),
        ),
        submissions=SubmissionUseCases(
            save_draft=SaveSubmissionDraft(unit_of_work_factory),
            submit=SubmitResponse(unit_of_work_factory),
        ),
        validation=ValidationUseCases(
            validate_submission=submission_validator,
            validate_current=ValidateCurrentSubmissions(
                unit_of_work_factory,
                submission_validator,
            ),
            finalize_bundle=FinalizeValidationBundle(
                unit_of_work_factory,
                weighting_registry,
            ),
            list_bundles=ListValidationBundles(unit_of_work_factory),
        ),
        ranking=RankingUseCases(
            create=CreateRanking(unit_of_work_factory, ranking_registry),
            list_runs=ListRankingRuns(unit_of_work_factory),
        ),
        participation=ParticipationUseCases(
            enroll=EnrollParticipant(enrollment_unit_of_work_factory),
            resume=ResumeParticipant(unit_of_work_factory),
            capture_consent=CaptureParticipantConsent(unit_of_work_factory),
        ),
        operations=OperationalUseCases(
            invitations=InvitationUseCases(
                issue=IssueInvitation(unit_of_work_factory),
                replace=ReplaceInvitation(unit_of_work_factory),
                revoke=RevokeInvitation(unit_of_work_factory),
                expire=ExpireInvitations(unit_of_work_factory),
                preview_import=PreviewInvitationImport(unit_of_work_factory),
                apply_import=ApplyInvitationImport(unit_of_work_factory),
            ),
            review_submission=ReviewSubmission(unit_of_work_factory),
            replace_participant_access=ReplaceParticipantAccessGrant(
                unit_of_work_factory
            ),
        ),
        participant_imports=ParticipantImportUseCases(
            get_session=GetParticipantImportSession(unit_of_work_factory),
            generate_template=GenerateParticipantImportTemplate(
                unit_of_work_factory
            ),
            preview=PreviewParticipantSubmissionImport(
                unit_of_work_factory,
                identity_protector,
                max_bytes=resolved_settings.participant_import_max_bytes,
                max_rows=resolved_settings.participant_import_max_rows,
            ),
            apply=ApplyParticipantSubmissionImport(
                unit_of_work_factory,
                identity_protector,
                max_bytes=resolved_settings.participant_import_max_bytes,
                max_rows=resolved_settings.participant_import_max_rows,
                identity_retention_days=(
                    resolved_settings.imported_identity_retention_days
                ),
            ),
            redact_expired_identity=RedactExpiredImportedIdentity(
                unit_of_work_factory
            ),
            generate_resume_links=GenerateImportedResumeLinks(
                unit_of_work_factory
            ),
        ),
    )
