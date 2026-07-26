from __future__ import annotations

from typing import Protocol, Sequence

from poli_insight.domain.participant import Participant
from poli_insight.domain.submissions import Submission, SubmissionValidation
from poli_insight.domain.scenario import (
    ScenarioBundle,
    ScenarioSnapshot,
)
from poli_insight.domain.sessions import (
    Session,
    SessionStakeholderGroup,
)

from poli_insight.application.session_queries import (
    SessionFilters,
    SessionPage,
)
from poli_insight.application.participant_queries import (
    ParticipantPage
)
from poli_insight.application.submission_queries import (
    SubmissionDashboardPage,
)

class SessionRepository(Protocol):
    def add(
        self,
        session: Session,
        stakeholder_groups: Sequence[SessionStakeholderGroup],
    ) -> None:
        ...
    
    def get(
        self,
        session_id: str,
    ) -> Session | None:
        ...

    def list_filtered(
        self,
        filters: SessionFilters,
        *,
        page: int,
        page_size: int,
    ) -> SessionPage:
        ...

    def save(
        self,
        session: Session,
    ) -> None:
        ...

    def delete(
        self,
        session_id: str,
    ) -> bool:
        ...

class ScenarioRepository(Protocol):
    def ensure_snapshot(
        self,
        bundle: ScenarioBundle,
    ) -> ScenarioSnapshot:
        ...
    
    def get_snapshot(
        self,
        scenario_id: str,
        scenario_version: str,
    ) -> ScenarioSnapshot | None:
        ...
    
    def get_many(
        self,
        identities: set[tuple[str, str]],
    ) -> dict[tuple[str, str], ScenarioSnapshot]:
        ...

class ParticipantRepository(Protocol):
    def add(
        self,
        participant: Participant,
    ) -> None:
        ...

    def get(
        self,
        participant_id: str,
    ) -> Participant | None:
        ...

    def save(
        self,
        participant: Participant,
    ) -> None:
        ...

    def list_for_session(
        self,
        session_id: str,
        *,
        page: int,
        page_size: int,
    ) -> ParticipantPage:
        ...


class SubmissionRepository(Protocol):
    def add(
        self,
        submission: Submission,
    ) -> None:
        ...
    def get(
        self,
        submission_id: str,
    ) -> Submission | None:
        ...

    def list_current_for_participants(
        self,
        participant_ids: set[str],
    ) -> Sequence[Submission]:
        ...

    def save(
        self,
        submission: Submission,
    ) -> None:
        ...

    def get_draft(
        self,
        participant_id: str,
    ) -> Submission | None:
        ...

    def get_effective(
        self,
        participant_id: str,
    ) -> Submission | None:
        ...

    def list_for_participant(
        self,
        participant_id: str,
    ) -> Sequence[Submission]:
        ...

class SubmissionValidationRepository(Protocol):
    def add(
        self,
        validation: SubmissionValidation,
    ) -> None:
        ...

class SubmissionDashboardQueryRepository(Protocol):
    def get_dashboard(
        self,
        session_id: str,
        *,
        page: int,
        page_size: int,
        consistency_threshold: float,
    ) -> SubmissionDashboardPage:
        ...