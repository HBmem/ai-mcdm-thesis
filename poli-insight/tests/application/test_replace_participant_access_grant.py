from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from poli_insight.application.use_cases.replace_participant_access_grant import (
    ReplaceParticipantAccessGrant,
    ReplaceParticipantAccessGrantCommand,
    ReplaceParticipantAccessGrantError,
)
from poli_insight.domain.enum import ParticipantAccessStatus
from poli_insight.domain.participation import Participant, ParticipantAccessGrant
from poli_insight.infrastructure.auth.tokens import IssuedToken, digest_token

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
OLD_TOKEN = "old-private-resume-token-with-sufficient-random-looking-material"
NEW_TOKEN = "new-private-resume-token-with-sufficient-random-looking-material"


class _GrantRepository:
    def __init__(self, grant: ParticipantAccessGrant | None) -> None:
        self.current = grant
        self.added: list[ParticipantAccessGrant] = []
        self.saved: list[ParticipantAccessGrant] = []

    def get_current_for_participant_for_update(self, participant_id: str, *, at):
        grant = self.current
        if grant is None or grant.participant_id != participant_id:
            return None
        return grant if grant.is_active(at=at) else None

    def add(self, grant: ParticipantAccessGrant) -> None:
        self.added.append(grant)

    def save(self, grant: ParticipantAccessGrant) -> None:
        self.saved.append(grant)
        self.current = self.added[-1]


class _Repository:
    def __init__(self, value) -> None:
        self.value = value

    def get_for_update(self, identifier: str):
        return self.value if self.value.participant_id == identifier else None


class _AuditRepository:
    def __init__(self) -> None:
        self.events = []

    def add(self, event) -> None:
        self.events.append(event)


class _UnitOfWork:
    def __init__(self, participant, grant) -> None:
        self.participants = _Repository(participant)
        self.access_grants = _GrantRepository(grant)
        self.audit_events = _AuditRepository()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def commit(self) -> None:
        self.committed = True


def _participant(*, status=ParticipantAccessStatus.ACTIVE) -> Participant:
    participant = Participant(
        participant_id="participant-1",
        session_id="session-1",
        configuration_version_id="configuration-1",
        session_stakeholder_group_id="group-1",
        access_status=ParticipantAccessStatus.ACTIVE,
        enrolled_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=1),
        created_by="participant-1",
        updated_at=NOW - timedelta(days=1),
        updated_by="participant-1",
    )
    if status == ParticipantAccessStatus.DISABLED:
        return participant.disable(
            actor_id="admin-1",
            reason="Test disable",
            at=NOW,
        )
    return participant


def _grant(*, expires_at=NOW + timedelta(days=1)) -> ParticipantAccessGrant:
    return ParticipantAccessGrant(
        access_grant_id="grant-old",
        participant_id="participant-1",
        token_digest=digest_token(OLD_TOKEN),
        issued_at=NOW - timedelta(days=1),
        expires_at=expires_at,
    )


def _command(**changes) -> ReplaceParticipantAccessGrantCommand:
    values = {
        "session_id": "session-1",
        "participant_id": "participant-1",
        "actor_id": "admin-1",
        "actor_roles": frozenset({"admin"}),
        "correlation_id": "correlation-1",
    }
    values.update(changes)
    return ReplaceParticipantAccessGrantCommand(**values)


def test_replacement_is_digest_only_linked_audited_and_redacted() -> None:
    participant = _participant()
    old_grant = _grant()
    unit_of_work = _UnitOfWork(participant, old_grant)
    use_case = ReplaceParticipantAccessGrant(
        lambda: unit_of_work,
        clock=lambda: NOW,
        id_factory=iter(("grant-new", "audit-1")).__next__,
        token_factory=lambda: IssuedToken(
            plaintext=NEW_TOKEN,
            token_digest=digest_token(NEW_TOKEN),
            token_hint=f"…{NEW_TOKEN[-6:]}",
        ),
    )

    result = use_case.execute(_command())

    assert unit_of_work.committed
    assert result.access_token == NEW_TOKEN
    assert NEW_TOKEN not in repr(result)
    assert "<redacted>" in repr(result)
    replacement = unit_of_work.access_grants.added[0]
    revoked = unit_of_work.access_grants.saved[0]
    assert replacement.token_digest == digest_token(NEW_TOKEN)
    assert not hasattr(replacement, "access_token")
    assert revoked.revoked_at == NOW
    assert revoked.replaced_by_grant_id == replacement.access_grant_id
    assert participant.configuration_version_id == "configuration-1"
    assert participant.session_stakeholder_group_id == "group-1"
    event = unit_of_work.audit_events.events[0]
    serialized_event = repr(event) + str(event.before_json) + str(event.after_json)
    assert NEW_TOKEN not in serialized_event
    assert digest_token(NEW_TOKEN) not in serialized_event
    assert event.after_json["replacement_access_grant_id"] == "grant-new"


@pytest.mark.parametrize(
    ("participant", "grant", "command", "message"),
    (
        (_participant(status=ParticipantAccessStatus.DISABLED), _grant(), _command(), "active participant"),
        (_participant(), None, _command(), "no current active"),
        (_participant(), _grant(expires_at=NOW), _command(), "no current active"),
        (_participant(), _grant(), _command(session_id="session-other"), "does not belong"),
    ),
)
def test_replacement_rejects_invalid_lifecycle_states(
    participant, grant, command, message
) -> None:
    unit_of_work = _UnitOfWork(participant, grant)
    use_case = ReplaceParticipantAccessGrant(
        lambda: unit_of_work,
        clock=lambda: NOW,
    )

    with pytest.raises(ReplaceParticipantAccessGrantError, match=message):
        use_case.execute(command)

    assert not unit_of_work.committed


def test_replacement_requires_authenticated_admin_and_future_expiration() -> None:
    with pytest.raises(ReplaceParticipantAccessGrantError, match="administrator"):
        _command(actor_roles=frozenset())

    unit_of_work = _UnitOfWork(_participant(), _grant())
    use_case = ReplaceParticipantAccessGrant(
        lambda: unit_of_work,
        clock=lambda: NOW,
    )
    with pytest.raises(ReplaceParticipantAccessGrantError, match="future"):
        use_case.execute(_command(expires_at=NOW))


def test_concurrent_replacement_is_reported_without_issuing_a_token() -> None:
    unit_of_work = _UnitOfWork(_participant(), _grant())

    def concurrent_lookup(participant_id: str, *, at):
        del participant_id, at
        raise ValueError("multiple active grants")

    unit_of_work.access_grants.get_current_for_participant_for_update = (
        concurrent_lookup
    )
    token_factory_called = False

    def token_factory():
        nonlocal token_factory_called
        token_factory_called = True
        raise AssertionError("Token generation must follow the lock check")

    use_case = ReplaceParticipantAccessGrant(
        lambda: unit_of_work,
        clock=lambda: NOW,
        token_factory=token_factory,
    )

    with pytest.raises(ReplaceParticipantAccessGrantError, match="concurrently"):
        use_case.execute(_command())

    assert not token_factory_called
    assert not unit_of_work.committed
