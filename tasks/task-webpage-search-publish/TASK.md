# task-webpage-search-publish

Export saved webpage search reports, publish the exported query files, and clean up the corresponding source outputs.
Follow the [task library policy](../AGENTS.md).

## Input

Invoke by task name alone. No input is required. Capture the invocation date in
the user's timezone and format it as `mm-dd-yy` with zero-padded month and day.

## Setup

Use the repository root as the working directory. Read the
[tools policy](../../tools/AGENTS.md),
[tool rules](../../.codex/rules/tools.rules),
[transactions policy](../../transactions/AGENTS.md),
[transaction rules](../../.codex/rules/transactions.rules), and the linked
component contracts. Confirm commit and push authorization under the Git
transaction policy before dispatch. Use the existing transaction and tool runtimes.

```sh
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-webpage-search --input '{}' --timeout 20
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '<JSON>'
tools/.venv/bin/python -B tools/runner.py --tool tool-skill-gc --input '<JSON>' --timeout 20
```

Serialize each complete input object as JSON and POSIX single-quote it, replacing each
apostrophe with `'"'"'`. Use no shell interpolation or temporary input files.

## Stages

`Q` is the complete accepted output array from `export_queries`, in returned
order. Verify each path is an existing repository-relative Markdown file directly
under `data/queries/` with a 64-character lowercase hexadecimal filename stem. `M` is the literal prefix `seach-queries-` followed by the
formatted invocation date.

`S` is the list of source output paths for Q. In Q order, take each query
filename stem as the search run ID and append these repository-relative paths
in order: `skills/skill-webpage-search/output/<run_id>.md` and
`skills/skill-webpage-search/output/<run_id>.txt`. The cleanup tool skips
missing paths. Use Q for query identity because the Git result's `page_ids`
field covers articles and indexes.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| export_queries | [tx-webpage-search](../../transactions/tx-webpage-search/AGENTS.md) | transaction runner / 20s | {} |
| git_commit | [tx-git-commit](../../transactions/tx-git-commit/AGENTS.md) | Git-specific transaction runner / per-command timeout under component policy | {"file_paths": Q, "commit_message": M} |
| skill_gc | [tool-skill-gc](../../tools/tool-skill-gc/AGENTS.md) | tool runner / 20s | {"file_paths": S} |

If Q is empty, finish successfully with both downstream stages marked as not run. Use the
[Git transaction contract](../../transactions/tx-git-commit/TRANSACTION.md) for
result acceptance. An accepted Git success, including a successful no-op,
unlocks cleanup. A Git failure leaves the source outputs available.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Export | export_queries | serial | 1 |
| Publish | git_commit | serial | 1 |
| Clean up | skill_gc | serial | 1 |

## Result

Report the exported count, link the paths in Q, and report the commit ID and push
status and cleanup outcome when available. Report the deleted source paths from
the cleanup result and link its receipt when available. If Q is empty, report that no new queries were exported.
The cleanup receipt ID identifies the batch. The task has no webpage ID for
shared page-based report persistence.
