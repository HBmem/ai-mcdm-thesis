from __future__ import annotations

import streamlit as st

from streamlit_extras.grid import grid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from functools import partial
from typing import Literal, Any


from poli_insight.domain.enums import SessionStatus, SessionVisibility
from poli_insight.domain.scenario import ScenarioSnapshot
from poli_insight.domain.sessions import SessionScenario

from poli_insight.application.services.session_service import SessionService, SessionScenario
from poli_insight.application.services.scenario_service import ScenarioSnapshot
from poli_insight.application.session_queries import SessionFilters
from poli_insight.application.session_queries import SessionFilters
from poli_insight.application.dto import UpdateSessionCommand

ROWS_PER_PAGE = 10

ActionName = Literal[
    "open",
    "close",
    "archive",
    "edit",
    "delete",
]

@dataclass(frozen=True, slots=True)
class RowAction:
    name: ActionName
    label: str
    icon: str
    button_type: str = "secondary"


ActionHandler = Callable[
    [
        ActionName,
        SessionScenario,
        ScenarioSnapshot | None,
    ],
    None,
]

ACTIONS_BY_STATUS: dict[
    SessionStatus,
    tuple[RowAction, ...],
] = {
    SessionStatus.DRAFT: (
        RowAction(
            name="open",
            label="Open",
            icon=":material/check_circle:",
            button_type="primary",
        ),
        RowAction(
            name="edit",
            label="Edit",
            icon=":material/edit:",
        ),
        RowAction(
            name="delete",
            label="Delete",
            icon=":material/delete:",
        ),
    ),
    SessionStatus.OPEN: (
        RowAction(
            name="close",
            label="Close",
            icon=":material/cancel:",
            button_type="primary",
        ),
        RowAction(
            name="edit",
            label="Edit",
            icon=":material/edit:",
        ),
    ),
    SessionStatus.CLOSED: (
        RowAction(
            name="archive",
            label="Archive",
            icon=":material/archive:",
            button_type="primary",
        ),
        RowAction(
            name="edit",
            label="Edit",
            icon=":material/edit:",
        ),
    ),
    SessionStatus.PROCESSED: (
        RowAction(
            name="archive",
            label="Archive",
            icon=":material/archive:",
            button_type="primary",
        ),
    ),
    SessionStatus.PUBLISHED: (
        RowAction(
            name="archive",
            label="Archive",
            icon=":material/archive:",
            button_type="primary",
        ),
    ),
    SessionStatus.ARCHIVED: (),
}

def render(
    session_service: SessionService,
    filters: SessionFilters,
    *,
    actor_id: str,
    app_timezone: str,
) -> None:
    page_key = "sessions_pagination"

    message = st.session_state.pop(
        "session_action_message",
        None,
    )

    if message is not None:
        st.success(message)

    requested_page = int(
        st.session_state.get(page_key, 1)
    )

    result = session_service.list_session_table(
        filters,
        page=requested_page,
        page_size=ROWS_PER_PAGE,
    )

    total_pages = result.total_pages

    st.markdown(
        f":primary[Sessions ({result.total})]"
    )

    with st.container(border=True):
        table_slot = st.empty()

        selected_page = st.pagination(
            num_pages=total_pages,
            key=page_key,
        )

    if selected_page != requested_page:
        result = session_service.list_session_table(
            filters,
            page=selected_page,
            page_size=ROWS_PER_PAGE,
        )
    
    with table_slot.container():
        if not result.items:
            st.info(
                "No sessions match the selected filters."
            )

        for item in result.items:
            _render_session_row(
                session=item.session,
                snapshot=item.snapshot,
                on_action=partial(
                    _handle_session_action,
                    session_service,
                    actor_id=actor_id,
                    app_timezone=app_timezone
                ),
            )

def _handle_session_action(
    session_service: SessionService,
    action: ActionName,
    session: SessionScenario,
    snapshot: ScenarioSnapshot | None,
    *,
    actor_id: str,
    app_timezone: str,
) -> None:
    if action == "edit":
            _render_edit_session_modal(
                session_service=session_service,
                session=session,
                snapshot=snapshot,
                actor_id=actor_id,
                app_timezone=app_timezone
            )
            return
    try:
        if action == "open":
            session_service.open_session(
                session.session_id,
                actor_id=actor_id,
            )
            message = "Session opened."

        elif action == "close":
            session_service.close_session(
                session.session_id,
                actor_id=actor_id,
            )
            message = "Session closed."

        elif action == "archive":
            session_service.archive_session(
                session.session_id,
                actor_id=actor_id,
            )
            message = "Session archived."

        elif action == "delete":
            session_service.delete_session(
                session.session_id,
            )
            message = "Session deleted."

        else:
            raise ValueError(
                f"Unsupported session action: {action}"
            )

    except Exception as error:
        st.error(str(error))
        return

    st.session_state[
        "session_action_message"
    ] = message

    st.rerun()

    # TODO: Implement other actions
    # if action == "open":
    #     session_service.open_session(
    #         session_id,
    #         actor_id="dev-admin",
    #     )
    # elif action == "close":
    #     session_service.close_session(
    #         session_id,
    #         actor_id="dev-admin",
    #     )
    # elif action == "archive":
    #     session_service.archive_session(
    #         session_id,
    #         actor_id="dev-admin",
    #     )

    # st.rerun()

    st.warning(
        f"The {action!r} action is not "
        "connected to an application service yet."
    )

def _render_session_row(
    session: SessionScenario,
    snapshot: ScenarioSnapshot | None,
    *,
    on_action: ActionHandler | None = None,
) -> None:
    container_key = f"session_row_{session.session_id}"

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

    with st.container(
        border=True,
        key=container_key,
    ):
        details_column, stats_column, actions_column = (
            st.columns(
                [4, 5, 4],
                gap="small",
                vertical_alignment="center",
            )
        )

        with details_column:
            _render_session_details(
                session,
                snapshot,
            )

        with stats_column:
            _render_session_stats(session)

        with actions_column:
            _render_session_actions(
                session,
                snapshot,
                on_action=on_action,
            )

def _render_session_details(
    session: SessionScenario,
    snapshot: ScenarioSnapshot | None,
) -> None:
    if snapshot is None:
        st.caption(
            f"{session.scenario_id} "
            f"version {session.scenario_version}"
        )
        st.warning(
            "The scenario snapshot could not be loaded."
        )
        return

    configuration = snapshot.configuration()
    scenario_document = configuration.get(
        "scenario",
        {},
    )
    criteria = configuration.get("criteria", [])

    alternatives = scenario_document.get(
        "alternatives",
        [],
    )

    st.write(
        f"""
        **{session.title}**  
        :gray[{len(alternatives)} alternatives · {len(criteria)} criteria · {len(session.stakeholder_groups)} stakeholder groups]
        """
    )

def _render_session_stats(
    session: SessionScenario,
) -> None:
    deadline_date = (
        session.end_at.strftime(
            "%b %d, %Y"
        )
        if session.end_at is not None
        else "N/A"
    )
    deadline_time = (
        session.end_at.strftime(
            "%I:%M %p"
        )
        if session.end_at is not None
        else "N/A"
    )

    group_count = len(
        session.stakeholder_groups
    )

    rp_column, deadline_column, status_column = (
        st.columns(
            [1, 1, 1],
            gap="small",
            vertical_alignment="center",
        )
    )

    with rp_column:
        participant_count = 0
        st.markdown(f"""
            :gray[Responses]  
            **0**  
            :gray[Participants]  
            **{participant_count}**
            """, text_alignment="center"
        )

    with deadline_column:
        st.markdown(
            f"""
            :gray[End Date]  
            **{deadline_date}**  
            :gray[End Time]  
            **{deadline_time}**
            """,
            text_alignment="center",
        )

    with status_column:
        _render_status_badge(session.status)

def _render_status_badge(
    status: SessionStatus,
) -> None:
    badge_by_status = {
        SessionStatus.DRAFT:
            ":orange-badge[:material/edit: Draft]",
        SessionStatus.OPEN:
            ":blue-badge[:material/check_circle: Open]",
        SessionStatus.CLOSED:
            ":green-badge[:material/cancel: Closed]",
        SessionStatus.PROCESSED:
            ":violet-badge[:material/settings: Processed]",
        SessionStatus.PUBLISHED:
            ":green-badge[:material/public: Published]",
        SessionStatus.ARCHIVED:
            ":gray-badge[:material/archive: Archived]",
    }

    st.markdown(
        badge_by_status.get(
            status,
            ":red-badge[:material/error: Unknown]",
        )
    )

def _render_session_actions(
    session: SessionScenario,
    snapshot: ScenarioSnapshot | None,
    *,
    on_action: ActionHandler | None,
) -> None:
    actions = ACTIONS_BY_STATUS.get(
        session.status,
        (),
    )

    if not actions:
        st.caption("No available actions")
        return

    columns = st.columns(
        len(actions),
        gap="small",
        vertical_alignment="center",
    )

    with st.container(
        horizontal=True,
        horizontal_alignment="right",
        vertical_alignment="center",
        gap="xsmall",
    ):
        for action in actions:
            clicked = st.button(
                action.label,
                icon=action.icon,
                type=action.button_type,
                width="stretch",
                key=(
                    f"{session.session_id}_"
                    f"{action.name}"
                ),
            )

            if clicked and on_action is not None:
                on_action(
                    action.name,
                    session,
                    snapshot,
                )

    # for column, action in zip(
    #     columns,
    #     actions,
    #     strict=True,
    # ):
    #     with column:
    #         clicked = st.button(
    #             action.label,
    #             icon=action.icon,
    #             type=action.button_type,
    #             width="stretch",
    #             key=(
    #                 f"{session.session_id}_{action.name}"
    #             ),
    #         )

    #         if clicked and on_action is not None:
    #             on_action(
    #                 action.name,
    #                 session,
    #                 snapshot,
    #             )

@st.dialog(":primary[Edit Session]", width="large", icon=":material/edit:", on_dismiss="rerun")
def _render_edit_session_modal(
    session_service: SessionService,
    session: SessionScenario,
    snapshot: ScenarioSnapshot | None,
    *,
    actor_id: str,
    app_timezone: str,
) -> None:
    scenario_title = (snapshot.title if snapshot is not None else "Unavailable")

    st.caption(
        f"Scenario: {scenario_title} · "
        f"Version {session.scenario_version}"
    )

    with st.form(
        key=f"edit_session_{session.session_id}",
        border=False,
    ):
        title = st.text_input(
            "Session title",
            value=session.title,
        )

        description = st.text_area(
            "Description",
            value=session.description or "",
        )

        visibility_options = list(
            SessionVisibility
        )

        visibility = st.radio(
            "Visibility",
            options=visibility_options,
            index=visibility_options.index(
                session.visibility
            ),
            format_func=lambda value: value.value,
            horizontal=True,
        )

        admin_notes = st.text_area(
            "Administrative notes",
            value=session.admin_notes or "",
        )

        st.markdown("**Session Model Configuration**")
        config_grid = grid(5)

        config_grid.markdown(f""":gray[Weighting Method]  
                            **{session.weighting_method.value}**
                            """)
        config_grid.markdown(f""":gray[Ranking Method]  
                            **{session.ranking_method.value}**
                            """)
        config_grid.markdown(f""":gray[Preference Scale]  
                            **{session.preference_scale.value}**
                            """)
        config_grid.markdown(f""":gray[Participation Method]  
                            **{session.participation_method.value}**
                            """)
        config_grid.markdown(f""":gray[Aggregation Method]  
                            **{session.aggregation_method.value}**
                            """)

        end_at = st.datetime_input(
            "End date and time",
            value=session.end_at,
            min_value=session.start_at,
        )

        save_column, cancel_column = st.columns(
            2,
            gap="small",
        )

        with save_column:
            save_clicked = st.form_submit_button(
                "Save changes",
                type="primary",
                icon=":material/save:",
                width="stretch",
            )

        with cancel_column:
            cancel_clicked = st.form_submit_button(
                "Cancel",
                width="stretch",
            )

    if cancel_clicked:
        st.rerun()
        return

    if not save_clicked:
        return

    command = UpdateSessionCommand(
        session_id=session.session_id,
        title=title,
        description=description.strip() or None,
        admin_notes=admin_notes.strip() or None,
        visibility=visibility,
        end_at=_to_aware_datetime(end_at, app_timezone),
        actor_id=actor_id,
    )

    try:
        session_service.update_session(command)
    except Exception as error:
        st.error(str(error))
        return

    st.session_state[
        "session_action_message"
    ] = "Session updated."

    st.rerun()
    # st.markdown(f"{session.title}  :gray[Scenario: {snapshot.title if snapshot else 'N/A'}]")

def _to_aware_datetime(
    value: datetime,
    timezone_name: str,
) -> datetime:
    if value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo(timezone_name))

    return value.astimezone(UTC)