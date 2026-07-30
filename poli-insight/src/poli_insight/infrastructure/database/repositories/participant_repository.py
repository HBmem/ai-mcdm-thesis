"""SQLAlchemy repositories for participation and credential aggregates.

Participant records, invitations, and access grants have independent
lifecycle boundaries, so each application port has a dedicated adapter. The
caller owns the transaction: these repositories may flush lifecycle updates,
but they never commit or roll back.

Credential lookups accept persistence-safe digests only. Plaintext invitation
and access tokens must remain in the application and authentication layers.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from poli_insight.domain.participation import (
    Participant,
    ParticipantAccessGrant,
    SessionInvitation,
)
from poli_insight.infrastructure.database.mappers.participation import (
    apply_participant_access_grant_state,
    apply_participant_state,
    apply_session_invitation_state,
    participant_access_grant_to_domain,
    participant_access_grant_to_row,
    participant_to_domain,
    participant_to_row,
    session_invitation_to_domain,
    session_invitation_to_row,
)
from poli_insight.infrastructure.database.models.participation import (
    ParticipantAccessGrantRow,
    ParticipantRow,
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
