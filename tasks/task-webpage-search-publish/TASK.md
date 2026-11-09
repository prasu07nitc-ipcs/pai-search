# task-webpage-search-publish

Export saved webpage search reports, then commit and push the exported query files.
Follow the [task library policy](../AGENTS.md).

## Input

Invoke by task name alone. No input is required. Capture the invocation date in
the user's timezone and format it as `mm-dd-yy` with zero-padded month and day.

## Setup

Use the repository root as the working directory. Read the
[transactions policy](../../transactions/AGENTS.md),
[transaction rules](../../.codex/rules/transactions.rules), and the linked
component contracts. Confirm commit and push authorization under the Git
transaction policy before dispatch. Use the existing transaction runtime.

```sh
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-webpage-search --input '{}' --timeout 20
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '<JSON>'
```

Serialize the complete Git input as JSON and POSIX single-quote it, replacing each
apostrophe with `'"'"'`. Use no shell interpolation or temporary input files.

## Stages

`Q` is the complete accepted output array from `export_queries`, in returned
order. Verify each path is an existing repository-relative Markdown file directly
under `data/queries/`. `M` is the literal prefix `seach-queries-` followed by the
formatted invocation date.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| export_queries | [tx-webpage-search](../../transactions/tx-webpage-search/AGENTS.md) | transaction runner / 20s | {} |
| git_commit | [tx-git-commit](../../transactions/tx-git-commit/AGENTS.md) | Git-specific transaction runner / per-command timeout under component policy | {"file_paths": Q, "commit_message": M} |

If Q is empty, finish successfully with `git_commit` marked as not run. Use the
[Git transaction contract](../../transactions/tx-git-commit/TRANSACTION.md) for
result acceptance.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Export | export_queries | serial | 1 |
| Publish | git_commit | serial | 1 |

## Result

Report the exported count, link the paths in Q, and report the commit ID and push
status when available. If Q is empty, report that no new queries were exported.
Neither stage supplies a page ID for this task, so the shared page-based report
persistence rule cannot save the final report.
