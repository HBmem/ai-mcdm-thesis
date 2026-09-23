"""Shared layout primitives for consistent Streamlit pages."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from poli_insight.presentation.streamlit.components.theme import render_theme


@dataclass(frozen=True, slots=True)
class PageHeader:
    title: str
    description: str
    eyebrow: str | None = None
    icon: str | None = None


AdminSurfaceVariant = Literal[
    "filter",
    "results",
    "session_card",
    "individual",
    "group_aggregate",
    "session_aggregate",
    "workflow_navigation",
    "configuration",
    "stage_content",
    "bundle_preview",
]


def render_admin_surface_styles() -> None:
    """Compatibility entrypoint for the application-wide theme."""
    render_theme()


def _safe_key(key: str) -> str:
    # The suffix prevents two identifiers that sanitize alike from colliding.
    readable = re.sub(r"[^a-zA-Z0-9_-]", "-", key.strip())
    return f"{readable}-{sha256(key.encode()).hexdigest()[:10]}"


def surface(
    *,
    key: str,
    variant: Literal["card", "filter", "feature", "metric"] = "card",
    **layout: Any,
) -> DeltaGenerator:
    """A keyed native container; usable with `with` or as a render target."""
    return st.container(key=f"pi_surface_{variant}_{_safe_key(key)}", **layout)


@contextmanager
def application_shell() -> Iterator[None]:
    render_theme()
    with st.container(key="pi_app_shell", gap="medium"):
        yield


@contextmanager
def reading_width(key: str) -> Iterator[None]:
    with st.container(key=f"pi_reading_{_safe_key(key)}", gap="medium"):
        yield


def render_section_heading(
    title: str, description: str | None = None, *, level: int = 2
) -> None:
    """Keep native Markdown headings semantic, with no skipped section levels."""
    st.markdown(f"{'#' * level} {title}")
    if description:
        st.caption(description)


def metric_card(label: str, value: Any, *, key: str) -> None:
    with surface(key=key, variant="metric"):
        st.metric(label, value)


def metric_row(count: int, *, key: str) -> list[DeltaGenerator]:
    """Wrap metric cards at their readable width rather than squeezing labels."""
    with st.container(horizontal=True, gap="small"):
        return [
            st.container(width=220, key=f"pi_metric_{_safe_key(f'{key}:{index}')}")
            for index in range(count)
        ]


@contextmanager
def admin_surface(
    *,
    key: str,
    variant: AdminSurfaceVariant,
) -> Iterator[None]:
    """Render content inside a semantically styled administration surface."""

    safe_key = _safe_key(key)
    with st.container(key=f"pi_admin_{variant}_{safe_key}"):
        yield


def render_page_header(header: PageHeader) -> None:
    with st.container(key=f"pi_header_{_safe_key(header.title)}", gap="small"):
        if header.eyebrow:
            st.caption(header.eyebrow)
        st.title(header.title, anchor=False)
        if header.description:
            st.write(header.description)


def render_empty_state(
    title: str,
    message: str,
    *,
    icon: str = ":material/inbox:",
) -> None:
    with st.container(border=True, gap="small"):
        st.subheader(f"{icon} {title}", anchor=False)
        st.write(message)


def render_capability_notice(
    title: str,
    message: str,
    *,
    available: bool = False,
) -> None:
    if available:
        st.success(f"**{title}** — {message}", icon=":material/check_circle:")
    else:
        st.info(f"**{title}** — {message}", icon=":material/construction:")


def page_link(
    route: Any,
    label: str,
    *,
    icon: str | None = None,
    use_container_width: bool = True,
) -> None:
    st.page_link(
        route,
        label=label,
        icon=icon,
        use_container_width=use_container_width,
    )


def format_datetime(
    value: datetime | None,
    *,
    timezone_name: str,
    empty: str = "Not scheduled",
) -> str:
    if value is None:
        return empty
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
        timezone_name = "UTC"
    localized = value.astimezone(timezone)
    time_label = localized.strftime("%I:%M %p").lstrip("0")
    return (
        f"{localized.strftime('%b')} {localized.day}, {localized.year} "
        f"at {time_label} {timezone_name}"
    )
