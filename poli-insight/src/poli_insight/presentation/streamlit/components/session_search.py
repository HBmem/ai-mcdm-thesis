"""Reusable, namespaced session-search controls."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import cast

import streamlit as st

from poli_insight.application.queries.page_queries import (
    SessionDateField,
    SessionScenarioOption,
    SessionSearchFilters,
)
from poli_insight.domain.enum import SessionStatus


def render_session_search(
    *,
    key: str,
    scenarios: Sequence[SessionScenarioOption] = (),
    domains: Sequence[str] = (),
    default_statuses: tuple[SessionStatus, ...] = (),
    status_options: Sequence[SessionStatus] = tuple(SessionStatus),
    default_date_field: SessionDateField = SessionDateField.UPDATED,
    processing_state_options: Sequence[tuple[str, str]] = (),
) -> SessionSearchFilters:
    """Render shared session filters and return normalized values."""

    search = st.text_input(
        "Search sessions",
        placeholder="Title, public slug, or scenario",
        icon=":material/search:",
        key=f"{key}:search",
    )
    primary = st.columns((0.36, 0.32, 0.32))
    statuses = tuple(
        primary[0].multiselect(
            "Operational status",
            options=tuple(status_options),
            default=tuple(
                status for status in default_statuses if status in status_options
            ),
            format_func=lambda value: value.value.replace("_", " ").title(),
            key=f"{key}:statuses",
        )
    )
    scenario_by_key = {item.scenario_key: item for item in scenarios}
    scenario_key = primary[1].selectbox(
        "Scenario",
        options=(None, *scenario_by_key),
        format_func=lambda value: (
            "All scenarios" if value is None else scenario_by_key[value].title
        ),
        key=f"{key}:scenario",
    )
    domain = primary[2].selectbox(
        "Domain",
        options=(None, *domains),
        format_func=lambda value: "All domains" if value is None else value,
        key=f"{key}:domain",
    )

    date_controls = st.columns((0.3, 0.15, 0.55), vertical_alignment="center")
    date_field = cast(
        SessionDateField,
        date_controls[0].selectbox(
            "Date field",
            options=tuple(SessionDateField),
            index=tuple(SessionDateField).index(default_date_field),
            format_func=lambda value: value.value.title(),
            key=f"{key}:date_field",
        ),
    )

    range_enabled = date_controls[1].checkbox(
        "Filter by date range",
        key=f"{key}:date_enabled",
    )
    date_from: date | None = None
    date_to: date | None = None
    if range_enabled:
        selected_range = date_controls[2].date_input(
            "Inclusive date range",
            value=(),  # type: ignore[arg-type]
            key=f"{key}:date_range",
        )
        if isinstance(selected_range, tuple):
            if selected_range:
                date_from = selected_range[0]
            if len(selected_range) > 1:
                date_to = selected_range[1]
        elif isinstance(selected_range, date):
            date_from = selected_range
            date_to = selected_range

    state_labels = dict(processing_state_options)
    processing_states: tuple[str, ...] = ()
    if state_labels:
        processing_states = tuple(
            st.multiselect(
                "Processing state",
                options=tuple(state_labels),
                format_func=state_labels.__getitem__,
                key=f"{key}:processing_states",
                help="Page-specific processing classifications; selections are combined.",
            )
        )

    return SessionSearchFilters(
        search=search,
        statuses=statuses,
        scenario_key=scenario_key,
        domain=domain,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
        processing_states=processing_states,
    )
