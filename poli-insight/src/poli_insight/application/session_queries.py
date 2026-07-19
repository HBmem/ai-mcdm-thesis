from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from poli_insight.domain.enums import (
    PreferenceScale,
    RankingMethod,
    SessionStatus,
    SessionVisibility,
    WeightingMethod,
)
from poli_insight.domain.sessions import SessionScenario
from poli_insight.domain.scenario import ScenarioSnapshot


@dataclass(frozen=True, slots=True)
class SessionFilters:
    scenario_id: str | None = None
    scenario_version: str | None = None
    status: SessionStatus | None = None
    visibility: SessionVisibility | None = None
    weighting_method: WeightingMethod | None = None
    ranking_method: RankingMethod | None = None
    preference_scale: PreferenceScale | None = None
    require_access_code: bool | None = None
    allow_resubmissions: bool | None = None


@dataclass(frozen=True, slots=True)
class SessionPage:
    items: tuple[SessionScenario, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 1

        return ceil(self.total / self.page_size)

@dataclass(frozen=True, slots=True)
class SessionTableItem:
    session: SessionScenario
    snapshot: ScenarioSnapshot | None


@dataclass(frozen=True, slots=True)
class SessionTablePage:
    items: tuple[SessionTableItem, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 1

        return ceil(self.total / self.page_size)