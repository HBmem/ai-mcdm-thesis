"""Shared layout primitives for consistent Streamlit pages."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st


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
    """Install the scoped visual language used by administration surfaces."""

    dark_theme = st.get_option("theme.base") == "dark"
    colors = (
        {
            "filter": "#1B2A4A",
            "results": "#15223B",
            "card": "#1B2A4A",
            "border": "#33425D",
            "shadow": "rgba(0, 0, 0, 0.22)",
        }
        if dark_theme
        else {
            "filter": "#E8E1D5",
            "results": "#FBFAF7",
            "card": "#FFFFFF",
            "border": "#D8D1C4",
            "shadow": "rgba(27, 42, 74, 0.08)",
        }
    )
    st.html(
        f"""
        <style>
        [class*="st-key-pi_admin_filter_"] {{
            background: {colors["filter"]};
            border: 1px solid {colors["border"]};
            border-radius: 0.8rem;
            padding: 1rem 1.15rem 1.15rem;
            margin-bottom: 1rem;
        }}
        [class*="st-key-pi_admin_results_"] {{
            background: {colors["results"]};
            border: 1px solid {colors["border"]};
            border-radius: 0.8rem;
            padding: 1rem 1.15rem 1.15rem;
        }}
        [class*="st-key-pi_admin_session_card_"] {{
            background: {colors["card"]};
            border: 1px solid {colors["border"]};
            border-left: 0.35rem solid #C4932A;
            border-radius: 0.7rem;
            box-shadow: 0 0.15rem 0.6rem {colors["shadow"]};
            padding: 0.9rem 1rem 1rem;
            margin: 0.65rem 0;
        }}
        [class*="st-key-pi_admin_individual_"] {{
            background: {colors["card"]};
            border: 1px solid {colors["border"]};
            border-left: 0.35rem solid #4F78A4;
            border-radius: 0.7rem;
            padding: 1rem 1.15rem 1.15rem;
            margin: 0.8rem 0;
        }}
        [class*="st-key-pi_admin_group_aggregate_"] {{
            background: {colors["card"]};
            border: 1px solid {colors["border"]};
            border-left: 0.35rem solid #C4932A;
            border-radius: 0.7rem;
            padding: 1rem 1.15rem 1.15rem;
            margin: 0.8rem 0;
        }}
        [class*="st-key-pi_admin_session_aggregate_"] {{
            background: {colors["card"]};
            border: 1px solid {colors["border"]};
            border-left: 0.35rem solid #1B2A4A;
            border-radius: 0.7rem;
            padding: 1rem 1.15rem 1.15rem;
            margin: 0.8rem 0;
        }}
        [class*="st-key-pi_admin_workflow_navigation_"] {{
            background: {colors["card"]};
            border: 1px solid {colors["border"]};
            border-top: 0.3rem solid #1B2A4A;
            border-radius: 0.8rem;
            box-shadow: 0 0.15rem 0.6rem {colors["shadow"]};
            padding: 1rem 1.15rem 1.15rem;
            margin-bottom: 1rem;
        }}
        [class*="st-key-pi_admin_configuration_"] {{
            background: {colors["filter"]};
            border: 1px solid {colors["border"]};
            border-radius: 0.8rem;
            padding: 0.8rem 1rem;
            margin-bottom: 1rem;
        }}
        [class*="st-key-pi_admin_stage_content_"] {{
            background: {colors["results"]};
            border: 1px solid {colors["border"]};
            border-left: 0.35rem solid #C4932A;
            border-radius: 0.8rem;
            padding: 1rem 1.15rem 1.15rem;
            margin-bottom: 1rem;
        }}
        [class*="st-key-pi_admin_bundle_preview_"] {{
            background: {colors["card"]};
            border: 1px solid {colors["border"]};
            border-left: 0.35rem solid #1B2A4A;
            border-radius: 0.8rem;
            padding: 1rem 1.15rem 1.15rem;
            margin-bottom: 1rem;
        }}
        </style>
        """
    )


@contextmanager
def admin_surface(
    *,
    key: str,
    variant: AdminSurfaceVariant,
) -> Iterator[None]:
    """Render content inside a semantically styled administration surface."""

    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "-", key.strip())
    with st.container(key=f"pi_admin_{variant}_{safe_key}"):
        yield


def render_page_header(header: PageHeader) -> None:
    if header.eyebrow:
        st.caption(header.eyebrow)
    st.title(header.title, anchor=False)
    st.markdown(header.description)


def render_empty_state(
    title: str,
    message: str,
    *,
    icon: str = ":material/inbox:",
) -> None:
    with st.container(border=True):
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
