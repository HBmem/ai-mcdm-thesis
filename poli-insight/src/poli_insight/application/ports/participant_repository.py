"""Persistence ports for participation and credential aggregates.

Authentication credentials cross this boundary only as digests. Plaintext
invitation and access-grant tokens belong in the application/security layer
and must never be passed to a repository implementation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from poli_insight.domain.participation import (
    Participant,
    ParticipantAccessGrant,
    ParticipantIdentity,
    SessionInvitation,
)


class ParticipantRepository(Protocol):
    """Persistence operations for analytical participant records."""

    def add(self, participant: Participant) -> None:
        """Add a newly enrolled participant to the current transaction."""
        ...

    def get(self, participant_id: str) -> Participant | None:
        """Load a participant by its application-generated identity."""
        ...

    def get_for_update(self, participant_id: str) -> Participant | None:
        """Load and lock a participant for a lifecycle-changing operation."""
        ...

    def save(self, participant: Participant) -> None:
        """Persist replacement participant lifecycle state."""
        ...

    def get_by_session_and_user_id(
        self,
        session_id: str,
        user_id: str,
    ) -> Participant | None:
        """Find the existing enrollment for a session-scoped user."""
        ...

    def get_by_session_and_alias(
        self,
        session_id: str,
        alias: str,
    ) -> Participant | None:
        """Find a session-scoped alias when alias uniqueness is enabled."""
        ...

    def get_by_invitation_id(
        self,
        invitation_id: str,
    ) -> Participant | None:
        """Find the participant created from a one-time invitation."""
        ...

    def get_many(self, participant_ids: tuple[str, ...]) -> tuple[Participant, ...]:
        """Bulk load analytical participants without optional identity."""
        ...


class ParticipantIdentityRepository(Protocol):
    """Persistence for encrypted optional PII and retention redaction."""

    def add(self, identity: ParticipantIdentity) -> None: ...

    def get(self, participant_id: str) -> ParticipantIdentity | None: ...

    def save(self, identity: ParticipantIdentity) -> None: ...

    def list_expired(
        self, *, at: datetime, limit: int
    ) -> tuple[ParticipantIdentity, ...]: ...


class SessionInvitationRepository(Protocol):
    """Persistence operations for one-time session invitations."""

    def add(self, invitation: SessionInvitation) -> None:
        """Add a newly issued invitation to the current transaction."""
        ...

    def get(self, invitation_id: str) -> SessionInvitation | None:
        """Load an invitation by identity without taking a write lock."""
        ...

    def get_for_update(
        self,
        invitation_id: str,
    ) -> SessionInvitation | None:
        """Load and lock an invitation for a lifecycle transition."""
        ...

    def get_by_token_digest(
        self,
        token_digest: str,
    ) -> SessionInvitation | None:
        """Look up an invitation using an already-computed token digest."""
        ...

    def get_by_token_digest_for_update(
        self,
        token_digest: str,
    ) -> SessionInvitation | None:
        """Look up and lock an invitation digest for atomic redemption."""
        ...

    def save(self, invitation: SessionInvitation) -> None:
        """Persist replacement invitation lifecycle state."""
        ...

    def list_due_for_expiration(
        self,
        session_id: str,
        at: datetime,
    ) -> tuple[SessionInvitation, ...]:
        """Load unexpired terminal candidates whose deadline has passed."""
        ...


class ParticipantAccessGrantRepository(Protocol):
    """Persistence operations for revocable participant credentials."""

    def add(self, access_grant: ParticipantAccessGrant) -> None:
        """Add a newly issued access grant to the current transaction."""
        ...

    def get(
        self,
        access_grant_id: str,
    ) -> ParticipantAccessGrant | None:
        """Load an access grant by identity without taking a write lock."""
        ...

    def get_for_update(
        self,
        access_grant_id: str,
    ) -> ParticipantAccessGrant | None:
        """Load and lock an access grant for rotation or revocation."""
        ...

    def get_by_token_digest(
        self,
        token_digest: str,
    ) -> ParticipantAccessGrant | None:
        """Look up an access grant using an already-computed token digest."""
        ...

    def get_by_token_digest_for_update(
        self,
        token_digest: str,
    ) -> ParticipantAccessGrant | None:
        """Look up and lock a digest before recording use or rotation."""
        ...

    def get_current_for_participant_for_update(
        self,
        participant_id: str,
        *,
        at: datetime,
    ) -> ParticipantAccessGrant | None:
        """Load and lock the participant's sole currently active grant."""
        ...

    def save(self, access_grant: ParticipantAccessGrant) -> None:
        """Persist replacement access-grant lifecycle state."""
        ...
