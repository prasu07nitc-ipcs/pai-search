# Tasks

A library of workflows executed by a single agent. The agent follows each task's
instructions, uses existing component runners, and saves checkpoints for resume.

## Library

- [task-index-web-page](task-index-web-page/TASK.md): collect a URL, extract
  selected metadata/Markdown, encode Markdown into entity context for Index, and
  generate a researched article for Read after both extractions succeed. Persist
  selected results through tx-bookmark, tx-index, and tx-save-article.

## Use

Ask the agent:

- "Run task-index-web-page."
- "Show the status of task-index-web-page run:`run-id`."
- "Resume task-index-web-page run: `run-id`."
- "Cancel task-index-web-page run: `run-id`."

The agent opens the form and waits up to five minutes for submission. Any selected checkbox requires metadata; Index or Read requires Markdown. Required
extraction tools run concurrently. Read enables article writing after both succeed.
The same agent executes the encoder after successful Markdown extraction.
No task-specific Python environment or separate model worker is needed.

Progress needs an active agent session. If interrupted, ask to resume using the
saved run ID. Checkpoints do not provide automatic background continuation or
reboot recovery. Renewing an expired form wait or repeating an uncertain tool
execution requires an explicit instruction.

## Structure

```text
tasks/
  AGENTS.md                     Shared execution and checkpoint rules
  README.md                     Library and user guide
  task-index-web-page/
    TASK.md                     Discovery entry
    AGENTS.md                   Contract, procedure, diagram, and recovery
    checkpoints/<run-id>.json          Component execution map
    output/<run-id>.json        Latest component output map
    logs/run.log               Append-only finished-attempt entries
```

Add another task by creating task-<name>/TASK.md and AGENTS.md. Follow the naming
and section conventions in the existing task. Keep the complete instructions in
AGENTS.md so procedure and diagram remain together. Read only the selected task
and components needed for its current stage.

## Persistence and recovery

[Shared policy](AGENTS.md#checkpoints) defines the checkpoint fields and atomic
write protocol. Component outputs and logs stay in their existing locations;
checkpoints retain IDs, paths, hashes, decisions, and stage outcomes. Run folders
are gitignored and may contain private URLs or user input; do not commit them.

Resume verifies outputs and reconciles committed component records before retry.
Successful branches are retained. Encoding requires Index. Read alone extracts metadata and Markdown and writes an
article, without encoding; Bookmark-only and neither-selected runs skip encoding.
Bookmark saves metadata in data/bookmark/, Index saves entity files in data/index/,
and Read saves the generated article in data/articles/. Transactions consume saved
producer files and perform all shared-data writes. Publication is local only.

The existing forms server and tool runtimes remain required. Their environment
and duplicate-input policies still apply. The dedicated transactions runtime is
also required; transaction stages preserve output path arrays and per-file hashes.
Partial or uncertain mutations require reconciliation before retry. The encoder uses its existing skill
cache/logging contract directly; no Codex CLI subprocess is launched.

## Verification

From the repository root, run the existing project checks:

```sh
tools/.venv/bin/python -B test_project.py --sandbox
```

Task checks validate discovery files, required instruction sections, and local
Markdown links. They do not execute tasks, submit forms, fetch pages, or create
production run records. Component regression and sandbox tests remain unchanged.

## Execution outputs and history

Every task follows the [shared output and logging contract](AGENTS.md#execution-log).
New run IDs hash the original chat session ID and exact triggering input. Each
finished execution appends one entry with an increasing attempt_seq. Resume and
authorized rerun retain the ID. A successful run requires user permission before
rerun; an explicit rerun request counts. No attempt-specific files are created.

After successful completion, the run-specific output JSON copies all component
stage attributes from the checkpoint into the matching stage: component_type,
component_name, started_at, completed_at, status, component run_id, stage
attempt_seq, repository-relative output path, transaction output array (or null), output_format, and error.
Other finished outcomes include only status, output, and output_format per stage.
Logs reference this map using
a task-relative path. Subsequent attempts replace the same map; earlier log
entries preserve their own outcomes but reference the latest file. Component
payloads stay in their own files. Status queries default to the latest appended
entry; explicitly request an attempt or history for earlier outcomes. Active
checkpoint progress is reported separately from finished execution status.

Production outputs, checkpoints, locks, and logs are private and gitignored.
Run lock files are removed after successful completion and committed publication.
Unsuccessful or interrupted runs may retain an unlocked file for later recovery.
Historical runs are not migrated or backfilled. Instruction-version handling is
deferred in [the development task](../dev-tasks/task-instruction-version-handling.md).

The checkpoint and a successful output map contain identical component stage
objects. For other outcomes, the checkpoint retains the additional component
attributes omitted from the output map. Its component stage IDs match the output
exactly; the additional top-level
recovery_meta_data object is excluded from the output map. Stage attempt_seq counts
component invocations; run.log attempt_seq counts task attempts. Recovery-only
identity inputs, arguments, deadlines, artifact hashes, and publication state
live in recovery_meta_data inside the same checkpoint. Resume reads that single
file; component state and recovery metadata are updated atomically together. Existing legacy checkpoints are not rewritten during management.
