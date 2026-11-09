# Webpage output cleanup

Supply `page_ids` as a nonempty JSON array of lowercase SHA-256 page ID
strings. The runner rejects invalid IDs before dispatch. Each distinct ID
is processed once. Invoking the tool requests deletion for the supplied IDs.

Run from the repository root with the shared macOS tool runner and project
virtual environment. This tool needs only the Python standard library and
uses the default worker timeout.

The tool checks the direct `output/` directories of other project tools for
`<page_id>.json` and `<page_id>.md`. It skips aliases and non-regular files.
Its own output directory, tool definitions, logs, and the data catalog are
outside the deletion scope. Missing files are harmless on retry.

On success, the tool atomically saves a JSON report under its own
`output/<first_page_id>.json` with `page_id`, `page_ids`, and `deleted`.
The first ID identifies the report and run. Runs with the same first ID
replace the same report. Deleted paths are relative to `tools/`.
An I/O failure returns `cleanup_error` with paths deleted so far in
`meta_data`.
Deletions are per file and are not rolled back if another deletion or report
write fails. Retained history may reference deleted files. Regenerating those
files requires an explicit rerun under the shared cache policy.

Runner logs are `logs/run.log` and `logs/runner.log`. Follow the
[shared logging and cache policy](../AGENTS.md#production-logging).
