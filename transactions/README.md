# Transactions

Standard-library-only Python 3.11+ runner for local persistent writes on macOS.
Read [shared policy](AGENTS.md), then only the selected contract:

| Transaction | Input | Output below data/ |
| --- | --- | --- |
| [tx-bookmark](tx-bookmark/AGENTS.md) | Flat metadata JSON object | bookmark/<domain>/<page_id>/{bookmark,meta}.md |
| [tx-index](tx-index/AGENTS.md) | page object and contexts array | index/<entity>/<domain>/<page_id>/{utterances,meta}.md |
| [tx-save-article](tx-save-article/AGENTS.md) | page_id and article_file | articles/<domain>/<page_id>/{article,meta}.md |

## Execute

From the repository root, supply JSON as an argument or through stdin:

```sh
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-index --input - < /path/to/input.json
```

No raw_input is accepted. Stdout is one compact six-field JSON result; inspect
status (a handled transaction error also exits 0). Diagnostics go to logs/runner.log;
accepted results append to logs/run.log. Do not read logs for routine discovery.
--timeout bounds worker execution (default 20 seconds, maximum 300); --verbose
adds per-function timings. No installation, environment change or network is needed.

## Guarantees and limits

- Fail-closed worker sandbox; only the owned data subtree is writable. Article
  input grants cover one supplied file. No worker subprocesses or network.
- Concurrent runs, no file locks. Last replacement wins per file; pairs/batches
  are not atomic and can mix versions. Retry the complete input after partial
  failure; affected_paths lists known replaced files. No automatic rollback,
  legacy migration, stale-entity deletion or journal replay.
- Bookmark/article successful identical input requires confirmed --rerun; index
  permits duplicates. Concurrent duplicate checks are advisory.
- Production logs use one O_APPEND write per UTF-8 JSON line plus fsync. Storage
  failure can prevent logging or leave an incomplete line; history is not repaired.
- Request IDs use canonical JSON SHA-256. Timestamps, article bytes and source
  signatures affect output; byte-identical replay is not promised. Only meta.md
  contains the signature; input/output paths do not archive content history.

## Verify

Isolated standard-library tests create only temporary data:

```sh
python3 -B -m unittest discover -s transactions -p 'test_*.py' -q
```

Runtime/dependency management requires separate explicit authorization.
