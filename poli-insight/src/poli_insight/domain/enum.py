"""
This module provides the enums for the project.

Enums values are persistent database/API values.
"""


from enum import StrEnum

class ScenarioDefinitionStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"

class ScenarioSnapshotStatus(StrEnum):
    VALIDATING = "validating"
    READY = "ready"
    INVALID = "invalid"
    RETIRED = "retired"

class ScenarioType(StrEnum):
    STANDARD = "standard"
    HIERARCHICAL = "hierarchical"

class ScenarioFileRole(StrEnum):
    SCENARIO_CONFIG = "scenario_config"
    CRITERIA_CONFIG = "criteria_config"
    DATA_SOURCE_CONFIG = "data_source_config"
    PREPROCESSING_CONFIG = "preprocessing_config"
    SESSION_RULES = "session_rules"
    UI_CONFIG = "ui_config"
    SOURCE_DATA = "source_data"
    CUSTOM_FUNCTION = "custom_function"
    OTHER = "other"

class CriterionDirection(StrEnum):
    COST = "cost"
    BENEFIT = "benefit"

class CriterionDataType(StrEnum):
    NUMERIC = "numeric"
    ORDINAL = "ordinal"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"

class SessionStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    OPEN = "open"
    PAUSED = "paused"
    CLOSED = "closed"
    CANCELED = "canceled"
    ARCHIVED = "archived"

class Discoverability(StrEnum):
    LISTED = "listed"
    UNLISTED = "unlisted"

class EnrollmentMode(StrEnum):
    OPEN = "open"
    INVITATION_ONLY = "invitation_only"

class AccessCodeMode(StrEnum):
    NONE = "none"
    SHARED_SESSION_CODE = "shared_session_code"
    PER_INVITATION_CODE = "per_invitation_code"

class StakeholderSelectionMode(StrEnum):
    SELF_SELECT = "self_select"
    INVITATION_ASSIGNED = "invitation_assigned"
    MODERATOR_ASSIGNED = "moderator_assigned"

class ResponseFormat(StrEnum):
    PAIRWISE = "pairwise"
    DIRECT_RATING = "direct_rating"
    DIRECT_RANKING = "direct_ranking"

class ResponseTargetType(StrEnum):
    CRITERION = "criterion"
    ALTERNATIVE = "alternative"

class QuestionType(StrEnum):
    CRITERION_PAIR = "criterion_pair"
    CRITERION_RATING = "criterion_rating"
    ALTERNATIVE_RATING = "alternative_rating"
    ALTERNATIVE_RANK = "alternative_rank" # Might not use this in the future

class AlgorithmRole(StrEnum):
    WEIGHTING = "weighting"
    WITHIN_GROUP_AGGREGATION = "within_group_aggregation"
    ACROSS_GROUP_AGGREGATION = "across_group_aggregation"
    RANKING = "ranking"
    VALIDATION = "validation"
    ANALYSIS = "analysis"

# Changed when new algorithm providers are used
class AlgorithmProvider(StrEnum):
    PYDECISION = "pydecision"
    INTERNAL = "internal" # will not be used for the thesis

class ParticipantAccessStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    WITHDRAWN = "withdrawn"

class ParticipantProgressStatus(StrEnum):
    INVITED = "invited"
    ENROLLED = "enrolled"
    STARTED = "started"
    SUBMITTED = "submitted"
    COMPLETED = "completed"

class InvitationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    REVOKED = "revoked"
    DELIVERY_FAILED = "delivery_failed"

class SubmissionStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"

class ValidationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    VALID = "valid"
    VALID_WITH_WARNING = "valid_with_warnings"
    INVALID = "invalid"
    ERROR = "error"

class MessageSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"

class RunInclusionStatus(StrEnum):
    INCLUDED = "included"
    EXCLUDED_INVALID = "excluded_invalid"
    EXCLUDED_SUPERSEDED = "excluded_superseded"
    EXCLUDED_WITHDRAWN = "excluded_withdrawn"
    EXCLUDED_DISABLED = "excluded_disabled"
    EXCLUDED_CUTOFF = "excluded_cutoff"
    EXCLUDED_MODERATOR = "excluded_moderator"
    EXCLUDED_ERROR = "excluded_error"

class MissingGroupPolicy(StrEnum):
    FAIL = "fail"
    EXCLUDED_RENORMALIZED = "exclude_and_renormalize"
    ZERO_CONTRIBUTION = "zero_contribution"

class AnalysisType(StrEnum):
    SENSITIVITY = "sensitivity"
    ROBUSTNESS = "robustness"
    STAKEHOLDER_COMPARISON = "stakeholder_comparison"
    PARTICIPANT_IMPACT = "participant_impact"
    COMMENT_SUMMARY = "comment_summary"
    CUSTOM = "custom"

class ArtifactType(StrEnum):
    INPUT_MANIFEST = "input_manifest"
    DECISION_MATRIX = "decision_matrix"
    PAIRWISE_MATRIX = "pairwise_matrix"
    NORMALIZED_MATRIX = "normalized_matrix"
    WEIGHTING_VECTOR = "weight_vector"
    RANKING_TRACE = "ranking_trace"
    DIAGNOSTIC = "diagnostic"
    STRUCTURED_RESULT = "structured_result"
    ANALYSIS_BUNDLE = "analysis_bundle"
    LOG = "log"
    OTHER = "other"

class ReportAudience(StrEnum):
    STAKEHOLDER_GROUP = "stakeholder_group"
    MODERATOR = "moderator"
    PARTICIPANT = "participant"
    PUBLIC = "public"

class ReportApprovalStatus(StrEnum):
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

class ActorType(StrEnum):
    USER = "user"
    PARTICIPANT = "participant"
    SYSTEM = "system"
    AI_SERVICE = "ai_service"
    IMPORT_PROCESS = "import_process"
    API_CLIENT = "api_client"

class AuditAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    OPENED = "opened"
    CLOSED = "closed"
    INVITED = "invited"
    REDEEMED = "redeemed"
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    INCLUDED = "included"
    EXCLUDED = "excluded"
    PROCESSED = "processed"
    ANALYZED = "analyzed"
    APPROVED = "approved"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    REDACTED = "redacted"
