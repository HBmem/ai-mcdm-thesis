"""Public discovery, enrollment, consent, and questionnaire workspace."""

from __future__ import annotations

from collections import defaultdict
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
)
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.urls import private_resume_url

_SEARCH_KEY = "participate:search"
_PAIRWISE_LEFT_KEY = "participate:pairwise-left"
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

    invite, public = st.columns([0.4,0.6], )

    with invite, st.container(border=True):
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
    with st.container(border=True):
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
                st.write("This study has no description. Contact the researcher for details.")

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
    with st.container(border=True):
        st.markdown("#### Participant access")
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
                "Your progress is saved to this private link. Keep it private "
                "and bookmark it if you plan to return later."
            ),
        )
    )
    if workspace.submission_status == SubmissionStatus.SUBMITTED:
        _render_completion(workspace)
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
        key=f"participation:{workspace.participant_id}",
    )
    with wizard[0]:
        if _render_consent(context, workspace, access_token):
            wizard.next()
    with wizard[1]:
        if not _consent_ready(workspace):
            st.info("Complete consent before beginning the questionnaire.")
        elif _render_questionnaire(context, workspace, access_token):
            refreshed = context.queries.get_participation_workspace(
                workspace.participant_id
            )
            if refreshed is not None:
                workspace = refreshed
            wizard.next()
    with wizard[2]:
        _render_review(context, workspace, access_token, wizard)
    with wizard[3]:
        refreshed = context.queries.get_participation_workspace(
            workspace.participant_id
        )
        if (
            refreshed is not None
            and refreshed.submission_status == SubmissionStatus.SUBMITTED
        ):
            _render_completion(refreshed)
        else:
            st.info("Review and submit your questionnaire to complete participation.")


def _render_consent(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    st.markdown("#### Study consent")
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
    with st.container(border=True):
        st.write(workspace.consent_statement)
    accepted = st.checkbox(
        "I have read this statement and voluntarily consent to participate."
    )
    if st.button("Record consent", type="primary", disabled=not accepted):
        try:
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


def _render_direct(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    st.markdown("#### Rate each criterion")
    st.write(
        f"Choose one value from **{workspace.scale_name}** for every required item."
    )
    answers = _answer_form(workspace, workspace.questions, key="direct")
    complete = _required_complete(workspace.questions, answers)
    return _save_controls(
        context,
        workspace,
        access_token,
        answers,
        complete=complete,
        continue_label="Save and review",
    )


def _render_pairwise(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
) -> bool:
    grouped: dict[str, list[ParticipationQuestion]] = defaultdict(list)
    for question in workspace.questions:
        grouped[question.left_name or "Criterion"].append(question)
    left_names = tuple(grouped)
    current = min(int(st.session_state.get(_PAIRWISE_LEFT_KEY, 0)), len(left_names) - 1)
    left_name = left_names[current]
    completed_count = sum(
        question.question_definition_id in workspace.answers
        for question in workspace.questions
    )
    st.progress(
        completed_count / len(workspace.questions),
        text=f"{completed_count} of {len(workspace.questions)} comparisons saved",
    )
    st.markdown(f"#### Compare {left_name}")
    st.write(
        "For each row, compare the left-side criterion with the right-side criterion."
    )
    questions = tuple(grouped[left_name])
    answers = _answer_form(workspace, questions, key=f"pairwise:{current}")
    page_complete = _required_complete(questions, answers)
    final_left = current == len(left_names) - 1
    continued = _save_controls(
        context,
        workspace,
        access_token,
        answers,
        complete=page_complete,
        continue_label=("Save and review" if final_left else "Save and compare next"),
    )
    if continued and not final_left:
        st.session_state[_PAIRWISE_LEFT_KEY] = current + 1
        st.rerun()
    return continued and final_left


def _answer_form(
    workspace: ParticipationWorkspace,
    questions: tuple[ParticipationQuestion, ...],
    *,
    key: str,
) -> dict[str, str | None]:
    option_ids = tuple(option.scale_value_id for option in workspace.scale_options)
    option_by_id = {option.scale_value_id: option for option in workspace.scale_options}
    answers: dict[str, str | None] = {}
    for question in questions:
        existing = workspace.answers.get(question.question_definition_id, {})
        selected_id = existing.get("selected_scale_value_id")
        index = option_ids.index(selected_id) if selected_id in option_ids else None
        label = question.prompt
        if question.left_name and question.right_name:
            label = f"{question.left_name} compared with {question.right_name}"
        answers[question.question_definition_id] = st.selectbox(
            label,
            options=option_ids,
            index=index,
            format_func=lambda value: option_by_id[value].label,
            placeholder="Choose a rating",
            key=f"participate:{key}:{question.question_definition_id}",
            help=question.target_description,
        )
    return answers


def _save_controls(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
    answers: dict[str, str | None],
    *,
    complete: bool,
    continue_label: str,
) -> bool:
    st.caption(
        f"Saved answers: {len(workspace.answers)} of {len(workspace.questions)}"
        + (
            f" · Last saved {workspace.last_saved_at.isoformat()}"
            if workspace.last_saved_at
            else ""
        )
    )
    columns = st.columns(2)
    save = columns[0].button("Save draft", icon=":material/save:", width="stretch")
    continue_clicked = columns[1].button(
        continue_label,
        icon=":material/arrow_forward:",
        type="primary",
        width="stretch",
        disabled=not complete,
    )
    if not save and not continue_clicked:
        return False
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
    if not continue_clicked:
        st.success("Draft saved. You may safely return using this private link.")
    return continue_clicked


def _render_review(
    context: PageContext,
    workspace: ParticipationWorkspace,
    access_token: str,
    wizard: object,
) -> None:
    st.markdown("#### Review your responses")
    missing = [
        question
        for question in workspace.questions
        if question.required
        and question.question_definition_id not in workspace.answers
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
    confirmed = st.checkbox(
        "I have reviewed these responses and understand submission is final."
    )
    if st.button(
        "Submit questionnaire",
        type="primary",
        icon=":material/send:",
        disabled=bool(missing) or not confirmed or workspace.submission_id is None,
    ):
        try:
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


def _render_completion(workspace: ParticipationWorkspace) -> None:
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
