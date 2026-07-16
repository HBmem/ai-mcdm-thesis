from enum import StrEnum

class SessionStatus(StrEnum):
    DRAFT = "Draft"
    OPEN = "Open"
    CLOSED = "Closed"
    PROCESSED = "Processed"
    PUBLISHED = "Published"
    ARCHIVED = "Archived"

class SessionVisibility(StrEnum):
    PUBLIC = "Public"
    PRIVATE = "Private"
    UNLISTED = "Unlisted"

class ParticipantStatus(StrEnum):
    INVITED = "Invited"
    STARTED = "Started"
    SUBMITTED = "Submitted"
    DISABLED = "Disabled"
    EXPIRED = "Expired"

class WeightingMethod(StrEnum):
    AHP = "AHP"
    FUZZY_AHP = "Fuzzy AHP"

class RankingMethod(StrEnum):
    TOPSIS = "TOPSIS"
    FUZZY_TOPSIS = "Fuzzy TOPSIS"

class PreferenceScale(StrEnum):
    FIVE_POINT_SCALE = "5 Point Scale"
    SEVEN_POINT_SCALE = "7 Point Scale"

class ParticipationMethod(StrEnum):
    SINGLE_PARTICIPANT = "Single Participant"
    MULTIPLE_PARTICIPANTS = "Multiple Participants"

class AggregationMethod(StrEnum):
    GROUP_STAKEHOLDER = "Group Stakeholder"
    INDIVIDUAL = "Individual"

class ScenarioType(StrEnum):
    STANDARD = "standard"
    HIERARCHICAL = "hierarchical"

# TODO: To be used later for audit logging to identify the type of actor performing an action and the type of entity being acted upon.
class ActorType(StrEnum):
    ADMIN = "Admin"
    MODERATOR = "moderator"
    PARTICIPANT = "participant"
    SYSTEM = "system"
    AI_SERVICE = "ai_service"
    IMPORT_PROCESS = "import_process"
    API_CLIENT = "api_client"

class EntityType(StrEnum):
    SCENARIO_SNAPSHOT = "scenario_snapshot"
    SESSION = "session"
    STAKEHOLDER_GROUP = "stakeholder_group"
    PARTICIPANT = "participant"
    SUBMISSION = "submission"
    PROCESSING_RUN = "processing_run"
    ANALYSIS_RESULT = "analysis_result"
    SENSITIVITY_RUN = "sensitivity_run"
    AI_ANALYSIS = "ai_analysis"
    PUBLICATION = "publication"
    EXPORT = "export"