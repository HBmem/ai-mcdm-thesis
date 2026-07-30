"""Application use case for secure, atomic participant enrollment."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from poli_insight.application.ports.audit_repository import (
    AuditEventRepository,
)
from poli_insight.application.ports.participant_repository import (
    ParticipantAccessGrantRepository,
    ParticipantRepository,
    SessionInvitationRepository,
)
from poli_insight.application.ports.session_repository import SessionRepository
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    AccessCodeMode,
    ActorType,
    AuditAction,
    EnrollmentMode,
    SessionStatus,
    StakeholderSelectionMode,
)
from poli_insight.domain.participation import (
    Participant,
    ParticipantAccessGrant,
    ParticipationRuleViolation,
    SessionInvitation,
)
from poli_insight.domain.session import (
    Session,
    SessionConfigurationVersion,
    SessionStakeholderGroup,
)
from poli_insight.infrastructure.auth.tokens import (
    TokenError,
    digest_token,
    generate_token,
)


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
JsonObject = Mapping[str, Any]
DEFAULT_ACCESS_GRANT_TTL = timedelta(days=30)
_SAFE_NETWORK_METADATA_KEYS = frozenset(
    {
        "client_type",
        "country_code",
        "network_class",
        "user_agent_family",
    }
)


class AccessAttemptOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AccessCodeVerificationResult:
    """Secret-free result from the slow-hash access-code adapter."""

    accepted: bool
    reason_code: str
    access_code_id: str | None = None

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise ValueError("reason_code cannot be empty.")
        if self.accepted and self.access_code_id is None:
            raise ValueError(
                "Accepted access-code verification requires access_code_id."
            )


class EnrollmentAccessCodeRepository(Protocol):
    """Verify human-chosen codes using a slow password-hash implementation."""

    def verify_for_enrollment(
        self,
        *,
        session_id: str,
        invitation_id: str | None,
        plaintext_code: str,
        at: datetime,
    ) -> AccessCodeVerificationResult:
        """Verify and lock the applicable code without recording a use."""
        ...

    def record_successful_use(
        self,
        *,
        access_code_id: str,
        at: datetime,
    ) -> None:
        """Increment use only after every enrollment check has succeeded."""
        ...


@dataclass(frozen=True, slots=True)
class AccessAttemptRecord:
    """Minimized security record that never contains submitted credentials."""

    access_attempt_id: str
    session_id: str
    attempted_at: datetime
    outcome: AccessAttemptOutcome
    reason_code: str
    invitation_id: str | None = None
    access_code_id: str | None = None
    rate_limit_key_hash: str | None = None
    network_metadata_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("access_attempt_id", self.access_attempt_id),
            ("session_id", self.session_id),
            ("reason_code", self.reason_code),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty.")
        if (
            self.attempted_at.tzinfo is None
            or self.attempted_at.utcoffset() is None
        ):
            raise ValueError("attempted_at must include timezone information.")
        if (
            self.rate_limit_key_hash is not None
            and not _is_sha256(self.rate_limit_key_hash)
        ):
            raise ValueError(
                "rate_limit_key_hash must be a lowercase SHA-256 digest."
            )


class AccessAttemptRepository(Protocol):
    def add(self, attempt: AccessAttemptRecord) -> None:
        """Add a secret-free access attempt to the current transaction."""
        ...


class EnrollmentUnitOfWork(Protocol):
    """Repositories required to enroll and audit in one transaction."""

    session: SessionRepository
    participants: ParticipantRepository
    invitations: SessionInvitationRepository
    access_grants: ParticipantAccessGrantRepository
    access_codes: EnrollmentAccessCodeRepository
    access_attempts: AccessAttemptRepository
    audit_events: AuditEventRepository

    def __enter__(self) -> EnrollmentUnitOfWork:
        ...

    def __exit__(self, exc_type, exc, traceback) -> None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...


EnrollmentUnitOfWorkFactory = Callable[[], EnrollmentUnitOfWork]


class EnrollParticipantError(ValueError):
    """Expected application failure during participant enrollment."""


class EnrollmentRejectedError(EnrollParticipantError):
    """Safe rejection carrying a stable, nonsecret reason code."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("Enrollment was not authorized.")


@dataclass(frozen=True, slots=True, repr=False)
class EnrollParticipantCommand:
    """Enrollment input; credential values are always redacted from repr."""

    session_id: str
    selected_group_id: str | None = None
    invitation_token: str | None = None
    access_code: str | None = None
    identity_lookup_hash: str | None = None
    user_id: str | None = None
    alias: str | None = None
    rate_limit_key_hash: str | None = None
    network_metadata_json: JsonObject = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("session_id", self.session_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise EnrollParticipantError(
                    f"{field_name} cannot be empty."
                )
        for field_name, value in (
            ("selected_group_id", self.selected_group_id),
            ("user_id", self.user_id),
            ("alias", self.alias),
        ):
            if value is not None and not value.strip():
                raise EnrollParticipantError(
                    f"{field_name} cannot be blank when provided."
                )
        for field_name, value in (
            ("identity_lookup_hash", self.identity_lookup_hash),
            ("rate_limit_key_hash", self.rate_limit_key_hash),
        ):
            if value is not None and not _is_sha256(value):
                raise EnrollParticipantError(
                    f"{field_name} must be a lowercase SHA-256 digest."
                )

    def __repr__(self) -> str:
        return (
            "EnrollParticipantCommand("
            f"session_id={self.session_id!r}, "
            f"selected_group_id={self.selected_group_id!r}, "
            "invitation_token=<redacted>, access_code=<redacted>, "
            f"user_id={self.user_id!r}, alias={self.alias!r}, "
            f"correlation_id={self.correlation_id!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class EnrollParticipantResult:
    """Successful enrollment DTO containing the resume token exactly once."""

    participant_id: str
    session_id: str
    configuration_version_id: str
    session_stakeholder_group_id: str
    access_grant_id: str
    access_token: str
    access_token_expires_at: datetime

    def __repr__(self) -> str:
        return (
            "EnrollParticipantResult("
            f"participant_id={self.participant_id!r}, "
            f"session_id={self.session_id!r}, "
            f"configuration_version_id={self.configuration_version_id!r}, "
            "access_token=<redacted>, "
            f"access_token_expires_at={self.access_token_expires_at!r})"
        )


@dataclass(frozen=True, slots=True)
class _Admission:
    session: Session
    configuration: SessionConfigurationVersion
    group: SessionStakeholderGroup
    participant: Participant
    invitation: SessionInvitation | None
    access_grant: ParticipantAccessGrant
    plaintext_access_token: str
    access_code_id: str | None


class _RejectEnrollment(Exception):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code


class EnrollParticipant:
    """Evaluate admission and create all enrollment records atomically."""

    def __init__(
        self,
        unit_of_work_factory: EnrollmentUnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
        access_grant_ttl: timedelta = DEFAULT_ACCESS_GRANT_TTL,
    ) -> None:
        if access_grant_ttl <= timedelta(0):
            raise ValueError("access_grant_ttl must be positive.")
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory
        self._access_grant_ttl = access_grant_ttl

    def execute(
        self,
        command: EnrollParticipantCommand,
    ) -> EnrollParticipantResult:
        occurred_at = self._clock()
        result: EnrollParticipantResult | None = None
        rejection: EnrollmentRejectedError | None = None

        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get_for_update(command.session_id)
            if session is None:
                rejection = EnrollmentRejectedError("session_unavailable")
            else:
                try:
                    admission = self._prepare_admission(
                        unit_of_work,
                        session=session,
                        command=command,
                        occurred_at=occurred_at,
                    )
                except _RejectEnrollment as error:
                    unit_of_work.access_attempts.add(
                        self._access_attempt(
                            session_id=session.session_id,
                            command=command,
                            occurred_at=occurred_at,
                            outcome=AccessAttemptOutcome.REJECTED,
                            reason_code=error.reason_code,
                        )
                    )
                    unit_of_work.commit()
                    rejection = EnrollmentRejectedError(error.reason_code)
                else:
                    self._persist_admission(
                        unit_of_work,
                        admission=admission,
                        command=command,
                        occurred_at=occurred_at,
                    )
                    unit_of_work.commit()
                    result = _result(admission)

        if rejection is not None:
            raise rejection
        if result is None:
            raise AssertionError("Enrollment completed without an outcome.")
        return result

    def _prepare_admission(
        self,
        unit_of_work: EnrollmentUnitOfWork,
        *,
        session: Session,
        command: EnrollParticipantCommand,
        occurred_at: datetime,
    ) -> _Admission:
        # Discoverability controls listings only. It is deliberately absent
        # from this admission decision.
        if (
            session.status is not SessionStatus.OPEN
            or not session.can_accept_submissions(at=occurred_at)
        ):
            raise _RejectEnrollment("session_unavailable")
        configuration = session.active_configuration
        if configuration is None or not configuration.is_activated:
            raise _RejectEnrollment("session_unavailable")

        invitation, invitation_digest = self._load_invitation(
            unit_of_work,
            command=command,
        )
        self._validate_enrollment_mode(session, invitation)

        access_code_result = self._verify_access_code(
            unit_of_work,
            session=session,
            invitation=invitation,
            command=command,
            occurred_at=occurred_at,
        )
        participant_id = self._id_factory()
        redeemed_invitation = self._redeem_invitation(
            invitation,
            participant_id=participant_id,
            invitation_digest=invitation_digest,
            command=command,
            occurred_at=occurred_at,
        )
        group = _resolve_group(
            session,
            configuration=configuration,
            invitation=redeemed_invitation,
            selected_group_id=command.selected_group_id,
        )
        self._require_unique_enrollment(
            unit_of_work,
            session_id=session.session_id,
            invitation=redeemed_invitation,
            user_id=command.user_id,
            alias=command.alias,
        )

        try:
            participant = Participant.enroll(
                participant_id=participant_id,
                session_id=session.session_id,
                configuration=configuration,
                group=group,
                invitation=redeemed_invitation,
                user_id=command.user_id,
                alias=command.alias,
                actor_id=participant_id,
                at=occurred_at,
            )
        except ParticipationRuleViolation as error:
            raise _RejectEnrollment("invalid_enrollment") from error

        issued_token = generate_token()
        access_grant = ParticipantAccessGrant(
            access_grant_id=self._id_factory(),
            participant_id=participant.participant_id,
            token_digest=issued_token.token_digest,
            issued_at=occurred_at,
            expires_at=occurred_at + self._access_grant_ttl,
        )
        return _Admission(
            session=session,
            configuration=configuration,
            group=group,
            participant=participant,
            invitation=redeemed_invitation,
            access_grant=access_grant,
            plaintext_access_token=issued_token.plaintext,
            access_code_id=(
                access_code_result.access_code_id
                if access_code_result is not None
                else None
            ),
        )

    def _load_invitation(
        self,
        unit_of_work: EnrollmentUnitOfWork,
        *,
        command: EnrollParticipantCommand,
    ) -> tuple[SessionInvitation | None, str | None]:
        if command.invitation_token is None:
            return None, None
        try:
            token_digest = digest_token(command.invitation_token)
        except TokenError as error:
            raise _RejectEnrollment("invalid_credentials") from error
        invitation = unit_of_work.invitations.get_by_token_digest_for_update(
            token_digest
        )
        if invitation is None or invitation.session_id != command.session_id:
            raise _RejectEnrollment("invalid_credentials")
        return invitation, token_digest

    @staticmethod
    def _validate_enrollment_mode(
        session: Session,
        invitation: SessionInvitation | None,
    ) -> None:
        if (
            session.enrollment_mode is EnrollmentMode.INVITATION_ONLY
            and invitation is None
        ):
            raise _RejectEnrollment("invalid_credentials")

    @staticmethod
    def _verify_access_code(
        unit_of_work: EnrollmentUnitOfWork,
        *,
        session: Session,
        invitation: SessionInvitation | None,
        command: EnrollParticipantCommand,
        occurred_at: datetime,
    ) -> AccessCodeVerificationResult | None:
        if session.access_code_mode is AccessCodeMode.NONE:
            return None
        if command.access_code is None:
            raise _RejectEnrollment("invalid_credentials")
        if (
            session.access_code_mode is AccessCodeMode.PER_INVITATION_CODE
            and invitation is None
        ):
            raise _RejectEnrollment("invalid_credentials")

        verification = unit_of_work.access_codes.verify_for_enrollment(
            session_id=session.session_id,
            invitation_id=(
                invitation.invitation_id
                if session.access_code_mode
                is AccessCodeMode.PER_INVITATION_CODE
                and invitation is not None
                else None
            ),
            plaintext_code=command.access_code,
            at=occurred_at,
        )
        if not verification.accepted:
            raise _RejectEnrollment("invalid_credentials")
        return verification

    @staticmethod
    def _redeem_invitation(
        invitation: SessionInvitation | None,
        *,
        participant_id: str,
        invitation_digest: str | None,
        command: EnrollParticipantCommand,
        occurred_at: datetime,
    ) -> SessionInvitation | None:
        if invitation is None:
            return None
        if invitation_digest is None:
            raise AssertionError("Loaded invitation is missing its digest.")
        try:
            return invitation.redeem(
                participant_id=participant_id,
                presented_token_digest=invitation_digest,
                presented_identity_lookup_hash=(
                    command.identity_lookup_hash
                ),
                at=occurred_at,
            )
        except ParticipationRuleViolation as error:
            raise _RejectEnrollment("invalid_credentials") from error

    @staticmethod
    def _require_unique_enrollment(
        unit_of_work: EnrollmentUnitOfWork,
        *,
        session_id: str,
        invitation: SessionInvitation | None,
        user_id: str | None,
        alias: str | None,
    ) -> None:
        if invitation is not None and unit_of_work.participants.get_by_invitation_id(
            invitation.invitation_id
        ) is not None:
            raise _RejectEnrollment("already_enrolled")
        if user_id is not None and (
            unit_of_work.participants.get_by_session_and_user_id(
                session_id,
                user_id,
            )
            is not None
        ):
            raise _RejectEnrollment("already_enrolled")
        if alias is not None and (
            unit_of_work.participants.get_by_session_and_alias(
                session_id,
                alias,
            )
            is not None
        ):
            raise _RejectEnrollment("alias_unavailable")

    def _persist_admission(
        self,
        unit_of_work: EnrollmentUnitOfWork,
        *,
        admission: _Admission,
        command: EnrollParticipantCommand,
        occurred_at: datetime,
    ) -> None:
        unit_of_work.participants.add(admission.participant)
        if admission.invitation is not None:
            unit_of_work.invitations.save(admission.invitation)
        unit_of_work.access_grants.add(admission.access_grant)
        if admission.access_code_id is not None:
            unit_of_work.access_codes.record_successful_use(
                access_code_id=admission.access_code_id,
                at=occurred_at,
            )
        unit_of_work.access_attempts.add(
            self._access_attempt(
                session_id=admission.session.session_id,
                command=command,
                occurred_at=occurred_at,
                outcome=AccessAttemptOutcome.ACCEPTED,
                reason_code="accepted",
                invitation_id=(
                    admission.invitation.invitation_id
                    if admission.invitation is not None
                    else None
                ),
                access_code_id=admission.access_code_id,
            )
        )
        unit_of_work.audit_events.add(
            _build_enrollment_event(
                admission,
                command=command,
                occurred_at=occurred_at,
                event_id=self._id_factory(),
            )
        )

    def _access_attempt(
        self,
        *,
        session_id: str,
        command: EnrollParticipantCommand,
        occurred_at: datetime,
        outcome: AccessAttemptOutcome,
        reason_code: str,
        invitation_id: str | None = None,
        access_code_id: str | None = None,
    ) -> AccessAttemptRecord:
        return AccessAttemptRecord(
            access_attempt_id=self._id_factory(),
            session_id=session_id,
            invitation_id=invitation_id,
            access_code_id=access_code_id,
            attempted_at=occurred_at,
            outcome=outcome,
            reason_code=reason_code,
            rate_limit_key_hash=command.rate_limit_key_hash,
            network_metadata_json=_safe_network_metadata(
                command.network_metadata_json
            ),
        )


def _resolve_group(
    session: Session,
    *,
    configuration: SessionConfigurationVersion,
    invitation: SessionInvitation | None,
    selected_group_id: str | None,
) -> SessionStakeholderGroup:
    assigned_group_id = (
        invitation.assigned_group_id
        if invitation is not None
        else None
    )
    if assigned_group_id is not None:
        if (
            selected_group_id is not None
            and selected_group_id != assigned_group_id
        ):
            raise _RejectEnrollment("invalid_group_selection")
        group_id = assigned_group_id
    elif session.stakeholder_selection_mode is StakeholderSelectionMode.SELF_SELECT:
        if selected_group_id is None:
            raise _RejectEnrollment("group_selection_required")
        group_id = selected_group_id
    elif (
        session.stakeholder_selection_mode
        is StakeholderSelectionMode.INVITATION_ASSIGNED
    ):
        raise _RejectEnrollment("invalid_group_selection")
    else:
        # Participant-supplied selections are never trusted as moderator
        # assignments. A moderator-assigned enrollment needs a preassigned
        # invitation (handled above) or a separate privileged workflow.
        raise _RejectEnrollment("group_assignment_required")

    group = next(
        (
            candidate
            for candidate in configuration.stakeholder_groups
            if candidate.session_stakeholder_group_id == group_id
        ),
        None,
    )
    if group is None or not group.is_active:
        raise _RejectEnrollment("invalid_group_selection")
    return group


def _safe_network_metadata(metadata: JsonObject) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key in _SAFE_NETWORK_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, (bool, int)):
            safe[key] = value
        elif isinstance(value, str) and len(value) <= 200:
            safe[key] = value
    return safe


def _build_enrollment_event(
    admission: _Admission,
    *,
    command: EnrollParticipantCommand,
    occurred_at: datetime,
    event_id: str,
) -> AuditEvent:
    participant = admission.participant
    after_json = {
        "schema_version": 1,
        "participant_id": participant.participant_id,
        "session_id": participant.session_id,
        "configuration_version_id": participant.configuration_version_id,
        "session_stakeholder_group_id": (
            participant.session_stakeholder_group_id
        ),
        "invitation_id": participant.invitation_id,
        "access_status": participant.access_status.value,
        "enrolled_at": participant.enrolled_at,
        "access_grant_id": admission.access_grant.access_grant_id,
    }
    source_metadata = {
        "schema_version": 1,
        "use_case": "enroll_participant",
        "discoverability": admission.session.discoverability.value,
        "enrollment_mode": admission.session.enrollment_mode.value,
        "access_code_mode": admission.session.access_code_mode.value,
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": participant.session_id,
        "actor_type": ActorType.PARTICIPANT.value,
        "actor_id": participant.participant_id,
        "action": AuditAction.CREATED.value,
        "entity_type": "participant",
        "entity_id": participant.participant_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        session_id=participant.session_id,
        actor_type=ActorType.PARTICIPANT,
        actor_id=participant.participant_id,
        action=AuditAction.CREATED,
        entity_type="participant",
        entity_id=participant.participant_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )


def _result(admission: _Admission) -> EnrollParticipantResult:
    return EnrollParticipantResult(
        participant_id=admission.participant.participant_id,
        session_id=admission.participant.session_id,
        configuration_version_id=(
            admission.participant.configuration_version_id
        ),
        session_stakeholder_group_id=(
            admission.participant.session_stakeholder_group_id
        ),
        access_grant_id=admission.access_grant.access_grant_id,
        access_token=admission.plaintext_access_token,
        access_token_expires_at=admission.access_grant.expires_at,
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef"
        for character in value
    )
