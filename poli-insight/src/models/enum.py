from enum import StrEnum

class SessionStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    PROCESSED = "processed"
    PUBLISHED = "published"
    ARCHIVED = "archived"

class SessionVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"

class ParticipantStatus(StrEnum):
    INVITED = "invited"
    STARTED = "started"
    SUBMITTED = "submitted"
    DISABLED = "disabled"
    EXPIRED = "expired"

class WeightingMethod(StrEnum):
    AHP = "ahp"
    FUZZY_AHP = "fuzzy_ahp"

class RankingMethod(StrEnum):
    TOPSIS = "topsis"
    FUZZY_TOPSIS = "fuzzy_topsis"

class PreferenceScale(StrEnum):
    FIVE_POINT_SCALE = "5_point_scale"
    SEVEN_POINT_SCALE = "7_point_scale"

class ParticipationMode(StrEnum):
    SINGLE_PARTICIPANT = "single_participant"
    MULTIPLE_PARTICIPANTS = "multiple_participants"

class AggregationMethod(StrEnum):
    GROUP_STAKEHOLDER = "group_stakeholder"
    INDIVIDUAL = "individual"