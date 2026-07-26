from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Self

from poli_insight.domain.enums import ParticipantStatus
from poli_insight.domain.submissions import Submission

class ParticipantRuleViolation(ValueError):
    """Raised when an operation violates participant business rule."""
    pass

def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and value.tzinfo is None:
        raise ParticipantRuleViolation(
            f"{field_name} must include timezone information."
        )
    
@dataclass
class Participant:
    """A person's enrollment in one session."""
    participant_id: str
    session_id: str
    user_id: str | None
    stakeholder_group_id: str

    name: str | None
    alias: str | None

    access_status: ParticipantStatus
    joined_at: datetime | None
    disabled_at: datetime | None
    disabled_by: str | None

    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_status()
        self._validate_timestamps()

    @classmethod
    def create(
        cls,
        *,
        participant_id: str,
        session_id: str,
        user_id: str | None,
        stakeholder_group_id: str,
        name: str | None,
        alias: str | None,
        actor_id: str,
        now: datetime | None = None,
    ) -> Self:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if not actor_id.strip():
            raise ParticipantRuleViolation(
                "Creating actor cannot be empty."
            )
        
        return cls(
            participant_id=participant_id,
            session_id=session_id,
            user_id=user_id,
            stakeholder_group_id=stakeholder_group_id,
            name=name.strip() if name is not None else None,
            alias=alias.strip() if alias is not None else None,
            access_status=ParticipantStatus.ACTIVE,
            joined_at=None,
            disabled_at=None,
            disabled_by=None,
            created_at=timestamp,
            created_by=actor_id,
            updated_at=timestamp,
            updated_by=actor_id,
        )
    
    def mark_joined(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.access_status != ParticipantStatus.ACTIVE:
            raise ParticipantRuleViolation(
                "Only an active participant can join."
            )

        # Preserve the time of the first successful entry.
        if self.joined_at is None:
            self.joined_at = timestamp
            self._mark_updated(actor_id, timestamp)

    def disable(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.access_status == ParticipantStatus.WITHDRAWN:
            raise ParticipantRuleViolation(
                "A withdrawn participant cannot be disabled."
            )

        self.access_status = ParticipantStatus.DISABLED
        self.disabled_at = timestamp
        self.disabled_by = actor_id
        self._mark_updated(actor_id, timestamp)
    
    def withdraw(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        self.access_status = ParticipantStatus.WITHDRAWN
        self._mark_updated(actor_id, timestamp)

    def _validate_identity(self) -> None:
        required_values = {
            "participant_id": self.participant_id,
            "session_id": self.session_id,
            "stakeholder_group_id": self.stakeholder_group_id,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
        }

        for field_name, value in required_values.items():
            if not value.strip():
                raise ParticipantRuleViolation(
                    f"{field_name} cannot be empty."
                )

        if self.user_id is not None and not self.user_id.strip():
            raise ParticipantRuleViolation(
                "user_id cannot be blank."
            )

        if self.name is not None and not self.name.strip():
            raise ParticipantRuleViolation(
                "Participant name cannot be blank."
            )

        if self.alias is not None and not self.alias.strip():
            raise ParticipantRuleViolation(
                "Participant alias cannot be blank."
            )

        if self.name is None and self.alias is None:
            raise ParticipantRuleViolation(
                "A participant must have a name or alias."
            )

    def _validate_status(self) -> None:
        if (
            self.access_status == ParticipantStatus.DISABLED
            and (
                self.disabled_at is None
                or self.disabled_by is None
            )
        ):
            raise ParticipantRuleViolation(
                "A disabled participant requires disabled_at "
                "and disabled_by."
            )

    def _validate_timestamps(self) -> None:
        _require_aware_datetime(self.joined_at, "joined_at")
        _require_aware_datetime(self.disabled_at, "disabled_at")
        _require_aware_datetime(self.created_at, "created_at")
        _require_aware_datetime(self.updated_at, "updated_at")

        if self.updated_at < self.created_at:
            raise ParticipantRuleViolation(
                "updated_at cannot be earlier than created_at."
            )

    def _mark_updated(
        self,
        actor_id: str,
        timestamp: datetime,
    ) -> None:
        if not actor_id.strip():
            raise ParticipantRuleViolation(
                "Updating actor cannot be empty."
            )

        self.updated_at = timestamp
        self.updated_by = actor_id
