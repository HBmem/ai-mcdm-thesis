import streamlit as st

from typing import Any

from poli_insight.domain.enums import (
    PreferenceScale,
    RankingMethod,
    SessionStatus,
    SessionVisibility,
    WeightingMethod,
)

def render(
    session_state_key: str,
    session_status: str,
    visibility: str,
    weighting_method: str,
    ranking_method: str,
    preference_scale: str,
    available_status: list[str] | None = None,
    available_visibility: list[str] | None = None,
    available_weighting_methods: list[str] | None = None,
    available_ranking_methods: list[str] | None = None,
    available_preference_scales: list[str] | None = None,
    require_access_code: bool = False,
    allow_resubmission: bool = False
) -> dict[str, Any]:
    if available_status is None:
        available_status = [
            "All",
            *(value.value for value in SessionStatus),
        ]

    if available_visibility is None:
        available_visibility = [
            "All",
            *(value.value for value in SessionVisibility),
        ]

    if available_weighting_methods is None:
        available_weighting_methods = [
            "All",
            *(value.value for value in WeightingMethod),
        ]

    if available_ranking_methods is None:
        available_ranking_methods = [
            "All",
            *(value.value for value in RankingMethod),
        ]

    if available_preference_scales is None:
        available_preference_scales = [
            "All",
            *(value.value for value in PreferenceScale),
        ]

    if session_state_key not in st.session_state:
        st.session_state[session_state_key] = {
            "status": session_status,
            "visibility": visibility,
            "weighting_method": weighting_method,
            "ranking_method": ranking_method,
            "preference_scale": preference_scale,
            "require_access_code": require_access_code,
            "allow_resubmission": allow_resubmission
        }

    st.html(f"""
            <style>
            .st-key-{session_state_key} {{
                background: #fff;
            }}
            </style>
            """)
    
    with st.container(border=True, key=session_state_key):
        filters = {}
    
        col1, col2, col3 = st.columns(3, vertical_alignment="center")

        with col1:
            filters["status"] = st.selectbox(key=f"{session_state_key}_status", label="Status", options=available_status, index=available_status.index(session_status) if session_status in available_status else 0)

            filters["weighting_method"] = st.selectbox(key=f"{session_state_key}_weighting_method", label="Weighting Method", options=available_weighting_methods, index=(available_weighting_methods).index(weighting_method) if weighting_method in (available_weighting_methods) else 0)
        
        with col2:
            filters["visibility"] = st.selectbox(key=f"{session_state_key}_visibility", label="Visibility", options=available_visibility, index=available_visibility.index(visibility) if visibility in available_visibility else 0)

            filters["ranking_method"] = st.selectbox(key=f"{session_state_key}_ranking_method", label="Ranking Method", options=available_ranking_methods, index=(available_ranking_methods).index(ranking_method) if ranking_method in (available_ranking_methods) else 0)

        with col3:
            # with st.container():
            #     filters["require_access_code"] = st.toggle("Require Access Code", value=require_access_code)
            #     filters["allow_resubmissions"] = st.toggle("Allow Resubmissions", value=allow_resubmission)

            st.space(size="large")
            filters["preference_scale"] = st.selectbox(key=f"{session_state_key}_preference_scale", label="Preference Scale", options=available_preference_scales, index=(available_preference_scales).index(preference_scale) if preference_scale in (available_preference_scales) else 0)

        return filters
    