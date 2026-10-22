# Transactions

Transactions manage persistent project data under `data/`. Read the [sub-project policy](AGENTS.md) before creating or changing a transaction.

The macOS transaction runner executes transactions in the dedicated Python 3.11+ `transactions/.venv`. Each worker can write only its own `data/<transaction_name>/` subtree; the runner owns logs. The runtime uses only the standard library and was created separately with user authorization.

**Strict runner dependency rule:** `runner.py` must use only Python built-ins and the standard library, including for optional or delegated runner functionality. Third-party Python libraries are prohibited. See the [full dependency policy](AGENTS.md#strict-runner-dependencies).

## Structure

Paths below are relative to the repository root:

```text
transactions/
  AGENTS.md
  README.md
  tx-bookmark/
    TRANSACTION.md
    AGENTS.md
    transaction.py
    validator.py
    test-cases.json
data/
  AGENTS.md
```

An implemented transaction will live in `transactions/tx-<transaction_name>/` with `TRANSACTION.md`, `AGENTS.md`, `transaction.py`, and `validator.py`. Its execution logs will live in its local logs/ directory. Use the runner commands below; do not invoke transaction modules directly.

Transaction-specific data folders are created and validated by the runner only at runtime for an authorized invocation. Scaffolding and discovery do not create them.

## Agreed output model

Each transaction exclusively owns the data subdirectory derived from its name: `tx-bookmark` owns `data/bookmark/`, and `tx-index` owns `data/index/`. The bookmark destination is:

```text
data/bookmark/www_thehindu_com/<page_id>.md
```

The standard six-field result envelope is retained, but transaction output paths are relative to the repository root and point directly to persistent data. For example, these fields appear in a successful result:

```json
{
  "output": "data/bookmark/www_thehindu_com/<page_id>.md",
  "output_format": "markdown",
  "status": "ok",
  "error": null
}
```

The example is an excerpt, not the complete result envelope. Production logs copy that output path directly. No separate receipt is necessary. Replacing a file changes the contents reached by earlier log entries; file versioning is not provided.

## Access model

Transactions alone may write shared data among framework workers. Each transaction can write only its own `data/<transaction_name>/` subtree. Other transactions cannot write there, and transaction definitions cannot override the naming convention. The parent runner writes transaction-local logs; workers cannot write their local implementation or logs. Tools keep their existing local write permissions. Transaction tests must use isolated disposable data, not production bookmarks. The runner installs and probes the macOS filesystem/subprocess sandbox before importing transaction code, and fails closed when unavailable.

## Available transaction definitions

[tx-bookmark](tx-bookmark/TRANSACTION.md) formats supplied webpage metadata as Markdown without an Original data section. data/bookmark/ is created only at runtime for a production invocation. Tests use disposable isolated data roots.

## Execution

All commands run from the repository root. --input is a JSON object of named arguments, including raw_input. Use --transaction to select a tx-<name> definition.

```sh
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-bookmark --input '{"raw_input":"Bookmark example","page":{"title":"Example","description":"Example page","url":"https://example.com/a","page_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}'

transactions/.venv/bin/python -B transactions/runner.py --transaction tx-bookmark --cases transactions/tx-bookmark/test-cases.json --summary

transactions/.venv/bin/python -B transactions/test_runner.py
```

The runner uses a 20-second worker timeout; --timeout accepts a positive finite number up to 300 seconds. Successful duplicate production inputs require explicit confirmation through --rerun. Noninteractive duplicates exit 2. Test failures exit 1; --summary reports counts while full case records remain in logs/test-report.log.

Production stdout is the six-field result object. API callers may use invoke(name, value, test_run=False, expected=None, timeout=20, run_id=None, rerun=False) under the authorized runtime. Test execution prepares and removes an isolated data destination for every case, never production data. Test output paths remain logical repository-relative paths; physical test artifacts are removed after validation.

Logs live under transactions/tx-<name>/logs/: run.log for production, test-report.log for cases and runner.log for function diagnostics and timings. See the [logging contract](AGENTS.md#logging-and-execution-requirements). Direct API users should configure runner.LOGGER for runner-owned diagnostics as the CLI does.

No automatic rollback or file versioning is provided. A worker may finish a write before a timeout or result-validation failure; retry and recovery must account for that possibility. Logs are operational records, not tamper-proof audits. The internal --worker mode is runner transport, not a public alternate execution interface.

## Source Code Signature

Bookmark Markdown ends with `## Source Code Signature`, containing Git repository URL,
Git branch, full Git commit SHA, and Local changes. The parent runner captures this
snapshot immediately before launching the worker and supplies it through runner-owned
`PROJECT_TRANSACTION_SOURCE_SIGNATURE` JSON configuration, never caller arguments.
The repository is resolved from the selected transaction directory. The origin URL is
converted from SSH to HTTPS where possible and stripped of credentials, query, fragment,
and trailing .git. No repository-name field is included. Missing remote URLs use
`Unavailable`; detached branches use `Detached HEAD`. Outside Git all Git fields use
`Unavailable`. Git repositories without a resolvable HEAD or with failed snapshot commands
fail execution rather than falsely report a clean snapshot.

Local changes include only the selected transaction directory, staged, unstaged, and
untracked files, excluding Git-ignored files (including tracked files matching current
ignore rules). Paths are repository-relative; entries retain Git porcelain two-column
status codes (index then working tree; `.` represents an unchanged column; `??` means untracked). Renames appear as deletion
and addition. Empty changes render `- Local changes: None`. Changes elsewhere, including
the shared runner, are excluded. This snapshot lists paths and statuses, not file contents
or diffs, and does not guarantee an atomic snapshot against concurrent source edits.
The public six-field result, inputs, metadata, and output path remain unchanged.
