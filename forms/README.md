# Forms

A form is an interactive execution entity. One Python standard-library server
hosts multiple independent sessions for any form directory. No MCP is required.
Requires Python 3.10+ and a modern browser with JavaScript modules.

## Start and reuse

From the parent repository (pai-search/):

```sh
python3 -B forms/runner.py --form "form-<name>"
```

Replace `form-<name>` with a form directory listed below. Open the printed localhost URL. Keep the process running. Another invocation on
the same port reuses the server and prints a new-form URL, then exits. Use
`--port 8766` for a separate server. Ctrl-C stops the serving process. Reopening
the saved `/session/<form>/<execution_id>` URL after restart restores saved data.
The runner does not launch a browser automatically or embed itself in chat.

## Available forms

Form-specific usage, fields, validation, and behavior are documented in each
form's instructions:

- [Contact form](form-contact/AGENTS.md)
- [Email form](form-email/AGENTS.md)

Initial values can be passed as a URI-encoded JSON object in the new-form URL
fragment (`/new/form-<name>#<encoded-json>`). The browser merges these values over
the form defaults before creating revision 0. Bookmark the resulting session URL
to resume it. Every new-form visit creates a new execution; accepted submission
freezes that execution. Use the form's new-session link for another response.

## Add a form

Create form-<name>/ with exactly these three code files:

- form.html: semantic markup, a form element, initially disabled fieldset with
  `data-fields`, status element with `data-status`, retry button with `data-retry`
  (initially hidden), session label with `data-session`, and link with `data-new`.
  Load `/runtime/runtime.css`, `/assets/<name>/form.css`, and the module
  `/assets/<name>/form.js` using absolute URL paths.
- form.js: import `mount` and optionally `action` from `/runtime/runtime.js`.
  Call `mount({defaults, render(data), collect(), validate(data)})`. Defaults and
  collected data must be JSON objects. collect() must return a complete, lossless
  snapshot; render() must restore it. validate() returns an array of `{field, message}` errors, where field is the control ID.
  Keep all form-specific behavior here. Custom buttons must use type="button".
- form.css: local layout and appearance. No external assets are required.

Document each form's usage, fields, validation, actions, output format, and side
effects in its own AGENTS.md, and add a link under Available forms above. Keep
this README focused on the shared framework.

Field edits remain in the browser until an explicit button action saves a complete
snapshot. There is no background autosave. Draft saving is optional: add
`<button type="button" data-action="save_draft">Save draft</button>` to enable it;
the runtime wires this button automatically without submission validation.
The submit button must have `data-action="submit"`. Each persisted action name
maps to exactly one form button with a matching data-action attribute.
For custom buttons, handle the click in form.js, update data, and call
`await action('add_row')` (with a matching button). Navigation and Retry save do
not create actions. Reloading loses unsaved edits; leaving prompts the browser.
Buttons pause while saving.  Action names
use lowercase letters, digits, and underscores and start with a letter (64 max).

No runner registration or Python changes are needed to add forms. Form defaults
and submission validation execute in the browser. The generic server validates
JSON transport and session rules, not form-specific field constraints; this is
a trusted local UI, not an authenticated public data-validation API.

## Persistence contract

Each session has a unique random execution_id and revisions beginning at 0.
`form-<name>/output/<execution_id>.txt` stores the complete JSON session envelope
with exactly these top-level fields:

```json
{
  "input": {"raw_input": "", "processed_input": {"initial_data": {}}},
  "output": "form-example/output/<execution_id>.txt",
  "output_format": "json",
  "status": "ok",
  "error": null,
  "meta_data": {
    "execution_id": "<execution_id>",
    "form": "form-example",
    "created_at": "UTC timestamp",
    "revision": 1,
    "execution_state": "in_progress",
    "initial_data": {},
    "current_data": {},
    "action_log": [{
      "sequence": 1,
      "action_id": "unique retry identifier",
      "action_name": "save_draft",
      "outcome": "accepted",
      "action_time": "UTC timestamp",
      "execution_state": "in_progress",
      "data_after": {}
    }]
  }
}
```

The output path is relative to forms/ and identifies this same envelope file.
Form values are in `meta_data.current_data`; initial values and action history
are preserved alongside them. There is no separate metadata directory. Each button action records a full snapshot, including incomplete draft values.
The browser validates before submission and shows errors inside each field border.
Invalid submissions do not persist an action and keep the session editable. Errors
clear on the next interaction or after 60 seconds; submission always revalidates.
The API continues to support rejected actions for existing clients. Successful submission records `submit` with `outcome: "accepted"`
and sets execution_state to submitted. Older clients default to accepted.
Existing history, including legacy field-change actions, remains unchanged. Transport errors use
HTTP errors and leave the last committed envelope unchanged; status/error describe
the last committed operation, rather than overwriting a successful snapshot.

Replacing the single output file is the commit point. The complete envelope is
written through a flushed, fsynced temporary file and atomic replacement, keeping
current data and history together. A failed replacement leaves the previous
revision intact. A crash before acknowledgement may still have committed:
retries reuse action_id to avoid duplicate actions. Revision checks prevent stale tabs from overwriting data.
One process owns a port; actions are serialized by its store lock. Do not run two
servers on different ports against the same storage directory.

The browser queues requests. On save failure, editing pauses and Retry save keeps
the failed action ID. Later queued actions are discarded; retry restores the last
acknowledged snapshot, so unsaved later edits may need re-entry. Stale revisions
require reload. Browser/process crashes can lose edits not yet persisted. Full
history uses growing disk space; there is no pruning or retention policy.

## HTTP interface

GET /runtime/config.json provides the in-memory capability token. API requests
require X-Forms-Token. POST additionally requires the exact localhost Origin and
application/json. Bodies are limited to 2 MiB. Routes:

- POST /api/sessions: `{form, raw_input, initial_data}` → new envelope.
- GET /api/sessions/<form>/<id>: latest persisted envelope.
- POST /api/sessions/<form>/<id>/actions:
  `{action_id, expected_revision, action_name, data, outcome}` → committed envelope.
- GET /api/sessions/<form>/<id>/snapshot?revision=N: exact historical data and
  lifecycle state. Revision 0 returns initial_data. Reading history never mutates it.

Historical snapshots are available through the API; a history-viewing interface
and linked branching sessions are not implemented in this example.

The server binds only 127.0.0.1 and checks Host, Origin, and a per-process token.
No CORS is enabled. These protect against ordinary cross-site browser requests,
not hostile local processes or untrusted forms. Session files contain unencrypted
personal data, including every persisted intermediate value, and are gitignored.

## Verification

From forms/: `python3 -B -m unittest -v test_store.py test_journal.py test_http.py`.
Tests use temporary form directories and do not write personal data into the example.

## Migrate existing sessions

Stop all forms runner processes first. From pai-search/, run:

```sh
python3 -B forms/runner.py --migrate
```

The migration replaces each legacy data-only output with its corresponding full
metadata envelope, verifies the saved JSON, then removes the legacy source file
and empty metadata directory. Execution IDs, paths, initial values, revisions,
and action logs stay unchanged. It can be rerun after interruption; conflicting
outputs and unexpected files stop migration without deleting their source.
Restart the runner and reload open browser sessions afterward.

## Production run.log

Each form owns an append-only `form-<name>/logs/run.log` in JSON Lines format. The
runner records initialization and every committed action, including rejected
submissions. Each record is the complete session envelope flattened at the root,
plus run_id and executed_at. The output attribute is a path string, never a nested
envelope. There are exactly eight root fields:

```json
{
  "run_id": "<execution_id>",
  "executed_at": "2026-10-19T10:00:00.000Z",
  "input": {"raw_input": "", "processed_input": {"initial_data": {}}},
  "output": "form-example/output/<execution_id>.txt",
  "output_format": "json",
  "status": "ok",
  "error": null,
  "meta_data": {
    "execution_id": "<execution_id>",
    "form": "form-example",
    "created_at": "2026-10-19T10:00:00.000Z",
    "revision": 0,
    "execution_state": "in_progress",
    "initial_data": {},
    "current_data": {},
    "action_log": []
  }
}
```

run_id is the unique form-session ID, not the input hash used by tools. Revision
identifies the operation within the session. executed_at is the initialization
or action timestamp. The saved output file retains its six-field envelope.

The runner commits output first, then locks and appends missing log records,
flushes and fsyncs before acknowledging success. Startup, session reads, and action
retries recover missing records from complete saved snapshots. Recovery preserves
original timestamps and includes revision 0. Existing sessions are backfilled on
startup; these records describe saved history, not newly executed actions. Recovery
appends can appear after newer records, so use executed_at and revision for ordering.
Repeated reads and successful action retries do not append duplicates.

An interrupted final append without a newline is discarded and regenerated.
Complete records are never rewritten. Malformed complete JSON or symlinked log
paths fail closed. The single output commit and log append are separate filesystem
operations: a failed acknowledgement may still have committed the action, and a
retry with the same action_id safely finishes logging. Logging failures do not roll
back committed data. They return an HTTP storage error until recovery succeeds.

Action storage failures are logged when the log remains writable: status is error,
error contains code/message, and meta_data.failed_action holds the attempted
request alongside the last committed data. Repeated failures for the same action
at the same revision are deduplicated. Pre-execution rejection (bad arguments,
stale revisions, or a submitted session) creates no execution record. Failures
before session creation or unavailable storage may prevent logging entirely.

run.log contains personal data and full cumulative history, increasing disk usage.
It is gitignored, is not served as a static resource, and has no retention limit.
Tests write only to temporary form directories, never production run.log. Existing
tools logging is unchanged.
