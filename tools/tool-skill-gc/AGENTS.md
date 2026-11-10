# Skill file cleanup

Supply `file_paths` as a nonempty JSON array of repository-relative strings.
Each path must be directly under `skills/skill-<name>/input/` or
`skills/skill-<name>/output/`. For example,
`{"file_paths":["skills/skill-webpage-search/output/report.md"]}`.
Reject traversal, absolute paths, and paths outside skill input and output directories
before deletion. Process duplicate paths once, in input order.

An invocation requests deletion of the listed regular, singly linked files.
Skip missing files, directories, and aliases. Preserve skill definitions and logs.
The runner grants unlink-only access to the exact validated paths.
Use the shared macOS runner from the repository root with its default timeout.

The result uses the first path as `input.raw_input`. The receipt ID is the
SHA-256 of the compact JSON array of supplied paths, in order, with ASCII
escaping. The tool stores the ID in `meta_data.page_id` and atomically saves
`output/<receipt_id>.json` with `page_id`, `deleted`, and `file_paths`.
Deleted paths are repository-relative. On I/O failure return `cleanup_error`
with any completed deletions in `meta_data.deleted`. Deletions are per file and
remain effective if a later operation fails.

Use `logs/run.log` and `logs/runner.log` under the
[shared logging policy](../AGENTS.md#production-logging). Always execute
authorized invocations. Existing skill records can reference deleted files.
