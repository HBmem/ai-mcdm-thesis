"""Explicit chart contracts with readable units and equivalent tabular evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
import streamlit as st

from poli_insight.presentation.streamlit.components.theme import is_dark_theme


@dataclass(frozen=True)
class ChartSpec:
    title: str
    category: str
    measure: str
    context: str
    description: str
    horizontal: bool = False
    integer: bool = False
    scale: Literal["number", "percent", "score"] = "number"


def chart_data(data, spec: ChartSpec) -> pd.DataFrame:
    frame = data.to_frame() if isinstance(data, pd.Series) else data.copy()
    frame.index.name = spec.category
    frame = frame.reset_index().melt(
        id_vars=spec.category, var_name="Series", value_name="Value"
    )
    frame["Value"] = pd.to_numeric(frame["Value"], errors="coerce")
    if spec.scale == "percent":
        frame["Value"] *= 100
    return frame


def vega_spec(spec: ChartSpec, series: list[str], *, dark: bool = False) -> dict:
    category = {
        "field": spec.category,
        "type": "nominal",
        "axis": {"title": spec.category, "labelLimit": 180},
        "sort": None,
    }
    scale = {"zero": True}
    if spec.scale in {"percent", "score"}:
        scale["domain"] = [0, 100 if spec.scale == "percent" else 1]
    measure = {
        "field": "Value",
        "type": "quantitative",
        "axis": {
            "title": spec.measure,
            **({"tickMinStep": 1, "format": "d"} if spec.integer else {}),
        },
        "scale": scale,
        "stack": None,
    }
    encoding = {
        "x": measure if spec.horizontal else category,
        "y": category if spec.horizontal else measure,
        "color": {
            "field": "Series",
            "type": "nominal",
            "scale": {
                "domain": series,
                "range": [
                    "#5EEAD4" if dark else "#0F766E",
                    "#FDBA74" if dark else "#B45309",
                    "#93C5FD" if dark else "#2563EB",
                    "#D8B4FE" if dark else "#9333EA",
                    "#FDA4AF" if dark else "#BE123C",
                    "#CBD5E1" if dark else "#475569",
                ][: len(series)],
            },
            "legend": {"title": "Series", "orient": "bottom"}
            if len(series) > 1
            else None,
        },
        "tooltip": [
            {"field": spec.category, "type": "nominal"},
            {"field": "Series", "type": "nominal"},
            {"field": "Value", "type": "quantitative", "title": spec.measure},
        ],
    }
    if len(series) > 1:
        encoding["yOffset" if spec.horizontal else "xOffset"] = {
            "field": "Series",
            "sort": series,
        }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"{spec.title}. {spec.context}. {spec.description}",
        "usermeta": {"embedOptions": {"actions": False}},
        "encoding": encoding,
        "layer": [
            {"mark": {"type": "bar", "aria": True}},
            {
                "transform": [{"filter": "datum.Value === 0"}],
                "mark": {"type": "point", "filled": False, "size": 60, "aria": False},
            },
        ],
        "config": {
            "axis": {"labelFontSize": 12, "titleFontSize": 13},
            "legend": {"labelFontSize": 12},
        },
    }


def render_chart(data, spec: ChartSpec) -> None:
    st.markdown(f"#### {spec.title}")
    st.caption(spec.context)
    frame = chart_data(data, spec)
    if frame.empty or frame["Value"].notna().sum() == 0:
        st.info("No numeric observations are available for this chart.")
    else:
        st.vega_lite_chart(
            frame,
            vega_spec(
                spec,
                list(frame["Series"].unique()),
                dark=is_dark_theme(),
            ),
            width="stretch",
        )
    st.caption(
        spec.description
        + " Hollow points mark zero; unavailable observations are omitted from the chart."
    )
    with st.expander(f"View data: {spec.title}"):
        display = frame.rename(columns={"Value": spec.measure})
        st.dataframe(display, hide_index=True, width="stretch")
        if frame["Value"].isna().any():
            st.caption("Blank numeric cells are unavailable, not zero.")
