from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.submission_queries import (
    SubmissionDashboardPage,
)

from poli_insight.domain.submissions import Submission

UnitOfWorkFactory = Callable[[], UnitOfWork]

class SubmissionNotFoundError(ValueError):
    """"""
    pass

class SubmissionService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def get_submission(
        self,
        submission_id: str,
    ) -> Submission | None:
        with self._unit_of_work_factory() as unit_of_work:
            submission = unit_of_work.submissions.get(
                    submission_id=submission_id
            )

        if submission is None:
            return None

        return submission

    def withdraw_submission(
        self,
        submission_id: str,
        *,
        session_id: str,
        actor_id: str,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            submission = unit_of_work.submissions.get(
                submission_id
            )

            if submission is None:
                raise SubmissionNotFoundError(
                    f"Submission {submission_id!r} "
                    "was not found."
                )

            participant = unit_of_work.participants.get(
                submission.participant_id
            )

            if (
                participant is None
                or participant.session_id != session_id
            ):
                raise SubmissionNotFoundError(
                    f"Submission {submission_id!r} "
                    f"does not belong to session {session_id!r}."
                )

            submission.withdraw(actor_id=actor_id)

            unit_of_work.submissions.save(submission)
            unit_of_work.commit()

    def get_dashboard(
        self,
        session_id: str,
        *,
        page: int,
        page_size: int,
        consistency_threshold: float = 0.10,
    ) -> SubmissionDashboardPage:
        if not session_id.strip():
            raise ValueError("Session ID is required.")

        if page < 1:
            raise ValueError("Page must be at least 1.")

        if not 1 <= page_size <= 100:
            raise ValueError(
                "Page size must be between 1 and 100."
            )

        if consistency_threshold < 0:
            raise ValueError(
                "Consistency threshold cannot be negative."
            )
    
        with self._unit_of_work_factory() as unit_of_work:
            dashboard_page = (
                unit_of_work.submission_dashboard.get_dashboard(
                    session_id=session_id,
                    page=page,
                    page_size=page_size,
                    consistency_threshold=consistency_threshold,
                )
            )

            return dashboard_page
        