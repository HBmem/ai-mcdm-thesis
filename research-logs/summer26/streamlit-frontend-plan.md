# Streamlit Frontend Information Architecture

## Purpose

This document defines the target page organization and user flows for the
Poli Insight Streamlit application. It aligns the frontend with the current
domain model and preserves a clear boundary between:

- public discovery and participation;
- session administration;
- deterministic validation and MCDM processing;
- AI-assisted reporting; and
- human-controlled publication.

The public experience should explain decisions in plain language. The admin
experience should expose the provenance, validation, reproducibility, and
review details required by the thesis.

## Recommended navigation

### Public

1. **Home** (`/`)
2. **Participate** (`/participate`)
3. **Published Results** (`/results`)
4. **About the Research** (`/about`)

The participant questionnaire and result-detail views are contextual
workspaces opened from these pages. They should not clutter the sidebar.

### Administration

Unauthenticated users see only **Administrator Login**. Authorized admins see:

1. **Admin Dashboard** (`/admin`)
2. **Manage Sessions** (`/admin-sessions`)
3. **Session Processing** (`/admin-processing`)
4. **AI Reports & Publication** (`/admin-reports`)

This keeps the four intended admin destinations while allowing each to open a
focused session workspace. If scenario authoring grows substantially, the
Scenario Library described under Manage Sessions can later become a fifth
admin destination without changing the rest of the information architecture.
The flat, hyphenated admin paths reflect `st.Page`'s restriction against `/`
inside a page's `url_path`; the sidebar still provides the visual hierarchy.

## Corrections to the previous plan

1. **A session does not own editable alternatives and criteria.** A session is
   created from a `ready` immutable scenario snapshot. Alternatives, criteria,
   scales, the decision matrix, UI copy, and source provenance belong to that
   snapshot. The session creation flow selects a snapshot and configures how
   participation and calculation will operate.

2. **Session status is only the participation lifecycle.** The implemented
   lifecycle is `draft`, `scheduled`, `open`, `paused`, `closed`, `canceled`,
   and `archived`. Processing failures, processed results, review, and
   publication must be represented by separate validation, run, report, and
   publication records—not additional session statuses.

3. **Closed already means the data boundary is frozen.** There is no separate
   `locked` session state in the current domain. If a moderator approval gate
   is still required before processing, model it as a processing-readiness or
   approval record rather than duplicating the closed state.

4. **Discoverability is not authorization.** `listed` sessions may appear in
   the public catalog; `unlisted` sessions do not. Either may still require an
   invitation or access code. An unlisted session remains reachable through a
   valid link or session identifier.

5. **An access code is not automatically a session locator.** Current
   enrollment verifies a code after the session is known. The Participate page
   should accept a session link/slug first and then request any required code.
   A single global “enter code to find a session” box would require a new,
   rate-limited code-resolution service and careful protection against session
   enumeration.

6. **Invitation credentials and participant resume credentials are distinct.**
   Enrollment may use an invitation token or access code and then issues a
   revocable, expiring participant access grant. Do not call all of these an
   “access code,” expose them in URLs, or store plaintext credentials in logs.

7. **Participant identifiers alone must never reveal personal results.** A
   participant result view requires an active participant credential plus a
   publication policy that explicitly permits the participant audience.

8. **AI output is optional and downstream.** AI consumes a versioned,
   validated analysis bundle. It does not perform or overwrite deterministic
   MCDM calculations. Public AI text must be human-reviewed and approved.

9. **Publishing deterministic results must not depend on AI.** A session can
   publish approved tables and charts without an AI report. Publication
   chooses exact result and report versions and records who approved them.

10. **Imports require preview, validation, and provenance.** Participant and
    submission imports should never write immediately after upload. Each
    import needs mapping, a dry-run preview, row-level errors, confirmation,
    an idempotency strategy, and an audit record.

## Public pages

### 1. Home

**Goal:** Introduce the project and make the three main public actions obvious.

**Content**

- One-sentence description of Poli Insight in non-technical language.
- Brief explanation that participant preferences inform a deterministic MCDM
  model and that reviewed AI may help explain—not calculate—the results.
- Primary actions:
  - **Participate in a Session**
  - **View Published Results**
  - **Learn About the Research**
- A short “How it works” sequence: join, contribute preferences, review
  published findings.
- A concise research/consent notice with links to full details.
- Optional count of listed open sessions and recently published results.

**Rules**

- Do not claim participation is anonymous unless the selected session's
  identity policy supports that claim; “pseudonymous” is safer as a default.
- Do not imply that every completed session or every AI output is published.
- Do not expose admin controls or technical diagnostics.

### 2. Participate

This replaces “Active Sessions” because it supports both public discovery and
entry into unlisted or invitation-only sessions.

**Top-level layout**

1. **Join with a link or session identifier**
   - Resolve the session before asking for a shared or per-invitation code.
   - Invitation links should carry only the minimum required opaque token.
   - Use generic rejection messages for invalid credentials.
2. **Open public sessions**
   - Show only `listed` sessions that are currently `open` and within their
     opening/closing window.
   - Support title/domain search and accessible pagination.

**Session card**

- Title and short scenario summary.
- Policy question or decision context.
- Closing date in the configured application timezone.
- Estimated time, if supplied by versioned UI configuration.
- Participation/access label such as “Open enrollment” or “Invitation
  required,” without exposing security details.
- Stakeholder-selection explanation when self-selection is enabled.
- **View details** or **Participate** action.

**Do not show**

- Draft, scheduled, paused, closed, canceled, or archived sessions.
- Unlisted sessions in search results.
- Participant counts when small counts could create privacy or coercion risk.
- Raw IDs, credential hints, admin notes, or processing state.

### Participant workspace

The workspace is a guided flow, not a sidebar page:

1. **Session overview**
   - Scenario summary, policy question, alternatives, criteria, expected time,
     participation window, researcher contact, and withdrawal information.
2. **Access and eligibility**
   - Invitation/access-code checks as required by the session.
   - Stakeholder self-selection only when configured; otherwise display the
     assigned group without allowing changes.
3. **Consent and enrollment**
   - Record the consent version and retention notice before collecting
     responses when identity data is used.
   - Issue the participant resume credential once and explain its expiry and
     recovery limitations.
4. **Instructions**
   - Render the immutable UI configuration and explain the response method and
     scale with a short example.
5. **Questionnaire**
   - Generate questions from the active configuration's ordered question
     definitions.
   - Support pairwise, direct-rating, and direct-ranking inputs as configured.
   - Save partial drafts through the application use case and show saved state.
   - Display safe, question-level validation feedback without internal traces.
6. **Review and submit**
   - Show all responses, missing required answers, and consequences of final
     submission or allowed resubmission.
   - Require explicit confirmation before submission.
7. **Confirmation**
   - Show a receipt/status, not raw analytical outputs that have not been
     processed and approved.
   - Explain whether a participant-facing result may later become available.

**Required interruption states**

- Session pauses or closes while a draft is open.
- Credential expires or is revoked.
- Participant is disabled or has withdrawn.
- Draft exists on another attempt/device.
- Submission is accepted but later validation returns warnings or errors.
- Resubmission creates a new attempt and supersedes the earlier submission.

### 3. Published Results

**Goal:** Present only deliberately published, audience-appropriate artifacts.

**Catalog**

- Search/filter by title, scenario domain, publication date, and method.
- Show publication date, plain-language summary, and available result types.
- Do not infer publication from `closed`, `archived`, or a successful run.

**Public result detail**

- Scenario context, alternatives, criteria, data/source notes, and session
  participation summary with privacy-safe aggregation.
- Deterministic ranking, criteria weights, closeness coefficients, and group
  summaries selected for publication.
- Sensitivity/robustness findings and limitations.
- Method and configuration version, processing timestamp, and reproducibility
  metadata appropriate for a public audience.
- Approved AI report clearly labeled as AI-assisted and separated visually
  from deterministic results.
- Download links only for explicitly published, disclosure-reviewed exports.

**Participant result access**

- Authenticate with an active participant access grant, not participant ID.
- Confirm the selected publication includes a `participant` audience artifact.
- Show only the participant's own submitted preferences, validation status,
  individual outputs, and approved comparison with privacy-safe aggregates.
- Suppress comparisons for groups below a configured disclosure threshold.

**States**

- No published results.
- Publication withdrawn/unpublished.
- Deterministic results available with no AI report.
- AI report pending review and therefore absent from the public view.
- Participant result not authorized or not included in the release.

### 4. About the Research

**Goal:** Explain the thesis, methodology, governance, and limitations at two
levels of detail.

**Recommended sections**

- Research problem, goals, and research questions.
- What participation contributes.
- Plain-language MCDM overview.
- Expandable technical methodology for AHP/Fuzzy AHP, TOPSIS/Fuzzy TOPSIS,
  aggregation, consistency, sensitivity, and stability measures actually used
  by the application.
- Clear boundary between deterministic calculations and AI explanation.
- Human review and publication governance.
- Data handling, pseudonymization, retention, withdrawal, and ethics/IRB
  information as applicable.
- Known limitations and non-goals; this is decision support, not an automated
  policy decision-maker.
- Thesis citation, researcher/advisor contact, version, and repository link if
  public.

Avoid describing algorithms the application does not yet implement as current
features. Label planned methods as planned.

## Admin pages

All admin pages require server-verified authentication and authorization. A
development password in Streamlit session state is not a production control.

### 1. Admin Dashboard

**Goal:** Show what requires attention and provide direct actions.

**Summary cards**

- Draft/scheduled sessions needing configuration.
- Open and paused sessions.
- Sessions approaching their close time.
- Submitted attempts awaiting validation.
- Invalid submissions or validations with warnings.
- Closed sessions not ready for processing.
- Failed or stale processing runs.
- Reports awaiting human review.
- Approved outputs ready to publish.
- Published releases and recently withdrawn releases.

**Attention queue**

Each row should state the problem, affected session, severity, age, and one
recommended action. Examples include missing active configuration, unmet
minimum-valid-submission rules, required stakeholder groups missing, failed
validation, run failure, and report awaiting review.

**Secondary content**

- Recent audit activity with actor, action, entity, timestamp, and correlation
  ID.
- Privacy-safe operational metrics and trends.
- Quick actions: import scenario, create session, manage invitations, validate
  submissions, run processing, review report.

Dashboard counts should come from query/read models rather than loading full
domain aggregates into Streamlit.

### 2. Manage Sessions

**Goal:** Own scenario selection, session configuration, participation
operations, submissions, and lifecycle controls without mixing in calculations
or publication.

#### Session list

- Search by title/slug and filter by operational status, discoverability,
  enrollment mode, scenario, and date.
- Show operational status separately from validation/processing/report badges.
- Provide a primary **Create Session** action.
- Open a selected session in a stable detail workspace rather than placing all
  records in one very large tab.

#### Create-session wizard

1. **Choose scenario snapshot**
   - Select only a `ready` snapshot.
   - Preview immutable alternatives, criteria, scales, decision matrix
     provenance, and declared version.
2. **Session identity and schedule**
   - Title, unique public slug, public description, private admin notes,
     timezone-aware open and close times.
3. **Discovery and access**
   - Listed/unlisted, open/invitation-only enrollment, no/shared/per-invitation
     code, identity policy, and stakeholder selection mode.
4. **Versioned calculation configuration**
   - Response format and target, scale, resubmission rules, maximum attempts,
     incomplete-submission policy, minimum valid submissions, required-group
     and missing-group policy, consistency threshold, stakeholder allocation,
     and algorithm implementations/parameters.
5. **Generated questions and review**
   - Preview ordered prompts and participant UI.
   - Validate allocation totals, algorithm roles, hashes, ownership, and
     activation requirements.
6. **Create draft and activate configuration**
   - Creation remains separate from opening. Show a readiness checklist before
     schedule/open actions become available.

#### Selected-session workspace

**Overview**

- Session metadata, scenario snapshot/version, access configuration, schedule,
  active configuration version, and public preview.
- Valid lifecycle actions only: schedule, open, pause, resume, close, cancel,
  and archive according to the domain transition rules.
- Destructive or consequential actions require confirmation, a reason, and an
  audit event.

**Configuration versions**

- View immutable configuration contents and hashes.
- Add/activate a new version only while draft or scheduled.
- Once a session opens, configuration is frozen; corrections require a new
  session, not silent editing.

**Invitations and participants**

- Create/import invitations, assign groups when required, inspect delivery and
  redemption state, resend, revoke, and export disclosure-safe lists.
- View participant access/progress separately: enrolled, started, submitted,
  completed; active, disabled, or withdrawn.
- Change group only before the configured cutoff.
- Revoke/replace access grants without displaying stored token digests.
- Keep encrypted participant identity and analytical participant records
  visually and operationally separate; support approved redaction workflows.

**Submissions and validation**

- List attempts by participant, attempt number, draft/submitted/superseded/
  withdrawn state, completion, current validation result, and effective
  inclusion eligibility.
- Inspect answers under least-privilege rules.
- Trigger/retry submission validation through the validation use case.
- Do not “edit” submitted answers in place. Corrections create a new imported
  attempt or an explicitly audited replacement/supersession workflow.
- Withdraw or exclude using reason-coded actions; avoid hard deletion of
  research records.

**Imports**

- Participant/invitation import and submission import are separate workflows.
- Accept documented CSV templates; spreadsheet support is optional.
- Upload -> map columns -> dry-run -> display row errors/warnings -> confirm ->
  commit atomically -> download outcome report.
- Require external row keys or another idempotency mechanism so reruns do not
  create duplicates.
- Record source-file digest, actor, timestamp, counts, and correlation ID.

**Audit and exports**

- Timeline of lifecycle, enrollment, submission, validation, and administrative
  actions.
- Separate internal research export from public/disclosure-reviewed exports.

#### Scenario Library (secondary workspace)

Because sessions depend on immutable snapshots, admins need a small scenario
workspace reachable from Manage Sessions:

- Import a scenario package through the existing import use case.
- Show import validation, preprocessing result, source provenance, manifest and
  materialized-input hashes.
- Browse definitions and snapshots by `validating`, `ready`, `invalid`, and
  `retired` state.
- Preview alternatives, criteria hierarchy, scales, matrix values, and UI
  configuration.
- Retire definitions/snapshots without altering sessions already pinned to
  them.

### 3. Session Processing

**Goal:** Validate a frozen input set, run deterministic MCDM, analyze
robustness, and generate reproducible structured artifacts for reporting.

#### Processing queue

- Show closed sessions and their readiness; archived sessions may expose prior
  run history but should not silently rerun.
- Readiness gate:
  - active immutable configuration and ready scenario snapshot;
  - minimum usable validations met;
  - required stakeholder-group policy met;
  - effective submissions selected and exclusions explained;
  - no unresolved input-integrity errors;
  - moderator approval present if the research protocol requires it.

#### Input manifest

Before execution, freeze and display:

- session, scenario snapshot, configuration, and algorithm implementation IDs;
- content/configuration/answer/parameter hashes;
- submission cutoff time;
- each included/excluded submission and stable reason code;
- stakeholder allocation and missing-group policy;
- software/library/adapter versions and run initiator.

#### Run deterministic processing

- Queue a new immutable run; never overwrite a prior run.
- Display queued/running/succeeded/failed/canceled state and safe logs.
- Execute configured weighting, within-group aggregation, across-group
  aggregation, ranking, validation, and analysis roles in defined order.
- Persist typed artifacts such as the input manifest, decision/pairwise matrix,
  normalized matrix, weight vector, ranking trace, diagnostics, structured
  result, analysis bundle, and log.
- A failed rerun does not invalidate a prior successful run.

#### Results and diagnostics

- Participant, stakeholder-group, and aggregate weights as allowed.
- Aggregate and group rankings, closeness coefficients, consistency metrics,
  excluded-input reasons, warnings, and full provenance.
- Compare runs side by side when inputs or algorithm versions differ.
- Export a machine-readable structured result and an AI-safe analysis bundle.

#### Sensitivity and robustness

Run analyses as versioned child runs/artifacts, not mutable checkboxes on the
main result:

- weight perturbation and stability intervals;
- criterion removal;
- rank reversal checks;
- Spearman and Kendall rank correlation;
- stakeholder-group influence;
- participant-impact analysis with privacy safeguards;
- configured crisp/fuzzy or algorithm comparisons;
- uncertainty, assumptions, and thresholds.

The UI should distinguish a sensitivity test that executed successfully from
a result that indicates instability.

### 4. AI Reports & Publication

**Goal:** Generate AI-assisted explanations from approved deterministic
artifacts, support human editorial review, and publish an explicit release.

#### Generate report

- Select a successful deterministic run and approved analysis-bundle version.
- Select report type and audience: moderator, stakeholder group, participant,
  or public.
- Preview exactly what will be sent to the model after redaction/minimization.
- Record provider/model, prompt/template version, parameters, input artifact
  hashes, generation time, and token/cost metadata where available.
- Generate a new immutable draft rather than overwriting earlier output.
- Offer supported report types such as result summary, trade-off explanation,
  stakeholder comparison, sensitivity explanation, or policy-discussion draft.
  Avoid presenting an AI “recommendation” as the deterministic result.

#### Review report

- Show deterministic evidence beside each AI claim where possible.
- Flag unsupported numbers, contradictions, missing caveats, sensitive content,
  and references to excluded data.
- Permit editorial revisions with revision history and editor attribution.
- Approval states should follow `draft`, `review_required`, `approved`,
  `rejected`, or `withdrawn`.
- Require a reviewer other than the AI service; consider separation of author
  and approver for research governance.

#### Build publication

Publication is an explicit release manifest, not a session status change.

- Select one successful deterministic run and exact artifact versions.
- Select approved AI report versions, or publish with no AI report.
- Choose public charts, tables, narrative, downloads, and participant-facing
  artifacts.
- Preview as each audience before release.
- Run disclosure/privacy checks, accessibility checks, and broken-link checks.
- Require publication notes and admin confirmation.
- Record publisher, reviewer, timestamp, release version, included hashes, and
  audit event.
- Support a new corrected release and an emergency unpublish/withdraw action;
  preserve historical audit metadata even when content is no longer public.

## State model used by the UI

Do not reduce all status to one badge. Every session row/detail should compose
independent state dimensions:

| Dimension | Values or source | Current support |
| --- | --- | --- |
| Scenario snapshot | validating, ready, invalid, retired | Domain/database implemented |
| Session operations | draft, scheduled, open, paused, closed, canceled, archived | Domain/database implemented; not all use cases wired |
| Participant access | active, disabled, withdrawn | Domain/database implemented |
| Participant progress | enrolled, started, submitted, completed | Domain/database implemented |
| Submission attempt | draft, submitted, superseded, withdrawn | Domain/database implemented |
| Submission validation | pending, running, valid, valid with warnings, invalid, error | In active development |
| Processing run | queued, running, succeeded, failed, canceled | Enums exist; run/artifact persistence still required |
| Report approval | draft, review required, approved, rejected, withdrawn | Enums exist; report persistence still required |
| Publication release | draft/review/published/withdrawn or equivalent | Must be designed and implemented |

Dashboard labels such as “needs processing” or “ready to publish” are derived
workflow projections over these states, not new session enum values.

## Shared interaction and design standards

### Architecture

- Page renderers receive the application container and call application use
  cases or dedicated query services.
- Streamlit pages must not import SQLAlchemy rows, open database sessions, or
  implement domain transitions directly.
- Commands perform writes through a unit of work and create audit events in the
  same transaction.
- Query/read models should supply paginated list, dashboard, and result views.
- Keep page modules thin; place reusable filters, status badges, confirmation
  dialogs, tables, charts, and result panels in components.

### Streamlit behavior

- Use `st.Page`/`st.navigation` with stable URL paths and role-based navigation.
- Preserve selected session/filter state with namespaced session-state keys.
- Never place credentials, PII, raw prompts, or sensitive identifiers in query
  parameters.
- Wrap multi-field writes in forms to avoid partial rerun behavior.
- Disable actions while commands run and make retries idempotent.
- Every data surface needs loading, empty, success, warning, error, stale-data,
  and permission-denied states.
- After a successful mutation, rerun from a fresh query and show a concise
  receipt/correlation ID.

### Security and privacy

- Use production identity and role claims for admin authorization; hiding a
  page in navigation is not authorization.
- Treat invitation tokens, access codes, access grants, participant identity,
  and unpublished results as sensitive.
- Store only digests/encrypted identity according to the domain model and never
  render stored digests as credentials.
- Rate-limit enrollment failures and return generic credential errors.
- Apply small-cell suppression and audience checks to group/participant
  comparisons.
- Prefer disable, withdraw, revoke, redact, retire, and archive workflows over
  hard deletion.

### Accessibility and research transparency

- Do not rely on color alone for status or ranking.
- Provide text/table alternatives for charts and meaningful labels for inputs.
- Use consistent timezone-aware date formatting and display the timezone.
- Explain formulas, thresholds, exclusions, missing data, and uncertainty in
  plain language with expandable technical detail.
- Label deterministic output, administrator interpretation, and AI-generated
  text distinctly.

## Backend gaps that block complete frontend implementation

The page shells can be built now, but the following capabilities need
application/domain support before their controls should be enabled:

1. Paginated query services for public sessions, admin session tables,
   participants, submissions, validations, dashboard projections, and audits.
2. Production authentication and role/permission enforcement.
3. Remaining session commands and wiring for schedule, pause, resume, cancel,
   archive, and metadata updates.
4. Complete invitation, access-code, participant-access, identity/consent, and
   participant-management use cases plus persistence wiring.
5. Previewable/idempotent participant and submission import workflows.
6. Processing-run, inclusion-manifest, artifact, sensitivity/robustness, and
   run-comparison models/repositories/use cases.
7. AI-generation adapters, report/revision/approval records, redaction policy,
   and human-review use cases.
8. Publication-release manifests, audience policy, privacy checks,
   publish/unpublish workflows, and public-result queries.
9. Secure export authorization and disclosure-reviewed export builders.

Until a capability exists, show a truthful “not yet available” or read-only
state. Do not let UI-local state simulate a completed domain action.

## Recommended implementation order

1. **Foundation:** production navigation/auth boundary, shared layout/status
   components, page-level query interfaces, and error handling.
2. **Admin session core:** Scenario Library, session list/create/detail,
   configuration activation, lifecycle actions, and audit display.
3. **Participation:** public catalog, access/enrollment, consent, questionnaire,
   draft save, review, submission, and resume behavior.
4. **Operational management:** invitations, participant/submission tables,
   validation queue, and safe import previews.
5. **Deterministic processing:** immutable runs, manifests, artifacts, results,
   exports, and sensitivity/robustness.
6. **AI reporting:** minimized analysis bundle, generation provenance,
   revisions, evidence review, and approval.
7. **Publication:** release manifest, audience previews, public/participant
   result views, withdrawal/correction workflow, and disclosure tests.
8. **Polish:** accessibility review, usability testing, performance/pagination,
   operational metrics, and thesis-methodology consistency review.

## Completion criteria

The frontend plan is satisfied when:

- public users can discover only eligible listed sessions while valid unlisted
  and invitation-only entry still works;
- participants can safely enroll, resume, save, validate, review, and submit
  against the immutable active configuration;
- admins can see and act on each workflow state without conflating session,
  validation, run, report, and publication status;
- every consequential write uses an application command and produces an audit
  trail;
- deterministic results remain reproducible and visibly separate from AI
  interpretation;
- no result becomes public solely because a session closed or a run succeeded;
  and
- every public or participant-facing artifact is explicitly audience-approved,
  privacy-checked, versioned, and withdrawable.
