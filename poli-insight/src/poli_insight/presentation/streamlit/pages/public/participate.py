"""Public discovery, enrollment, consent, and questionnaire workspace."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import streamlit as st
from streamlit_extras.steps import steps  # type: ignore[import-untyped]

from poli_insight.application.queries.page_queries import (
    ParticipationQuestion,
    ParticipationWorkspace,
    PublicParticipationSession,
    PublicSessionSummary,
)
from poli_insight.application.use_cases.enroll_participant import (
    EnrollParticipantCommand,
    EnrollParticipantError,
)
from poli_insight.application.use_cases.participant_access import (
    ParticipantAccessError,
)
from poli_insight.application.use_cases.save_submission_draft import (
    DraftAnswerInput,
    SaveSubmissionDraftCommand,
    SaveSubmissionDraftError,
)
from poli_insight.application.use_cases.submit_response import (
    SubmitResponseCommand,
    SubmitResponseError,
)
from poli_insight.domain.enum import (
    AccessCodeMode,
    EnrollmentMode,
    ResponseFormat,
    StakeholderSelectionMode,
    SubmissionStatus,
)
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    format_datetime,
    render_empty_state,
    render_page_header,
    render_section_heading,
    surface,
)
from poli_insight.presentation.streamlit.components.preference_slider import (
    balanced_options,
    preference_slider,
)
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.urls import (
    private_results_url,
    private_resume_url,
)

_SEARCH_KEY = "participate:search"
_PENDING_RESUME_KEY = "participate:pending-resume-credential"


@dataclass(frozen=True, slots=True, repr=False)
class _PendingResumeCredential:
    resume_url: str
    expires_at: datetime

    def __repr__(self) -> str:
        return "_PendingResumeCredential(resume_url=<redacted>)"


def render(context: PageContext) -> None:
    if isinstance(
        st.session_state.get(_PENDING_RESUME_KEY),
        _PendingResumeCredential,
    ):
        _render_save_resume_link_dialog(context)
        return
    access_token = _query_value("access")
    if access_token:
        _render_authenticated_workspace(context, access_token)
        return
    selected_slug = _query_value("session")
    if selected_slug:
        _render_enrollment(context, selected_slug)
        return
    _render_catalog(context)


def _render_catalog(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="Public participation",
            title="Participate",
            description=(
                "Discover open research questionnaires, review the study "
                "information, and save progress as you participate."
            ),
        )
    )

    invite, public = st.columns(
        [0.4, 0.6],
    )

    with invite, surface(key="participate:invitation", variant="filter"):
        st.subheader("Have an invitation or private resume link?", anchor=False)
        st.write(
            "Open the complete link supplied by the researcher. Unlisted and "
            "invitation-only studies do not appear in the public catalog."
        )
    with public:
        with st.form("participate:search-form", height="stretch"):
            search = st.text_input(
                "Search open studies",
                value=st.session_state.get(_SEARCH_KEY, ""),
                placeholder="Search by study title",
            )
            submitted = st.form_submit_button("Search", icon=":material/search:")
        if submitted:
            st.session_state[_SEARCH_KEY] = search.strip()
    result = context.queries.list_open_public_sessions(
        search=st.session_state.get(_SEARCH_KEY) or None,
    )
    if not result.items:
        render_empty_state(
            "No matching studies are open",
            "Try another search or return later.",
            icon=":material/event_busy:",
        )
        return
    st.caption(f"{result.total} open stud{'y' if result.total == 1 else 'ies'}")
    for session in result.items:
        _render_session_card(
            session,
            timezone_name=context.container.settings.app_timezone,
        )


def _render_session_card(
    session: PublicSessionSummary,
    *,
    timezone_name: str,
) -> None:
    with surface(
        key=f"participate:session-card:{session.session_id}", variant="feature"
    ):
        header_columns = st.columns([0.7, 0.3], vertical_alignment="center")
        with header_columns[0]:
            st.subheader(session.title, anchor=False)
            st.markdown(session.domain)
            tags = ""
            for tag in session.tags:
                tags += f":blue-badge[{tag}] "
            st.markdown(tags)
        with header_columns[1]:
            st.caption(_access_label(session))
            st.caption(
                "Closes: "
                + format_datetime(
                    session.closes_at,
                    timezone_name=timezone_name,
                    empty="No closing time listed",
                )
            )
        detail_columns = st.columns(2)
        with detail_columns[0]:
            st.markdown("**Policy question**")
            st.write(session.policy_question)
        with detail_columns[1]:
            st.markdown("**Session Description**")
            if session.description:
                st.write(session.description)
            else:
                st.write(
                    "This study has no description. Contact the researcher for details."
                )

        if st.button(
            "View study",
            key=f"participate:session:{session.session_id}",
            icon=":material/arrow_forward:",
            type="primary",
        ):
            st.query_params["session"] = session.public_slug
            st.rerun()


def _render_enrollment(context: PageContext, slug: str) -> None:
    session = context.queries.get_public_participation_session(slug)
    if session is None:
        _unavailable_study()
        return
    render_page_header(
        PageHeader(
            eyebrow="Study access",
            title=session.title,
            description=session.description or "Review access details and enroll.",
        )
    )
    if not session.groups:
        st.error(
            "This study has no eligible participant groups. Contact the researcher.",
            icon=":material/error:",
        )
        return
    invitation_token = _query_value("invitation")
    if (
        session.enrollment_mode == EnrollmentMode.INVITATION_ONLY
        and not invitation_token
    ):
        st.warning(
            "This study requires the invitation link supplied by the researcher.",
            icon=":material/key:",
        )
        _back_to_catalog()
        return
    if (
        session.identity_policy == "authenticated"
        and not context.principal.is_authenticated
    ):
        st.warning(
            "This study requires an authenticated account. Sign in using the "
            "administrator account page, then return to this study.",
            icon=":material/account_circle:",
        )
        _back_to_catalog()
        return
    enrollment_key = f"participate:enroll:{session.session_id}"
    with surface(key=enrollment_key):
        render_section_heading("Participant access")
        alias = st.text_input(
            "Participant alias (optional)",
            max_chars=160,
            help="Use a pseudonym. Do not enter identifying information.",
            key=f"{enrollment_key}:alias",
        )
        selected_group_id = _group_selection(session)
        access_code = None
        requires_access_code = session.access_code_mode in (
            AccessCodeMode.SHARED_SESSION_CODE,
            AccessCodeMode.PER_INVITATION_CODE,
        )
        if requires_access_code:
            access_code = st.text_input(
                "Access code",
                type="password",
                key=f"{enrollment_key}:access-code",
            )
        confirmed = st.checkbox(
            "I understand that I will receive a private resume link after enrollment.",
            key=f"{enrollment_key}:confirmed",
        )
        missing_group = (
            session.stakeholder_selection_mode == StakeholderSelectionMode.SELF_SELECT
            and selected_group_id is None
        )
        missing_code = requires_access_code and not access_code
        enroll = st.button(
            "Enroll and continue",
            type="primary",
            icon=":material/login:",
            disabled=missing_group or missing_code or not confirmed,
            key=f"{enrollment_key}:submit",
        )
    if enroll and missing_group:
        st.error(
            "Select the participant perspective that you represent.",
            icon=":material/error:",
        )
        _back_to_catalog()
        return
    if enroll and missing_code:
        st.error(
            "Enter the access code supplied by the researcher.",
            icon=":material/error:",
        )
        _back_to_catalog()
        return
    if enroll and not confirmed:
        st.error(
            "Confirm that you understand how the private resume link works.",
            icon=":material/error:",
        )
        _back_to_catalog()
        return
    if enroll:
        try:
            with st.spinner("Preparing your questionnaire…"):
                result = context.container.participation.enroll.execute(
                    EnrollParticipantCommand(
                        session_id=session.session_id,
                        selected_group_id=selected_group_id,
                        invitation_token=invitation_token,
                        access_code=access_code or None,
                        user_id=(
                            context.principal.subject
                            if session.identity_policy == "authenticated"
                            else None
                        ),
                        alias=alias.strip() or None,
                    )
                )
        except EnrollParticipantError:
            st.error(
                "Enrollment could not be authorized. Check the invitation, "
                "access code, and participant group, then try again.",
                icon=":material/error:",
            )
            return
        st.query_params["session"] = slug
        st.query_params["access"] = result.access_token
        st.query_params.pop("invitation", None)
        st.session_state[_PENDING_RESUME_KEY] = _PendingResumeCredential(
            resume_url=private_resume_url(
                context.container.settings.public_base_url,
                session_slug=slug,
                access_token=result.access_token,
            ),
            expires_at=result.access_token_expires_at,
        )
        st.rerun()
    _back_to_catalog()


@st.dialog("Save your private return link", width="large", dismissible=False)
def _render_save_resume_link_dialog(context: PageContext) -> None:
    pending = st.session_state.get(_PENDING_RESUME_KEY)
    if not isinstance(pending, _PendingResumeCredential):
        st.error("The one-time resume link is no longer available.")
        return
    st.warning(
        "This private link grants access to your questionnaire. Do not share it.",
        icon=":material/key:",
    )
    st.code(pending.resume_url, language=None, wrap_lines=True)
    st.caption(
        "Expires "
        + format_datetime(
            pending.expires_at,
            timezone_name=context.container.settings.app_timezone,
        )
    )
    st.write(
        "Bookmark this page or copy the complete link now. Answers are retained "
        "only after you choose **Save draft** or another action that saves them."
    )
    download = (
        "Poli Insight private questionnaire return link\n\n"
        f"{pending.resume_url}\n\n"
        f"Expires: {pending.expires_at.isoformat()}\n"
    )
    st.download_button(
        "Download link as text",
        data=download,
        file_name="poli-insight-private-return-link.txt",
        mime="text/plain",
        key="participate:resume-link:download",
    )
    acknowledged = st.checkbox(
        "I have saved this link in a private place.",
        key="participate:resume-link:acknowledged",
    )
    if st.button(
        "Continue to questionnaire",
        type="primary",
        disabled=not acknowledged,
        key="participate:resume-link:continue",
    ):
        # This is the only temporary application-owned plaintext copy. The
        # query parameter remains because it is the participant credential.
        st.session_state.pop(_PENDING_RESUME_KEY, None)
        st.session_state.pop("participate:resume-link:acknowledged", None)
        st.rerun()


def _group_selection(session: PublicParticipationSession) -> str | None:
    if session.stakeholder_selection_mode != StakeholderSelectionMode.SELF_SELECT:
        st.caption("Your participant group is assigned by the invitation.")
        return None
    options = {group.name: group.group_id for group in session.groups}
    selected = st.selectbox(
        "Participant perspective",
        options=tuple(options),
        index=None,
        placeholder="Choose the perspective you represent",
        key=f"participate:enroll:{session.session_id}:group",
    )
    if selected:
        group = next(group for group in session.groups if group.name == selected)
        st.caption(group.description)
        return options[selected]
    return None


def _render_authenticated_workspace(context: PageContext, access_token: str) -> None:
    try:
        access = context.container.participation.resume.execute(access_token)
    except ParticipantAccessError as error:
        render_page_header(
            PageHeader(
                eyebrow="Participation access",
                title="Resume link unavailable",
                description=str(error),
            )
        )
        st.warning(
            "Ask the researcher for a new link if you believe access should still be active.",
            icon=":material/link_off:",
        )
        _back_to_catalog()
        return
    workspace = context.queries.get_participation_workspace(access.participant_id)
    if workspace is None:
        _unavailable_study()
        return
    render_page_header(
        PageHeader(
            eyebrow="Questionnaire workspace",
            title=workspace.session.title,
            description=(
                "Your answers are saved when you move between questions or select "
                "Save draft. Keep this private link if you plan to return later."
            ),
        )
    )
    if workspace.submission_status == SubmissionStatus.SUBMITTED:
        _render_completion(
            workspace,
            results_url=_released_results_url(context, workspace, access_token),
        )
        return
    if not workspace.questions:
        st.error(
            "This questionnaire has no response questions. Contact the researcher.",
            icon=":material/error:",
        )
        return
    if not workspace.scale_options:
        st.error(
            "The configured response scale is empty. Contact the researcher.",
            icon=":material/error:",
        )
        return
    wizard = steps(
        ("Consent", "Questionnaire", "Review", "Complete"),
        icons=(
            ":material/fact_check:",
            ":material/checklist:",
            ":material/rate_review:",
            ":material/task_alt:",
        ),
        horizontal=True,
        key=f"participation:{workspace.participant_id}:{workspace.attempt_number or 1}",
    )
    if wizard.current > 0 and not _consent_ready(workspace):
        wizard.set(0)
    if wizard.current == 0:
        with surface(key="participate:consent"):
            if _render_consent(context, workspace, access_token):
                wizard.next()
    elif wizard.current == 1:
        if _render_questionnaire(context, workspace, access_token):
            wizard.next()
    elif wizard.current == 2:
        with surface(key="participate:review"):
            _render_review(context, workspace, access_token, wizard)
    else:
        # A draft cannot enter Complete by manipulating wizard state.
        wizard.set(1)


def _render_consent(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    render_section_heading("Study consent", level=3)
    if not workspace.consent_required:
        st.info(
            "This questionnaire does not require a separate consent acknowledgement."
        )
        return st.button("Continue to questionnaire", type="primary")
    if workspace.consent_completed:
        st.success(
            f"Consent version {workspace.consent_version} has been recorded.",
            icon=":material/verified:",
        )
        return st.button("Continue to questionnaire", type="primary")
    st.subheader(workspace.consent_title, anchor=False)
    with surface(key="participate:consent-statement"):
        st.write(workspace.consent_statement)
    accepted = st.checkbox(
        "I have read this statement and voluntarily consent to participate."
    )
    if st.button("Record consent", type="primary", disabled=not accepted):
        try:
            with st.spinner("Recording consent…"):
                context.container.participation.capture_consent.execute(
                    access_token=access_token,
                    accepted=accepted,
                )
        except ParticipantAccessError as error:
            st.error(str(error), icon=":material/error:")
            return False
        st.success("Consent recorded.", icon=":material/check_circle:")
        return True
    return False


def _render_questionnaire(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    if workspace.response_format == ResponseFormat.PAIRWISE:
        return _render_pairwise(context, workspace, access_token)
    return _render_direct(context, workspace, access_token)


@dataclass
class _QuestionnaireDraft:
    answers: dict[str, str | None]
    current: int
    requested: int | None = None
    notice: str | None = None


def _questionnaire_key(workspace: ParticipationWorkspace) -> str:
    # The first save changes attempt_number from None to 1, not to a new draft.
    return (
        f"participate:questionnaire:{workspace.participant_id}:"
        f"{workspace.attempt_number or 1}"
    )


def _saved_answers(workspace: ParticipationWorkspace) -> dict[str, str | None]:
    valid = {option.scale_value_id for option in workspace.scale_options}
    answers = {}
    for question in workspace.questions:
        value = workspace.answers.get(question.question_definition_id, {}).get(
            "selected_scale_value_id"
        )
        answers[question.question_definition_id] = (
            value if isinstance(value, str) and value in valid else None
        )
    return answers


def _render_direct(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    return _render_question_navigation(context, workspace, access_token)


def _render_pairwise(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    return _render_question_navigation(context, workspace, access_token)


def _render_question_navigation(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    questions = tuple(sorted(workspace.questions, key=lambda item: item.display_order))
    if not questions:
        st.info("There are no questions in this questionnaire.")
        return False
    scope = _questionnaire_key(workspace)
    if scope not in st.session_state:
        saved = _saved_answers(workspace)
        first_missing = next(
            (
                i
                for i, question in enumerate(questions)
                if question.required and saved[question.question_definition_id] is None
            ),
            0,
        )
        st.session_state[scope] = _QuestionnaireDraft(saved, first_missing)
    draft = st.session_state[scope]
    draft.current = max(0, min(draft.current, len(questions) - 1))
    question = questions[draft.current]
    render_section_heading(
        "Compare criteria"
        if workspace.response_format == ResponseFormat.PAIRWISE
        else "Rate each criterion",
        level=3,
    )
    st.write("Choose your preference, then use Next. You can return to any question.")
    # Populate this container after capturing this run's current answer, so the
    # progress and selector reflect it immediately while appearing above the card.
    overview = st.container()
    draft.answers.update(
        _answer_form(
            workspace,
            (question,),
            key=f"{scope}:input",
            defaults=draft.answers,
        )
    )
    valid = {option.scale_value_id for option in workspace.scale_options}
    answers = {
        item.question_definition_id: (
            value
            if isinstance(value := draft.answers.get(item.question_definition_id), str)
            and value in valid
            else None
        )
        for item in questions
    }
    draft.answers = answers
    complete = _required_complete(questions, answers)
    answered = sum(value is not None for value in answers.values())
    with overview:
        st.progress(
            answered / len(questions), text=f"{answered} of {len(questions)} answered"
        )
        selector_key = f"{scope}:selector"

        def request_question() -> None:
            draft.requested = st.session_state[selector_key]

        def question_label(index: int) -> str:
            item = questions[index]
            label = (
                f"{item.left_name} compared with {item.right_name}"
                if item.left_name and item.right_name
                else item.prompt
            )
            status = (
                "Answered"
                if answers[item.question_definition_id] is not None
                else "Unanswered"
            )
            optional = " · Optional" if not item.required else ""
            return f"{index + 1}. {label} — {status}{optional}"

        # Restore the displayed position before mounting. The callback stores the
        # requested destination; it becomes current only after a successful save.
        st.session_state[selector_key] = draft.current
        st.selectbox(
            "Question",
            options=range(len(questions)),
            format_func=question_label,
            key=selector_key,
            on_change=request_question,
        )

    previous_column, position_column, next_column = st.columns([1, 1, 1])
    previous = previous_column.button(
        "Previous",
        icon=":material/arrow_back:",
        width="stretch",
        disabled=draft.current == 0,
        key=f"{scope}:previous",
    )
    position_column.caption(f"Question {draft.current + 1} of {len(questions)}")
    next_clicked = next_column.button(
        "Next",
        icon=":material/arrow_forward:",
        width="stretch",
        disabled=draft.current == len(questions) - 1,
        key=f"{scope}:next",
    )
    saved_answers = _saved_answers(workspace)
    st.caption(
        "You have unsaved changes."
        if answers != saved_answers
        else "Your answers are saved."
        if workspace.submission_id
        else "Your progress will be saved when you move to another question."
    )
    save_column, review_column = st.columns(2)
    save = save_column.button(
        "Save draft", icon=":material/save:", width="stretch", key=f"{scope}:save"
    )
    review = review_column.button(
        "Save and review",
        icon=":material/rate_review:",
        type="primary",
        width="stretch",
        disabled=not complete,
        key=f"{scope}:review",
    )
    if not complete:
        remaining = sum(
            item.required and answers[item.question_definition_id] is None
            for item in questions
        )
        noun = "question" if remaining == 1 else "questions"
        st.caption(f"Answer the remaining {remaining} required {noun} to review.")
    if draft.notice:
        st.success(draft.notice)
        draft.notice = None

    destination = draft.requested
    draft.requested = None
    if previous and draft.current > 0:
        destination = draft.current - 1
    if next_clicked and draft.current < len(questions) - 1:
        destination = draft.current + 1
    if destination is not None:
        destination = max(0, min(destination, len(questions) - 1))
    navigating = destination is not None and destination != draft.current
    if not (save or review or navigating):
        return False
    if review and not complete:
        return False
    if not _save_answers(context, workspace, access_token, answers):
        return False
    if review:
        refreshed = context.queries.get_participation_workspace(
            workspace.participant_id
        )
        if (
            refreshed is None
            or not _required_complete(refreshed.questions, _saved_answers(refreshed))
            or refreshed.submission_id is None
        ):
            st.error(
                "Your saved answers are not yet complete. Please save and try again."
            )
            return False
        return True
    if navigating:
        draft.current = destination
    else:
        draft.notice = "Draft saved. You may safely return using this private link."
    st.rerun()
    return False


def _answer_form(
    workspace: ParticipationWorkspace,
    questions: tuple[ParticipationQuestion, ...],
    *,
    key: str,
    defaults: dict[str, str | None] | None = None,
) -> dict[str, str | None]:
    option_ids = tuple(option.scale_value_id for option in workspace.scale_options)
    option_by_id = {option.scale_value_id: option for option in workspace.scale_options}
    answers: dict[str, str | None] = {}
    for question in questions:
        existing = workspace.answers.get(question.question_definition_id, {})
        selected_id = (
            defaults.get(question.question_definition_id)
            if defaults is not None
            else existing.get("selected_scale_value_id")
        )
        default = selected_id if selected_id in option_ids else None
        label = question.prompt
        if question.left_name and question.right_name:
            label = f"{question.left_name} compared with {question.right_name}"
        with surface(
            key=f"participate:question:{key}:{question.question_definition_id}"
        ):
            st.caption("Required" if question.required else "Optional")
            if (
                workspace.response_format == ResponseFormat.PAIRWISE
                and question.left_name
                and question.right_name
                and (
                    choices := balanced_options(
                        workspace.scale_options,
                        left_name=question.left_name,
                        right_name=question.right_name,
                    )
                )
                is not None
            ):
                answers[question.question_definition_id] = preference_slider(
                    choices=choices,
                    left_name=question.left_name,
                    right_name=question.right_name,
                    left_description=question.left_description,
                    right_description=question.right_description,
                    value=default,
                    key=f"{key}:{question.question_definition_id}",
                )
                continue
            if question.target_description:
                st.text(question.target_description)
            answers[question.question_definition_id] = st.select_slider(
                label,
                options=(None, *option_ids),
                value=default,
                format_func=lambda value: (
                    "Not answered" if value is None else option_by_id[value].label
                ),
                key=f"{key}:{question.question_definition_id}",
                help=question.target_description,
            )
            st.caption(
                f"Scale: {workspace.scale_options[0].label} → "
                f"{workspace.scale_options[-1].label}. "
                "Choose ‘Not answered’ to leave this item blank."
            )
    return answers


def _save_answers(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
    answers: dict[str, str | None],
) -> bool:
    updates = tuple(
        DraftAnswerInput(
            question_definition_id=question_id,
            raw_value_json={"selected_scale_value_id": selected_id},
        )
        for question_id, selected_id in answers.items()
        if selected_id is not None
    )
    removals = tuple(
        question_id
        for question_id, selected_id in answers.items()
        if selected_id is None and question_id in workspace.answers
    )
    try:
        with st.spinner("Saving your answers…"):
            context.container.submissions.save_draft.execute(
                SaveSubmissionDraftCommand(
                    session_id=workspace.session.session_id,
                    participant_id=workspace.participant_id,
                    actor_id=workspace.participant_id,
                    answers=updates,
                    remove_question_definition_ids=removals,
                    access_token=access_token,
                )
            )
    except SaveSubmissionDraftError as error:
        st.error(str(error), icon=":material/error:")
        return False
    return True


def _render_review(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
    wizard,
) -> None:
    render_section_heading("Review your responses", level=3)
    saved_answers = _saved_answers(workspace)
    missing = [
        question
        for question in workspace.questions
        if question.required and saved_answers[question.question_definition_id] is None
    ]
    if missing:
        st.warning(
            f"{len(missing)} required response{'s are' if len(missing) != 1 else ' is'} missing. "
            "Return to the questionnaire and save all required ratings.",
            icon=":material/warning:",
        )
    labels = {option.scale_value_id: option.label for option in workspace.scale_options}
    st.dataframe(
        [
            {
                "Question": question.prompt,
                "Response": labels.get(
                    str(
                        workspace.answers.get(question.question_definition_id, {}).get(
                            "selected_scale_value_id", ""
                        )
                    ),
                    "Missing",
                ),
            }
            for question in workspace.questions
        ],
        hide_index=True,
        width="stretch",
    )
    if st.button("Edit answers", icon=":material/edit:"):
        wizard.previous()
    confirmed = st.checkbox(
        "I have reviewed these responses and understand submission is final."
    )
    if st.button(
        "Submit questionnaire",
        type="primary",
        icon=":material/send:",
        disabled=bool(missing) or not confirmed or workspace.submission_id is None,
    ):
        if (
            missing
            or not confirmed
            or workspace.submission_id is None
            or not _consent_ready(workspace)
        ):
            return
        try:
            with st.spinner("Submitting your questionnaire…"):
                context.container.submissions.submit.execute(
                    SubmitResponseCommand(
                        session_id=workspace.session.session_id,
                        participant_id=workspace.participant_id,
                        submission_id=workspace.submission_id or "",
                        actor_id=workspace.participant_id,
                        access_token=access_token,
                    )
                )
        except SubmitResponseError as error:
            st.error(str(error), icon=":material/error:")
            return
        next_method = getattr(wizard, "next", None)
        if callable(next_method):
            next_method()
        st.rerun()


def _render_completion(
    workspace: ParticipationWorkspace,
    *,
    results_url: str | None = None,
) -> None:
    st.success(
        "Your questionnaire has been submitted successfully.",
        icon=":material/check_circle:",
    )
    st.subheader("Thank you for participating", anchor=False)
    st.write(
        "Your completed response is now read-only and cannot be accidentally "
        "overwritten. You may close this page."
    )
    if workspace.submission_id:
        st.caption(f"Submission reference: `{workspace.submission_id}`")
    if results_url:
        st.link_button(
            "View released results",
            results_url,
            icon=":material/analytics:",
            type="primary",
        )


def _released_results_url(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> str | None:
    if not context.container.packages.participant_access.available(
        workspace.participant_id
    ):
        return None
    return private_results_url(
        context.container.settings.public_base_url,
        session_slug=workspace.session.public_slug,
        access_token=access_token,
    )


def _required_complete(
    questions: tuple[ParticipationQuestion, ...],
    answers: dict[str, str | None],
) -> bool:
    return all(
        not question.required
        or answers.get(question.question_definition_id) is not None
        for question in questions
    )


def _consent_ready(workspace: ParticipationWorkspace) -> bool:
    return not workspace.consent_required or workspace.consent_completed


def _query_value(key: str) -> str | None:
    value = st.query_params.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _back_to_catalog() -> None:
    if st.button("Back to public studies", icon=":material/arrow_back:"):
        st.query_params.clear()
        st.rerun()


def _unavailable_study() -> None:
    render_page_header(
        PageHeader(
            eyebrow="Public participation",
            title="Study unavailable",
            description=(
                "This study is missing, closed, not yet open, or no longer has "
                "an active questionnaire configuration."
            ),
        )
    )
    _back_to_catalog()


def _access_label(session: PublicSessionSummary) -> str:
    if session.enrollment_mode == EnrollmentMode.INVITATION_ONLY:
        return "Access: invitation required"
    if session.access_code_mode == AccessCodeMode.SHARED_SESSION_CODE:
        return "Access: session code required"
    return "Access: open enrollment"
