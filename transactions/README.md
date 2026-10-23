# Transactions

Run explicitly authorized persistent changes through the dedicated macOS Python
3.11+ environment. Commands run from the repository root, regardless of the
chat's current context. The runner uses only the standard library and installs a
fail-closed OS sandbox before importing a worker.

## Run

```sh
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-index --input '{"raw_input":"Index saved contexts","page_file":"tools/tool-webpage-og-crawler/output/<run_id>.txt","context_file":"skills/skill-context-encoder/output/<run_id>.txt"}'
```

| Transaction | Inputs besides `raw_input` | Owned destination |
| --- | --- | --- |
| [tx-bookmark](tx-bookmark/AGENTS.md) | `page_file` | `data/bookmark/<domain>/<page_id>.md` |
| [tx-save-article](tx-save-article/AGENTS.md) | `page_id_file`, `article_file` | `data/articles/<domain>/<page_id>.md` |
| [tx-index](tx-index/AGENTS.md) | `page_file`, `context_file` | `data/index/<exact entity_name>/<domain>/<page_id>.md` |

Producer run IDs are 64 lowercase hexadecimal characters. See the linked
transaction contracts for allowed source folders, validation, and replacement rules.

Stdout is one compact JSON object with `input`, `output`, `output_format`, `status`,
`error`, and `meta_data`. Success returns an array of repository-relative files;
failure returns null output. Diagnostics go to transaction-local `logs/runner.log`.
Production records append to `logs/run.log`.
Avoid reading logs or source payloads during routine discovery.

`--timeout` bounds the worker (default 20 seconds; maximum 300). Index lock waiting
has a separate bound of the same length. An identical successful request exits 2
noninteractively; use `--rerun` only after explicit user confirmation.

## Reproducibility and recovery

Production request identity is SHA-256 of canonical UTF-8 JSON: sorted keys,
compact separators, literal Unicode, no non-finite numbers. Original arguments,
including `raw_input`, participate; defaults do not. This is request identity,
not a fingerprint of implementation or source payloads.

Index replacement batches additionally hash both source byte streams, verify
worker reads, and journal their original Asia/Kolkata timestamp under an exclusive
lock. Failed or interrupted batches reuse that timestamp when recovered. Files
are replaced atomically one at a time; there is no batch rollback. Old index
layouts and removed entities are not automatically migrated or deleted.

Byte-for-byte replay across arbitrary runs is not guaranteed: timestamps, Git
snapshot metadata, runtime/timezone data, and source changes can affect output.
Every transaction output ends with a Source Code Signature describing the selected
transaction's Git state, not a complete
content archive. Preserve these dependencies when comparing artifacts.

[AGENTS.md](AGENTS.md) defines framework policy; transaction-local instructions
contain the payload contracts. Runtime/dependency changes require separate
authorization. Do not invoke transaction modules or internal worker mode directly.
