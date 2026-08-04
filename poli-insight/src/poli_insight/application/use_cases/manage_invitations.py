"""Audited administrator invitation lifecycle use cases."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import is_aware_datetime, utc_now
from poli_insight.domain.enum import (
    AccessCodeMode,
    ActorType,
    AuditAction,
    InvitationStatus,
    SessionStatus,
    StakeholderSelectionMode,
)
from poli_insight.domain.participation import (
    ParticipationRuleViolation,
    SessionInvitation,
)
from poli_insight.domain.session import Session, SessionConfigurationVersion
from poli_insight.infrastructure.auth.tokens import IssuedToken, generate_token

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
TokenFactory = Callable[[], IssuedToken]


class InvitationManagementError(ValueError):
    """Safe administrator-facing invitation lifecycle failure."""


@dataclass(frozen=True, slots=True)
class IssueInvitationCommand:
    session_id: str
    assigned_group_id: str | None
    expires_at: datetime
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))

    def __post_init__(self) -> None:
        _validate_command_text(
            session_id=self.session_id,
            actor_id=self.actor_id,
            correlation_id=self.correlation_id,
        )
        if not is_aware_datetime(self.expires_at):
            raise InvitationManagementError(
                "Invitation expiration must include timezone information."
            )


@dataclass(frozen=True, slots=True, repr=False)
class IssuedInvitationResult:
    invitation_id: str
    token: str
    token_hint: str
    access_code: str | None
    expires_at: datetime
    replaced_invitation_id: str | None = None

    def __repr__(self) -> str:
        return (
            "IssuedInvitationResult("
            f"invitation_id={self.invitation_id!r}, token=<redacted>, "
            f"token_hint={self.token_hint!r}, access_code=<redacted>)"
        )


class IssueInvitation:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
        token_factory: TokenFactory = generate_token,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory
        self._token_factory = token_factory

    def execute(self, command: IssueInvitationCommand) -> IssuedInvitationResult:
        at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            session, configuration = _load_invitation_scope(
                unit_of_work, command.session_id
            )
            invitation, token, access_code = self._build_invitation(
                session=session,
                configuration=configuration,
                assigned_group_id=command.assigned_group_id,
                expires_at=command.expires_at,
                actor_id=command.actor_id,
                at=at,
            )
            unit_of_work.invitations.add(invitation)
            _add_invitation_code(
                unit_of_work,
                session=session,
                invitation=invitation,
                access_code=access_code,
                actor_id=command.actor_id,
                at=at,
                id_factory=self._id_factory,
            )
            unit_of_work.audit_events.add(
                _invitation_event(
                    invitation,
                    event_id=self._id_factory(),
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    correlation_id=command.correlation_id,
                    occurred_at=at,
                )
            )
            unit_of_work.commit()
        return IssuedInvitationResult(
            invitation_id=invitation.invitation_id,
            token=token.plaintext,
            token_hint=token.token_hint,
            access_code=access_code,
            expires_at=invitation.expires_at,
        )

    def _build_invitation(
        self,
        *,
        session: Session,
        configuration: SessionConfigurationVersion,
        assigned_group_id: str | None,
        expires_at: datetime,
        actor_id: str,
        at: datetime,
    ) -> tuple[SessionInvitation, IssuedToken, str | None]:
        _validate_assignment(session, configuration, assigned_group_id)
        if expires_at <= at:
            raise InvitationManagementError("Expiration must be in the future.")
        token = self._token_factory()
        try:
            invitation = SessionInvitation(
                invitation_id=self._id_factory(),
                session_id=session.session_id,
                configuration_version_id=configuration.configuration_version_id,
                assigned_group_id=assigned_group_id,
                token_digest=token.token_digest,
                token_hint=token.token_hint,
                status=InvitationStatus.PENDING,
                expires_at=expires_at,
                created_at=at,
                created_by=actor_id,
            ).mark_sent(at=at)
        except ParticipationRuleViolation as error:
            raise InvitationManagementError(str(error)) from error
        access_code = (
            secrets.token_urlsafe(9)
            if session.access_code_mode == AccessCodeMode.PER_INVITATION_CODE
            else None
        )
        return invitation, token, access_code


@dataclass(frozen=True, slots=True)
class ReplaceInvitationCommand:
    invitation_id: str
    actor_id: str
    expires_at: datetime | None = None
    reason: str = "Replaced for secure redelivery"
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))

    def __post_init__(self) -> None:
        _validate_command_text(
            invitation_id=self.invitation_id,
            actor_id=self.actor_id,
            reason=self.reason,
            correlation_id=self.correlation_id,
        )
        if self.expires_at is not None and not is_aware_datetime(self.expires_at):
            raise InvitationManagementError(
                "Invitation expiration must include timezone information."
            )


class ReplaceInvitation:
    """Revoke an unused token and return a new one exactly once."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
        token_factory: TokenFactory = generate_token,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory
        self._token_factory = token_factory

    def execute(self, command: ReplaceInvitationCommand) -> IssuedInvitationResult:
        at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            previous = unit_of_work.invitations.get_for_update(command.invitation_id)
            if previous is None:
                raise InvitationManagementError("Invitation was not found.")
            session, configuration = _load_invitation_scope(
                unit_of_work, previous.session_id
            )
            if previous.status_at(at=at) == InvitationStatus.EXPIRED:
                raise InvitationManagementError("Expired invitations cannot be resent.")
            try:
                revoked = previous.revoke(
                    actor_id=command.actor_id,
                    reason=command.reason,
                    at=at,
                )
            except ParticipationRuleViolation as error:
                raise InvitationManagementError(str(error)) from error
            expires_at = command.expires_at or previous.expires_at
            issuer = IssueInvitation(
                self._unit_of_work_factory,
                clock=self._clock,
                id_factory=self._id_factory,
                token_factory=self._token_factory,
            )
            replacement, token, access_code = issuer._build_invitation(
                session=session,
                configuration=configuration,
                assigned_group_id=previous.assigned_group_id,
                expires_at=expires_at,
                actor_id=command.actor_id,
                at=at,
            )
            unit_of_work.invitations.save(revoked)
            unit_of_work.invitations.add(replacement)
            _add_invitation_code(
                unit_of_work,
                session=session,
                invitation=replacement,
                access_code=access_code,
                actor_id=command.actor_id,
                at=at,
                id_factory=self._id_factory,
            )
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=at,
                    session_id=previous.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.UPDATED,
                    entity_type="session_invitation",
                    entity_id=previous.invitation_id,
                    correlation_id=command.correlation_id,
                    use_case="replace_invitation",
                    before_json={"status": previous.status.value},
                    after_json={
                        "status": revoked.status.value,
                        "replacement_invitation_id": replacement.invitation_id,
                    },
                    reason_text=command.reason,
                )
            )
            unit_of_work.audit_events.add(
                _invitation_event(
                    replacement,
                    event_id=self._id_factory(),
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    correlation_id=command.correlation_id,
                    occurred_at=at,
                    use_case="replace_invitation",
                )
            )
            unit_of_work.commit()
        return IssuedInvitationResult(
            invitation_id=replacement.invitation_id,
            token=token.plaintext,
            token_hint=token.token_hint,
            access_code=access_code,
            expires_at=replacement.expires_at,
            replaced_invitation_id=previous.invitation_id,
        )


@dataclass(frozen=True, slots=True)
class RevokeInvitationCommand:
    invitation_id: str
    actor_id: str
    reason: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))

    def __post_init__(self) -> None:
        _validate_command_text(
            invitation_id=self.invitation_id,
            actor_id=self.actor_id,
            reason=self.reason,
            correlation_id=self.correlation_id,
        )


class RevokeInvitation:
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

    def execute(self, command: RevokeInvitationCommand) -> None:
        at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            invitation = unit_of_work.invitations.get_for_update(command.invitation_id)
            if invitation is None:
                raise InvitationManagementError("Invitation was not found.")
            try:
                replacement = invitation.revoke(
                    actor_id=command.actor_id,
                    reason=command.reason,
                    at=at,
                )
            except ParticipationRuleViolation as error:
                raise InvitationManagementError(str(error)) from error
            unit_of_work.invitations.save(replacement)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=at,
                    session_id=invitation.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.UPDATED,
                    entity_type="session_invitation",
                    entity_id=invitation.invitation_id,
                    correlation_id=command.correlation_id,
                    use_case="revoke_invitation",
                    before_json={"status": invitation.status.value},
                    after_json={"status": replacement.status.value},
                    reason_text=command.reason,
                )
            )
            unit_of_work.commit()


@dataclass(frozen=True, slots=True)
class ExpireInvitationsCommand:
    session_id: str
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))

    def __post_init__(self) -> None:
        _validate_command_text(
            session_id=self.session_id,
            actor_id=self.actor_id,
            correlation_id=self.correlation_id,
        )


class ExpireInvitations:
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

    def execute(self, command: ExpireInvitationsCommand) -> int:
        at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.session.get(command.session_id) is None:
                raise InvitationManagementError("Session was not found.")
            due = unit_of_work.invitations.list_due_for_expiration(
                command.session_id, at
            )
            for invitation in due:
                expired = invitation.expire(at=at)
                unit_of_work.invitations.save(expired)
                unit_of_work.audit_events.add(
                    operational_audit_event(
                        event_id=self._id_factory(),
                        occurred_at=at,
                        session_id=invitation.session_id,
                        actor_id=command.actor_id,
                        actor_type=command.actor_type,
                        action=AuditAction.UPDATED,
                        entity_type="session_invitation",
                        entity_id=invitation.invitation_id,
                        correlation_id=command.correlation_id,
                        use_case="expire_invitations",
                        before_json={"status": invitation.status.value},
                        after_json={"status": expired.status.value},
                    )
                )
            unit_of_work.commit()
        return len(due)


def _load_invitation_scope(
    unit_of_work: UnitOfWork,
    session_id: str,
    *,
    for_update: bool = False,
) -> tuple[Session, SessionConfigurationVersion]:
    session = (
        unit_of_work.session.get_for_update(session_id)
        if for_update
        else unit_of_work.session.get(session_id)
    )
    if session is None:
        raise InvitationManagementError("Session was not found.")
    if session.status in {
        SessionStatus.CLOSED,
        SessionStatus.CANCELED,
        SessionStatus.ARCHIVED,
    }:
        raise InvitationManagementError(
            f"Invitations cannot be issued for a {session.status.value} session."
        )
    configuration = unit_of_work.session.get_active_configuration(session_id)
    if configuration is None:
        raise InvitationManagementError(
            "Activate a session configuration before issuing invitations."
        )
    return session, configuration


def _validate_assignment(
    session: Session,
    configuration: SessionConfigurationVersion,
    assigned_group_id: str | None,
) -> None:
    groups = {
        group.session_stakeholder_group_id: group
        for group in configuration.stakeholder_groups
        if group.is_active
    }
    if (
        session.stakeholder_selection_mode
        == StakeholderSelectionMode.INVITATION_ASSIGNED
        and assigned_group_id is None
    ):
        raise InvitationManagementError(
            "An assigned participant group is required for this session."
        )
    if assigned_group_id is not None and assigned_group_id not in groups:
        raise InvitationManagementError(
            "The selected participant group is not active in this configuration."
        )


def _add_invitation_code(
    unit_of_work: UnitOfWork,
    *,
    session: Session,
    invitation: SessionInvitation,
    access_code: str | None,
    actor_id: str,
    at: datetime,
    id_factory: IdFactory,
) -> None:
    if session.access_code_mode != AccessCodeMode.PER_INVITATION_CODE:
        return
    if access_code is None:
        raise AssertionError("Per-invitation access code was not generated.")
    unit_of_work.access_codes.add_invitation_code(
        access_code_id=id_factory(),
        session_id=session.session_id,
        invitation_id=invitation.invitation_id,
        plaintext_code=access_code,
        expires_at=invitation.expires_at,
        created_at=at,
        created_by=actor_id,
    )


def _invitation_event(
    invitation: SessionInvitation,
    *,
    event_id: str,
    actor_id: str,
    actor_type: ActorType,
    correlation_id: str,
    occurred_at: datetime,
    use_case: str = "issue_invitation",
):
    return operational_audit_event(
        event_id=event_id,
        occurred_at=occurred_at,
        session_id=invitation.session_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=AuditAction.INVITED,
        entity_type="session_invitation",
        entity_id=invitation.invitation_id,
        correlation_id=correlation_id,
        use_case=use_case,
        after_json={
            "status": invitation.status.value,
            "configuration_version_id": invitation.configuration_version_id,
            "assigned_group_id": invitation.assigned_group_id,
            "token_hint": invitation.token_hint,
            "expires_at": invitation.expires_at,
            "send_count": invitation.send_count,
        },
    )


def _validate_command_text(**values: str) -> None:
    for field_name, value in values.items():
        if not value.strip():
            raise InvitationManagementError(
                f"{field_name.replace('_', ' ').title()} cannot be empty."
            )
