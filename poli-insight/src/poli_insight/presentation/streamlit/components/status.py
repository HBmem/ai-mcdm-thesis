"""Consistent labels and visual semantics for independent workflow states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import streamlit as st

from poli_insight.domain.enum import (
    ReportApprovalStatus,
    RunStatus,
    SessionStatus,
    ValidationStatus,
)


class StatusTone(StrEnum):
    NEUTRAL = "neutral"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    label: str
    icon: str
    tone: StatusTone


_SESSION_STATUS: dict[StrEnum, StatusPresentation] = {
    SessionStatus.DRAFT: StatusPresentation(
        "Draft", ":material/edit_note:", StatusTone.NEUTRAL
    ),
    SessionStatus.SCHEDULED: StatusPresentation(
        "Scheduled", ":material/schedule:", StatusTone.INFO
    ),
    SessionStatus.OPEN: StatusPresentation(
        "Open", ":material/event_available:", StatusTone.SUCCESS
    ),
    SessionStatus.PAUSED: StatusPresentation(
        "Paused", ":material/pause_circle:", StatusTone.WARNING
    ),
    SessionStatus.CLOSED: StatusPresentation(
        "Closed", ":material/lock:", StatusTone.NEUTRAL
    ),
    SessionStatus.CANCELED: StatusPresentation(
        "Canceled", ":material/cancel:", StatusTone.ERROR
    ),
    SessionStatus.ARCHIVED: StatusPresentation(
        "Archived", ":material/archive:", StatusTone.NEUTRAL
    ),
}

_VALIDATION_STATUS: dict[StrEnum, StatusPresentation] = {
    ValidationStatus.PENDING: StatusPresentation(
        "Pending", ":material/hourglass_empty:", StatusTone.NEUTRAL
    ),
    ValidationStatus.RUNNING: StatusPresentation(
        "Running", ":material/progress_activity:", StatusTone.INFO
    ),
    ValidationStatus.VALID: StatusPresentation(
        "Valid", ":material/check_circle:", StatusTone.SUCCESS
    ),
    ValidationStatus.VALID_WITH_WARNING: StatusPresentation(
        "Valid with warnings", ":material/warning:", StatusTone.WARNING
    ),
    ValidationStatus.INVALID: StatusPresentation(
        "Invalid", ":material/error:", StatusTone.ERROR
    ),
    ValidationStatus.ERROR: StatusPresentation(
        "Error", ":material/report:", StatusTone.ERROR
    ),
}

_RUN_STATUS: dict[StrEnum, StatusPresentation] = {
    RunStatus.QUEUED: StatusPresentation(
        "Queued", ":material/queue:", StatusTone.NEUTRAL
    ),
    RunStatus.RUNNING: StatusPresentation(
        "Running", ":material/progress_activity:", StatusTone.INFO
    ),
    RunStatus.SUCCEEDED: StatusPresentation(
        "Succeeded", ":material/check_circle:", StatusTone.SUCCESS
    ),
    RunStatus.FAILED: StatusPresentation(
        "Failed", ":material/error:", StatusTone.ERROR
    ),
    RunStatus.CANCELED: StatusPresentation(
        "Canceled", ":material/cancel:", StatusTone.WARNING
    ),
}

_REPORT_STATUS: dict[StrEnum, StatusPresentation] = {
    ReportApprovalStatus.DRAFT: StatusPresentation(
        "Draft", ":material/draft:", StatusTone.NEUTRAL
    ),
    ReportApprovalStatus.REVIEW_REQUIRED: StatusPresentation(
        "Review required", ":material/rate_review:", StatusTone.WARNING
    ),
    ReportApprovalStatus.APPROVED: StatusPresentation(
        "Approved", ":material/verified:", StatusTone.SUCCESS
    ),
    ReportApprovalStatus.REJECTED: StatusPresentation(
        "Rejected", ":material/block:", StatusTone.ERROR
    ),
    ReportApprovalStatus.WITHDRAWN: StatusPresentation(
        "Withdrawn", ":material/remove_circle:", StatusTone.WARNING
    ),
}


def status_presentation(value: StrEnum) -> StatusPresentation:
    for mapping in (
        _SESSION_STATUS,
        _VALIDATION_STATUS,
        _RUN_STATUS,
        _REPORT_STATUS,
    ):
        presentation = mapping.get(value)
        if presentation is not None:
            return presentation
    return StatusPresentation(
        value.value.replace("_", " ").title(),
        ":material/info:",
        StatusTone.NEUTRAL,
    )


def render_status(value: StrEnum, *, detail: str | None = None) -> None:
    presentation = status_presentation(value)
    st.badge(
        presentation.label,
        icon=presentation.icon,
        color=_badge_color(presentation.tone),
    )
    if detail:
        st.caption(detail)


def _badge_color(
    tone: StatusTone,
) -> Literal["gray", "blue", "green", "orange", "red"]:
    return {
        StatusTone.NEUTRAL: "gray",
        StatusTone.INFO: "blue",
        StatusTone.SUCCESS: "green",
        StatusTone.WARNING: "orange",
        StatusTone.ERROR: "red",
    }[tone]
