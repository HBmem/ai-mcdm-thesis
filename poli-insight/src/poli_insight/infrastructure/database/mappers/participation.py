"""Bidirectional mappings for participation and credential domain objects.

Plaintext credentials never cross this module. Invitation and access-grant
rows contain only persistence-safe digests, while optional identity payloads
remain encrypted bytes separated from analytical participant state.
"""

from __future__ import annotations

from datetime import datetime

from poli_insight.core.time import as_utc
from poli_insight.domain.enum import (
    InvitationStatus,
    ParticipantAccessStatus,
)
from poli_insight.domain.participation import (
    Participant,
    ParticipantAccessGrant,
    ParticipantIdentity,
    SessionInvitation,
)
from poli_insight.infrastructure.database.models.participation import (
    ParticipantAccessGrantRow,
    ParticipantIdentityRow,
    ParticipantRow,
    SessionInvitationRow,
)


def _required_utc(value: datetime, field_name: str) -> datetime:
    utc_value = as_utc(value)
    if utc_value is None:
        raise ValueError(f"Persisted participation row is missing {field_name}.")
    return utc_value


def _optional_utc(value: datetime | None) -> datetime | None:
    return as_utc(value) if value is not None else None


def _optional_id(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _optional_bytes(value: bytes | None) -> bytes | None:
    return bytes(value) if value is not None else None


def _require_immutable_fields(
    entity_name: str,
    fields: tuple[tuple[str, object, object], ...],
) -> None:
    for field_name, persisted, replacement in fields:
        if persisted != replacement:
            raise ValueError(
                f"{entity_name} {field_name} cannot be replaced during save."
            )


def session_invitation_to_row(
    invitation: SessionInvitation,
) -> SessionInvitationRow:
    """Map an invitation without exposing or persisting its plaintext token."""

    return SessionInvitationRow(
        invitation_id=invitation.invitation_id,
        session_id=invitation.session_id,
        configuration_version_id=invitation.configuration_version_id,
        assigned_group_id=invitation.assigned_group_id,
        token_digest=invitation.token_digest,
        token_hint=invitation.token_hint,
        identity_lookup_hash=invitation.identity_lookup_hash,
        identity_ciphertext=_optional_bytes(invitation.identity_ciphertext),
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        max_redemptions=invitation.max_redemptions,
        sent_at=invitation.sent_at,
        send_count=invitation.send_count,
        redeemed_at=invitation.redeemed_at,
        redeemed_participant_id=invitation.redeemed_participant_id,
        revoked_at=invitation.revoked_at,
        revoked_by=invitation.revoked_by,
        revocation_reason=invitation.revocation_reason,
        created_at=invitation.created_at,
        created_by=invitation.created_by,
    )


def session_invitation_to_domain(
    row: SessionInvitationRow,
) -> SessionInvitation:
    """Reconstruct a detached invitation from digest-only persistence."""

    return SessionInvitation(
        invitation_id=str(row.invitation_id),
        session_id=str(row.session_id),
        configuration_version_id=str(row.configuration_version_id),
        assigned_group_id=_optional_id(row.assigned_group_id),
        token_digest=row.token_digest,
        token_hint=row.token_hint,
        identity_lookup_hash=row.identity_lookup_hash,
        identity_ciphertext=_optional_bytes(row.identity_ciphertext),
        status=InvitationStatus(row.status),
        expires_at=_required_utc(row.expires_at, "invitation expires_at"),
        max_redemptions=row.max_redemptions,
        sent_at=_optional_utc(row.sent_at),
        send_count=row.send_count,
        redeemed_at=_optional_utc(row.redeemed_at),
        redeemed_participant_id=_optional_id(row.redeemed_participant_id),
        revoked_at=_optional_utc(row.revoked_at),
        revoked_by=row.revoked_by,
        revocation_reason=row.revocation_reason,
        created_at=_required_utc(row.created_at, "invitation created_at"),
        created_by=row.created_by,
    )


def apply_session_invitation_state(
    row: SessionInvitationRow,
    invitation: SessionInvitation,
) -> None:
    """Apply a valid invitation lifecycle transition to an existing row."""

    _require_immutable_fields(
        "Invitation",
        (
            ("ID", str(row.invitation_id), invitation.invitation_id),
            ("session", str(row.session_id), invitation.session_id),
            (
                "configuration",
                str(row.configuration_version_id),
                invitation.configuration_version_id,
            ),
            (
                "assigned group",
                _optional_id(row.assigned_group_id),
                invitation.assigned_group_id,
            ),
            ("token digest", row.token_digest, invitation.token_digest),
            ("token hint", row.token_hint, invitation.token_hint),
            (
                "identity lookup hash",
                row.identity_lookup_hash,
                invitation.identity_lookup_hash,
            ),
            (
                "identity ciphertext",
                _optional_bytes(row.identity_ciphertext),
                _optional_bytes(invitation.identity_ciphertext),
            ),
            (
                "expires_at",
                _required_utc(row.expires_at, "invitation expires_at"),
                as_utc(invitation.expires_at),
            ),
            (
                "maximum redemptions",
                row.max_redemptions,
                invitation.max_redemptions,
            ),
            (
                "created_at",
                _required_utc(row.created_at, "invitation created_at"),
                as_utc(invitation.created_at),
            ),
            ("creator", row.created_by, invitation.created_by),
        ),
    )
    persisted_status = InvitationStatus(row.status)
    _validate_invitation_transition(persisted_status, invitation.status)
    if persisted_status in {
        InvitationStatus.REDEEMED,
        InvitationStatus.EXPIRED,
        InvitationStatus.REVOKED,
    }:
        if session_invitation_to_domain(row) != invitation:
            raise ValueError("Terminal invitation state cannot be changed.")
        return
    if invitation.send_count < row.send_count:
        raise ValueError("Invitation send count cannot decrease.")
    if row.sent_at is not None and invitation.sent_at is None:
        raise ValueError("Invitation send history cannot be removed.")
    persisted_sent_at = _optional_utc(row.sent_at)
    replacement_sent_at = _optional_utc(invitation.sent_at)
    if (
        persisted_sent_at is not None
        and replacement_sent_at is not None
        and replacement_sent_at < persisted_sent_at
    ):
        raise ValueError("Invitation send history cannot move backward.")

    row.status = invitation.status.value
    row.sent_at = invitation.sent_at
    row.send_count = invitation.send_count
    row.redeemed_at = invitation.redeemed_at
    row.redeemed_participant_id = invitation.redeemed_participant_id
    row.revoked_at = invitation.revoked_at
    row.revoked_by = invitation.revoked_by
    row.revocation_reason = invitation.revocation_reason


def _validate_invitation_transition(
    persisted: InvitationStatus,
    replacement: InvitationStatus,
) -> None:
    allowed = {
        InvitationStatus.PENDING: {
            InvitationStatus.PENDING,
            InvitationStatus.SENT,
            InvitationStatus.DELIVERY_FAILED,
            InvitationStatus.EXPIRED,
            InvitationStatus.REVOKED,
        },
        InvitationStatus.SENT: {
            InvitationStatus.SENT,
            InvitationStatus.DELIVERY_FAILED,
            InvitationStatus.REDEEMED,
            InvitationStatus.EXPIRED,
            InvitationStatus.REVOKED,
        },
        InvitationStatus.DELIVERY_FAILED: {
            InvitationStatus.DELIVERY_FAILED,
            InvitationStatus.SENT,
            InvitationStatus.EXPIRED,
            InvitationStatus.REVOKED,
        },
        InvitationStatus.REDEEMED: {InvitationStatus.REDEEMED},
        InvitationStatus.EXPIRED: {InvitationStatus.EXPIRED},
        InvitationStatus.REVOKED: {InvitationStatus.REVOKED},
    }
    if replacement not in allowed[persisted]:
        raise ValueError(
            "Invalid persisted invitation transition: "
            f"{persisted.value} -> {replacement.value}."
        )


def participant_to_row(participant: Participant) -> ParticipantRow:
    """Map analytical participant state without optional identity data."""

    return ParticipantRow(
        participant_id=participant.participant_id,
        session_id=participant.session_id,
        configuration_version_id=participant.configuration_version_id,
        session_stakeholder_group_id=(
            participant.session_stakeholder_group_id
        ),
        user_id=participant.user_id,
        invitation_id=participant.invitation_id,
        alias=participant.alias,
        access_status=participant.access_status.value,
        enrolled_at=participant.enrolled_at,
        joined_at=participant.joined_at,
        started_at=participant.started_at,
        submitted_at=participant.submitted_at,
        completed_at=participant.completed_at,
        disabled_at=participant.disabled_at,
        disabled_by=participant.disabled_by,
        disable_reason=participant.disable_reason,
        withdrawn_at=participant.withdrawn_at,
        withdrawn_by=participant.withdrawn_by,
        withdrawal_reason=participant.withdrawal_reason,
        created_at=participant.created_at,
        created_by=participant.created_by,
        updated_at=participant.updated_at,
        updated_by=participant.updated_by,
    )


def participant_to_domain(row: ParticipantRow) -> Participant:
    """Reconstruct analytical participant state without loading PII."""

    return Participant(
        participant_id=str(row.participant_id),
        session_id=str(row.session_id),
        configuration_version_id=str(row.configuration_version_id),
        session_stakeholder_group_id=str(
            row.session_stakeholder_group_id
        ),
        user_id=_optional_id(row.user_id),
        invitation_id=_optional_id(row.invitation_id),
        alias=row.alias,
        access_status=ParticipantAccessStatus(row.access_status),
        enrolled_at=_required_utc(row.enrolled_at, "participant enrolled_at"),
        joined_at=_optional_utc(row.joined_at),
        started_at=_optional_utc(row.started_at),
        submitted_at=_optional_utc(row.submitted_at),
        completed_at=_optional_utc(row.completed_at),
        disabled_at=_optional_utc(row.disabled_at),
        disabled_by=row.disabled_by,
        disable_reason=row.disable_reason,
        withdrawn_at=_optional_utc(row.withdrawn_at),
        withdrawn_by=row.withdrawn_by,
        withdrawal_reason=row.withdrawal_reason,
        created_at=_required_utc(row.created_at, "participant created_at"),
        created_by=row.created_by,
        updated_at=_required_utc(row.updated_at, "participant updated_at"),
        updated_by=row.updated_by,
    )


def apply_participant_state(
    row: ParticipantRow,
    participant: Participant,
) -> None:
    """Apply participant progress, group, and access lifecycle state."""

    _require_immutable_fields(
        "Participant",
        (
            ("ID", str(row.participant_id), participant.participant_id),
            ("session", str(row.session_id), participant.session_id),
            (
                "configuration",
                str(row.configuration_version_id),
                participant.configuration_version_id,
            ),
            ("user", _optional_id(row.user_id), participant.user_id),
            (
                "invitation",
                _optional_id(row.invitation_id),
                participant.invitation_id,
            ),
            ("alias", row.alias, participant.alias),
            (
                "enrolled_at",
                _required_utc(row.enrolled_at, "participant enrolled_at"),
                as_utc(participant.enrolled_at),
            ),
            (
                "created_at",
                _required_utc(row.created_at, "participant created_at"),
                as_utc(participant.created_at),
            ),
            ("creator", row.created_by, participant.created_by),
        ),
    )
    persisted_status = ParticipantAccessStatus(row.access_status)
    _validate_participant_access_transition(
        persisted_status,
        participant.access_status,
    )
    _validate_progress_history(row, participant)
    _validate_participant_access_history(row, participant)
    persisted_updated_at = _required_utc(
        row.updated_at,
        "participant updated_at",
    )
    replacement_updated_at = as_utc(participant.updated_at)
    if (
        replacement_updated_at is not None
        and replacement_updated_at < persisted_updated_at
    ):
        raise ValueError("Participant update history cannot move backward.")

    if persisted_status is ParticipantAccessStatus.WITHDRAWN:
        if participant_to_domain(row) != participant:
            raise ValueError("Withdrawn participant state cannot be changed.")
        return
    if (
        persisted_status is not ParticipantAccessStatus.ACTIVE
        and str(row.session_stakeholder_group_id)
        != participant.session_stakeholder_group_id
    ):
        raise ValueError(
            "Participant stakeholder group cannot change after access closes."
        )

    row.session_stakeholder_group_id = (
        participant.session_stakeholder_group_id
    )
    row.access_status = participant.access_status.value
    row.joined_at = participant.joined_at
    row.started_at = participant.started_at
    row.submitted_at = participant.submitted_at
    row.completed_at = participant.completed_at
    row.disabled_at = participant.disabled_at
    row.disabled_by = participant.disabled_by
    row.disable_reason = participant.disable_reason
    row.withdrawn_at = participant.withdrawn_at
    row.withdrawn_by = participant.withdrawn_by
    row.withdrawal_reason = participant.withdrawal_reason
    row.updated_at = participant.updated_at
    row.updated_by = participant.updated_by


def _validate_participant_access_transition(
    persisted: ParticipantAccessStatus,
    replacement: ParticipantAccessStatus,
) -> None:
    allowed = {
        ParticipantAccessStatus.ACTIVE: {
            ParticipantAccessStatus.ACTIVE,
            ParticipantAccessStatus.DISABLED,
            ParticipantAccessStatus.WITHDRAWN,
        },
        ParticipantAccessStatus.DISABLED: {
            ParticipantAccessStatus.DISABLED,
            ParticipantAccessStatus.WITHDRAWN,
        },
        ParticipantAccessStatus.WITHDRAWN: {
            ParticipantAccessStatus.WITHDRAWN,
        },
    }
    if replacement not in allowed[persisted]:
        raise ValueError(
            "Invalid persisted participant access transition: "
            f"{persisted.value} -> {replacement.value}."
        )


def _validate_progress_history(
    row: ParticipantRow,
    participant: Participant,
) -> None:
    for field_name, persisted, replacement in (
        (
            "joined_at",
            _optional_utc(row.joined_at),
            _optional_utc(participant.joined_at),
        ),
        (
            "started_at",
            _optional_utc(row.started_at),
            _optional_utc(participant.started_at),
        ),
        (
            "submitted_at",
            _optional_utc(row.submitted_at),
            _optional_utc(participant.submitted_at),
        ),
        (
            "completed_at",
            _optional_utc(row.completed_at),
            _optional_utc(participant.completed_at),
        ),
    ):
        if persisted is not None and persisted != replacement:
            raise ValueError(
                f"Participant {field_name} history cannot be rewritten."
            )


def _validate_participant_access_history(
    row: ParticipantRow,
    participant: Participant,
) -> None:
    for field_name, persisted, replacement in (
        (
            "disabled_at",
            _optional_utc(row.disabled_at),
            _optional_utc(participant.disabled_at),
        ),
        ("disabled_by", row.disabled_by, participant.disabled_by),
        ("disable_reason", row.disable_reason, participant.disable_reason),
        (
            "withdrawn_at",
            _optional_utc(row.withdrawn_at),
            _optional_utc(participant.withdrawn_at),
        ),
        ("withdrawn_by", row.withdrawn_by, participant.withdrawn_by),
        (
            "withdrawal_reason",
            row.withdrawal_reason,
            participant.withdrawal_reason,
        ),
    ):
        if persisted is not None and persisted != replacement:
            raise ValueError(
                f"Participant {field_name} history cannot be rewritten."
            )


def participant_identity_to_row(
    identity: ParticipantIdentity,
) -> ParticipantIdentityRow:
    """Map encrypted optional identity data independently of analytics."""

    return ParticipantIdentityRow(
        participant_id=identity.participant_id,
        consent_version=identity.consent_version,
        consented_at=identity.consented_at,
        retention_until=identity.retention_until,
        display_name_ciphertext=_optional_bytes(
            identity.display_name_ciphertext
        ),
        email_ciphertext=_optional_bytes(identity.email_ciphertext),
        email_lookup_hash=identity.email_lookup_hash,
        additional_identity_ciphertext=_optional_bytes(
            identity.additional_identity_ciphertext
        ),
        redacted_at=identity.redacted_at,
        redacted_by=identity.redacted_by,
    )


def participant_identity_to_domain(
    row: ParticipantIdentityRow,
) -> ParticipantIdentity:
    """Reconstruct a detached encrypted or explicitly redacted identity."""

    return ParticipantIdentity(
        participant_id=str(row.participant_id),
        consent_version=row.consent_version,
        consented_at=_required_utc(row.consented_at, "identity consented_at"),
        retention_until=_required_utc(
            row.retention_until,
            "identity retention_until",
        ),
        display_name_ciphertext=_optional_bytes(
            row.display_name_ciphertext
        ),
        email_ciphertext=_optional_bytes(row.email_ciphertext),
        email_lookup_hash=row.email_lookup_hash,
        additional_identity_ciphertext=_optional_bytes(
            row.additional_identity_ciphertext
        ),
        redacted_at=_optional_utc(row.redacted_at),
        redacted_by=row.redacted_by,
    )


def apply_participant_identity_state(
    row: ParticipantIdentityRow,
    identity: ParticipantIdentity,
) -> None:
    """Apply one-way identity redaction without permitting PII replacement."""

    _require_immutable_fields(
        "Participant identity",
        (
            ("participant", str(row.participant_id), identity.participant_id),
            ("consent version", row.consent_version, identity.consent_version),
            (
                "consented_at",
                _required_utc(row.consented_at, "identity consented_at"),
                as_utc(identity.consented_at),
            ),
            (
                "retention_until",
                _required_utc(
                    row.retention_until,
                    "identity retention_until",
                ),
                as_utc(identity.retention_until),
            ),
        ),
    )
    persisted = participant_identity_to_domain(row)
    if persisted.is_redacted:
        if persisted != identity:
            raise ValueError("Redacted participant identity cannot be changed.")
        return
    if not identity.is_redacted:
        if persisted != identity:
            raise ValueError(
                "Encrypted participant identity cannot be replaced."
            )
        return

    row.display_name_ciphertext = None
    row.email_ciphertext = None
    row.email_lookup_hash = None
    row.additional_identity_ciphertext = None
    row.redacted_at = identity.redacted_at
    row.redacted_by = identity.redacted_by


def participant_access_grant_to_row(
    grant: ParticipantAccessGrant,
) -> ParticipantAccessGrantRow:
    """Map a digest-only participant access credential."""

    return ParticipantAccessGrantRow(
        access_grant_id=grant.access_grant_id,
        participant_id=grant.participant_id,
        token_digest=grant.token_digest,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
        last_used_at=grant.last_used_at,
        revoked_at=grant.revoked_at,
        revoked_by=grant.revoked_by,
        revocation_reason=grant.revocation_reason,
        replaced_by_grant_id=grant.replaced_by_grant_id,
    )


def participant_access_grant_to_domain(
    row: ParticipantAccessGrantRow,
) -> ParticipantAccessGrant:
    """Reconstruct a credential without ever materializing plaintext."""

    return ParticipantAccessGrant(
        access_grant_id=str(row.access_grant_id),
        participant_id=str(row.participant_id),
        token_digest=row.token_digest,
        issued_at=_required_utc(row.issued_at, "access grant issued_at"),
        expires_at=_required_utc(row.expires_at, "access grant expires_at"),
        last_used_at=_optional_utc(row.last_used_at),
        revoked_at=_optional_utc(row.revoked_at),
        revoked_by=row.revoked_by,
        revocation_reason=row.revocation_reason,
        replaced_by_grant_id=_optional_id(row.replaced_by_grant_id),
    )


def apply_participant_access_grant_state(
    row: ParticipantAccessGrantRow,
    grant: ParticipantAccessGrant,
) -> None:
    """Apply monotonic use, revocation, or replacement state."""

    _require_immutable_fields(
        "Participant access grant",
        (
            ("ID", str(row.access_grant_id), grant.access_grant_id),
            ("participant", str(row.participant_id), grant.participant_id),
            ("token digest", row.token_digest, grant.token_digest),
            (
                "issued_at",
                _required_utc(row.issued_at, "access grant issued_at"),
                as_utc(grant.issued_at),
            ),
            (
                "expires_at",
                _required_utc(row.expires_at, "access grant expires_at"),
                as_utc(grant.expires_at),
            ),
        ),
    )
    persisted = participant_access_grant_to_domain(row)
    if persisted.is_revoked:
        if persisted != grant:
            raise ValueError("Revoked access grant cannot be changed.")
        return
    if (
        persisted.last_used_at is not None
        and (
            grant.last_used_at is None
            or grant.last_used_at < persisted.last_used_at
        )
    ):
        raise ValueError("Access grant use history cannot move backward.")

    row.last_used_at = grant.last_used_at
    row.revoked_at = grant.revoked_at
    row.revoked_by = grant.revoked_by
    row.revocation_reason = grant.revocation_reason
    row.replaced_by_grant_id = grant.replaced_by_grant_id
