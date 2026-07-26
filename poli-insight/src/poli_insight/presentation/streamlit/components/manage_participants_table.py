from __future__ import annotations

import streamlit as st
from streamlit_extras.metric_cards import style_metric_cards

from poli_insight.application.services.participant_service import ParticipantService
from poli_insight.domain.sessions import Session

ROWS_PER_PAGE = 10

def render(
    participant_service: ParticipantService,
    session: Session,
    *,
    actor_id: str,
) -> None:
    page_key = "participants_pagination"

    message = st.session_state.pop(
        "participants_action_message",
        None,
    )

    if message is not None:
        st.success(message)

    requested_page = int(
        st.session_state.get(page_key, 1)
    )

    result = participant_service.list_participant_table(
        session_id=session.session_id,
        page=requested_page,
        page_size=ROWS_PER_PAGE,
    )

    total_pages = result.total_pages

    metric1, metric2, metric3, metric4 = st.columns(4)

    metric1.metric(label="Total", value=result.total)
    metric2.metric(label="Submitted", value=0)
    metric3.metric(label="Revisions", value=0)
    metric4.metric(label="Withdrawn", value=0)

    style_metric_cards()

    with st.container(border=True):
        table_slot = st.empty()

        selected_page = st.pagination(
            num_pages=total_pages,
            key=page_key,
        )

    if selected_page != requested_page:
        result = participant_service.list_participant_table(
            session.scenario_id,
            page=selected_page,
            page_size=ROWS_PER_PAGE,
        )

    with table_slot.container():
        if not result.items:
            st.info(
                "No participants for the selected session."
            )

        # for item in result.items:
        #     _render_participant_row(
        #         session=
        #     )
    