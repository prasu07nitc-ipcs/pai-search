# Transactions

Local Markdown persistence through a standard-library-only Python 3.11+ macOS runner.
For execution, read [shared policy](AGENTS.md) and the selected contract only:

| Contract | Consumed files | Output below data/ |
| --- | --- | --- |
| [tx-webpage-index](tx-webpage-index/AGENTS.md) | encoder JSON + encoder input article | articles/<domain>/<page_id>.md and index/<domain>/<normalized_entity>/<page_id>.md |
| [tx-webpage-search](tx-webpage-search/AGENTS.md) | saved search reports | queries/<run_id>.md |

From the repository root, using the existing runtime:

```sh
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-webpage-index --input '{"context_file_path":"contexts.json","article_file_path":"article.md"}'
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-webpage-search --input '{}'
```

Inspect JSON status even after exit 0. Sandbox enforcement, atomic per-file writes,
partial-failure recovery and log contracts are defined once in
the shared policy. Environment/dependency changes require separate authorization.

## Verification

Tests isolate writes in temporary directories:

```sh
transactions/.venv/bin/python -B -m unittest discover -s transactions -p 'test_*.py' -q
```

On macOS, add `TRANSACTION_SANDBOX_TEST=1` to that command to test real sandboxed
runners in a disposable project, outside any enclosing sandbox. This does not execute
production inputs or modify persisted data.
