# Transactions

Local Markdown persistence through a standard-library-only Python 3.11+ macOS runner.
For execution, read [shared policy](AGENTS.md) and the selected contract only:

| Contract | Consumed files | Output below data/ |
| --- | --- | --- |
| [tx-bookmark](tx-bookmark/AGENTS.md) | metadata + optional context JSON | bookmark/<domain>/<page_id>/{bookmark,meta}.md |
| [tx-index](tx-index/AGENTS.md) | metadata + context JSON | index/<entity>/<domain>/<page_id>/{utterances,meta}.md |
| [tx-save-article](tx-save-article/AGENTS.md) | metadata JSON + article Markdown | articles/<domain>/<page_id>/{article,meta}.md |

From the repository root, using the existing runtime:

```sh
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-index --input '{"page_id":"<sha256>","meta_data_file_path":"metadata.json","context_file_path":"contexts.json","article_file_path":null}'
```

Inspect JSON status even after exit 0. Sandbox enforcement, atomic per-file writes,
rerun confirmation, partial-failure recovery and log contracts are defined once in
the shared policy. Environment/dependency changes require separate authorization.

## Verification

Tests isolate writes in temporary directories:

```sh
transactions/.venv/bin/python -B -m unittest discover -s transactions -p 'test_*.py' -q
```

On macOS, add `TRANSACTION_SANDBOX_TEST=1` to that command to test real sandboxed
runners in a disposable project, outside any enclosing sandbox. This does not execute
production inputs or modify persisted data.
