"""Shared layout primitives for consistent Streamlit pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st


@dataclass(frozen=True, slots=True)
class PageHeader:
    title: str
    description: str
    eyebrow: str | None = None
    icon: str | None = None


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
