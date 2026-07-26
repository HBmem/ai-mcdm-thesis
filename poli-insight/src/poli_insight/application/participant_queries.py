from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from poli_insight.domain.participant import Participant
from poli_insight.domain.submissions import Submission

@dataclass(frozen=True, slots=True)
class ParticipantPage:
    items: tuple[Participant, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 1

        return ceil(self.total / self.page_size)

@dataclass(frozen=True, slots=True)
class ParticipantDashboardMetric:
    total: int
    submitted: int
    revisions: int
    withdrawn: int

@dataclass(frozen=True, slots=True)
class ParticipantTableItem:
    participant: Participant
    draft_submission: Submission | None
    effective_submission: Submission | None

@dataclass(frozen=True, slots=True)
class ParticipantTablePage:
    items: tuple[ParticipantTableItem, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 1

        return ceil(self.total / self.page_size)