import streamlit as st

from typing import Any

def render(
    session_state_key: str,
    session_status: str,
    session_visibility: str,
    weighting_method: str,
    ranking_method: str,
    preference_method: str,
    available_status: list[str] | None = None,
    available_visibility: list[str] | None = None,
    available_weighting_methods: list[str] | None = None,
    available_ranking_methods: list[str] | None = None,
    available_preference_methods: list[str] | None = None,
    require_access_code: bool = False,
    allow_resubmission: bool = False
) -> dict[str, Any]:
    if available_status is None:
        available_status = ["All","Open", "Draft", "Closed", "Archived"]

    if available_visibility is None:
        available_visibility = ["All", "Public", "Private"]

    if available_weighting_methods is None:
        available_weighting_methods = ["All", "AHP", "FUZZY AHP"]

    if available_ranking_methods is None:
        available_ranking_methods = ["All", "TOPSIS", "FUZZY TOPSIS"]

    if available_preference_methods is None:
        available_preference_methods = ["All", "5-point scale", "7-point scale"]

    if session_state_key not in st.session_state:
        st.session_state[session_state_key] = {
            "status": session_status,
            "visibility": session_visibility,
            "weighting_method": weighting_method,
            "ranking_method": ranking_method,
            "preference_method": preference_method,
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

            filters["weighting_method"] = st.selectbox(key=f"{session_state_key}_weighting_method", label="Weighting Method", options=available_weighting_methods or ["AHP", "FUZZY AHP"], index=(available_weighting_methods or ["AHP", "FUZZY AHP"]).index(weighting_method) if weighting_method in (available_weighting_methods or ["AHP", "FUZZY AHP"]) else 0)
        
        with col2:
            filters["session_visibility"] = st.selectbox(key=f"{session_state_key}_visibility", label="Visibility", options=available_visibility, index=available_visibility.index(session_visibility) if session_visibility in available_visibility else 0)

            filters["ranking_method"] = st.selectbox(key=f"{session_state_key}_ranking_method", label="Ranking Method", options=available_ranking_methods or ["TOPSIS", "FUZZY TOPSIS"], index=(available_ranking_methods or ["TOPSIS", "FUZZY TOPSIS"]).index(ranking_method) if ranking_method in (available_ranking_methods or ["TOPSIS", "FUZZY TOPSIS"]) else 0)

        with col3:
            # with st.container():
            #     filters["require_access_code"] = st.toggle("Require Access Code", value=require_access_code)
            #     filters["allow_resubmissions"] = st.toggle("Allow Resubmissions", value=allow_resubmission)

            st.space(size="large")
            filters["preference_method"] = st.selectbox(key=f"{session_state_key}_preference_method", label="Preference Method", options=available_preference_methods or ["5-point scale", "7-point scale"], index=(available_preference_methods or ["5-point scale", "7-point scale"]).index(preference_method) if preference_method in (available_preference_methods or ["5-point scale", "7-point scale"]) else 0)

        return filters