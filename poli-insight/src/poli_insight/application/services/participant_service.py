from __future__ import annotations

import uuid

from collections.abc import Callable
from datetime import UTC, datetime

from poli_insight.domain.enums import SubmissionStatus

from poli_insight.application.dto import CreateParticipantCommand
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.participant_queries import (
    ParticipantPage,
    ParticipantTableItem,
    ParticipantTablePage
)

from poli_insight.domain.participant import (
    Participant
)

class CreateParticipantError(ValueError):
    pass

class ParticipantNotFoundError(LookupError):
    pass

UnitOfWorkFactory = Callable[[], UnitOfWork]

class ParticipantService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def create_participant(
        self,
        command: CreateParticipantCommand,
    ) -> str:
        participant_id = command.participant_id.strip()

        if not participant_id:
            raise CreateParticipantError("Participant ID is required.")
        
    def get_participant(
        self,
        participant_id: str,
    ) -> Participant:
        with self._unit_of_work_factory() as unit_of_work:
            participant = unit_of_work.participants.get(participant_id)

        if participant is None:
            raise ParticipantNotFoundError(
                f"Participant {participant_id!r} was not found."
            )
        
        return participant
    
    def list_participant_table(
        self,
        session_id: str,
        *,
        page: int = 1,
        page_size: int = 10,
    ) -> ParticipantTablePage:
        if page < 1:
            raise ValueError("Page must be at least 1.")

        if not 1 <= page_size <= 100:
            raise ValueError(
                "Page size must be between 1 and 100."
            )
        
        with self._unit_of_work_factory() as unit_of_work:
            participant_page = unit_of_work.participants.list_for_session(
                session_id=session_id,
                page=page,
                page_size=page_size,
            )

            participant_ids = {
                participant.participant_id
                for participant in participant_page.items
            }

            current_submissions = (
                unit_of_work.submissions.list_current_for_participants(
                    participant_ids
                )
            )

            drafts = {
                submission.participant_id: submission
                for submission in current_submissions
                if submission.status == SubmissionStatus.DRAFT
            }

            effective = {
                submission.participant_id: submission
                for submission in current_submissions
                if submission.status == SubmissionStatus.SUBMITTED
            }

            items = tuple(
                ParticipantTableItem(
                    participant=participant,
                    draft_submission=drafts.get(
                        participant.participant_id
                    ),
                    effective_submission=effective.get(
                        participant.participant_id
                    ),
                )
                for participant in participant_page.items
            )

            return ParticipantTablePage(
                items=items,
                total=participant_page.total,
                page=participant_page.page,
                page_size=participant_page.page_size,
            )