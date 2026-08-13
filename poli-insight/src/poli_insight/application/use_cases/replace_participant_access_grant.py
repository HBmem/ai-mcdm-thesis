"""Secure, audited administrator replacement of participant resume access."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.enum import ActorType, AuditAction, ParticipantAccessStatus
from poli_insight.domain.participation import (
    ParticipantAccessGrant,
    ParticipationRuleViolation,
)
from poli_insight.infrastructure.auth.tokens import IssuedToken, generate_token

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
TokenFactory = Callable[[], IssuedToken]
DEFAULT_REPLACEMENT_TTL = timedelta(days=30)


class ReplaceParticipantAccessGrantError(ValueError):
    """Safe administrator-facing credential replacement failure."""


@dataclass(frozen=True, slots=True, repr=False)
class ReplaceParticipantAccessGrantCommand:
    session_id: str
    participant_id: str
    actor_id: str
    actor_roles: frozenset[str]
    reason: str = "Administrator-generated replacement resume link"
    expires_at: datetime | None = None
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("participant_id", self.participant_id),
            ("actor_id", self.actor_id),
            ("reason", self.reason),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise ReplaceParticipantAccessGrantError(
                    f"{field_name} cannot be blank."
                )
        if self.actor_type != ActorType.USER or "admin" not in self.actor_roles:
            raise ReplaceParticipantAccessGrantError(
                "An authenticated authorized administrator is required."
            )
        if self.expires_at is not None and (
            self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ReplaceParticipantAccessGrantError(
                "Access expiration must include timezone information."
            )

    def __repr__(self) -> str:
        return (
            "ReplaceParticipantAccessGrantCommand("
            f"session_id={self.session_id!r}, participant_id={self.participant_id!r}, "
            f"actor_id={self.actor_id!r}, expires_at={self.expires_at!r}, "
            f"correlation_id={self.correlation_id!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ReplaceParticipantAccessGrantResult:
    participant_id: str
    session_id: str
    access_grant_id: str
    replaced_access_grant_id: str
    access_token: str
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            "ReplaceParticipantAccessGrantResult("
            f"participant_id={self.participant_id!r}, session_id={self.session_id!r}, "
            f"access_grant_id={self.access_grant_id!r}, "
            f"replaced_access_grant_id={self.replaced_access_grant_id!r}, "
            "access_token=<redacted>, "
            f"expires_at={self.expires_at!r})"
        )


class ReplaceParticipantAccessGrant:
    """Rotate one active resume credential without changing participant state."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
        token_factory: TokenFactory = generate_token,
        access_grant_ttl: timedelta = DEFAULT_REPLACEMENT_TTL,
    ) -> None:
        if access_grant_ttl <= timedelta(0):
            raise ValueError("access_grant_ttl must be positive.")
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory
        self._token_factory = token_factory
        self._access_grant_ttl = access_grant_ttl

    def execute(
        self,
        command: ReplaceParticipantAccessGrantCommand,
    ) -> ReplaceParticipantAccessGrantResult:
        at = self._clock()
        expires_at = command.expires_at or at + self._access_grant_ttl
        if expires_at <= at:
            raise ReplaceParticipantAccessGrantError(
                "Replacement access expiration must be in the future."
            )
        with self._unit_of_work_factory() as unit_of_work:
            participant = unit_of_work.participants.get_for_update(
                command.participant_id
            )
            if participant is None:
                raise ReplaceParticipantAccessGrantError(
                    "Participant was not found."
                )
            if participant.session_id != command.session_id:
                raise ReplaceParticipantAccessGrantError(
                    "Participant does not belong to this session."
                )
            if participant.access_status != ParticipantAccessStatus.ACTIVE:
                raise ReplaceParticipantAccessGrantError(
                    "Only an active participant can receive a replacement link."
                )
            try:
                previous = (
                    unit_of_work.access_grants
                    .get_current_for_participant_for_update(
                        participant.participant_id,
                        at=at,
                    )
                )
            except ValueError as error:
                raise ReplaceParticipantAccessGrantError(
                    "Resume access changed concurrently. Refresh and try again."
                ) from error
            if previous is None:
                raise ReplaceParticipantAccessGrantError(
                    "The participant has no current active resume link."
                )
            issued = self._token_factory()
            replacement = ParticipantAccessGrant(
                access_grant_id=self._id_factory(),
                participant_id=participant.participant_id,
                token_digest=issued.token_digest,
                issued_at=at,
                expires_at=expires_at,
            )
            try:
                revoked = previous.replace_with(
                    replacement,
                    actor_id=command.actor_id,
                    reason=command.reason,
                    at=at,
                )
            except ParticipationRuleViolation as error:
                raise ReplaceParticipantAccessGrantError(
                    "Resume access changed concurrently. Refresh and try again."
                ) from error

            # The successor must exist before the same-participant replacement
            # foreign key is written. Both changes commit or roll back together.
            unit_of_work.access_grants.add(replacement)
            unit_of_work.access_grants.save(revoked)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=at,
                    session_id=participant.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.UPDATED,
                    entity_type="participant_access_grant",
                    entity_id=previous.access_grant_id,
                    correlation_id=command.correlation_id,
                    use_case="replace_participant_access_grant",
                    before_json={
                        "access_grant_id": previous.access_grant_id,
                        "status": "active",
                    },
                    after_json={
                        "access_grant_id": previous.access_grant_id,
                        "status": "replaced",
                        "replacement_access_grant_id": replacement.access_grant_id,
                        "replacement_expires_at": replacement.expires_at,
                    },
                    reason_text=command.reason,
                )
            )
            unit_of_work.commit()
        return ReplaceParticipantAccessGrantResult(
            participant_id=participant.participant_id,
            session_id=participant.session_id,
            access_grant_id=replacement.access_grant_id,
            replaced_access_grant_id=previous.access_grant_id,
            access_token=issued.plaintext,
            expires_at=replacement.expires_at,
        )
