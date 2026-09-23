"""Balanced, discrete pairwise preference input with an explicit blank state."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import streamlit as st

from poli_insight.application.queries.page_queries import ParticipationScaleOption

_ASSETS = Path(__file__).with_name("preference_slider_frontend")
_HTML = (_ASSETS / "index.html").read_text(encoding="utf-8")
_CSS = (_ASSETS / "style.css").read_text(encoding="utf-8")
_JS = (_ASSETS / "index.js").read_text(encoding="utf-8")


def balanced_options(
    options: tuple[ParticipationScaleOption, ...],
    *,
    left_name: str,
    right_name: str,
) -> list[dict[str, str]] | None:
    """Order by ratio, not ordinal: ratios above one always favor the left.

    Older snapshots and the application catalog have opposite ordinal orders.
    Unsupported scales retain the page's native input rather than guessing.
    """
    if len(options) not in (5, 7):
        return None
    try:
        ratios = [Decimal(option.numeric_value or "NaN") for option in options]
    except InvalidOperation:
        return None
    if any(not ratio.is_finite() or ratio <= 0 for ratio in ratios):
        return None
    middle = len(options) // 2
    if (
        len(set(ratios)) != len(options)
        or len({option.scale_value_id for option in options}) != len(options)
        or sum(ratio > 1 for ratio in ratios) != middle
        or sum(ratio < 1 for ratio in ratios) != middle
        or Decimal(1) not in ratios
    ):
        return None

    labels = {
        "much more important": "Much more",
        "more important": "More",
        "slightly more important": "Slightly more",
        "very strongly preferred": "Very strongly",
        "strongly preferred": "Strongly",
        "moderately preferred": "Moderately",
    }
    choices = []
    for ratio, option in sorted(
        zip(ratios, options, strict=True), key=lambda item: item[0], reverse=True
    ):
        label = option.label
        for prefix in ("Left criterion is ", "Right criterion is "):
            label = label.removeprefix(prefix)
        summary = option.label.replace("Left criterion", left_name).replace(
            "Right criterion", right_name
        )
        if ratio == 1:
            label = "Equal"
            summary = f"{left_name} and {right_name} are equally important."
        else:
            label = labels.get(label, label)
        choices.append(
            {"id": option.scale_value_id, "label": label, "summary": summary}
        )
    return choices


def preference_slider(
    *,
    choices: list[dict[str, str]],
    left_name: str,
    right_name: str,
    value: str | None,
    key: str,
    left_description: str | None = None,
    right_description: str | None = None,
) -> str | None:
    """Return a scale value ID or None; saved defaults never replace live edits."""
    valid_ids = {choice["id"] for choice in choices}
    state = st.session_state.get(key, {})
    selected = state.get("selected", value)
    if not isinstance(selected, str) or selected not in valid_ids:
        selected = None
    # Register in the active runtime (also works after AppTest resets its runtime).
    component = st.components.v2.component(
        "balanced_preference_slider", html=_HTML, css=_CSS, js=_JS
    )
    result = component(
        key=key,
        data={
            "left": left_name,
            "right": right_name,
            "left_description": left_description or "",
            "right_description": right_description or "",
            "choices": choices,
            "selected": selected,
        },
        default={"selected": selected},
        on_selected_change=lambda: None,
        width="stretch",
        height="content",
    )
    return (
        result.selected
        if isinstance(result.selected, str) and result.selected in valid_ids
        else None
    )
