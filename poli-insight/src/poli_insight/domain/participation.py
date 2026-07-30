"""Invitation, participant, identity, and access-grant domain models.

Participation records contain analytical identity only: session,
configuration, stakeholder group, and an optional alias. Personally identifying
data belongs to :class:`ParticipantIdentity`, which can be retained and
redacted independently.

All lifecycle objects are immutable. Methods return replacement values so an
application service can persist the state change and its audit event in one
transaction.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Self

from poli_insight.domain.enum import (
    InvitationStatus,
    ParticipantAccessStatus,
    ParticipantProgressStatus,
)
from poli_insight.domain.session import (
    SessionConfigurationVersion,
    SessionStakeholderGroup,
)


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ParticipationRuleViolation(ValueError):
    """Raised when an operation violates a participation business rule."""


class GroupChangeCutoff(StrEnum):
    """Participant milestone after which stakeholder group changes stop."""

    ENROLLMENT = "enrollment"
    JOINED = "joined"
    STARTED = "started"
    SUBMITTED = "submitted"


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ParticipationRuleViolation(f"{field_name} cannot be empty.")
    if value != value.strip():
        raise ParticipationRuleViolation(
            f"{field_name} cannot contain leading or trailing whitespace."
        )


def _require_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_actor(actor_id: str) -> None:
    _require_text(actor_id, "Actor ID")


def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and (
        value.tzinfo is None or value.utcoffset() is None
    ):
        raise ParticipationRuleViolation(
            f"{field_name} must include timezone information."
        )


def _require_sha256(value: str, field_name: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ParticipationRuleViolation(
            f"{field_name} must be a lowercase hexadecimal SHA-256 digest."
        )


def _require_nonnegative_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ParticipationRuleViolation(
            f"{field_name} must be a nonnegative integer."
        )


def _require_not_before(
    value: datetime,
    earliest: datetime,
    field_name: str,
) -> None:
    if value < earliest:
        raise ParticipationRuleViolation(
            f"{field_name} cannot precede {earliest.isoformat()}."
        )


@dataclass(frozen=True, slots=True)
class SessionInvitation:
    """A one-time invitation pinned to a session configuration."""

    invitation_id: str
    session_id: str
    configuration_version_id: str
    token_digest: str
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime
    created_by: str

    assigned_group_id: str | None = None
    token_hint: str | None = None
    identity_lookup_hash: str | None = None
    identity_ciphertext: bytes | None = None
    max_redemptions: int = 1
    sent_at: datetime | None = None
    send_count: int = 0
    redeemed_at: datetime | None = None
    redeemed_participant_id: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_schedule()
        self._validate_lifecycle_state()

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            InvitationStatus.REDEEMED,
            InvitationStatus.EXPIRED,
            InvitationStatus.REVOKED,
        }

    def status_at(self, *, at: datetime) -> InvitationStatus:
        """Return the effective status without silently mutating expiration."""

        _require_aware_datetime(at, "Invitation status time")
        if not self.is_terminal and at >= self.expires_at:
            return InvitationStatus.EXPIRED
        return self.status

    def mark_sent(self, *, at: datetime) -> Self:
        """Record a successful delivery or redelivery attempt."""

        self._require_sendable(at)
        return replace(
            self,
            status=InvitationStatus.SENT,
            sent_at=at,
            send_count=self.send_count + 1,
        )

    def mark_delivery_failed(self, *, at: datetime) -> Self:
        """Record a failed delivery attempt while retaining retryability."""

        self._require_sendable(at)
        return replace(
            self,
            status=InvitationStatus.DELIVERY_FAILED,
            sent_at=at,
            send_count=self.send_count + 1,
        )

    def expire(self, *, at: datetime) -> Self:
        """Materialize expiration after the configured deadline."""

        _require_aware_datetime(at, "Invitation expiration time")
        if self.is_terminal:
            raise ParticipationRuleViolation(
                f"A {self.status.value} invitation cannot expire."
            )
        if at < self.expires_at:
            raise ParticipationRuleViolation(
                "Invitation cannot expire before expires_at."
            )
        return replace(self, status=InvitationStatus.EXPIRED)

    def redeem(
        self,
        *,
        participant_id: str,
        presented_token_digest: str,
        at: datetime,
        presented_identity_lookup_hash: str | None = None,
    ) -> Self:
        """Redeem the invitation exactly once after binding checks pass."""

        _require_text(participant_id, "Participant ID")
        _require_sha256(
            presented_token_digest,
            "Presented invitation token digest",
        )
        _require_aware_datetime(at, "Invitation redemption time")
        if self.status is not InvitationStatus.SENT:
            raise ParticipationRuleViolation(
                "Only a sent invitation can be redeemed."
            )
        if at >= self.expires_at:
            raise ParticipationRuleViolation("Invitation has expired.")
        if self.sent_at is not None:
            _require_not_before(
                at,
                self.sent_at,
                "Invitation redemption time",
            )
        if not hmac.compare_digest(
            self.token_digest,
            presented_token_digest,
        ):
            raise ParticipationRuleViolation(
                "Presented invitation token digest does not match."
            )
        if self.identity_lookup_hash is not None:
            if presented_identity_lookup_hash is None:
                raise ParticipationRuleViolation(
                    "Invitation requires its bound identity."
                )
            _require_sha256(
                presented_identity_lookup_hash,
                "Presented identity lookup hash",
            )
            if not hmac.compare_digest(
                self.identity_lookup_hash,
                presented_identity_lookup_hash,
            ):
                raise ParticipationRuleViolation(
                    "Presented identity does not match the invitation binding."
                )
        return replace(
            self,
            status=InvitationStatus.REDEEMED,
            redeemed_at=at,
            redeemed_participant_id=participant_id,
        )

    def revoke(
        self,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> Self:
        """Revoke an unredeemed invitation with an auditable reason."""

        _require_actor(actor_id)
        _require_text(reason, "Invitation revocation reason")
        _require_aware_datetime(at, "Invitation revocation time")
        if self.is_terminal:
            raise ParticipationRuleViolation(
                f"A {self.status.value} invitation cannot be revoked."
            )
        _require_not_before(at, self.created_at, "Invitation revocation time")
        if self.sent_at is not None:
            _require_not_before(
                at,
                self.sent_at,
                "Invitation revocation time",
            )
        return replace(
            self,
            status=InvitationStatus.REVOKED,
            revoked_at=at,
            revoked_by=actor_id,
            revocation_reason=reason,
        )

    def validate_assignment(
        self,
        *,
        configuration: SessionConfigurationVersion,
        group: SessionStakeholderGroup,
    ) -> None:
        """Validate that invitation, configuration, and group share ownership."""

        if configuration.configuration_version_id != self.configuration_version_id:
            raise ParticipationRuleViolation(
                "Invitation references a different configuration version."
            )
        if configuration.session_id != self.session_id:
            raise ParticipationRuleViolation(
                "Invitation configuration belongs to a different session."
            )
        if group.configuration_version_id != self.configuration_version_id:
            raise ParticipationRuleViolation(
                "Invitation group belongs to a different configuration."
            )
        if (
            self.assigned_group_id is not None
            and group.session_stakeholder_group_id != self.assigned_group_id
        ):
            raise ParticipationRuleViolation(
                "Participant group does not match the invitation assignment."
            )

    def _require_sendable(self, at: datetime) -> None:
        _require_aware_datetime(at, "Invitation send time")
        if self.status not in {
            InvitationStatus.PENDING,
            InvitationStatus.DELIVERY_FAILED,
            InvitationStatus.SENT,
        }:
            raise ParticipationRuleViolation(
                f"A {self.status.value} invitation cannot be sent."
            )
        _require_not_before(at, self.created_at, "Invitation send time")
        if self.sent_at is not None:
            _require_not_before(at, self.sent_at, "Invitation send time")
        if at >= self.expires_at:
            raise ParticipationRuleViolation(
                "An expired invitation cannot be sent."
            )

    def _validate_identity(self) -> None:
        for field_name, value in (
            ("Invitation ID", self.invitation_id),
            ("Invitation session ID", self.session_id),
            ("Invitation configuration ID", self.configuration_version_id),
            ("Invitation creator", self.created_by),
        ):
            _require_text(value, field_name)
        for field_name, value in (
            ("Assigned group ID", self.assigned_group_id),
            ("Invitation token hint", self.token_hint),
        ):
            _require_optional_text(value, field_name)
        _require_sha256(self.token_digest, "Invitation token digest")
        if self.identity_lookup_hash is not None:
            _require_sha256(
                self.identity_lookup_hash,
                "Invitation identity lookup hash",
            )
        if self.identity_ciphertext == b"":
            raise ParticipationRuleViolation(
                "Invitation identity ciphertext cannot be empty."
            )
        if (
            self.identity_ciphertext is None
            and self.identity_lookup_hash is not None
        ):
            raise ParticipationRuleViolation(
                "Invitation identity hash requires encrypted identity data."
            )
        _require_nonnegative_integer(
            self.max_redemptions,
            "Invitation maximum redemptions",
        )
        if self.max_redemptions != 1:
            raise ParticipationRuleViolation(
                "Invitations are one-time and must allow exactly one redemption."
            )
        _require_nonnegative_integer(self.send_count, "Invitation send count")

    def _validate_schedule(self) -> None:
        for field_name, value in (
            ("Invitation created_at", self.created_at),
            ("Invitation expires_at", self.expires_at),
            ("Invitation sent_at", self.sent_at),
            ("Invitation redeemed_at", self.redeemed_at),
            ("Invitation revoked_at", self.revoked_at),
        ):
            _require_aware_datetime(value, field_name)
        if self.expires_at <= self.created_at:
            raise ParticipationRuleViolation(
                "Invitation expires_at must be later than created_at."
            )
        for field_name, value in (
            ("sent_at", self.sent_at),
            ("redeemed_at", self.redeemed_at),
            ("revoked_at", self.revoked_at),
        ):
            if value is not None:
                _require_not_before(
                    value,
                    self.created_at,
                    f"Invitation {field_name}",
                )
        if self.redeemed_at is not None and self.redeemed_at >= self.expires_at:
            raise ParticipationRuleViolation(
                "Invitation redemption must precede expiration."
            )

    def _validate_lifecycle_state(self) -> None:
        redemption_present = (
            self.redeemed_at is not None
            or self.redeemed_participant_id is not None
        )
        revocation_present = any(
            value is not None
            for value in (
                self.revoked_at,
                self.revoked_by,
                self.revocation_reason,
            )
        )
        if (self.redeemed_at is None) != (
            self.redeemed_participant_id is None
        ):
            raise ParticipationRuleViolation(
                "Invitation redemption time and participant must be set together."
            )
        if self.status is InvitationStatus.REDEEMED:
            if not redemption_present or revocation_present:
                raise ParticipationRuleViolation(
                    "Redeemed invitation requires only redemption metadata."
                )
            _require_text(
                self.redeemed_participant_id or "",
                "Redeemed participant ID",
            )
        elif redemption_present:
            raise ParticipationRuleViolation(
                "Only a redeemed invitation may have redemption metadata."
            )

        if self.status is InvitationStatus.REVOKED:
            if not all(
                value is not None
                for value in (
                    self.revoked_at,
                    self.revoked_by,
                    self.revocation_reason,
                )
            ) or redemption_present:
                raise ParticipationRuleViolation(
                    "Revoked invitation requires complete revocation metadata."
                )
            _require_text(self.revoked_by or "", "Invitation revoker")
            _require_text(
                self.revocation_reason or "",
                "Invitation revocation reason",
            )
        elif revocation_present:
            raise ParticipationRuleViolation(
                "Only a revoked invitation may have revocation metadata."
            )

        send_required_statuses = {
            InvitationStatus.SENT,
            InvitationStatus.DELIVERY_FAILED,
            InvitationStatus.REDEEMED,
        }
        has_send_metadata = self.sent_at is not None or self.send_count != 0
        has_complete_send_metadata = (
            self.sent_at is not None and self.send_count >= 1
        )
        if self.status in send_required_statuses:
            if not has_complete_send_metadata:
                raise ParticipationRuleViolation(
                    "Sent invitation states require send metadata."
                )
        elif self.status is InvitationStatus.PENDING and has_send_metadata:
            raise ParticipationRuleViolation(
                "Unsent invitation states cannot contain send metadata."
            )
        elif has_send_metadata and not has_complete_send_metadata:
            raise ParticipationRuleViolation(
                "Invitation send metadata must be complete when retained."
            )


@dataclass(frozen=True, slots=True)
class Participant:
    """Analytical participant identity pinned to configuration and group."""

    participant_id: str
    session_id: str
    configuration_version_id: str
    session_stakeholder_group_id: str
    access_status: ParticipantAccessStatus
    enrolled_at: datetime
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

    user_id: str | None = None
    invitation_id: str | None = None
    alias: str | None = None
    joined_at: datetime | None = None
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    disabled_at: datetime | None = None
    disabled_by: str | None = None
    disable_reason: str | None = None
    withdrawn_at: datetime | None = None
    withdrawn_by: str | None = None
    withdrawal_reason: str | None = None

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_schedule()
        self._validate_access_state()

    @classmethod
    def enroll(
        cls,
        *,
        participant_id: str,
        session_id: str,
        configuration: SessionConfigurationVersion,
        group: SessionStakeholderGroup,
        actor_id: str,
        at: datetime,
        invitation: SessionInvitation | None = None,
        user_id: str | None = None,
        alias: str | None = None,
    ) -> Participant:
        """Create an active participant after ownership checks pass."""

        _require_actor(actor_id)
        _require_aware_datetime(at, "Participant enrollment time")
        if configuration.session_id != session_id:
            raise ParticipationRuleViolation(
                "Participant configuration belongs to a different session."
            )
        if group.configuration_version_id != configuration.configuration_version_id:
            raise ParticipationRuleViolation(
                "Participant group belongs to a different configuration."
            )
        if not group.is_active:
            raise ParticipationRuleViolation(
                "Participant cannot enroll in an inactive stakeholder group."
            )

        invitation_id = None
        if invitation is not None:
            invitation.validate_assignment(
                configuration=configuration,
                group=group,
            )
            if invitation.status is not InvitationStatus.REDEEMED:
                raise ParticipationRuleViolation(
                    "Invitation must be redeemed before participant enrollment."
                )
            if invitation.redeemed_participant_id != participant_id:
                raise ParticipationRuleViolation(
                    "Invitation was redeemed for a different participant."
                )
            invitation_id = invitation.invitation_id

        return cls(
            participant_id=participant_id,
            session_id=session_id,
            configuration_version_id=(
                configuration.configuration_version_id
            ),
            session_stakeholder_group_id=(
                group.session_stakeholder_group_id
            ),
            access_status=ParticipantAccessStatus.ACTIVE,
            enrolled_at=at,
            created_at=at,
            created_by=actor_id,
            updated_at=at,
            updated_by=actor_id,
            user_id=user_id,
            invitation_id=invitation_id,
            alias=alias,
        )

    @property
    def progress_status(self) -> ParticipantProgressStatus:
        if self.completed_at is not None:
            return ParticipantProgressStatus.COMPLETED
        if self.submitted_at is not None:
            return ParticipantProgressStatus.SUBMITTED
        if self.started_at is not None:
            return ParticipantProgressStatus.STARTED
        return ParticipantProgressStatus.ENROLLED

    @property
    def can_access(self) -> bool:
        return self.access_status is ParticipantAccessStatus.ACTIVE

    def join(self, *, actor_id: str, at: datetime) -> Self:
        self._require_active_transition(actor_id=actor_id, at=at)
        if self.joined_at is not None:
            raise ParticipationRuleViolation("Participant has already joined.")
        return self._updated(actor_id=actor_id, at=at, joined_at=at)

    def start(self, *, actor_id: str, at: datetime) -> Self:
        self._require_active_transition(actor_id=actor_id, at=at)
        if self.joined_at is None:
            raise ParticipationRuleViolation(
                "Participant must join before starting."
            )
        if self.started_at is not None:
            raise ParticipationRuleViolation(
                "Participant has already started."
            )
        return self._updated(actor_id=actor_id, at=at, started_at=at)

    def record_submission(self, *, actor_id: str, at: datetime) -> Self:
        self._require_active_transition(actor_id=actor_id, at=at)
        if self.started_at is None:
            raise ParticipationRuleViolation(
                "Participant must start before submitting."
            )
        if self.submitted_at is not None:
            raise ParticipationRuleViolation(
                "Participant submission milestone is already recorded."
            )
        return self._updated(actor_id=actor_id, at=at, submitted_at=at)

    def complete(self, *, actor_id: str, at: datetime) -> Self:
        self._require_active_transition(actor_id=actor_id, at=at)
        if self.submitted_at is None:
            raise ParticipationRuleViolation(
                "Participant must submit before completion."
            )
        if self.completed_at is not None:
            raise ParticipationRuleViolation(
                "Participant is already complete."
            )
        return self._updated(actor_id=actor_id, at=at, completed_at=at)

    def change_group(
        self,
        group: SessionStakeholderGroup,
        *,
        actor_id: str,
        at: datetime,
        cutoff: GroupChangeCutoff = GroupChangeCutoff.STARTED,
    ) -> Self:
        """Change group only before the configured participation milestone."""

        self._require_active_transition(actor_id=actor_id, at=at)
        if group.configuration_version_id != self.configuration_version_id:
            raise ParticipationRuleViolation(
                "Participant cannot move to a group in another configuration."
            )
        if not group.is_active:
            raise ParticipationRuleViolation(
                "Participant cannot move to an inactive stakeholder group."
            )
        if group.session_stakeholder_group_id == self.session_stakeholder_group_id:
            raise ParticipationRuleViolation(
                "Participant is already assigned to that stakeholder group."
            )
        if self._group_change_cutoff_reached(cutoff):
            raise ParticipationRuleViolation(
                f"Stakeholder group cannot change after {cutoff.value}."
            )
        return self._updated(
            actor_id=actor_id,
            at=at,
            session_stakeholder_group_id=(
                group.session_stakeholder_group_id
            ),
        )

    def disable(
        self,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> Self:
        _require_actor(actor_id)
        _require_text(reason, "Participant disable reason")
        self._require_update_time(at)
        if self.access_status is not ParticipantAccessStatus.ACTIVE:
            raise ParticipationRuleViolation(
                "Only an active participant can be disabled."
            )
        return self._updated(
            actor_id=actor_id,
            at=at,
            access_status=ParticipantAccessStatus.DISABLED,
            disabled_at=at,
            disabled_by=actor_id,
            disable_reason=reason,
        )

    def withdraw(
        self,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> Self:
        _require_actor(actor_id)
        _require_text(reason, "Participant withdrawal reason")
        self._require_update_time(at)
        if self.access_status is ParticipantAccessStatus.WITHDRAWN:
            raise ParticipationRuleViolation(
                "Participant is already withdrawn."
            )
        return self._updated(
            actor_id=actor_id,
            at=at,
            access_status=ParticipantAccessStatus.WITHDRAWN,
            withdrawn_at=at,
            withdrawn_by=actor_id,
            withdrawal_reason=reason,
        )

    def validate_binding(
        self,
        *,
        configuration: SessionConfigurationVersion,
        group: SessionStakeholderGroup,
    ) -> None:
        """Recheck persisted participant ownership at a trust boundary."""

        if configuration.session_id != self.session_id:
            raise ParticipationRuleViolation(
                "Participant configuration belongs to a different session."
            )
        if (
            configuration.configuration_version_id
            != self.configuration_version_id
        ):
            raise ParticipationRuleViolation(
                "Participant is pinned to a different configuration version."
            )
        if group.configuration_version_id != self.configuration_version_id:
            raise ParticipationRuleViolation(
                "Participant group belongs to a different configuration."
            )
        if (
            group.session_stakeholder_group_id
            != self.session_stakeholder_group_id
        ):
            raise ParticipationRuleViolation(
                "Participant is pinned to a different stakeholder group."
            )

    def _group_change_cutoff_reached(self, cutoff: GroupChangeCutoff) -> bool:
        if cutoff is GroupChangeCutoff.ENROLLMENT:
            return True
        if cutoff is GroupChangeCutoff.JOINED:
            return self.joined_at is not None
        if cutoff is GroupChangeCutoff.STARTED:
            return self.started_at is not None
        if cutoff is GroupChangeCutoff.SUBMITTED:
            return self.submitted_at is not None
        raise ParticipationRuleViolation(
            f"Unsupported group-change cutoff: {cutoff!r}."
        )

    def _require_active_transition(
        self,
        *,
        actor_id: str,
        at: datetime,
    ) -> None:
        _require_actor(actor_id)
        self._require_update_time(at)
        if self.access_status is not ParticipantAccessStatus.ACTIVE:
            raise ParticipationRuleViolation(
                "Participant access must be active for this operation."
            )

    def _require_update_time(self, at: datetime) -> None:
        _require_aware_datetime(at, "Participant update time")
        _require_not_before(at, self.updated_at, "Participant update time")

    def _updated(
        self,
        *,
        actor_id: str,
        at: datetime,
        **changes: object,
    ) -> Self:
        return replace(
            self,
            **changes,
            updated_at=at,
            updated_by=actor_id,
        )

    def _validate_identity(self) -> None:
        for field_name, value in (
            ("Participant ID", self.participant_id),
            ("Participant session ID", self.session_id),
            ("Participant configuration ID", self.configuration_version_id),
            ("Participant stakeholder group ID", self.session_stakeholder_group_id),
            ("Participant creator", self.created_by),
            ("Participant updater", self.updated_by),
        ):
            _require_text(value, field_name)
        for field_name, value in (
            ("Participant user ID", self.user_id),
            ("Participant invitation ID", self.invitation_id),
            ("Participant alias", self.alias),
        ):
            _require_optional_text(value, field_name)

    def _validate_schedule(self) -> None:
        timestamps = {
            "enrolled_at": self.enrolled_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "joined_at": self.joined_at,
            "started_at": self.started_at,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "disabled_at": self.disabled_at,
            "withdrawn_at": self.withdrawn_at,
        }
        for field_name, value in timestamps.items():
            _require_aware_datetime(value, f"Participant {field_name}")
        if self.enrolled_at < self.created_at:
            raise ParticipationRuleViolation(
                "Participant enrollment cannot precede creation."
            )
        if self.updated_at < self.created_at:
            raise ParticipationRuleViolation(
                "Participant update cannot precede creation."
            )

        previous = self.enrolled_at
        for field_name in (
            "joined_at",
            "started_at",
            "submitted_at",
            "completed_at",
        ):
            value = timestamps[field_name]
            if value is None:
                if any(
                    timestamps[later] is not None
                    for later in _later_progress_fields(field_name)
                ):
                    raise ParticipationRuleViolation(
                        f"Participant {field_name} is required before later "
                        "progress milestones."
                    )
                break
            if value < previous:
                raise ParticipationRuleViolation(
                    f"Participant {field_name} is out of chronological order."
                )
            previous = value

        for field_name in ("disabled_at", "withdrawn_at"):
            value = timestamps[field_name]
            if value is not None and value < self.created_at:
                raise ParticipationRuleViolation(
                    f"Participant {field_name} cannot precede creation."
                )
        for field_name, value in timestamps.items():
            if value is not None and value > self.updated_at:
                raise ParticipationRuleViolation(
                    f"Participant {field_name} cannot follow updated_at."
                )

    def _validate_access_state(self) -> None:
        disabled_metadata = (
            self.disabled_at,
            self.disabled_by,
            self.disable_reason,
        )
        withdrawn_metadata = (
            self.withdrawn_at,
            self.withdrawn_by,
            self.withdrawal_reason,
        )
        if self.access_status is ParticipantAccessStatus.ACTIVE:
            if any(value is not None for value in disabled_metadata):
                raise ParticipationRuleViolation(
                    "Active participant cannot contain disable metadata."
                )
            if any(value is not None for value in withdrawn_metadata):
                raise ParticipationRuleViolation(
                    "Active participant cannot contain withdrawal metadata."
                )
        elif self.access_status is ParticipantAccessStatus.DISABLED:
            if not all(value is not None for value in disabled_metadata):
                raise ParticipationRuleViolation(
                    "Disabled participant requires complete disable metadata."
                )
            if any(value is not None for value in withdrawn_metadata):
                raise ParticipationRuleViolation(
                    "Disabled participant cannot contain withdrawal metadata."
                )
            _require_text(self.disabled_by or "", "Participant disabler")
            _require_text(
                self.disable_reason or "",
                "Participant disable reason",
            )
        elif self.access_status is ParticipantAccessStatus.WITHDRAWN:
            if not all(value is not None for value in withdrawn_metadata):
                raise ParticipationRuleViolation(
                    "Withdrawn participant requires complete withdrawal metadata."
                )
            _require_text(self.withdrawn_by or "", "Participant withdrawer")
            _require_text(
                self.withdrawal_reason or "",
                "Participant withdrawal reason",
            )
        else:
            raise ParticipationRuleViolation(
                f"Unsupported participant access status: {self.access_status!r}."
            )


def _later_progress_fields(field_name: str) -> tuple[str, ...]:
    fields = ("joined_at", "started_at", "submitted_at", "completed_at")
    index = fields.index(field_name)
    return fields[index + 1 :]


@dataclass(frozen=True, slots=True)
class ParticipantIdentity:
    """Optional encrypted PII stored separately from analytical records."""

    participant_id: str
    consent_version: str
    consented_at: datetime
    retention_until: datetime
    display_name_ciphertext: bytes | None = None
    email_ciphertext: bytes | None = None
    email_lookup_hash: str | None = None
    additional_identity_ciphertext: bytes | None = None
    redacted_at: datetime | None = None
    redacted_by: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.participant_id, "Identity participant ID")
        _require_text(self.consent_version, "Identity consent version")
        _require_aware_datetime(self.consented_at, "Identity consented_at")
        _require_aware_datetime(
            self.retention_until,
            "Identity retention_until",
        )
        _require_aware_datetime(self.redacted_at, "Identity redacted_at")
        _require_optional_text(self.redacted_by, "Identity redactor")
        if self.retention_until <= self.consented_at:
            raise ParticipationRuleViolation(
                "Identity retention must extend beyond consent time."
            )
        for field_name, value in (
            ("display_name_ciphertext", self.display_name_ciphertext),
            ("email_ciphertext", self.email_ciphertext),
            (
                "additional_identity_ciphertext",
                self.additional_identity_ciphertext,
            ),
        ):
            if value == b"":
                raise ParticipationRuleViolation(
                    f"Identity {field_name} cannot be empty."
                )
        if (self.email_ciphertext is None) != (
            self.email_lookup_hash is None
        ):
            raise ParticipationRuleViolation(
                "Encrypted email and lookup hash must be set together."
            )
        if self.email_lookup_hash is not None:
            _require_sha256(self.email_lookup_hash, "Identity email lookup hash")

        payload_present = any(
            value is not None
            for value in (
                self.display_name_ciphertext,
                self.email_ciphertext,
                self.additional_identity_ciphertext,
            )
        )
        if self.redacted_at is None:
            if self.redacted_by is not None:
                raise ParticipationRuleViolation(
                    "Identity redactor requires redacted_at."
                )
            if not payload_present:
                raise ParticipationRuleViolation(
                    "An unredacted identity requires encrypted identity data."
                )
        else:
            if self.redacted_by is None:
                raise ParticipationRuleViolation(
                    "Redacted identity requires a redactor."
                )
            if self.redacted_at < self.consented_at:
                raise ParticipationRuleViolation(
                    "Identity redaction cannot precede consent."
                )
            if payload_present or self.email_lookup_hash is not None:
                raise ParticipationRuleViolation(
                    "Redacted identity cannot retain identity data or hashes."
                )

    @property
    def is_redacted(self) -> bool:
        return self.redacted_at is not None

    def redact(self, *, actor_id: str, at: datetime) -> Self:
        """Remove all stored PII and searchable identity hashes."""

        _require_actor(actor_id)
        _require_aware_datetime(at, "Identity redaction time")
        if self.is_redacted:
            raise ParticipationRuleViolation(
                "Participant identity is already redacted."
            )
        if at < self.consented_at:
            raise ParticipationRuleViolation(
                "Identity redaction cannot precede consent."
            )
        return replace(
            self,
            display_name_ciphertext=None,
            email_ciphertext=None,
            email_lookup_hash=None,
            additional_identity_ciphertext=None,
            redacted_at=at,
            redacted_by=actor_id,
        )


@dataclass(frozen=True, slots=True)
class ParticipantAccessGrant:
    """Revocable participant credential distinct from invitation tokens."""

    access_grant_id: str
    participant_id: str
    token_digest: str
    issued_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    revocation_reason: str | None = None
    replaced_by_grant_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("Access grant ID", self.access_grant_id),
            ("Access grant participant ID", self.participant_id),
        ):
            _require_text(value, field_name)
        _require_sha256(self.token_digest, "Access grant token digest")
        for field_name, value in (
            ("Access grant issued_at", self.issued_at),
            ("Access grant expires_at", self.expires_at),
            ("Access grant last_used_at", self.last_used_at),
            ("Access grant revoked_at", self.revoked_at),
        ):
            _require_aware_datetime(value, field_name)
        for field_name, value in (
            ("Access grant revoker", self.revoked_by),
            ("Access grant revocation reason", self.revocation_reason),
            ("Replacement access grant ID", self.replaced_by_grant_id),
        ):
            _require_optional_text(value, field_name)
        if self.expires_at <= self.issued_at:
            raise ParticipationRuleViolation(
                "Access grant expires_at must be later than issued_at."
            )
        if self.last_used_at is not None:
            if not self.issued_at <= self.last_used_at < self.expires_at:
                raise ParticipationRuleViolation(
                    "Access grant last use must be within its validity period."
                )
        revocation_metadata = (
            self.revoked_at,
            self.revoked_by,
            self.revocation_reason,
        )
        if any(value is not None for value in revocation_metadata):
            if not all(value is not None for value in revocation_metadata):
                raise ParticipationRuleViolation(
                    "Access grant revocation metadata must be complete."
                )
            if self.revoked_at is not None and self.revoked_at < self.issued_at:
                raise ParticipationRuleViolation(
                    "Access grant revocation cannot precede issuance."
                )
            if (
                self.last_used_at is not None
                and self.revoked_at is not None
                and self.revoked_at < self.last_used_at
            ):
                raise ParticipationRuleViolation(
                    "Access grant revocation cannot precede its last use."
                )
        if self.replaced_by_grant_id is not None:
            if self.revoked_at is None:
                raise ParticipationRuleViolation(
                    "A replaced access grant must also be revoked."
                )
            if self.replaced_by_grant_id == self.access_grant_id:
                raise ParticipationRuleViolation(
                    "Access grant cannot replace itself."
                )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_active(self, *, at: datetime) -> bool:
        _require_aware_datetime(at, "Access grant check time")
        return (
            not self.is_revoked
            and self.issued_at <= at < self.expires_at
        )

    def use(
        self,
        *,
        participant: Participant,
        presented_token_digest: str,
        at: datetime,
    ) -> Self:
        """Validate the credential and record its latest successful use."""

        _require_sha256(
            presented_token_digest,
            "Presented access grant token digest",
        )
        _require_aware_datetime(at, "Access grant use time")
        if participant.participant_id != self.participant_id:
            raise ParticipationRuleViolation(
                "Access grant belongs to a different participant."
            )
        if not participant.can_access:
            raise ParticipationRuleViolation(
                "Participant access is not active."
            )
        if not self.is_active(at=at):
            if self.is_revoked:
                raise ParticipationRuleViolation("Access grant is revoked.")
            raise ParticipationRuleViolation(
                "Access grant is not currently valid."
            )
        if self.last_used_at is not None and at < self.last_used_at:
            raise ParticipationRuleViolation(
                "Access grant use cannot precede its previous use."
            )
        if not hmac.compare_digest(
            self.token_digest,
            presented_token_digest,
        ):
            raise ParticipationRuleViolation(
                "Presented access grant token digest does not match."
            )
        return replace(self, last_used_at=at)

    def revoke(
        self,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> Self:
        """Revoke an access grant without changing participant history."""

        return self._revoke(
            actor_id=actor_id,
            reason=reason,
            at=at,
            replacement_grant_id=None,
        )

    def replace_with(
        self,
        replacement: ParticipantAccessGrant,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> Self:
        """Revoke this credential and link its independently issued successor."""

        if replacement.participant_id != self.participant_id:
            raise ParticipationRuleViolation(
                "Replacement grant belongs to a different participant."
            )
        if replacement.access_grant_id == self.access_grant_id:
            raise ParticipationRuleViolation(
                "Access grant cannot replace itself."
            )
        if replacement.issued_at != at:
            raise ParticipationRuleViolation(
                "Replacement grant must be issued at the replacement time."
            )
        if replacement.is_revoked:
            raise ParticipationRuleViolation(
                "Replacement access grant must be active when issued."
            )
        return self._revoke(
            actor_id=actor_id,
            reason=reason,
            at=at,
            replacement_grant_id=replacement.access_grant_id,
        )

    def _revoke(
        self,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
        replacement_grant_id: str | None,
    ) -> Self:
        _require_actor(actor_id)
        _require_text(reason, "Access grant revocation reason")
        _require_aware_datetime(at, "Access grant revocation time")
        if self.is_revoked:
            raise ParticipationRuleViolation(
                "Access grant is already revoked."
            )
        _require_not_before(at, self.issued_at, "Access grant revocation time")
        return replace(
            self,
            revoked_at=at,
            revoked_by=actor_id,
            revocation_reason=reason,
            replaced_by_grant_id=replacement_grant_id,
        )
