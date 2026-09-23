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
