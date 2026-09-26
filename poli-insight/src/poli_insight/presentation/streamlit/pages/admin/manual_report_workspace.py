"""Document, narrative editing, and review controls for manual reports."""

import difflib

import streamlit as st

from poli_insight.application.use_cases.manual_reporting import package_warnings
from poli_insight.domain.reporting import (
    EVIDENCE_SECTIONS,
    NARRATIVE_SECTIONS,
)
from poli_insight.presentation.streamlit.components.process_ui import (
    admin_action_button,
    admin_form_submit_button,
)
from poli_insight.presentation.streamlit.urls import public_report_url


def _action(call):
    try:
        call()
    except ValueError as error:
        st.error(str(error))
    else:
        st.rerun()


def documents(context, session_id, workspace):
    service, actor = context.container.reporting, context.principal
    st.subheader("Supporting documents")
    st.caption(
        "Manage versions and sharing approval. Files load only when you open a preview."
    )
    if st.button("Upload document", icon=":material/upload:"):
        _upload_document_dialog(context, session_id, workspace)
    versions = workspace["versions"]
    if not versions:
        st.info("No supporting documents have been uploaded.")
        return
    version = st.selectbox(
        "Document version",
        versions,
        format_func=lambda v: f"{v.title} · v{v.number} · {v.classification.title()}",
        key=f"docs:{session_id}:selected",
    )
    approved = version.version_id in workspace["approved_documents"]
    st.text(
        f"Source: {version.source_reference or 'Not provided'}\nUploaded by {version.created_by} at {version.created_at.isoformat()}"
    )
    st.caption(
        "Approved for shared reports" if approved else "Not approved for shared reports"
    )
    if st.toggle(
        "Open document preview and download", key=f"doc:{version.version_id}:load"
    ):
        loaded = service.document(actor, version.version_id)
        if loaded.media_type in {"text/plain", "text/markdown"}:
            text = loaded.content.decode("utf-8-sig")
            st.text(text[:50000])
            if len(text) > 50000:
                st.caption(
                    "Preview truncated. Download the document for the complete text."
                )
        st.download_button(
            "Download document",
            loaded.content,
            file_name=loaded.filename,
            mime=loaded.media_type,
            key=f"doc:{version.version_id}:download",
        )
    if version.classification == "shareable" and not approved:
        confirm = st.checkbox(
            "I approve this exact document version for sharing with report recipients.",
            key=f"doc:{version.version_id}:confirm",
        )
        if st.button(
            "Approve document version",
            disabled=not confirm,
            key=f"doc:{version.version_id}:approve",
        ):
            _action(lambda: service.approve_document(actor, version.version_id))


@st.dialog("Upload a supporting document", width="large")
def _upload_document_dialog(context, session_id, workspace):
    service, actor = context.container.reporting, context.principal
    docs = {doc.document_id: doc for doc in workspace["documents"]}
    versions = workspace["versions"]
    latest = {
        doc.document_id: next(
            v
            for v in versions
            if v.document_id == doc.document_id and v.number == doc.head_number
        )
        for doc in docs.values()
    }
    target = st.selectbox(
        "Upload destination",
        (None, *docs),
        format_func=lambda value: (
            "New document" if value is None else latest[value].title
        ),
        key=f"docs:{session_id}:target",
    )
    # Pin the replacement version to the displayed form, not the current DB head.
    expected_key = f"docs:{session_id}:{target}:expected"
    if target and expected_key not in st.session_state:
        st.session_state[expected_key] = docs[target].head_number
    with st.form(f"docs:{session_id}:upload:{target}"):
        title = st.text_input(
            "Document title", value=latest[target].title if target else ""
        )
        source = st.text_input(
            "Source reference", value=latest[target].source_reference if target else ""
        )
        classification = st.selectbox(
            "Classification", ("confidential", "shareable"), format_func=str.title
        )
        uploaded = st.file_uploader(
            "Document (maximum 20 MB)",
            type=["pdf", "docx", "txt", "md"],
            max_upload_size=20,
        )
        save = admin_form_submit_button(
            "Save document version", panel_key="manual_report_workspace:120"
        )
    if save:
        if uploaded is None:
            st.error("Select a document to upload.")
        else:

            def upload():
                service.upload_document(
                    actor,
                    session_id=session_id,
                    title=title,
                    source_reference=source,
                    classification=classification,
                    filename=uploaded.name,
                    content=uploaded.getvalue(),
                    document_id=target,
                    expected_version=st.session_state.get(expected_key),
                )
                st.session_state.pop(expected_key, None)

            _action(upload)
    if target and st.button("Reload document version", key=f"{expected_key}:reload"):
        st.session_state.pop(expected_key, None)
        st.rerun()


def select_report(context, package, workspace):
    reports = [
        r for r in workspace["reports"] if r.package_run_id == package.package_run_id
    ]
    if not reports:
        st.info("No report exists for this package yet.")
        return None
    by_id = {r.report_id: r for r in reports}
    identity = st.selectbox(
        "Report",
        tuple(by_id),
        format_func=lambda value: f"{by_id[value].title} · {value[:8]}",
        key=f"reports:{package.package_run_id}:report",
    )
    return by_id[identity]


def editor(context, package, report, workspace, *, show_create=True):
    service, actor = context.container.reporting, context.principal
    st.subheader("Edit report")
    st.caption(
        "Save a new revision before leaving this editor. Calculated evidence cannot be edited."
    )
    if show_create and st.button("Create report draft"):
        create_report_dialog(context, package)
    if report is None:
        return
    history = service.history(actor, report.report_id)
    revisions = history["revisions"]
    head = revisions[0]
    prefix = f"editor:{report.report_id}"
    base_key = f"{prefix}:base"
    if base_key not in st.session_state:
        st.session_state[base_key] = head.revision_id
    base = next(r for r in revisions if r.revision_id == st.session_state[base_key])
    if base.revision_id != head.revision_id:
        st.warning(
            "A newer revision exists. Your form still contains the revision you opened; reload before saving."
        )
    if st.button("Reload latest revision", key=f"{prefix}:reload"):
        for key in list(st.session_state):
            if key.startswith(prefix):
                del st.session_state[key]
        st.rerun()
    st.caption(
        f"Editing revision {base.number}. Saving creates a new draft; evidence tables remain fixed."
    )
    allowed = {
        v.version_id: v
        for v in workspace["versions"]
        if v.version_id in workspace["approved_documents"]
        and v.classification == "shareable"
    }
    with st.form(f"{prefix}:form:{base.revision_id}"):
        sections = {}
        for name in NARRATIVE_SECTIONS:
            value = base.sections[name]
            text = st.text_area(
                name, value=value or "", key=f"{prefix}:{base.revision_id}:{name}:text"
            )
            unassessed = st.checkbox(
                f"{name}: Not assessed",
                value=value is None,
                key=f"{prefix}:{base.revision_id}:{name}:na",
            )
            sections[name] = None if unassessed else text
        refs = st.multiselect(
            "Package evidence references",
            EVIDENCE_SECTIONS,
            default=list(base.evidence_refs),
            key=f"{prefix}:{base.revision_id}:refs",
        )
        doc_ids = st.multiselect(
            "Approved documents to cite and attach",
            tuple(allowed),
            default=list(base.document_ids),
            format_func=lambda value: (
                f"{allowed[value].title} · v{allowed[value].number}"
            ),
            key=f"{prefix}:{base.revision_id}:docs",
        )
        summary = st.text_input(
            "Change summary", key=f"{prefix}:{base.revision_id}:summary"
        )
        save = admin_form_submit_button(
            "Save new draft revision", panel_key="manual_report_workspace:230"
        )
    if save:

        def save_revision():
            revision = service.save_revision(
                actor,
                report_id=report.report_id,
                expected_revision_id=base.revision_id,
                sections=sections,
                evidence_refs=refs,
                document_ids=doc_ids,
                change_summary=summary,
            )
            st.session_state[base_key] = revision.revision_id

        _action(save_revision)
    with st.expander("Revision history and comparison"):
        chosen = st.selectbox(
            "Compare with latest revision",
            revisions,
            format_func=lambda r: f"Revision {r.number} · {r.change_summary}",
            key=f"{prefix}:compare",
        )
        st.caption(f"Latest: {head.created_by} · {head.created_at.isoformat()}")
        changed = False
        for name in NARRATIVE_SECTIONS:
            old = (
                "Not assessed"
                if chosen.sections[name] is None
                else chosen.sections[name]
            )
            new = "Not assessed" if head.sections[name] is None else head.sections[name]
            if old != new:
                changed = True
                st.caption(name)
                st.code(
                    "\n".join(
                        difflib.unified_diff(
                            old.splitlines(),
                            new.splitlines(),
                            fromfile=f"v{chosen.number}",
                            tofile=f"v{head.number}",
                            lineterm="",
                        )
                    ),
                    language="diff",
                )
        if not changed:
            st.caption("No narrative differences.")
        st.write(
            {
                "Previous evidence sources": chosen.evidence_refs,
                "Latest evidence sources": head.evidence_refs,
                "Previous document versions": chosen.document_ids,
                "Latest document versions": head.document_ids,
            }
        )
    with st.expander("Moderator-only notes"):
        st.caption(
            "These notes never appear in shared pages or exports. Keep confidential observations here."
        )
        with st.form(f"{prefix}:notes", clear_on_submit=True):
            note = st.text_area("New internal note")
            add = admin_form_submit_button(
                "Add internal note", panel_key="manual_report_workspace:293"
            )
        if add:
            _action(
                lambda: service.add_note(actor, report_id=report.report_id, body=note)
            )
        for note in history["notes"]:
            st.caption(f"{note.created_by} · {note.created_at.isoformat()}")
            st.text(note.body)


@st.dialog("Create a report draft", width="large")
def create_report_dialog(context, package):
    st.caption(
        "AI drafting is deferred. This creates a moderator-authored draft grounded in the selected package."
    )
    with st.form(f"reports:{package.package_run_id}:create"):
        title = st.text_input("Report title")
        create = admin_form_submit_button(
            "Create report draft", panel_key="manual_report_workspace:310"
        )
    if create:
        _action(
            lambda: context.container.reporting.create_report(
                context.principal, package_run_id=package.package_run_id, title=title
            )
        )


@st.dialog("Review report revision", width="large")
def review_dialog(context, package, revision, status):
    service, actor = context.container.reporting, context.principal
    st.caption(f"Revision {revision.number} · {status.title()}")
    evidence = service.package_evidence(actor, package.package_run_id)
    warnings = package_warnings(evidence)
    if warnings:
        st.warning("Package warnings: " + "; ".join(warnings))
    acknowledged = st.checkbox(
        "I have reviewed this revision, its sources, completeness, and privacy warnings.",
        key=f"review:{revision.revision_id}:ack",
    )
    reason = st.text_area(
        "Review comment / required rejection reason",
        key=f"review:{revision.revision_id}:reason",
    )
    if status in {"draft", "rejected"}:
        if st.button("Submit for review", disabled=not acknowledged):
            _action(
                lambda: service.review(
                    actor,
                    revision_id=revision.revision_id,
                    status="submitted",
                    reason=reason,
                    warnings_acknowledged=acknowledged,
                )
            )
    elif status == "submitted":
        a, b = st.columns(2)
        if a.button("Approve revision", disabled=not acknowledged):
            _action(
                lambda: service.review(
                    actor,
                    revision_id=revision.revision_id,
                    status="approved",
                    reason=reason,
                    warnings_acknowledged=acknowledged,
                )
            )
        if b.button("Reject revision", disabled=not reason.strip()):
            _action(
                lambda: service.review(
                    actor,
                    revision_id=revision.revision_id,
                    status="rejected",
                    reason=reason,
                )
            )
    else:
        st.success(
            "This revision is already approved. Changes require a new draft revision."
        )


@st.dialog("Confirm report publication", width="large")
def publish_dialog(context, revision, audience):
    st.write(
        f"Publish revision {revision.number} to {'session participants through their private links' if audience == 'participant' else 'the public catalog and a shareable link'}."
    )
    confirmed = st.checkbox("I authorize publication of this exact revision.")
    if admin_action_button(
        "Confirm publication",
        disabled=not confirmed,
        type="primary",
        panel_key="manual_report_workspace:379",
    ):
        _action(
            lambda: context.container.reporting.publish(
                context.principal, revision_id=revision.revision_id, audience=audience
            )
        )


@st.dialog("Export report", width="large")
def export_dialog(context, revision_id):
    from poli_insight.presentation.streamlit.components.report_view import (
        render_report_downloads,
    )

    report = context.container.reporting.preview(context.principal, revision_id)
    st.caption(f"{report.title} · Revision {report.revision.number}")
    if report.draft:
        st.warning("This revision is a draft. Downloads are marked as unapproved.")
    render_report_downloads(report, key=f"export:{revision_id}")


@st.dialog("Withdraw report release", width="large")
def _withdraw_dialog(context, release):
    st.write(f"Withdraw {release.audience} release {release.number}.")
    reason = st.text_area("Withdrawal reason")
    if st.button("Confirm withdrawal", disabled=not reason.strip()):
        _action(
            lambda: context.container.reporting.withdraw(
                context.principal, release_id=release.release_id, reason=reason
            )
        )


def release_history(context, workspace):
    st.subheader("Release history")
    if not workspace["releases"]:
        st.info("No reports have been released for this session.")
        return
    release = st.selectbox(
        "Release",
        workspace["releases"],
        format_func=lambda r: f"{r.audience.title()} release {r.number} · {r.status}",
        key="reports:release-history",
    )
    st.caption(f"Revision {release.revision_id} · {release.created_at.isoformat()}")
    if release.status == "active":
        if release.audience == "public":
            url = public_report_url(
                context.container.settings.public_base_url,
                release_id=release.release_id,
            )
            st.link_button("Open public report", url)
            st.code(url, language=None)
        if st.button("Withdraw release"):
            _withdraw_dialog(context, release)
    else:
        st.text(release.withdrawal_reason or "")
