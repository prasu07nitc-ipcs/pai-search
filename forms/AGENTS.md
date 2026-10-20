# Forms project

Manage and execute browser-based forms only within the user's requested scope.
Each form-<name> directory uses lowercase kebab-case, under 64 characters, and
contains form.html, form.js, form.css, and AGENTS.md.
Each form-specific AGENTS.md must begin on its first line with `# <name>`
(for example, `# Contact` or `# Email`), using only the form name. Keep form-specific fields, rendering,
and validation in those files. Shared HTTP, persistence, and action orchestration
belong in runner.py, store.py, and runtime/. Do not hardcode individual form
schemas in shared infrastructure. No MCP integration or third-party dependencies.

Every session uses the six-field result envelope documented in README.md.
Each output/<execution_id>.txt contains the complete JSON envelope. Its meta_data preserves immutable initial data and
complete snapshots after each persisted action. Never record visual UI state.
Persist changes only through explicit button actions using the runtime action queue.
No background autosave. Each action_name maps to one button with matching
data-action. Draft saving requires an explicit save_draft button. Browser submit validates first and persists only accepted submissions; the API supports
outcome accepted or rejected; preserve existing committed history. Acknowledge saves
only after durable persistence. Preserve history and reject stale revisions.

Forms are trusted local code, not sandboxed plugins. Serve only on loopback;
retain host/origin/token protections and allowlisted static routes. Never serve
output, Python source, or arbitrary filesystem paths as static assets.
Maintain form-local logs/run.log as flattened JSONL: exactly run_id, executed_at,
input, output, output_format, status, error, meta_data. output is a relative file
path, never a nested envelope. Log only durably submitted executions, once per
session at its final revision. Recover missing final records from output files.
The runner owns locked, flushed log writes. Initialization, draft saves, Reader,
rejected submissions, and storage failures do not create log entries.
meta_data contains only form, revision, execution_state, and created_at at its root.
Output files retain complete metadata and history. Never mix test fixtures
with production logs. Session files and logs contain personal data: do not print
their contents into diagnostics or commit them. Test only in temporary directories.
Use Python 3.10+ from forms/.venv/bin/python for the runtime and tests. The runner
requires this project virtual environment and never installs packages or falls
back to another interpreter. Keep .venv/ gitignored. Environment creation or changes
and dependency installation require explicit user authorization. Use only the
standard library; no package installation is needed. Existing tools/ policies
apply within tools/ only.
