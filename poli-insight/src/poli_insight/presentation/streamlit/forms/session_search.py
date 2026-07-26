from __future__ import annotations

import streamlit as st

from typing import Any
from collections.abc import Sequence

from poli_insight.domain.sessions import Session
from poli_insight.domain.enums import (
    PreferenceScale,
    RankingMethod,
    SessionStatus,
    SessionVisibility,
    WeightingMethod,
)

ALL = "All"

def render(
    *,
    session_state_key: str,
    sessions: Sequence[Session],
    available_status: list[str] | None = None,
    available_visibility: list[str] | None = None,
    available_weighting_methods: list[str] | None = None,
    available_ranking_methods: list[str] | None = None,
    available_preference_scales: list[str] | None = None,
    require_access_code: bool = False,
    allow_resubmission: bool = False
) -> Session | None:
    status_options = (
        tuple(available_status)
        if available_status is not None
        else (
            ALL,
            *(status.value for status in SessionStatus),
        )
    )

    visibility_options = (
        tuple(available_visibility)
        if available_visibility is not None
        else (
            ALL,
            *(visibility.value for visibility in SessionVisibility),
        )
    )

    weighting_method_options = (
        tuple(available_weighting_methods)
        if available_weighting_methods is not None
        else (
            ALL,
            *(status.value for status in WeightingMethod),
        )
    )

    ranking_method_options = (
        tuple(available_ranking_methods)
        if available_ranking_methods is not None
        else (
            ALL,
            *(ranking_method.value for ranking_method in RankingMethod),
        )
    )

    preference_scale_options = (
        tuple(available_preference_scales)
        if available_preference_scales is not None
        else (
            ALL,
            *(preference_scale.value for preference_scale in PreferenceScale),
        )
    )

    st.html(f"""
        <style>
        .st-key-{session_state_key} {{
            background: #fff;
        }}
        </style>
        """)

    with st.container(border=True, key=session_state_key):
        st.markdown("##### Session Search")

        if not sessions:
            st.info("No sessions are available.")
            return None

        title_column, status_column = st.columns(
            [3, 1],
            vertical_alignment="center",
        )

        with status_column:
            selected_status = st.selectbox(
                key=f"{session_state_key}_status",
                label="Status",
                options=status_options,
            )

        vis_column, wm_column, rm_column, ps_column = st.columns(4, vertical_alignment="center")

        with vis_column:
            selected_visibility = st.selectbox(
                key=f"{session_state_key}_visibility",
                label="Visibility",
                options=visibility_options,
            )

        with wm_column:
            selected_weighting_method = st.selectbox(
                key=f"{session_state_key}_weighting_method",
                label="Weighting Method",
                options=weighting_method_options,
            )

        with rm_column:
            selected_ranking_method = st.selectbox(
                key=f"{session_state_key}_ranking_method",
                label="Ranking Method",
                options=ranking_method_options
            )

        with ps_column:
            selected_preference_scale = st.selectbox(
                key=f"{session_state_key}_preference_scale",
                label="Preference Scale",
                options=preference_scale_options,
            )

        filtered_sessions = _apply_filters(
            sessions,
            selected_status,
            selected_visibility,
            selected_weighting_method,
            selected_ranking_method,
            selected_preference_scale,
        )
        sessions_by_id = {
            session.session_id: session
            for session in filtered_sessions
        }

        with title_column:
            selected_session_id = st.selectbox(
                "Session",
                options=tuple(sessions_by_id),
                index=None,
                key=f"{session_state_key}_session_id",
                placeholder=(
                    "Search by title, status, or session ID"
                ),
                format_func=lambda session_id: _session_label(
                    sessions_by_id[session_id]
                ),
            )

    if selected_session_id is None:
        return None

    return sessions_by_id[selected_session_id]
    #     with rm_col:
    #         filters["ranking_method"] = st.selectbox(key=f"{session_state_key}_ranking_method", label="Ranking Method", options=available_ranking_methods, index=(available_ranking_methods).index(ranking_method) if ranking_method in (available_ranking_methods) else 0)
        
    #     with ps_col:
    #         filters["preference_scale"] = st.selectbox(key=f"{session_state_key}_preference_scale", label="Preference Scale", options=available_preference_scales, index=(available_preference_scales).index(preference_scale) if preference_scale in (available_preference_scales) else 0)

    #     return filters

def _session_label(session: Session) -> str:
    return (
        f"{session.title} · "
        f"{session.status.value} · "
        f"{session.session_id}"
    )

def _apply_filters(
    sessions: Sequence[Session],
    status: str,
    visibility: str,
    weighting_method: str,
    ranking_method: str,
    preference_scales: str,
) -> tuple[Session, ...]:
    return tuple(
        session
        for session in sessions
        if (
            (status == ALL or session.status.value == status)
            and (
                visibility == ALL
                or session.visibility.value == visibility
            )
            and (
                weighting_method == ALL
                or session.weighting_method.value
                == weighting_method
            )
            and (
                ranking_method == ALL
                or session.ranking_method.value
                == ranking_method
            )
            and (
                preference_scales == ALL
                or session.preference_scale.value
                == preference_scales
            )
        )
    )
