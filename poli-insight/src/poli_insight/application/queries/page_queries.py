"""Read models used by the Streamlit page layer.

Page queries deliberately return small immutable projections rather than domain
aggregates or ORM rows.  They are read-only and do not share a transaction with
commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Generic, Mapping, Protocol, TypeVar

from poli_insight.domain.enum import (
    AccessCodeMode,
    EnrollmentMode,
    SessionStatus,
)


ItemT = TypeVar("ItemT", covariant=True)


class PageQueryError(RuntimeError):
    """Safe application-level failure raised by page query adapters."""


@dataclass(frozen=True, slots=True)
class PageResult(Generic[ItemT]):
    """One validated page of query results."""

    items: tuple[ItemT, ...]
    page: int
    page_size: int
    total: int

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be at least 1.")
        if self.page_size < 1:
            raise ValueError("page_size must be at least 1.")
        if self.total < 0:
            raise ValueError("total cannot be negative.")
        if len(self.items) > self.page_size:
            raise ValueError("items cannot exceed page_size.")
        if len(self.items) > self.total:
            raise ValueError("items cannot exceed total.")

    @property
    def page_count(self) -> int:
        if self.total == 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size


@dataclass(frozen=True, slots=True)
class PublicSessionSummary:
    session_id: str
    public_slug: str
    title: str
    description: str | None
    closes_at: datetime | None
    enrollment_mode: EnrollmentMode
    access_code_mode: AccessCodeMode


@dataclass(frozen=True, slots=True)
class AdminDashboardSnapshot:
    generated_at: datetime
    session_status_counts: Mapping[SessionStatus, int]

    def __post_init__(self) -> None:
        counts = {
            status: int(self.session_status_counts.get(status, 0))
            for status in SessionStatus
        }
        if any(count < 0 for count in counts.values()):
            raise ValueError("Session status counts cannot be negative.")
        object.__setattr__(
            self,
            "session_status_counts",
            MappingProxyType(counts),
        )

    def count(self, status: SessionStatus) -> int:
        return self.session_status_counts[status]

@dataclass(frozen=True, slots=True)
class HomeActiveSessionSummary:
    total_active_sessions: int
    total_participants_today: int


class PageQueries(Protocol):
    """Read-only interface tailored to current page requirements."""

    def list_open_public_sessions(
        self,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = 10,
        at: datetime | None = None,
    ) -> PageResult[PublicSessionSummary]:
        """Return listed sessions that can currently accept submissions."""
        ...

    def get_admin_dashboard(
        self,
        *,
        at: datetime | None = None,
    ) -> AdminDashboardSnapshot:
        """Return the operational dashboard projection."""
        ...

    def get_home_metrics(
        self,
        *,
        at: datetime | None = None,
    ) -> HomeActiveSessionSummary:
        """Return the home active session metics."""
        ...
