# URL

Follow [../AGENTS.md](../AGENTS.md) and [../README.md](../README.md).

Run `forms/.venv/bin/python -B forms/runner.py --form form-url` from pai-search/.

The required `url` string must be an absolute HTTP(S) URL with a hostname and no whitespace. Preserve the entered URL
without rewriting it. `bookmark`, `read` and `index` are independent boolean checkboxes, unchecked by default; no
selection is required.

Save (`save_draft`) persists the complete snapshot without validation. Submit (`submit`) validates, saves `url`,
`bookmark`, `read` and `index` in meta_data.current_data, and freezes the session. The selections record intent only;
this form does not read, bookmark, or index content.

Reader reserves a new tab during the user gesture, then navigates it to the exact URL input only after a successful
save. Validation failures open nothing; save failures close the reserved tab. The new tab has no opener. Popup blocking
may prevent opening. The browser may normalize the URL when navigating. All fields and action buttons disable during
saves and after submission.

Initial values may be passed in the new-session URL fragment. Session files and logs contain personal data; never print
or commit them. Test only in temporary directories.

Reader is an icon button positioned inside the URL input area at the right, vertically aligned with the input text,
using the existing header-actions styling and inherited icon colors. Its `reader` action validates the HTTP(S) URL and
persists only `url`, `bookmark`, `read` and `index`. It leaves the session editable and opens the entered URL in a new
tab after saving. Submit saves and freezes the session without opening a tab. No message field is collected or saved by
this form. Existing committed history remains unchanged.

Read appears between Bookmark and Index and records intent only. Older snapshots without `read` render it unchecked;
existing committed snapshots are not rewritten.
