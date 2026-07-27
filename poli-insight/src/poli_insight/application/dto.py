from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, TypeAlias

from poli_insight.domain.enums import (
    AggregationMethod,
    ParticipationMethod,
    PreferenceScale,
    RankingMethod,
    SessionVisibility,
    WeightingMethod,
    ParticipantStatus,
    PreferenceElicitationMethod
)
from poli_insight.domain.scenario import ScenarioBundle


# =============================================================================
# SESSION COMMANDS
# =============================================================================

@dataclass(frozen=True)
class CreateSessionCommand:
    scenario: ScenarioBundle
    title: str
    description: str | None
    admin_notes: str | None

    visibility: SessionVisibility
    participation_method: ParticipationMethod
    preference_scale: PreferenceScale
    weighting_method: WeightingMethod
    ranking_method: RankingMethod
    aggregation_method: AggregationMethod
    preference_elicitation_method: PreferenceElicitationMethod

    require_access_code: bool
    access_code_type: str | None
    allow_resubmissions: bool

    start_at: datetime | None
    end_at: datetime | None

    voting_power: Mapping[str, float]
    actor_id: str

@dataclass(frozen=True)
class UpdateSessionCommand:
    session_id: str
    title: str
    description: str | None
    admin_notes: str | None
    visibility: SessionVisibility
    end_at: datetime | None
    actor_id: str


# =============================================================================
# PARTICIPANT COMMANDS
# =============================================================================

@dataclass(frozen=True)
class CreateParticipantCommand:
    participant_id: str
    session_id: str
    user_id: str | None
    stakeholder_group_id: str

    name: str | None
    alias: str | None
    access_status: ParticipantStatus
    disabled_at: datetime | None
    disabled_by: str | None

    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

# =============================================================================
# SUBMISSION COMMANDS
# =============================================================================

@dataclass(frozen=True, slots=True)
class StartSubmissionCommand:
    """Requests creation or resumption of a participant's draft submission."""
    participant_id: str
    actor_id: str

dataclass(frozen=True, slots=True)
class DirectRatingAnswer:
    criterion_id: str
    option_id: str

@dataclass(frozen=True, slots=True)
class PairwiseComparisonAnswer:
    left_criterion_id: str
    right_criterion_id: str
    option_id: str

PreferenceAnswer: TypeAlias = (
    DirectRatingAnswer | PairwiseComparisonAnswer
)

@dataclass(frozen=True, slots=True)
class SavePreferenceAnswerCommand:
    submission_id: str
    answer: PreferenceAnswer
    actor_id: str


@dataclass(frozen=True, slots=True)
class SavePreferenceAnswersCommand:
    submission_id: str
    answers: tuple[PreferenceAnswer, ...]
    actor_id: str

@dataclass(frozen=True)
class ValidateSubmissionCommand:
    """Requests validation without finalizing the submission."""
    submission_id: str
    actor_id: str

@dataclass(frozen=True)
class SubmitSubmissionCommand:
    """Finalizes a draft."""
    submission_id: str
    actor_id: str

# TODO: Create read only representation of questions for UI
# @dataclass(frozen=True)
# class PairwiseQuestionDTO:
#     """Read-only representation of one generated question for the UI."""
#     left_criterion_id: str
#     left_criterion_label: str
#     right_criterion_id: str
#     right_criterion_label: str
#     options: tuple[ScaleOptionDTO, ...]
#     selected_option_id: str | None


@dataclass(frozen=True)
class SubmissionDraftDTO:
    """Read-only snapshot of draft progress returned to the UI: submission identity, ordered questions, saved answers, completion count, and timestamps."""
    submission_id: str
    participant_id: str
    attempt_number: int
    questions: tuple[PreferenceAnswer, ...]
    answered_question_count: int
    expected_question_count: int
    completion_ratio: float
    last_saved_at: datetime | None


@dataclass(frozen=True)
class SubmissionValidationDTO:
    """Read-only validation result: validity, completion ratio, errors, generated weights, consistency ratio, and validation metadata."""
    submission_id: str
    is_valid: bool
    completion_ratio: float
    weights: Mapping[str, float]
    consistency_ratio: float | None
    errors: tuple[str, ...]
    validated_at: datetime
