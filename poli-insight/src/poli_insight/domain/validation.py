from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from poli_insight.domain.enums import (
    WeightingMethod,
    PreferenceScale,
    PreferenceElicitationMethod,
)

@dataclass
class SubmissionValidation:
    validation_id: str
    submission_id: str

    answers_hash: str
    weighting_method: WeightingMethod
    preference_scale: PreferenceScale
    preference_elicitation_method: PreferenceElicitationMethod

    completion_ratio: float
    weights: dict[str, float]
    consistency_ratio: float | None
    is_valid: bool
    errors: tuple[str, ...]

    validator_version: str
    validated_at: datetime
    validated_by: str