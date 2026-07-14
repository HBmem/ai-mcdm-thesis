from __future__ import annotations
from datetime import datetime

from streamlit_extras.grid import grid
import streamlit as st

from src.models.enum import (
    SessionStatus,
    SessionVisibility,
)
from src.models.scenario import ScenarioBundle
from src.models.session import SessionScenario, SessionStakeholderGroup

from src.repositories.participant_repository import get_participants_by_session

DRAFT_ACTIONS = [
    {
        "label": "Open",
        "icon": ":material/check_circle:",
        "type": "primary",
        "function": "open"
    },
    {
        "label": "Edit",
        "icon": ":material/visibility:",
        "type": "secondary",
        "function": "edit"
    },
    {
        "label": "Delete",
        "icon": ":material/delete:",
        "type": "secondary",
        "function": "delete"
    }
]

OPEN_ACTIONS = [
    {
        "label": "Close",
        "icon": ":material/cancel:",
        "type": "primary",
        "function": "close"
    },
    {
        "label": "Edit",
        "icon": ":material/visibility:",
        "type": "secondary",
        "function": "edit"
    },
    {
        "label": "Delete",
        "icon": ":material/delete:",
        "type": "secondary",
        "function": "delete"
    }
]

CLOSED_ACTIONS = [
    {
        "label": "Archive",
        "icon": ":material/archive:",
        "type": "primary",
        "function": "archive"
    },
    {
        "label": "Edit",
        "icon": ":material/visibility:",
        "type": "secondary",
        "function": "edit"
    },
    {
        "label": "Delete",
        "icon": ":material/delete:",
        "type": "secondary",
        "function": "delete"
    }
]

ARCHIVED_ACTIONS = [
    {
        "label": "Restore",
        "icon": ":material/restore:",
        "type": "primary",
        "function": "restore"
    },
    {
        "label": "Edit",
        "icon": ":material/visibility:",
        "type": "secondary",
        "function": "edit"
    },
    {
        "label": "Delete",
        "icon": ":material/delete:",
        "type": "secondary",
        "function": "delete"
    }
]

def render_session_row(session: SessionScenario, scenario: ScenarioBundle | None):
    st.html(f"""
            <style>
            .st-key-{session.session_id} {{
                background: #fff;
                
            }}
            .st-key-{session.session_id}:hover {{
                background: #f0f0f0;
                transition: background 0.3s ease;
                cursor: pointer;
            }}
            </style>
            """)
    
    with st.container(border=True, key=session.session_id):
        col1, col2, col3 = st.columns([0.4,0.3,0.25], gap=None)
        
        if scenario is None:
            with col1:
                st.write(
                        f"""
                        **{session.title}**
                        :gray[Could not pull scenario data]
                        """
                        )
        else:
            with col1:
                st.write(
                        f"""
                        **{session.title}**  
                        :gray[{len(scenario.alternatives)} alternatives · {len(scenario.criteria)} criteria · {len(scenario.stakeholder_groups)} stakeholder groups]
                        """
                        )
                
            with col2:
                _render_session_stats(session)

            with col3:
                _render_session_actions(session, scenario)

def _render_session_stats(session: SessionScenario):
    col1, col2, col3, col4 = st.columns(4, gap=None, vertical_alignment="center")
    with col1:
        st.markdown(f"""
                    :gray[Responses]  
                    **0**
                    """, text_alignment="center")
    with col2:
        participant_count = len(get_participants_by_session(session.session_id))
        st.markdown(f"""
                    :gray[Participants]  
                    **{participant_count}**
                    """, text_alignment="center")
    with col3:
        if session.status == SessionStatus.DRAFT:
            st.markdown(""":gray[Deadline]  
                        **N/A**
                        """, text_alignment="center")
        elif session.status == SessionStatus.OPEN:
            if session.end_at is None:
                st.markdown("""
                            :gray[Deadline]  
                            **N/A**
                            """, text_alignment="center")
            else:
                date_time = session.end_at.strftime("%Y-%m-%d %H:%M %p")
                st.markdown(f"""
                            :gray[Deadline]  
                            **{date_time}**
                            """, text_alignment="center")
        elif session.status == SessionStatus.CLOSED:
            if session.end_at is None:
                st.markdown("""
                            :gray[Deadline]  
                            **N/A**
                            """, text_alignment="center")
            else:
                date_time = session.end_at.strftime("%Y-%m-%d %H:%M %p")
                st.markdown(f"""
                            :gray[Deadline]  
                            **{date_time}**
                            """, text_alignment="center")
        elif session.status == SessionStatus.ARCHIVED:
            if session.end_at is None:
                st.markdown("""
                            :gray[Deadline]  
                            **N/A**
                            """, text_alignment="center")
            else:
                date_time = session.end_at.strftime("%Y-%m-%d %H:%M %p")
                st.markdown(f"""
                            :gray[Deadline]  
                            **{date_time}**
                            """, text_alignment="center")
                
    with col4:
        if session.status == SessionStatus.DRAFT:
            st.markdown(":orange-badge[:material/circle: Draft]")
        elif session.status == SessionStatus.OPEN:
            st.markdown(":blue-badge[:material/check_circle: Open]")
        elif session.status == SessionStatus.CLOSED:
            st.markdown(":green-badge[:material/cancel: Closed]")
        elif session.status == SessionStatus.ARCHIVED:
            st.markdown(":gray-badge[:material/archive: Archived]")
        else:
            st.markdown(":red-badge[:material/error: Unknown]")

def _render_session_actions(session: SessionScenario, scenario: ScenarioBundle | None):
    if session.status == SessionStatus.DRAFT:
        actions = DRAFT_ACTIONS
    elif session.status == SessionStatus.OPEN:
        actions = OPEN_ACTIONS
    elif session.status == SessionStatus.CLOSED:
        actions = CLOSED_ACTIONS
    elif session.status == SessionStatus.ARCHIVED:
        actions = ARCHIVED_ACTIONS
    else:
        actions = []

    cols = st.columns(len(actions), gap="small", vertical_alignment="center")
    for i, action in enumerate(actions):
        with cols[i]:
            if st.button(action["label"], icon=action["icon"], width="stretch", key=f"{session.session_id}_{action['label']}", type=action["type"]):
                if action["function"] == "open":
                    _open_session(session)
                elif action["function"] == "edit":
                    _edit_session(session, scenario)
                elif action["function"] == "delete":
                    _delete_session(session)

def _open_session(session: SessionScenario):
    x = ""

def _close_session(session: SessionScenario):
    x = ""

def _edit_session(session: SessionScenario, scenario: ScenarioBundle | None):
    _render_edit_session_modal(session, scenario)

def _delete_session(session: SessionScenario):
    x = ""

@st.dialog(":primary[Edit Session]", width="large")
def _render_edit_session_modal(session: SessionScenario, scenario: ScenarioBundle | None):
    st.markdown(f"{session.title}  :gray[Scenario: {scenario.title if scenario else 'N/A'}]")
    # st.space(size="small")
    st.markdown("**Session Details**")
    session_title = st.text_input("Session Title", value=session.title, key=f"{session.session_id}_edit_title")
    session_description = st.text_area("Session Description", value=session.description or "", key=f"{session.session_id}_edit_description")

    visibility_options = [SessionVisibility.PUBLIC, SessionVisibility.PRIVATE, SessionVisibility.UNLISTED]
    session_visibility = st.radio("Session Visibility", options=visibility_options, format_func=lambda x: x.value, index=visibility_options.index(session.visibility), key=f"{session.session_id}_edit_visibility", horizontal=True)

    admin_notes = st.text_area("Admin Notes", value=session.admin_notes or "", key=f"{session.session_id}_edit_admin_notes")

    st.markdown("**Session Model Configuration**")
    config_grid = grid(5)

    config_grid.markdown(f""":gray[Weighting Method]  
                         **{session.weighting_method.value}**
                         """)
    config_grid.markdown(f""":gray[Ranking Method]  
                         **{session.ranking_method.value}**
                         """)
    config_grid.markdown(f""":gray[Preference Method]  
                         **{session.preference_method.value}**
                         """)
    config_grid.markdown(f""":gray[Participation Method]  
                         **{session.participation_method.value}**
                         """)
    config_grid.markdown(f""":gray[Aggregation Method]  
                         **{session.aggregation_method.value}**
                         """)

    st.markdown("**Session Timeline**")
    timeline_grid = grid(4)
    timeline_grid.markdown(f""":gray[Start Date]  
                         **{session.start_at.strftime("%Y-%m-%d %H:%M %p") if session.start_at else 'N/A'}**
                         """)
    timeline_grid.datetime_input(":gray[End Date]", value=session.end_at, min_value=session.start_at)
    # timeline_grid.markdown(f""":gray[End Date]  
    #                      **{session.end_at.strftime("%Y-%m-%d %H:%M %p") if session.end_at else 'N/A'}**
    #                      """)
    timeline_grid.markdown(f""":gray[Opened At]  
                         **{session.opened_at.strftime("%Y-%m-%d %H:%M %p") if session.opened_at else 'N/A'}**
                         """)
    timeline_grid.markdown(f""":gray[Closed At]  
                         **{session.closed_at.strftime("%Y-%m-%d %H:%M %p") if session.closed_at else 'N/A'}**
                         """)

    save_col, cancel_col = st.columns([0.5, 0.5], gap="small")
    with cancel_col:
        if st.button("Cancel", type="secondary", key=f"{session.session_id}_cancel"):
            st.rerun()
    with save_col:
        if st.button("Save Changes", type="primary", key=f"{session.session_id}_save_changes"):
            _save_session_changes(session, session_title, session_description, session_visibility, admin_notes)
            st.success("Session changes saved.")
            st.rerun()


def _save_session_changes(session: SessionScenario, title: str, description: str | None, visibility: SessionVisibility, admin_notes: str | None, end_at: datetime | None):
    x = ""