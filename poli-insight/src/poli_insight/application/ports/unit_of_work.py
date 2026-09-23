from __future__ import annotations

from typing import Protocol, Self

from poli_insight.application.ports.algorithm_repository import (
    AlgorithmRepository,
)
from poli_insight.application.ports.analysis_repository import AnalysisRunRepository
from poli_insight.application.ports.audit_repository import AuditEventRepository
from poli_insight.application.ports.operations_repository import (
    InvitationImportRepository,
    ParticipantSubmissionImportRepository,
    SubmissionReviewRepository,
)
from poli_insight.application.ports.participant_repository import (
    ParticipantAccessGrantRepository,
    ParticipantIdentityRepository,
    ParticipantRepository,
    SessionInvitationRepository,
)
from poli_insight.application.ports.participation_access import (
    AccessAttemptRepository,
    EnrollmentAccessCodeRepository,
    ParticipantConsentRepository,
)
from poli_insight.application.ports.processing_repository import ProcessingRunRepository
from poli_insight.application.ports.ranking_repository import RankingRunRepository
from poli_insight.application.ports.reporting_repository import ReportingRepository
from poli_insight.application.ports.result_package_repository import (
    ParticipantResultReleaseRepository,
    ResultPackageRepository,
)
from poli_insight.application.ports.scenario_repository import ScenarioRepository
from poli_insight.application.ports.session_repository import SessionRepository
from poli_insight.application.ports.submission_repository import (
    SubmissionRepository,
)
from poli_insight.application.ports.validation_repository import (
    ValidationRepository,
)


class UnitOfWork(Protocol):
    reporting: ReportingRepository
    analysis_runs: AnalysisRunRepository
    algorithms: AlgorithmRepository
    audit_events: AuditEventRepository
    scenarios: ScenarioRepository
    session: SessionRepository
    participants: ParticipantRepository
    invitations: SessionInvitationRepository
    access_grants: ParticipantAccessGrantRepository
    access_codes: EnrollmentAccessCodeRepository
    access_attempts: AccessAttemptRepository
    consents: ParticipantConsentRepository
    submissions: SubmissionRepository
    validations: ValidationRepository
    submission_reviews: SubmissionReviewRepository
    invitation_imports: InvitationImportRepository
    participant_imports: ParticipantSubmissionImportRepository
    participant_identities: ParticipantIdentityRepository
    processing_runs: ProcessingRunRepository
    ranking_runs: RankingRunRepository
    result_packages: ResultPackageRepository
    participant_result_releases: ParticipantResultReleaseRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
