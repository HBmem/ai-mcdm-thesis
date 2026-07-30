"""Application use case for atomically finalizing a participant response."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AuditAction,
    SubmissionStatus,
)
from poli_insight.domain.participation import (
    Participant,
    ParticipationRuleViolation,
)
from poli_insight.domain.session import (
    Session,
    SessionConfigurationVersion,
    SessionRuleViolation,
    SessionStakeholderGroup,
)
from poli_insight.domain.submission import (
    Submission,
    SubmissionRuleViolation,
)


UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class SubmitResponseError(ValueError):
    """Expected application failure while finalizing a response."""


@dataclass(frozen=True, slots=True)
class SubmitResponseCommand:
    """Identity and audit context for finalizing the current draft."""

    session_id: str
    participant_id: str
    submission_id: str
    actor_id: str
    actor_type: ActorType = ActorType.PARTICIPANT
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("participant_id", self.participant_id),
            ("submission_id", self.submission_id),
            ("actor_id", self.actor_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise SubmitResponseError(f"{field_name} cannot be empty.")


@dataclass(frozen=True, slots=True)
class SubmitResponseResult:
    """Application DTO for the newly effective submission."""

    submission_id: str
    participant_id: str
    configuration_version_id: str
    attempt_number: int
    status: SubmissionStatus
    answer_count: int
    answers_hash: str
    submitted_at: datetime
    superseded_submission_id: str | None


class SubmitResponse:
    """Finalize a draft and supersede its effective predecessor atomically."""

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

    def execute(
        self,
        command: SubmitResponseCommand,
    ) -> SubmitResponseResult:
        occurred_at = self._clock()

        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            configuration = _eligible_configuration(
                session,
                expected_session_id=command.session_id,
                at=occurred_at,
            )
            try:
                plan = unit_of_work.submissions.lock_attempt_plan(
                    command.participant_id,
                    configuration.configuration_version_id,
                )
            except LookupError as error:
                raise SubmitResponseError(
                    "Participant is not eligible for this configuration."
                ) from error

            participant = unit_of_work.participants.get(
                command.participant_id
            )
            _eligible_participant(
                participant,
                session=session,
                configuration=configuration,
            )
            if plan.draft is None:
                raise SubmitResponseError(
                    "Participant has no draft response to submit."
                )
            if plan.draft.submission_id != command.submission_id:
                raise SubmitResponseError(
                    "Requested submission is not the participant's current "
                    "draft."
                )

            draft = unit_of_work.submissions.get_for_update(
                command.submission_id
            )
            if draft is None:
                raise SubmitResponseError(
                    f"Submission {command.submission_id!r} does not exist."
                )
            _validate_draft_binding(
                draft,
                participant=participant,
                configuration=configuration,
            )

            effective = unit_of_work.submissions.get_effective_submission(
                participant.participant_id,
                configuration.configuration_version_id,
            )
            _validate_effective_predecessor(draft, effective)

            before_json = _submission_projection(draft)
            try:
                finalized = draft.submit(
                    configuration,
                    actor_id=command.actor_id,
                    at=occurred_at,
                )
                superseded = (
                    effective.supersede_with(
                        finalized,
                        actor_id=command.actor_id,
                        at=occurred_at,
                    )
                    if effective is not None
                    else None
                )
            except SubmissionRuleViolation as error:
                raise SubmitResponseError(str(error)) from error

            # Move the old effective row first so the partial unique index can
            # accept the newly submitted row in the same transaction.
            if superseded is not None:
                unit_of_work.submissions.save(superseded)
            unit_of_work.submissions.save(finalized)

            submitted_event = _build_submitted_event(
                finalized,
                before_json=before_json,
                command=command,
                occurred_at=occurred_at,
                event_id=self._id_factory(),
            )
            unit_of_work.audit_events.add(submitted_event)
            if superseded is not None and effective is not None:
                unit_of_work.audit_events.add(
                    _build_superseded_event(
                        before=effective,
                        after=superseded,
                        replacement=finalized,
                        command=command,
                        occurred_at=occurred_at,
                        event_id=self._id_factory(),
                        causation_event_id=submitted_event.audit_event_id,
                    )
                )
            unit_of_work.commit()

        if finalized.answers_hash is None or finalized.submitted_at is None:
            raise AssertionError(
                "Finalized submission is missing immutable evidence metadata."
            )
        return SubmitResponseResult(
            submission_id=finalized.submission_id,
            participant_id=finalized.participant_id,
            configuration_version_id=finalized.configuration_version_id,
            attempt_number=finalized.attempt_number,
            status=finalized.status,
            answer_count=len(finalized.answers),
            answers_hash=finalized.answers_hash,
            submitted_at=finalized.submitted_at,
            superseded_submission_id=(
                superseded.submission_id
                if superseded is not None
                else None
            ),
        )


def _eligible_configuration(
    session: Session | None,
    *,
    expected_session_id: str,
    at: datetime,
) -> SessionConfigurationVersion:
    if session is None or session.session_id != expected_session_id:
        raise SubmitResponseError(
            f"Session {expected_session_id!r} does not exist."
        )
    if not session.can_accept_submissions(at=at):
        raise SubmitResponseError(
            "Session is no longer accepting submissions."
        )
    try:
        configuration = session.active_configuration
    except SessionRuleViolation as error:
        raise SubmitResponseError(str(error)) from error
    if configuration is None or not configuration.is_activated:
        raise SubmitResponseError(
            "Session has no active submission configuration."
        )
    return configuration


def _eligible_participant(
    participant: Participant | None,
    *,
    session: Session,
    configuration: SessionConfigurationVersion,
) -> SessionStakeholderGroup:
    if participant is None or participant.session_id != session.session_id:
        raise SubmitResponseError(
            "Participant is not enrolled in this session."
        )
    if not participant.can_access:
        raise SubmitResponseError("Participant access is not active.")
    group = next(
        (
            candidate
            for candidate in configuration.stakeholder_groups
            if candidate.session_stakeholder_group_id
            == participant.session_stakeholder_group_id
        ),
        None,
    )
    if group is None:
        raise SubmitResponseError(
            "Participant stakeholder group is outside the active "
            "configuration."
        )
    try:
        participant.validate_binding(
            configuration=configuration,
            group=group,
        )
    except ParticipationRuleViolation as error:
        raise SubmitResponseError(str(error)) from error
    return group


def _validate_draft_binding(
    draft: Submission,
    *,
    participant: Participant,
    configuration: SessionConfigurationVersion,
) -> None:
    if draft.status is not SubmissionStatus.DRAFT:
        raise SubmitResponseError("Only a draft response can be submitted.")
    if draft.participant_id != participant.participant_id:
        raise SubmitResponseError(
            "Draft belongs to a different participant."
        )
    if (
        draft.session_stakeholder_group_id
        != participant.session_stakeholder_group_id
    ):
        raise SubmitResponseError(
            "Draft stakeholder group no longer matches the participant."
        )
    try:
        draft.validate_against_configuration(configuration)
    except SubmissionRuleViolation as error:
        raise SubmitResponseError(str(error)) from error


def _validate_effective_predecessor(
    draft: Submission,
    effective: Submission | None,
) -> None:
    if draft.previous_submission_id is None:
        if effective is not None:
            raise SubmitResponseError(
                "First attempt conflicts with an existing effective response."
            )
        return
    if (
        effective is None
        or effective.submission_id != draft.previous_submission_id
    ):
        raise SubmitResponseError(
            "Draft predecessor is no longer the effective submission."
        )


def _submission_projection(submission: Submission) -> dict[str, object]:
    return {
        "schema_version": 1,
        "submission_id": submission.submission_id,
        "participant_id": submission.participant_id,
        "configuration_version_id": submission.configuration_version_id,
        "attempt_number": submission.attempt_number,
        "previous_submission_id": submission.previous_submission_id,
        "status": submission.status.value,
        "answer_count": len(submission.answers),
        "answers_hash": submission.answers_hash,
        "submitted_at": submission.submitted_at,
        "superseded_at": submission.superseded_at,
    }


def _build_submitted_event(
    submission: Submission,
    *,
    before_json: dict[str, object],
    command: SubmitResponseCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    after_json = _submission_projection(submission)
    source_metadata = {
        "schema_version": 1,
        "use_case": "submit_response",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": submission.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.SUBMITTED.value,
        "entity_type": "submission",
        "entity_id": submission.submission_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "causation_event_id": command.causation_event_id,
        "before_json": before_json,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        session_id=submission.session_id,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=AuditAction.SUBMITTED,
        entity_type="submission",
        entity_id=submission.submission_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        before_json=before_json,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )


def _build_superseded_event(
    *,
    before: Submission,
    after: Submission,
    replacement: Submission,
    command: SubmitResponseCommand,
    occurred_at: datetime,
    event_id: str,
    causation_event_id: str,
) -> AuditEvent:
    before_json = _submission_projection(before)
    after_json = {
        **_submission_projection(after),
        "replacement_submission_id": replacement.submission_id,
    }
    source_metadata = {
        "schema_version": 1,
        "use_case": "submit_response",
        "transition": "supersession",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": after.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.UPDATED.value,
        "entity_type": "submission",
        "entity_id": after.submission_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "causation_event_id": causation_event_id,
        "reason_code": "superseded_by_submission",
        "before_json": before_json,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        session_id=after.session_id,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=AuditAction.UPDATED,
        entity_type="submission",
        entity_id=after.submission_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=causation_event_id,
        reason_code="superseded_by_submission",
        before_json=before_json,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
