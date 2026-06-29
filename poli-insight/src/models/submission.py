from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class PreferenceSubmission:
    submission_id: str
    session_id: str
    participant_id: str
    submission_version: int
    preference_scale: str
    raw_preference_json: str
    transformed_preference_json: str | None
    validation_status: str | None
    is_current: bool
    submitted_at: str
    superseded_at: str | None
    created_at: str
    updated_at: str