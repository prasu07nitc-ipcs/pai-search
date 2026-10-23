# Tasks

Tasks orchestrate existing components: read upstream artifacts, assemble declared
inputs, control parallel groups, route outcomes and retain execution state.
Components own semantic validation, content processing, research and persistence.

## Library

[task-index-web-page](task-index-web-page/TASK.md) follows this sequence:
URL validator → parallel metadata/Markdown extraction → parallel context/article
skills → parallel bookmark/index/article transactions → completion publication.
Each group must fully succeed before the next starts. See its
[flowchart](task-index-web-page/flowchart.md) and
[input wiring](task-index-web-page/AGENTS.md#2-wire-inputs).

## Use

- "Run task-index-web-page: https://example.com/article"
- "Show status of task-index-web-page run: <run-id>."
- "Resume task-index-web-page run: <run-id>."
- "Cancel task-index-web-page run: <run-id>."

The task forwards designated input unchanged to the validator; the validator owns
URL interpretation. Task management does not execute components. One orchestrator
owns task state; declared skill groups use parallel component agents. Existing tool
and transaction runners, permissions, cache and duplicate policies remain authoritative.
No task runner, new environment, form polling or background continuation is created.

On failure, stop dispatch, reconcile active siblings, record the outcome and forward
the component error and supplied remedy. Do not diagnose, repair or retry automatically.
A saved checkpoint needs an active agent and explicit resume request to continue.

## Structure

```text
tasks/
  AGENTS.md                       Shared orchestration and durable-state policy
  README.md                       Library and usage
  task-<name>/
    TASK.md                       Discovery entry
    AGENTS.md                     Input wiring and orchestration procedure
    flowchart.md                  Component graph and parallel groups
    checkpoints/<run-id>.json     Stage map and recovery metadata
    output/<run-id>.json          Latest finished-attempt output map
    logs/run.log                  Append-only finished-attempt records
```

Read only the selected task and component contracts needed for the current group.
Keep shared infrastructure rules in [AGENTS.md](AGENTS.md), task wiring in the
selected task's AGENTS.md, and graph structure in flowchart.md. Do not duplicate
component processing instructions in tasks.

## Persistence and recovery

[Shared policy](AGENTS.md) defines identities, stage fields, locks, atomic checkpoints,
publication and logs. Task state contains IDs, arguments/source references, hashes,
statuses and recovery details; component payloads stay in component-owned files.
Only transactions write shared data/. Preserve every returned transaction path.

Reuse verified completed stages, reconcile uncertain effects and respect component
confirmation/cache rules. Parallel siblings may have committed before failure;
no rollback is implied. Historical records retain their existing scope and format;
do not migrate them during management. State/logs are private and gitignored.

Status defaults to the latest finished-attempt record, with active checkpoint
progress distinguished separately. Successful output maps copy all stage fields;
other outcomes project status/output/output_format. Return task IDs, status and
artifact links, forwarding any component-required execution entries.

## Verification

Check contracts and local documentation links without executing a task:

```sh
tools/.venv/bin/python -B -c 'import test_project; test_project.check_contracts()'
```

Full component checks are available through `tools/.venv/bin/python -B test_project.py`;
`--sandbox` adds the project's sandbox checks. No task production run is needed for
instruction edits. Workflow input collection and instruction-version handling remain
deferred; this refactor introduces neither.
