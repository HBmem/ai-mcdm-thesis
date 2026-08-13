"""SQLAlchemy repositories for participation and credential aggregates.

Participant records, invitations, and access grants have independent
lifecycle boundaries, so each application port has a dedicated adapter. The
caller owns the transaction: these repositories may flush lifecycle updates,
but they never commit or roll back.

Credential lookups accept persistence-safe digests only. Plaintext invitation
and access tokens must remain in the application and authentication layers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from poli_insight.application.ports.participation_access import (
    AccessAttemptRecord,
    AccessCodeVerificationResult,
)
from poli_insight.domain.enum import InvitationStatus
from poli_insight.domain.participation import (
    Participant,
    ParticipantAccessGrant,
    ParticipantConsent,
    ParticipantIdentity,
    SessionInvitation,
)
from poli_insight.infrastructure.auth.access_codes import (
    hash_access_code,
    verify_access_code,
)
from poli_insight.infrastructure.database.mappers.participation import (
    apply_participant_access_grant_state,
    apply_participant_identity_state,
    apply_participant_state,
    apply_session_invitation_state,
    participant_access_grant_to_domain,
    participant_access_grant_to_row,
    participant_identity_to_domain,
    participant_identity_to_row,
    participant_to_domain,
    participant_to_row,
    session_invitation_to_domain,
    session_invitation_to_row,
)
from poli_insight.infrastructure.database.models.participation import (
    ParticipantAccessAttemptRow,
    ParticipantAccessGrantRow,
    ParticipantConsentRow,
    ParticipantIdentityRow,
    ParticipantRow,
    SessionAccessCodeRow,
    SessionInvitationRow,
)


class ParticipantNotFoundError(LookupError):
    """Raised when a participant requested for persistence does not exist."""


class SessionInvitationNotFoundError(LookupError):
    """Raised when an invitation requested for persistence does not exist."""


class ParticipantAccessGrantNotFoundError(LookupError):
    """Raised when an access grant requested for persistence does not exist."""


def _uses_postgresql(database_session: DatabaseSession) -> bool:
    """Return whether row-level ``FOR UPDATE`` locking is available."""

    bind = database_session.get_bind()
    return bind.dialect.name == "postgresql"


class SqlAlchemyParticipantRepository:
    """Persist analytical participant state without loading optional PII."""

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, participant: Participant) -> None:
        """Add a newly enrolled participant to the current transaction."""

        self._database_session.add(participant_to_row(participant))
        # Enrollment creates grants and may redeem an invitation in the same
        # transaction. Flush the participant identity first so dependent rows
        # satisfy immediate SQLite foreign-key checks.
        self._database_session.flush()

    def get(self, participant_id: str) -> Participant | None:
        """Load a participant without taking a database row lock."""

        row = self._load_by_id(participant_id, for_update=False)
        return None if row is None else participant_to_domain(row)

    def get_for_update(self, participant_id: str) -> Participant | None:
        """Load and lock a participant for a lifecycle transition."""

        row = self._load_by_id(participant_id, for_update=True)
        return None if row is None else participant_to_domain(row)

    def save(self, participant: Participant) -> None:
        """Persist participant lifecycle state without committing."""

        row = self._load_by_id(participant.participant_id, for_update=True)
        if row is None:
            raise ParticipantNotFoundError(
                f"Participant {participant.participant_id!r} does not exist."
            )

        apply_participant_state(row, participant)
        self._database_session.flush()

    def get_by_session_and_user_id(
        self,
        session_id: str,
        user_id: str,
    ) -> Participant | None:
        """Find the participant bound to a session-scoped user account."""

        statement = select(ParticipantRow).where(
            ParticipantRow.session_id == session_id,
            ParticipantRow.user_id == user_id,
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else participant_to_domain(row)

    def get_by_session_and_alias(
        self,
        session_id: str,
        alias: str,
    ) -> Participant | None:
        """Find a participant by a session-scoped analytical alias."""

        statement = select(ParticipantRow).where(
            ParticipantRow.session_id == session_id,
            ParticipantRow.alias == alias,
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else participant_to_domain(row)

    def get_by_invitation_id(
        self,
        invitation_id: str,
    ) -> Participant | None:
        """Find the participant enrolled through a one-time invitation."""

        statement = select(ParticipantRow).where(
            ParticipantRow.invitation_id == invitation_id
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else participant_to_domain(row)

    def get_many(self, participant_ids: tuple[str, ...]) -> tuple[Participant, ...]:
        if not participant_ids:
            return ()
        rows = self._database_session.scalars(
            select(ParticipantRow).where(
                ParticipantRow.participant_id.in_(participant_ids)
            )
        ).all()
        return tuple(participant_to_domain(row) for row in rows)

    def _load_by_id(
        self,
        participant_id: str,
        *,
        for_update: bool,
    ) -> ParticipantRow | None:
        statement = select(ParticipantRow).where(
            ParticipantRow.participant_id == participant_id
        )
        if for_update and _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()

class SqlAlchemyParticipantIdentityRepository:
    """Persist ciphertext separately from analytical participant queries."""

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, identity: ParticipantIdentity) -> None:
        self._database_session.add(participant_identity_to_row(identity))

    def get(self, participant_id: str) -> ParticipantIdentity | None:
        row = self._database_session.get(ParticipantIdentityRow, participant_id)
        return None if row is None else participant_identity_to_domain(row)

    def save(self, identity: ParticipantIdentity) -> None:
        row = self._database_session.get(ParticipantIdentityRow, identity.participant_id)
        if row is None:
            raise ParticipantNotFoundError("Participant identity does not exist.")
        apply_participant_identity_state(row, identity)
        self._database_session.flush()

    def list_expired(
        self, *, at: datetime, limit: int
    ) -> tuple[ParticipantIdentity, ...]:
        statement = (
            select(ParticipantIdentityRow)
            .where(
                ParticipantIdentityRow.redacted_at.is_(None),
                ParticipantIdentityRow.retention_until <= at,
            )
            .order_by(ParticipantIdentityRow.retention_until)
            .limit(limit)
        )
        if _uses_postgresql(self._database_session):
            statement = statement.with_for_update(skip_locked=True)
        return tuple(
            participant_identity_to_domain(row)
            for row in self._database_session.scalars(statement)
        )


class SqlAlchemySessionInvitationRepository:
    """Persist one-time invitation lifecycle state using token digests."""

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, invitation: SessionInvitation) -> None:
        """Add a new digest-only invitation to the current transaction."""

        self._database_session.add(session_invitation_to_row(invitation))

    def get(self, invitation_id: str) -> SessionInvitation | None:
        """Load an invitation without taking a database row lock."""

        row = self._load_by_id(invitation_id, for_update=False)
        return None if row is None else session_invitation_to_domain(row)

    def get_for_update(
        self,
        invitation_id: str,
    ) -> SessionInvitation | None:
        """Load and lock an invitation for a lifecycle transition."""

        row = self._load_by_id(invitation_id, for_update=True)
        return None if row is None else session_invitation_to_domain(row)

    def get_by_token_digest(
        self,
        token_digest: str,
    ) -> SessionInvitation | None:
        """Look up an invitation by an already-computed token digest."""

        row = self._load_by_token_digest(token_digest, for_update=False)
        return None if row is None else session_invitation_to_domain(row)

    def get_by_token_digest_for_update(
        self,
        token_digest: str,
    ) -> SessionInvitation | None:
        """Look up and lock a digest to serialize one-time redemption."""

        row = self._load_by_token_digest(token_digest, for_update=True)
        return None if row is None else session_invitation_to_domain(row)

    def save(self, invitation: SessionInvitation) -> None:
        """Persist a valid invitation lifecycle change without committing."""

        row = self._load_by_id(invitation.invitation_id, for_update=True)
        if row is None:
            raise SessionInvitationNotFoundError(
                f"Invitation {invitation.invitation_id!r} does not exist."
            )

        apply_session_invitation_state(row, invitation)
        self._database_session.flush()

    def list_due_for_expiration(
        self,
        session_id: str,
        at: datetime,
    ) -> tuple[SessionInvitation, ...]:
        statement = (
            select(SessionInvitationRow)
            .where(
                SessionInvitationRow.session_id == session_id,
                SessionInvitationRow.status.in_(
                    (
                        InvitationStatus.PENDING.value,
                        InvitationStatus.SENT.value,
                        InvitationStatus.DELIVERY_FAILED.value,
                    )
                ),
                SessionInvitationRow.expires_at <= at,
            )
            .order_by(SessionInvitationRow.expires_at, SessionInvitationRow.invitation_id)
        )
        if _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        return tuple(
            session_invitation_to_domain(row)
            for row in self._database_session.scalars(statement)
        )

    def _load_by_id(
        self,
        invitation_id: str,
        *,
        for_update: bool,
    ) -> SessionInvitationRow | None:
        statement = select(SessionInvitationRow).where(
            SessionInvitationRow.invitation_id == invitation_id
        )
        if for_update and _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()

    def _load_by_token_digest(
        self,
        token_digest: str,
        *,
        for_update: bool,
    ) -> SessionInvitationRow | None:
        statement = select(SessionInvitationRow).where(
            SessionInvitationRow.token_digest == token_digest
        )
        if for_update and _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()


class SqlAlchemyParticipantAccessGrantRepository:
    """Persist revocable participant credentials using token digests."""

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, access_grant: ParticipantAccessGrant) -> None:
        """Add a new digest-only access grant to the current transaction."""

        self._database_session.add(
            participant_access_grant_to_row(access_grant)
        )
        # Replacement rows are referenced immediately by the revoked
        # predecessor. Materialize the successor first while retaining the
        # caller-owned transaction boundary.
        self._database_session.flush()

    def get(
        self,
        access_grant_id: str,
    ) -> ParticipantAccessGrant | None:
        """Load an access grant without taking a database row lock."""

        row = self._load_by_id(access_grant_id, for_update=False)
        return (
            None
            if row is None
            else participant_access_grant_to_domain(row)
        )

    def get_current_for_participant_for_update(
        self,
        participant_id: str,
        *,
        at: datetime,
    ) -> ParticipantAccessGrant | None:
        """Load and lock the current unrevoked, unexpired credential."""

        statement = (
            select(ParticipantAccessGrantRow)
            .where(
                ParticipantAccessGrantRow.participant_id == participant_id,
                ParticipantAccessGrantRow.revoked_at.is_(None),
                ParticipantAccessGrantRow.issued_at <= at,
                ParticipantAccessGrantRow.expires_at > at,
            )
            .order_by(
                ParticipantAccessGrantRow.issued_at.desc(),
                ParticipantAccessGrantRow.access_grant_id.desc(),
            )
            .limit(2)
        )
        if _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        rows = tuple(self._database_session.scalars(statement))
        if len(rows) > 1:
            raise ValueError(
                "Participant has multiple active access grants; replacement "
                "cannot proceed safely."
            )
        return (
            None
            if not rows
            else participant_access_grant_to_domain(rows[0])
        )

    def get_for_update(
        self,
        access_grant_id: str,
    ) -> ParticipantAccessGrant | None:
        """Load and lock a grant for use, revocation, or replacement."""

        row = self._load_by_id(access_grant_id, for_update=True)
        return (
            None
            if row is None
            else participant_access_grant_to_domain(row)
        )

    def get_by_token_digest(
        self,
        token_digest: str,
    ) -> ParticipantAccessGrant | None:
        """Look up an access grant by an already-computed token digest."""

        row = self._load_by_token_digest(token_digest, for_update=False)
        return (
            None
            if row is None
            else participant_access_grant_to_domain(row)
        )

    def get_by_token_digest_for_update(
        self,
        token_digest: str,
    ) -> ParticipantAccessGrant | None:
        """Look up and lock a digest before recording use or rotation."""

        row = self._load_by_token_digest(token_digest, for_update=True)
        return (
            None
            if row is None
            else participant_access_grant_to_domain(row)
        )

    def save(self, access_grant: ParticipantAccessGrant) -> None:
        """Persist valid grant lifecycle state without committing."""

        row = self._load_by_id(access_grant.access_grant_id, for_update=True)
        if row is None:
            raise ParticipantAccessGrantNotFoundError(
                "Participant access grant "
                f"{access_grant.access_grant_id!r} does not exist."
            )

        apply_participant_access_grant_state(row, access_grant)
        self._database_session.flush()

    def _load_by_id(
        self,
        access_grant_id: str,
        *,
        for_update: bool,
    ) -> ParticipantAccessGrantRow | None:
        statement = select(ParticipantAccessGrantRow).where(
            ParticipantAccessGrantRow.access_grant_id == access_grant_id
        )
        if for_update and _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()

    def _load_by_token_digest(
        self,
        token_digest: str,
        *,
        for_update: bool,
    ) -> ParticipantAccessGrantRow | None:
        statement = select(ParticipantAccessGrantRow).where(
            ParticipantAccessGrantRow.token_digest == token_digest
        )
        if for_update and _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()


class SqlAlchemyEnrollmentAccessCodeRepository:
    """Verify and account for slow-hashed session access codes."""

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add_shared_code(
        self,
        *,
        access_code_id: str,
        session_id: str,
        plaintext_code: str,
        created_at: datetime,
        created_by: str,
    ) -> None:
        self._database_session.add(
            SessionAccessCodeRow(
                access_code_id=access_code_id,
                session_id=session_id,
                invitation_id=None,
                code_hash=hash_access_code(plaintext_code),
                active=True,
                use_count=0,
                max_uses=None,
                expires_at=None,
                created_at=created_at,
                created_by=created_by,
                last_used_at=None,
            )
        )

    def add_invitation_code(
        self,
        *,
        access_code_id: str,
        session_id: str,
        invitation_id: str,
        plaintext_code: str,
        expires_at: datetime,
        created_at: datetime,
        created_by: str,
    ) -> None:
        self._database_session.add(
            SessionAccessCodeRow(
                access_code_id=access_code_id,
                session_id=session_id,
                invitation_id=invitation_id,
                code_hash=hash_access_code(plaintext_code),
                active=True,
                use_count=0,
                max_uses=1,
                expires_at=expires_at,
                created_at=created_at,
                created_by=created_by,
                last_used_at=None,
            )
        )

    def verify_for_enrollment(
        self,
        *,
        session_id: str,
        invitation_id: str | None,
        plaintext_code: str,
        at: datetime,
    ) -> AccessCodeVerificationResult:
        statement = select(SessionAccessCodeRow).where(
            SessionAccessCodeRow.session_id == session_id,
            SessionAccessCodeRow.invitation_id == invitation_id,
        )
        if _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        row = self._database_session.execute(statement).scalar_one_or_none()
        eligible = (
            row is not None
            and row.active
            and (row.expires_at is None or at < row.expires_at)
            and (row.max_uses is None or row.use_count < row.max_uses)
        )
        accepted = bool(
            eligible
            and row is not None
            and verify_access_code(plaintext_code, row.code_hash)
        )
        return AccessCodeVerificationResult(
            accepted=accepted,
            reason_code="accepted" if accepted else "invalid_credentials",
            access_code_id=str(row.access_code_id) if accepted and row else None,
        )

    def record_successful_use(
        self, *, access_code_id: str, at: datetime
    ) -> None:
        statement = select(SessionAccessCodeRow).where(
            SessionAccessCodeRow.access_code_id == access_code_id
        )
        if _uses_postgresql(self._database_session):
            statement = statement.with_for_update()
        row = self._database_session.execute(statement).scalar_one()
        row.use_count += 1
        row.last_used_at = at


class SqlAlchemyAccessAttemptRepository:
    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, attempt: AccessAttemptRecord) -> None:
        self._database_session.add(
            ParticipantAccessAttemptRow(
                access_attempt_id=attempt.access_attempt_id,
                session_id=attempt.session_id,
                invitation_id=attempt.invitation_id,
                access_code_id=attempt.access_code_id,
                attempted_at=attempt.attempted_at,
                outcome=attempt.outcome.value,
                reason_code=attempt.reason_code,
                rate_limit_key_hash=attempt.rate_limit_key_hash,
                network_metadata_json=dict(attempt.network_metadata_json),
            )
        )


class SqlAlchemyParticipantConsentRepository:
    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, consent: ParticipantConsent) -> None:
        self._database_session.add(
            ParticipantConsentRow(
                participant_consent_id=consent.participant_consent_id,
                participant_id=consent.participant_id,
                session_id=consent.session_id,
                configuration_version_id=consent.configuration_version_id,
                consent_version=consent.consent_version,
                statement_hash=consent.statement_hash,
                accepted_at=consent.accepted_at,
            )
        )

    def get_for_participant(
        self,
        participant_id: str,
        configuration_version_id: str,
        consent_version: str,
    ) -> ParticipantConsent | None:
        row = self._database_session.execute(
            select(ParticipantConsentRow).where(
                ParticipantConsentRow.participant_id == participant_id,
                ParticipantConsentRow.configuration_version_id
                == configuration_version_id,
                ParticipantConsentRow.consent_version == consent_version,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return ParticipantConsent(
            participant_consent_id=str(row.participant_consent_id),
            participant_id=str(row.participant_id),
            session_id=str(row.session_id),
            configuration_version_id=str(row.configuration_version_id),
            consent_version=row.consent_version,
            statement_hash=row.statement_hash,
            accepted_at=row.accepted_at,
        )
