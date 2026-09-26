# Poli Insight

Streamlit workspace for policy participation, session administration, deterministic
multi-criteria analysis, and controlled participant result releases.

## Run locally

Requires Python 3.12+, Streamlit 1.58+, and streamlit-extras 1.6+ (see
`pyproject.toml`). From this directory, with the project environment activated:

```sh
python -m pip install -e '.[dev]'
python -m alembic upgrade head
python -m streamlit run app.py
```

Configure the database, environment, authentication, and participant identity
settings using `.env.example` and `.streamlit/secrets.toml.example`. Environment
variables must be provided to the process; copying the example does not load them.
Use development authentication only for local development. Existing OIDC role
checks and participant private-link authorization remain in place.

## UI design system

Native control styling lives in `.streamlit/config.toml`. Application-owned surface
styles live in `src/poli_insight/presentation/streamlit/components/theme.py`; page
code must not inject CSS. The entrypoint installs the theme once through
`application_shell()`, including startup errors.

| Token | Default |
| --- | --- |
| Text | Navy `#172B4D` |
| Primary action and links | Teal `#0F766E` |
| Page background | `#F4F7FA` |
| Cards and input backgrounds | White `#FFFFFF` |
| Filters and sidebar | `#EAF0F5` |
| Borders | `#D6DEE8` |
| Type | System sans-serif; 16px body |
| Spacing | 4, 8, 12, 16, 24, 32px at the default font size |
| Cards / buttons | 12px / 8px corner radius |
| Maximum content width | 1280px workspace; 880px reading/questionnaire |

Shared helpers in `components/layout.py`:

- `render_page_header(PageHeader(...))`: exactly one native page title and concise orientation.
- `render_section_heading(...)`: section and subsection hierarchy; level 2 for major sections.
- `surface(key=..., variant=...)`: native container styled as a card, filter, feature, or metric surface.
- `metric_row(count, key=...)`: wrapping native containers for bordered metrics; readable at narrow widths.
- `reading_width(key)`: fluid, bounded reading layouts.
- Existing `admin_surface`, status badges, empty-state helpers, and capability notices remain available.

Use stable, descriptive surface keys, including record identity when rendering a
list. Surface keys are separate from widget/session-state keys. Sanitized CSS keys
include a hash suffix to avoid punctuation collisions. Widget keys must remain
unchanged when moving controls between surfaces.

Prefer native tabs, forms, expanders, alerts, metrics, and controls. Existing extras
steps, pagination, and card selectors provide workflow navigation and selection.
The former extras metric-card CSS was removed; the dependency remains for the other
components. CSS targets only application-owned key classes, without scripts,
generated class names, DOM-position selectors, or widget-internal overrides.
Dynamic titles and labels stay in native Streamlit components rather than HTML.

The reviewed default is the light theme. Server-configured dark themes have matching
surface colors, but a separate dark visual review is not part of this redesign.
The sidebar starts in Streamlit's automatic mode so it collapses on narrow screens.
Tables retain their native scrolling, selection, sorting, and download behavior.

## Preference sliders and state contract

Both direct ratings and pairwise comparisons use `st.select_slider`. The discrete
scale IDs, labels, supplied order, saved answers, existing widget keys, validation,
and draft/submit service calls are preserved. Categorical selections remain select
boxes.

`None` is a presentation-only first position labeled **Not answered**. A new question
must not silently choose the first rating. Clearing a saved answer produces the
existing removal command; `None` is never submitted as a scale ID. Required items
continue to block advancement until answered. Moving the slider does not save the
draft; participants use **Save draft** or the existing save-and-continue action.

## Verification

```sh
PYTHONPATH=src python -m pytest tests -q
python -m ruff check app.py src/poli_insight/presentation/streamlit/pages \
  src/poli_insight/presentation/streamlit/components/layout.py \
  src/poli_insight/presentation/streamlit/components/theme.py \
  src/poli_insight/presentation/streamlit/components/session_search.py \
  src/poli_insight/presentation/streamlit/navigation.py \
  tests/presentation/test_ui_redesign.py --select E4,E7,E9,F,I
```

The redesign adds focused AppTest coverage for unanswered, saved, edited, and cleared
ratings; exact keys and IDs; single-option and optional questions; pairwise saving
and progression; and collision-safe layout keys. Streamlit 1.58 AppTest treats
`set_value(None)` as no test override, so the clearing test supplies the same
formatted widget message sent by the browser.

For visual verification, use a disposable migrated database with bundled scenarios
and representative open/closed sessions. Inspect public pages, questionnaire stages,
admin tabs and dialogs, processing, and reports at 1440px, 900px, and 390px. Check
keyboard slider interaction, disabled actions, preserved drafts, visible focus,
long labels, and table overflow. Browser-testing tools are optional development
tools; no browser package was added to project dependencies.

## Redesign change inventory

- `.streamlit/config.toml`, `app.py`: native theme, shared shell, responsive sidebar default.
- `components/theme.py` (new), `components/layout.py`, `components/session_search.py`:
  tokens, surfaces, headings, wrapping metrics, and filter layout.
- `navigation.py`: bounded public reading layouts and sidebar identity presentation.
- Public pages: `home.py`, `participate.py`, `about.py`, `published_results.py`.
- Admin pages: `dashboard.py`, `login.py`, `manage_sessions.py`, `processing.py`,
  `reports.py`; embedded `analysis_section.py` and `package_section.py`.
- `tests/presentation/test_manage_sessions.py`: updated semantic heading assertions.
- `tests/presentation/test_ui_redesign.py` (new): layout and slider regression coverage.

Routes, role checks, form submission boundaries, tab execution, use-case commands,
calculations, database schema, exported report formats, and archive code in
`old-src` are unchanged. General public publication and AI drafting remain existing
future capabilities; this redesign does not enable them.

### Verified redesign baseline

- Full suite: **203 tests and 2 subtests passed**.
- Final presentation suite: **78 tests passed**, including the five new slider/layout tests.
- Scoped Ruff checks and Python compilation passed. Broader inherited lint policy
  still reports an existing `SIM114` simplification suggestion in processing-stage
  status selection; that calculation/navigation logic was preserved.
- Headless Chromium checked 20 populated/empty page and dialog views, including
  1440px, 900px, and 390px layouts, without page-width overflow or rendered exceptions.
- Real browser checks exercised development sign-in, draft saving, keyboard slider
  changes and clearing, session creation-dialog navigation, admin tabs, and entry
  into the processing workspace against a disposable database.

External OIDC-provider sign-in and production deployment were not exercised. The
private report/export and analysis workflows retain their existing automated
coverage; the browser reporting check used the empty-package state.

## Manual reports and publication

Apply the additive `0014` migration before starting the updated application:

```sh
python -m alembic upgrade head
```

**Reports & Publication** contains **AI Analysis**, **Report Publication**, and
**LLM Configuration**. Only the selected tab loads its workspace. Search processed
sessions with pagination and select a frozen package. Analysis input inspection,
document management, report editing, previews, and release history use focused
subpages; uploads, review, publication, and exports open in dialogs. Moderators
can create a report draft from package evidence in Report Publication. Calculated evidence stays fixed;
moderators supply the six narrative sections or explicitly mark them **Not
assessed**. Saving creates an immutable revision with a change summary. Concurrent
editors must reload when their base revision is no longer current.

Supporting documents accept PDF, DOCX, UTF-8 TXT, and Markdown up to 20 MB. File
bytes and immutable versions are stored in the database. Shareable versions require
explicit approval before citation/attachment. Confidential documents and internal
notes remain administrator-only; the shared report projection does not include
them. Text files have bounded previews; document extraction and OCR are not enabled.

Submit and approve an exact report revision before publishing. Participant and
public releases are independent. Participant publication transactionally aligns the
shared report with its source package's private results; public publication creates
a catalog entry and `/results?report=<release_id>` link. Closed-session and package
freshness checks apply at publication and retrieval. Replaced, withdrawn, and stale
public releases are unavailable; their history remains visible to administrators.
All reporting operations use the configured administrator role, including document
retrieval and preview; self-approval is supported.

HTML and ZIP exports use the same shareable evidence as the report view. ZIPs
contain the report, a source manifest, aggregate evidence, and explicitly selected
approved shareable documents. Downloads are prepared only on request. The temporary
deterministic bundle-export workspace has been removed from this page; existing
package storage and export-service compatibility are preserved. Private participant
breakdowns remain available through authorized private links. The stored `public`
bundle variant never grants permission to publish personal results. New packages record effective group voting
power; historical packages remain unchanged.

AI Analysis explains the planned agent stages, with execution explicitly disabled.
LLM Configuration is an administrator-only placeholder and stores no settings or
credentials. AI integrations, agents, prompts, regeneration, automatic email
delivery, and native PDF/DOCX report export remain deferred.

Focused verification:

```sh
PYTHONPATH=src:. python -m pytest tests/integration/test_manual_reporting.py \
  tests/presentation/test_manual_reporting.py tests/presentation/test_package_reporting.py -q
```

## Session Processing workflow

Processing uses six evidence-backed steps with a shared, separated **Begin Process**
action. Successful operations reload saved evidence and advance to the next step,
with a receipt and focus on the new step heading. Incomplete reviews, failures,
and analysis batches without evaluated cases remain available for review. Progress
is reconstructed from the current roster and processing lineage; inspecting an
older run does not advance current work.

Stakeholder-group influence includes hypothetical omissions of required groups.
It leaves the session's actual group policy and participant influence restrictions
unchanged. Group-influence method revision 2 is included in the input hash, so old
runs that skipped required groups are not reused; their history stays readable.
Charts provide explicit labels, units, scope, and tabular alternatives, while all
five tests explain their inputs, methods, outputs, and interpretation.

The package completion screen retains its **Open Reports & Publication** action
across reruns and uses the registered `reports` route with the session selected.
See [browser regression instructions](tests/browser/README.md) for the full flow,
mobile review scenarios, screenshots, and accessibility-check limitations.
