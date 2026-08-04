"""Authenticate resume credentials and capture participation consent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from poli_insight.application.participation_policy import consent_policy
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import ActorType, AuditAction
from poli_insight.domain.participation import (
    Participant,
    ParticipantConsent,
    ParticipationRuleViolation,
)
from poli_insight.infrastructure.auth.tokens import TokenError, digest_token


class ParticipantAccessError(ValueError):
    """Safe failure for invalid, expired, or unauthorized participant access."""


@dataclass(frozen=True, slots=True)
class ParticipantAccessResult:
    participant_id: str
    session_id: str
    configuration_version_id: str
    already_submitted: bool
    completed: bool


class ResumeParticipant:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def execute(self, access_token: str) -> ParticipantAccessResult:
        with self._unit_of_work_factory() as unit_of_work:
            participant = authorize_participant_access(
                unit_of_work, access_token=access_token, at=self._clock()
            )
            unit_of_work.commit()
        return ParticipantAccessResult(
            participant_id=participant.participant_id,
            session_id=participant.session_id,
            configuration_version_id=participant.configuration_version_id,
            already_submitted=participant.submitted_at is not None,
            completed=participant.completed_at is not None,
        )


class CaptureParticipantConsent:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory

    def execute(self, *, access_token: str, accepted: bool) -> ParticipantConsent:
        if not accepted:
            raise ParticipantAccessError(
                "Consent must be accepted before the questionnaire can begin."
            )
        occurred_at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            participant = authorize_participant_access(
                unit_of_work, access_token=access_token, at=occurred_at
            )
            session = unit_of_work.session.get(participant.session_id)
            if session is None:
                raise ParticipantAccessError(
                    "This participation session is unavailable."
                )
            configuration = next(
                (
                    item
                    for item in session.configurations
                    if item.configuration_version_id
                    == participant.configuration_version_id
                ),
                None,
            )
            if configuration is None:
                raise ParticipantAccessError(
                    "The questionnaire configuration is unavailable."
                )
            policy = consent_policy(configuration)
            existing = unit_of_work.consents.get_for_participant(
                participant.participant_id,
                configuration.configuration_version_id,
                policy.version,
            )
            if existing is not None:
                unit_of_work.commit()
                return existing
            consent = ParticipantConsent(
                participant_consent_id=self._id_factory(),
                participant_id=participant.participant_id,
                session_id=participant.session_id,
                configuration_version_id=configuration.configuration_version_id,
                consent_version=policy.version,
                statement_hash=policy.statement_hash,
                accepted_at=occurred_at,
            )
            unit_of_work.consents.add(consent)
            unit_of_work.audit_events.add(
                _consent_event(consent, event_id=self._id_factory())
            )
            unit_of_work.commit()
            return consent


def authorize_participant_access(
    unit_of_work: UnitOfWork,
    *,
    access_token: str,
    at: datetime,
    expected_participant_id: str | None = None,
) -> Participant:
    try:
        token_digest = digest_token(access_token)
    except TokenError as error:
        raise ParticipantAccessError(
            "The participation link is invalid or expired."
        ) from error
    grant = unit_of_work.access_grants.get_by_token_digest_for_update(token_digest)
    if grant is None:
        raise ParticipantAccessError("The participation link is invalid or expired.")
    participant = unit_of_work.participants.get_for_update(grant.participant_id)
    if participant is None or (
        expected_participant_id is not None
        and participant.participant_id != expected_participant_id
    ):
        raise ParticipantAccessError("The participation link is invalid or expired.")
    try:
        used = grant.use(
            participant=participant,
            presented_token_digest=token_digest,
            at=at,
        )
    except ParticipationRuleViolation as error:
        raise ParticipantAccessError(
            "The participation link is invalid or expired."
        ) from error
    unit_of_work.access_grants.save(used)
    return participant


def require_consent(
    unit_of_work: UnitOfWork, participant: Participant, configuration: object
) -> None:
    from poli_insight.domain.session import SessionConfigurationVersion

    if not isinstance(configuration, SessionConfigurationVersion):
        raise ParticipantAccessError("The questionnaire configuration is unavailable.")
    policy = consent_policy(configuration)
    if not policy.required:
        return
    accepted = unit_of_work.consents.get_for_participant(
        participant.participant_id,
        configuration.configuration_version_id,
        policy.version,
    )
    if accepted is None or accepted.statement_hash != policy.statement_hash:
        raise ParticipantAccessError(
            "Consent must be completed before questionnaire responses can be saved."
        )


def _consent_event(
    consent: ParticipantConsent,
    *,
    event_id: str,
) -> AuditEvent:
    after_json = {
        "schema_version": 1,
        "participant_consent_id": consent.participant_consent_id,
        "participant_id": consent.participant_id,
        "configuration_version_id": consent.configuration_version_id,
        "consent_version": consent.consent_version,
        "statement_hash": consent.statement_hash,
        "accepted_at": consent.accepted_at,
    }
    source_metadata = {
        "schema_version": 1,
        "use_case": "capture_participant_consent",
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": consent.accepted_at,
        "session_id": consent.session_id,
        "actor_type": ActorType.PARTICIPANT.value,
        "actor_id": consent.participant_id,
        "action": AuditAction.CREATED.value,
        "entity_type": "participant_consent",
        "entity_id": consent.participant_consent_id,
        "correlation_id": consent.participant_consent_id,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=consent.accepted_at,
        session_id=consent.session_id,
        actor_type=ActorType.PARTICIPANT,
        actor_id=consent.participant_id,
        action=AuditAction.CREATED,
        entity_type="participant_consent",
        entity_id=consent.participant_consent_id,
        correlation_id=consent.participant_consent_id,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
