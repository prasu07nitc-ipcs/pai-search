# Email form

Follow the shared policies in [../AGENTS.md](../AGENTS.md) and the runtime contract
in [../README.md](../README.md). Keep email-specific behavior in this folder.

## Usage

From pai-search/, run:

```sh
python3 -B forms/runner.py --form form-email
```

Open the printed localhost URL. Initial values may be supplied as a URI-encoded
JSON object in the URL fragment, with `to`, `subject`, and `body` string values.

## Fields and validation

- `to`: required comma-separated email addresses; each address must pass basic
  email syntax validation; maximum 2,000 characters.
- `subject`: required, nonempty after trimming, no carriage returns or newlines;
  maximum 998 characters.
- `body`: required HTML string containing nonempty message text; maximum 100,000
  HTML characters. Whitespace and zero-width characters alone are insufficient.

The rich text editor supports bold, italic, underline, ordered and unordered lists,
and clearing formatting. Formatting and paste remain local edits until an explicit
save or submission. Restored, pasted, and collected HTML is rebuilt using only
`p`, `div`, `br`, `b`, `strong`, `i`, `em`, `u`, `ul`, `ol`, and `li` elements,
with no attributes or embedded media. Do not introduce unsafe HTML insertion.
The editor uses native browser editing commands; use a modern desktop browser.
Contenteditable must track the fieldset's disabled state during saves and after
submission. No attachments or sender credentials are collected.

## Actions and output

Save draft (`save_draft`) saves the complete snapshot without submission validation.
Submit email (`submit`) validates recipients, subject, and body, records accepted
or rejected, and freezes the session only when accepted.

The saved envelope's `meta_data.current_data` contains `to`, `subject`, and `body`
as strings. A sending agent/tool should read these values and use `body` as HTML.
The shared runtime preserves initial data and action history.

Submission saves the email for an agent/tool to send. This form does not deliver
email or mark it as sent. Do not add direct delivery without user authorization.
Session files and logs contain email contents and addresses; use temporary
directories for tests and never print or commit production records.
