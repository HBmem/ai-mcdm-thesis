"""Persistence ports for participant admission and research consent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from poli_insight.domain.participation import ParticipantConsent


class AccessAttemptOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AccessCodeVerificationResult:
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


@dataclass(frozen=True, slots=True)
class AccessAttemptRecord:
    access_attempt_id: str
    session_id: str
    attempted_at: datetime
    outcome: AccessAttemptOutcome
    reason_code: str
    invitation_id: str | None = None
    access_code_id: str | None = None
    rate_limit_key_hash: str | None = None
    network_metadata_json: Mapping[str, Any] = field(default_factory=dict)


class EnrollmentAccessCodeRepository(Protocol):
    def verify_for_enrollment(
        self,
        *,
        session_id: str,
        invitation_id: str | None,
        plaintext_code: str,
        at: datetime,
    ) -> AccessCodeVerificationResult: ...

    def record_successful_use(
        self,
        *,
        access_code_id: str,
        at: datetime,
    ) -> None: ...

    def add_shared_code(
        self,
        *,
        access_code_id: str,
        session_id: str,
        plaintext_code: str,
        created_at: datetime,
        created_by: str,
    ) -> None: ...

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
    ) -> None: ...


class AccessAttemptRepository(Protocol):
    def add(self, attempt: AccessAttemptRecord) -> None: ...


class ParticipantConsentRepository(Protocol):
    def add(self, consent: ParticipantConsent) -> None: ...

    def get_for_participant(
        self,
        participant_id: str,
        configuration_version_id: str,
        consent_version: str,
    ) -> ParticipantConsent | None: ...
