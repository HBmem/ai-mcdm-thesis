from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil

from poli_insight.domain.enums import SubmissionStatus

@dataclass(frozen=True, slots=True)
class SubmissionDashboardMetrics:
    expected: int
    complete: int
    in_progress: int
    missing: int
    high_consistency_ratio: int


@dataclass(frozen=True, slots=True)
class SubmissionTableItem:
    participant_id: str
    participant_name: str | None
    participant_alias: str | None
    stakeholder_group_id: str
    stakeholder_group_name: str
    submission_id: str | None
    submission_status: SubmissionStatus | None
    submitted_at: datetime | None
    completion_ratio: float
    consistency_ratio: float | None
    validation_status: str


@dataclass(frozen=True, slots=True)
class SubmissionDashboardPage:
    metrics: SubmissionDashboardMetrics
    items: tuple[SubmissionTableItem, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 1

        return ceil(self.total / self.page_size)