from __future__ import annotations

import streamlit as st

from streamlit_extras.metric_cards import style_metric_cards
from streamlit_extras.steps import steps, StepsState

from poli_insight.application.services.submissions_service import SubmissionService
from poli_insight.domain.enums import SubmissionStatus, AggregationMethod
from poli_insight.domain.sessions import Session

ROWS_PER_PAGE = 10

def render(
    submission_service: SubmissionService,
    session: Session,
    *,
    actor_id: str,
) -> None:
    page_key = (
        f"submission_pagination_{session.session_id}"
    )
    message_key = "submission_action_message"
    consistency_threshold = 0.10

    message = st.session_state.pop(
        message_key,
        None,
    )

    if message is not None:
        st.success(message)

    requested_page = int(
        st.session_state.get(page_key, 1)
    )

    try:
        dashboard = submission_service.get_dashboard(
            session_id=session.session_id,
            page=requested_page,
            page_size=ROWS_PER_PAGE,
            consistency_threshold=consistency_threshold,
        )
    except Exception as error:
        st.error(
            "The submission dashboard could not be loaded: "
            f"{error}"
        )
        return

    total_pages = dashboard.total_pages

    if requested_page > total_pages:
        st.session_state[page_key] = total_pages
        st.rerun()

    metrics = dashboard.metrics

    if metrics.high_consistency_ratio > 0:
        count = metrics.high_consistency_ratio
        noun = "submission has" if count == 1 else "submissions have"

        st.warning(
            f"{count} {noun} a high consistency ratio "
            f"(>{consistency_threshold:.2f}). "
            "Review these responses before processing.",
            icon=":material/warning:",
        )

    metric_columns = st.columns(5)

    metric_columns[0].metric(
        label="Expected",
        value=metrics.expected,
    )
    metric_columns[1].metric(
        label="Complete",
        value=metrics.complete,
    )
    metric_columns[2].metric(
        label="In Progress",
        value=metrics.in_progress,
    )
    metric_columns[3].metric(
        label="Missing",
        value=metrics.missing,
    )
    metric_columns[4].metric(
        label=f"CR > {consistency_threshold:.2f}",
        value=metrics.high_consistency_ratio,
    )

    style_metric_cards()

    heading_column, filter_column, validate_column = (
        st.columns(
            [5, 2, 1.5],
            vertical_alignment="bottom",
        )
    )

    heading_column.markdown("### Submission status")

    filter_column.selectbox(
        "Submission filter",
        options=("All submissions",),
        key=f"submission_filter_{session.session_id}",
        label_visibility="collapsed",
    )

    validate_column.button(
        "Validate all",
        icon=":material/fact_check:",
        width="stretch",
        disabled=True,
        help=(
            "Connect this button after batch validation "
            "is implemented in the application service."
        ),
    )

    with st.container(border=True):
        if not dashboard.items:
            st.info(
                "No participants are currently expected "
                "to submit for this session."
            )
        else:
            header = st.columns(
                [2.2, 1.5, 1.7, 1.7, 1.5, 1.5, 1.2],
                vertical_alignment="center",
            )

            header[0].markdown("**PARTICIPANT**")
            header[1].markdown("**GROUP**")
            header[2].markdown("**SUBMITTED AT**")
            header[3].markdown("**COMPLETION**")
            header[4].markdown("**CONSISTENCY**")
            header[5].markdown("**VALIDATION**")
            header[6].markdown("**ACTIONS**")

            st.divider()

            for item in dashboard.items:
                row = st.columns(
                    [2.2, 1.5, 1.7, 1.7, 1.5, 1.5, 1.2],
                    vertical_alignment="center",
                )

                display_name = (
                    item.participant_name
                    or item.participant_alias
                    or "Unnamed participant"
                )

                with row[0]:
                    st.markdown(f"**{display_name}**")
                    st.caption(item.participant_id)

                with row[1]:
                    st.markdown(
                        f":blue-badge[{item.stakeholder_group_name}]"
                    )

                with row[2]:
                    if item.submitted_at is not None:
                        st.markdown(
                            item.submitted_at.strftime(
                                "%d %b %Y, %H:%M"
                            )
                        )
                    elif (
                        item.submission_status
                        == SubmissionStatus.DRAFT
                    ):
                        st.markdown(":orange[In progress…]")
                    else:
                        st.markdown(":gray[Not submitted]")

                with row[3]:
                    completion = min(
                        max(item.completion_ratio, 0.0),
                        1.0,
                    )
                    completion_percent = round(
                        completion * 100
                    )

                    st.progress(
                        completion,
                        text=f"{completion_percent}%",
                    )

                with row[4]:
                    ratio = item.consistency_ratio

                    if ratio is None:
                        st.markdown(":gray[—]")
                    elif ratio > consistency_threshold:
                        st.markdown(
                            f":red[CR = {ratio:.2f}]"
                        )
                    else:
                        st.markdown(
                            f":green[CR = {ratio:.2f}]"
                        )

                with row[5]:
                    badge_by_status = {
                        "valid": (
                            ":green-badge[:material/check: Valid]"
                        ),
                        "cr_high": (
                            ":red-badge[:material/close: CR high]"
                        ),
                        "invalid": (
                            ":red-badge[:material/error: Invalid]"
                        ),
                        "pending": (
                            ":orange-badge[:material/hourglass_empty: "
                            "Pending]"
                        ),
                        "missing": (
                            ":gray-badge[:material/remove: Missing]"
                        ),
                    }

                    st.markdown(
                        badge_by_status.get(
                            item.validation_status,
                            ":gray-badge[Unknown]",
                        )
                    )

                with row[6]:
                    can_withdraw = (
                        item.submission_id is not None
                        and item.submission_status
                        in {
                            SubmissionStatus.DRAFT,
                            SubmissionStatus.SUBMITTED,
                        }
                    )

                    if can_withdraw:
                        withdraw_clicked = st.button(
                            "Withdraw",
                            icon=":material/cancel:",
                            key=(
                                "withdraw_submission_"
                                f"{item.submission_id}"
                            ),
                            width="stretch",
                        )

                        if withdraw_clicked:
                            try:
                                submission_service.withdraw_submission(
                                    item.submission_id,
                                    session_id=session.session_id,
                                    actor_id=actor_id,
                                )
                            except Exception as error:
                                st.error(str(error))
                            else:
                                st.session_state[
                                    message_key
                                ] = (
                                    "Submission withdrawn "
                                    "successfully."
                                )
                                st.rerun()
                    else:
                        st.markdown(":gray[—]")

                st.divider()

        st.pagination(
            num_pages=total_pages,
            key=page_key,
            # width="stretch",
        )

    st.divider()

    text_col, log_col = st.columns([0.7,0.3])

    with text_col.container(horizontal_alignment="left", vertical_alignment="center"):
        st.markdown(
            f"""
            :primary[IMPORT SUBMISSIONS]  
            Create participants and their submissions in bulk from a CSV or Excel file. 
            Each row becomes one participant record and one complete submission.
            """
        )

    with log_col.container(horizontal_alignment="right", vertical_alignment="center"):
        st.button(
            "View Import Log",
            disabled=True,
        )

    st.html(
        f"""
        <style>
        .st-key-import_container {{
            background: #fff;
        }}
        </style>
        """
    )
    
    with st.container(
        border=True,
        key="import_container"
    ):
        import_steps = steps(
            ["Download Template", "Upload & Preview", "Validate", "Import"],
            horizontal=True,
            icons=range(1, 4),
            key="import_steps",
        )

        with import_steps[0]:
            _render_import_step1(session, import_steps)

        with import_steps[1]:
            _render_import_step2(session, import_steps)

def _render_import_step1(session: Session, steps: StepsState):
    st.markdown(
        """
        Download the appropriate template for your data." \
        "Each row should represent one stakeholder — include their display name, alias, stakeholder group ID, and one preference rating column per criterion.
        """
    )

    _build_import_template(session=session)

    if session.aggregation_method == AggregationMethod.INDIVIDUAL:
        st.info(
            """
            Single-stakeholder session  
            This session has one stakeholder group.
            Each import file should contain rows for one group only.
            Importing mixed-group files will cause validation errors. 
            """
        )

    left_button, right_button = st.columns(2)

    with right_button.container(horizontal_alignment="right"):
        if st.button("Next", key="step1_next"):
            steps.next()

def _render_import_step2(session: Session, steps: StepsState):
    st.markdown(
            """
            Upload your completed CSV or Excel file.
            A preview of the first rows will appear immediately so you can confirm the data parsed correctly before validating.
            """
        )

    uploaded_file = st.file_uploader(
        "Drop a CSV or JSON file to import submissions",
        type=("csv", "json"),
        key=f"submission_import_{session.session_id}",
        help=(
            "Import parsing and participant creation must "
            "be handled by an application service."
        ),
    )

    if uploaded_file is not None:
        st.info(
            f"{uploaded_file.name} is ready for a dry-run "
            "validation. Connect this uploader to the batch "
            "import service before writing records."
        )

    left_button, right_button = st.columns(2)

    with left_button.container(horizontal_alignment="left"):
            if st.button("Back", key="step2_Back"):
                steps.previous()
    
    with right_button.container(horizontal_alignment="right"):
        if st.button("Next", key="step2_next"):
            steps.next()
    
    # st.markdown("#### :primary[Import submissions]")

    # uploaded_file = st.file_uploader(
    #     "Drop a CSV or JSON file to import submissions",
    #     type=("csv", "json"),
    #     key=f"submission_import_{session.session_id}",
    #     help=(
    #         "Import parsing and participant creation must "
    #         "be handled by an application service."
    #     ),
    # )

    # if uploaded_file is not None:
    #     st.info(
    #         f"{uploaded_file.name} is ready for a dry-run "
    #         "validation. Connect this uploader to the batch "
    #         "import service before writing records."
    #     )

def _build_import_template(session: Session):
    csv_col, excel_col = st.columns(2)

    stakeholder_group_id = (
        session.stakeholder_groups[0].stakeholder_group_id
        if session.stakeholder_groups
        else "example_stakeholder_group"
    )
    
    with csv_col:
        st.button(
            "CSV Template",
            disabled=True,
            width="stretch",
        )
    with excel_col:
        st.button(
            "Excel Template",
            disabled=True,
            width="stretch",
        )
