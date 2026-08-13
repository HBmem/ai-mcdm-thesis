# Participant and submission imports

The Manage Sessions **Imports** tab accepts UTF-8 `.csv` files and `.xlsx`
workbooks. Legacy `.xls`, macro-enabled workbooks, formulas, external workbook
links, and direct-ranking responses are rejected. Imports support frozen
pairwise criterion comparisons, direct criterion ratings, and direct
alternative ratings.

## Workflow

1. Choose a session with an activated configuration.
2. Download a blank or filled CSV/Excel template. Excel is preferred and
   includes `Responses`, `Instructions`, `Scale values`, `Groups`, and
   `Configuration` sheets plus data-validation lists.
3. Upload and preview. Preview is read-only and reports row/column errors,
   warnings, conflicts, and the exact create/skip/replacement plan.
4. Confirm the plan and apply it atomically. Any apply-time lifecycle,
   configuration, permission, or concurrency failure rolls the batch back.

Draft and open sessions import normally. Paused and closed sessions require a
separate historical-data override and reason. Canceled and archived sessions
cannot be imported. The lifecycle and active frozen configuration are checked
again during apply.

## Columns

Reserved columns are followed by one deterministic `answer.*` column per
frozen question:

- `template_schema_version`, `session_slug`, and `configuration_version` bind
  the file to its template contract.
- `participant_ref` is required and is the authoritative import match key. It
  is Unicode NFKC-normalized and trimmed. The plaintext reference is sensitive,
  transient, and never persisted; the database stores only a domain-separated
  HMAC-SHA256 lookup digest.
- `participant_alias` is the normal analytical/admin label and is required.
- `participant_name` and `participant_email` are optional. They are rejected
  for anonymous sessions. Accepted authored values are encrypted; email is
  normalized only for its protected keyed lookup digest.
- `group` accepts an active stable group key or an unambiguous exact label.
- `record_state` accepts `enrolled`, `draft`, or `submitted`; blank defaults to
  `submitted`. Enrolled rows must have no answers. Drafts may be partial.
- `recorded_at` is an optional timezone-aware ISO 8601 timestamp. Blank values
  use import time with a preview warning; invalid and future values are rejected.

Answer cells accept a configured stable scale-value key or an exact,
unambiguous configured label. Arbitrary numeric values are not accepted.
Pairwise headers retain the frozen left/right criterion order; a selection
always describes the left criterion relative to the right criterion and is
never reversed or reciprocated automatically.

## Conflicts, consent, and identity

Existing references are skipped by default. **Replace existing submission**
creates a new attempt and preserves the previous attempt, answers, validation,
and lineage. Existing drafts are frozen and withdrawn before replacement. If
the session disallows resubmissions, replacement also needs a separate policy
override and reason.

Administrator-imported records receive the distinct disposition **Consent not
applicable — administrator import**; no participant consent acceptance is
fabricated. When a row contains identity data, apply requires an administrator
attestation and processing basis. This authority is recorded separately from
questionnaire consent. Imported identity is automatically eligible for
idempotent redaction after the configured retention period.

No access grant is created during import. After a successful batch, an
administrator may explicitly generate resume links for eligible imported
participants. Only token digests persist; plaintext `/participate` URLs are
available once in a transient credentials download. A later participant-authored
web attempt follows the normal configured consent workflow.

## Security configuration

Production requires independent secrets of at least 32 UTF-8 bytes:

- `PARTICIPANT_IMPORT_HMAC_SECRET`
- `PARTICIPANT_IDENTITY_ENCRYPTION_KEY`

Related bounds:

- `IMPORTED_IDENTITY_RETENTION_DAYS` (default `365`, range 1–3650)
- `PARTICIPANT_IMPORT_MAX_BYTES` (default 10 MiB)
- `PARTICIPANT_IMPORT_MAX_ROWS` (default 5000)

Uploaded files are not stored. Import metadata and audit events contain safe
counts, IDs, state, and override flags—not raw references, PII, answers,
credentials, token digests, or spreadsheet internals. CSV reports escape cells
that could be interpreted as formulas. XLSX parsing applies compressed-size,
expanded-size, archive-path, macro, external-link, and formula checks; as with
all file parsers, keep `openpyxl` patched and enforce upstream request limits.
