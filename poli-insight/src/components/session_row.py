from __future__ import annotations
from datetime import datetime

import streamlit as st

from src.models.scenario import ScenarioBundle

from src.utils.repositories import get_session, get_sessions

def render_session_row(session: dict, scenario: ScenarioBundle | None):
    st.html(f"""
            <style>
            .st-key-{session['session_id']} {{
                background: #fff;
            }}
            </style>
            """)
    with st.container(border=True, key=session['session_id']):
        if scenario is None:
            st.error("Scenario not found")
            return
        
        rowcol1, rowcol2 = st.columns([0.7, 0.3])

        with rowcol1:
            st.write(f"""
                    **{session['session_title']}**  
                    :gray[{len(scenario.scenario.get('alternatives', []))} alternatives · {len(scenario.criteria)} criteria · {len(scenario.scenario.get('stakeholder_groups', []))} stakeholder groups]
                    """)
        with rowcol2:
            if session.get('status').lower() == "draft":
                button_options = [{"label": "View", "icon": ":material/visibility:"}, {"label": "Edit", "icon": ":material/edit:"}]
            elif session.get('status').lower() == "open":
                button_options = [{"label": "View", "icon": ":material/visibility:"}, {"label": "Close", "icon": ":material/cancel:"}]
            elif session.get('status').lower() == "closed":
                button_options = [{"label": "View", "icon": ":material/visibility:"}, {"label": "Reopen", "icon": ":material/refresh:"}]
            elif session.get('status').lower() == "archived":
                button_options = [{"label": "View", "icon": ":material/visibility:"}, {"label": "Restore", "icon": ":material/restore:"}]
            else:
                button_options = [{"label": "View", "icon": ":material/visibility:"}]

            cols = st.columns(len(button_options))
            for i, option in enumerate(button_options):
                with cols[i]:
                    if st.button(option["label"], icon=option["icon"], width="stretch", key=f"{session['session_id']}_{option['label']}"):
                        if option["label"] == "View":
                            _render_session_modal(session, scenario)
                        pass
        
        col1, col2, col3, col4 = st.columns(4, vertical_alignment="center")

        with col1:
        #     # TODO: Responses
            st.markdown(":gray[Responses]")
        with col2:
        #     # TODO: Participants
            st.markdown(":gray[Participants]")
        with col3:
            date_time = session.get('end_date_time', 'N/A')
            if date_time != 'N/A':
                date_time = datetime.fromisoformat(date_time)
                date_time = date_time.strftime("%Y-%m-%d %H:%M %p")
                st.markdown(f":gray[Deadline] **{date_time}**")
        with col4:
            if session.get('status').lower() == "draft":
                st.markdown(":orange-badge[:material/circle: Draft]")
            elif session.get('status').lower() == "open":
                st.markdown(":blue-badge[:material/check_circle: Open]")
            elif session.get('status').lower() == "closed":
                st.markdown(":green-badge[:material/cancel: Closed]")
            elif session.get('status').lower() == "archived":
                st.markdown(":gray-badge[:material/archive: Archived]")
            else:
                st.markdown(":red-badge[:material/error: Unknown]")

@st.dialog("Session Details")
def _render_session_modal(session: dict, scenario: ScenarioBundle | None):
    if scenario is None:
        st.error("Scenario not found")
        return

    st.write(f"**{session['session_title']}**")
    st.write(f"**Scenario:** {scenario.scenario.get('name', 'N/A')}")