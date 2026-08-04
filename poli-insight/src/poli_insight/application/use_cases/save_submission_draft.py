"""Application use case for creating and incrementally saving a draft."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases.participant_access import (
    ParticipantAccessError,
    authorize_participant_access,
    require_consent,
)
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
    SubmissionAnswer,
    SubmissionRuleViolation,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
JsonObject = Mapping[str, Any]


class SaveSubmissionDraftError(ValueError):
    """Expected application failure while saving a draft response."""


@dataclass(frozen=True, slots=True)
class DraftAnswerInput:
    """One question update in a partial draft-save command."""

    question_definition_id: str
    raw_value_json: JsonObject
    response_time_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.question_definition_id.strip():
            raise SaveSubmissionDraftError(
                "question_definition_id cannot be empty."
            )
        if not isinstance(self.raw_value_json, Mapping):
            raise SaveSubmissionDraftError(
                "raw_value_json must be a JSON object."
            )
        if (
            self.response_time_ms is not None
            and (
                isinstance(self.response_time_ms, bool)
                or not isinstance(self.response_time_ms, int)
                or self.response_time_ms < 0
            )
        ):
            raise SaveSubmissionDraftError(
                "response_time_ms must be a nonnegative integer."
            )


@dataclass(frozen=True, slots=True, repr=False)
class SaveSubmissionDraftCommand:
    """Partial answer changes for the participant's current draft."""

    session_id: str
    participant_id: str
    actor_id: str
    answers: tuple[DraftAnswerInput, ...] = field(default_factory=tuple)
    remove_question_definition_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    client_metadata_json: JsonObject = field(default_factory=dict)
    actor_type: ActorType = ActorType.PARTICIPANT
    access_token: str | None = None
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("participant_id", self.participant_id),
            ("actor_id", self.actor_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise SaveSubmissionDraftError(
                    f"{field_name} cannot be empty."
                )
        if not isinstance(self.client_metadata_json, Mapping):
            raise SaveSubmissionDraftError(
                "client_metadata_json must be a JSON object."
            )
        if self.actor_type == ActorType.PARTICIPANT and not self.access_token:
            raise SaveSubmissionDraftError(
                "Participant draft saves require a valid access token."
            )
        answer_question_ids = tuple(
            answer.question_definition_id for answer in self.answers
        )
        if len(answer_question_ids) != len(set(answer_question_ids)):
            raise SaveSubmissionDraftError(
                "answers cannot update the same question more than once."
            )
        if any(
            not question_id.strip()
            for question_id in self.remove_question_definition_ids
        ):
            raise SaveSubmissionDraftError(
                "remove_question_definition_ids cannot contain blanks."
            )
        if len(self.remove_question_definition_ids) != len(
            set(self.remove_question_definition_ids)
        ):
            raise SaveSubmissionDraftError(
                "A question cannot be removed more than once."
            )
        overlap = set(answer_question_ids).intersection(
            self.remove_question_definition_ids
        )
        if overlap:
            raise SaveSubmissionDraftError(
                "A question cannot be updated and removed together: "
                f"{sorted(overlap)!r}."
            )

    def __repr__(self) -> str:
        return (
            "SaveSubmissionDraftCommand("
            f"session_id={self.session_id!r}, participant_id={self.participant_id!r}, "
            f"answer_count={len(self.answers)}, access_token=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class SaveSubmissionDraftResult:
    """Application-facing state after a successful draft save."""

    submission_id: str
    participant_id: str
    configuration_version_id: str
    attempt_number: int
    status: SubmissionStatus
    answer_count: int
    last_saved_at: datetime
    created: bool


class SaveSubmissionDraft:
    """Create or patch an eligible participant's current draft."""

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
        command: SaveSubmissionDraftCommand,
    ) -> SaveSubmissionDraftResult:
        occurred_at = self._clock()

        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            configuration = _eligible_configuration(
                session,
                expected_session_id=command.session_id,
                at=occurred_at,
            )
            assert session is not None
            try:
                plan = unit_of_work.submissions.lock_attempt_plan(
                    command.participant_id,
                    configuration.configuration_version_id,
                )
            except LookupError as error:
                raise SaveSubmissionDraftError(
                    "Participant is not eligible for this configuration."
                ) from error

            participant = unit_of_work.participants.get(
                command.participant_id
            )
            if command.actor_type == ActorType.PARTICIPANT:
                try:
                    participant = authorize_participant_access(
                        unit_of_work,
                        access_token=command.access_token or "",
                        at=occurred_at,
                        expected_participant_id=command.participant_id,
                    )
                except ParticipantAccessError as error:
                    raise SaveSubmissionDraftError(str(error)) from error
            group = _eligible_participant(
                participant,
                session=session,
                configuration=configuration,
            )
            assert participant is not None
            try:
                require_consent(unit_of_work, participant, configuration)
            except ParticipantAccessError as error:
                raise SaveSubmissionDraftError(str(error)) from error
            snapshot = unit_of_work.scenarios.get_by_id(
                configuration.scenario_snapshot_id
            )
            if snapshot is None:
                raise SaveSubmissionDraftError(
                    "The questionnaire scenario is unavailable."
                )
            scale = next(
                (item for item in snapshot.scales if item.scale_id == configuration.scale_id),
                None,
            )
            if scale is None or not scale.values:
                raise SaveSubmissionDraftError(
                    "The questionnaire response scale is unavailable."
                )
            allowed_scale_value_ids = {
                item.scale_value_id for item in scale.values
            }

            created = plan.draft is None
            try:
                if plan.draft is None:
                    if participant.joined_at is None:
                        participant = participant.join(
                            actor_id=command.actor_id, at=occurred_at
                        )
                    if participant.started_at is None:
                        participant = participant.start(
                            actor_id=command.actor_id, at=occurred_at
                        )
                    unit_of_work.participants.save(participant)
                    draft = Submission.start(
                        submission_id=self._id_factory(),
                        participant=participant,
                        configuration=configuration,
                        group=group,
                        previous_submission=plan.previous_submission,
                        actor_id=command.actor_id,
                        at=occurred_at,
                        client_metadata_json=command.client_metadata_json,
                    )
                    if draft.attempt_number != plan.next_attempt_number:
                        raise SaveSubmissionDraftError(
                            "Allocated submission attempt changed unexpectedly."
                        )
                else:
                    draft = plan.draft
                    _validate_draft_binding(
                        draft,
                        participant=participant,
                        configuration=configuration,
                    )

                draft = self._apply_changes(
                    draft,
                    configuration=configuration,
                    command=command,
                    occurred_at=occurred_at,
                    allowed_scale_value_ids=allowed_scale_value_ids,
                )
            except (
                ParticipationRuleViolation,
                SessionRuleViolation,
                SubmissionRuleViolation,
            ) as error:
                raise SaveSubmissionDraftError(str(error)) from error

            if created:
                unit_of_work.submissions.add(draft)
                unit_of_work.audit_events.add(
                    _build_draft_created_event(
                        draft,
                        command=command,
                        occurred_at=occurred_at,
                        event_id=self._id_factory(),
                    )
                )
            elif draft != plan.draft:
                unit_of_work.submissions.save(draft)

            unit_of_work.commit()

        return SaveSubmissionDraftResult(
            submission_id=draft.submission_id,
            participant_id=draft.participant_id,
            configuration_version_id=draft.configuration_version_id,
            attempt_number=draft.attempt_number,
            status=draft.status,
            answer_count=len(draft.answers),
            last_saved_at=draft.last_saved_at,
            created=created,
        )

    def _apply_changes(
        self,
        draft: Submission,
        *,
        configuration: SessionConfigurationVersion,
        command: SaveSubmissionDraftCommand,
        occurred_at: datetime,
        allowed_scale_value_ids: set[str],
    ) -> Submission:
        questions = {
            question.question_definition_id: question
            for question in configuration.question_definitions
        }
        for answer_input in command.answers:
            selected_scale_value_id = answer_input.raw_value_json.get(
                "selected_scale_value_id"
            )
            if (
                selected_scale_value_id is not None
                and selected_scale_value_id not in allowed_scale_value_ids
            ):
                raise SaveSubmissionDraftError(
                    "Answer uses a value outside the configured response scale."
                )
            question = questions.get(answer_input.question_definition_id)
            if question is None:
                raise SaveSubmissionDraftError(
                    "Answer references a question outside the active "
                    f"configuration: {answer_input.question_definition_id!r}."
                )
            existing = draft.answer_for_question(
                answer_input.question_definition_id
            )
            answer = SubmissionAnswer.create(
                submission_answer_id=(
                    existing.submission_answer_id
                    if existing is not None
                    else self._id_factory()
                ),
                submission_id=draft.submission_id,
                question=question,
                raw_value_json=answer_input.raw_value_json,
                answered_at=occurred_at,
                response_time_ms=answer_input.response_time_ms,
            )
            draft = draft.save_answer(
                answer,
                configuration=configuration,
                actor_id=command.actor_id,
                at=occurred_at,
            )

        for question_id in command.remove_question_definition_ids:
            if question_id not in questions:
                raise SaveSubmissionDraftError(
                    "Removal references a question outside the active "
                    f"configuration: {question_id!r}."
                )
            if draft.answer_for_question(question_id) is not None:
                draft = draft.remove_answer(
                    question_id,
                    actor_id=command.actor_id,
                    at=occurred_at,
                )
        return draft


def _eligible_configuration(
    session: Session | None,
    *,
    expected_session_id: str,
    at: datetime,
) -> SessionConfigurationVersion:
    if session is None or session.session_id != expected_session_id:
        raise SaveSubmissionDraftError(
            f"Session {expected_session_id!r} does not exist."
        )
    if not session.can_accept_submissions(at=at):
        raise SaveSubmissionDraftError(
            "Session is not accepting submission drafts."
        )
    try:
        configuration = session.active_configuration
    except SessionRuleViolation as error:
        raise SaveSubmissionDraftError(str(error)) from error
    if configuration is None or not configuration.is_activated:
        raise SaveSubmissionDraftError(
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
        raise SaveSubmissionDraftError(
            "Participant is not enrolled in this session."
        )
    if not participant.can_access:
        raise SaveSubmissionDraftError("Participant access is not active.")
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
        raise SaveSubmissionDraftError(
            "Participant stakeholder group is outside the active "
            "configuration."
        )
    try:
        participant.validate_binding(
            configuration=configuration,
            group=group,
        )
    except ParticipationRuleViolation as error:
        raise SaveSubmissionDraftError(str(error)) from error
    return group


def _validate_draft_binding(
    draft: Submission,
    *,
    participant: Participant,
    configuration: SessionConfigurationVersion,
) -> None:
    if draft.status != SubmissionStatus.DRAFT:
        raise SaveSubmissionDraftError(
            "Only a draft submission can receive answer updates."
        )
    if draft.participant_id != participant.participant_id:
        raise SaveSubmissionDraftError(
            "Draft belongs to a different participant."
        )
    if (
        draft.session_stakeholder_group_id
        != participant.session_stakeholder_group_id
    ):
        raise SaveSubmissionDraftError(
            "Draft stakeholder group no longer matches the participant."
        )
    draft.validate_against_configuration(configuration)


def _draft_projection(draft: Submission) -> dict[str, object]:
    return {
        "schema_version": 1,
        "submission_id": draft.submission_id,
        "participant_id": draft.participant_id,
        "configuration_version_id": draft.configuration_version_id,
        "attempt_number": draft.attempt_number,
        "previous_submission_id": draft.previous_submission_id,
        "status": draft.status.value,
        "answer_count": len(draft.answers),
        "started_at": draft.started_at,
    }


def _build_draft_created_event(
    draft: Submission,
    *,
    command: SaveSubmissionDraftCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    after_json = _draft_projection(draft)
    source_metadata = {
        "schema_version": 1,
        "use_case": "save_submission_draft",
        "audit_policy": "draft_creation_only",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": draft.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.CREATED.value,
        "entity_type": "submission",
        "entity_id": draft.submission_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "causation_event_id": command.causation_event_id,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        session_id=draft.session_id,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=AuditAction.CREATED,
        entity_type="submission",
        entity_id=draft.submission_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
