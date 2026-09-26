# Participation browser regression

Run from the repository with its Python development dependencies and Playwright
available to Node:

```sh
python -m streamlit run tests/browser/participation_app.py --server.port=8517
node tests/browser/participation.cjs
```

The app creates an isolated temporary SQLite database using the real migrations,
scenario imports, consent, draft-save, and submission services. It creates
five- and seven-point sessions with 15 comparisons each. No application database
or existing participants are used. Restart the test server to load changed
component assets or to start with a fresh database.

The browser check covers skipping, forward/back navigation, question selection,
clearing saved answers, resume after reload, review/edit, and final submission.
It runs the seven-point case with mobile touch input and the five-point case
with keyboard input. Python tests cover direct ratings, optional questions,
invalid answers, description data, and save failures.

Optional environment variables: `PARTICIPATION_URL` (default
`http://127.0.0.1:8517`), `BROWSER_CHANNEL`, `PLAYWRIGHT_MODULE`, and
`PARTICIPATION_SCREENSHOTS`. Windows defaults to Edge; other platforms use
Playwright's Chromium. The first and second script arguments can also specify
the Playwright module path and screenshot directory, respectively.

## Session Processing regression

The processing fixture uses real migrations, submissions, validation, weighting,
ranking, analysis, and packaging against an isolated temporary SQLite database.
It seeds two required stakeholder groups, with three participants in each group.
Every browser run creates its own study. It uses the production admin route
registry so the completion-to-Reports navigation is covered.

```sh
python -m pip install playwright axe-playwright-python
python -m playwright install chromium
python -m streamlit run tests/browser/processing_app.py --server.port=8527 --server.headless=true
# In another terminal:
python tests/browser/processing.py --accessibility --output /tmp/processing-desktop
python tests/browser/processing.py --mobile --review --accessibility --output /tmp/processing-mobile
```

The checks cover automatic advancement, programmatic heading focus, keyboard
activation, required-group omission, results review, reload, completion, and
Reports navigation with the session retained. `--review` seeds one required group
and selects criterion removal alongside group influence, verifying that a batch
with no evaluable group-omission cases stays open for review before explicit
continuation. Screenshots and optional axe reports are written to `--output`.

The accessibility checks retain the full axe report and allow only the existing
Streamlit 1.58 `aria-allowed-attr` findings on its sidebar and dataframe toolbar.
Application-owned violations fail the check. These native widget findings remain
open; the checks do not constitute WCAG certification or manual screen-reader
verification. Keyboard, focus, live-region markup, 200% zoom, and touch navigation
are covered. To check a separately configured dark-theme server, pass its address
with `--url`.
