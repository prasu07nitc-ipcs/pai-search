# Tools

Explicitly selected Python functions, run in isolated macOS workers. The parent
runner owns validation, deadlines, and logs; each tool owns its domain contract.

## Start here

- [Project policy and shared contracts](AGENTS.md)
- [URL validation](tool-url-validate/TOOL.md): offline text → URL and SHA-256 ID
- [Webpage metadata](tool-webpage-metadata/TOOL.md): URL + ID → JSON metadata
- [Markdown extraction](tool-webpage-markdown/TOOL.md): URL + ID → article Markdown

Read the selected tool's instructions before invoking it. Commands start in the
repository root containing `tools/`. Use the existing `tools/.venv` environment;
Python 3.11+ and macOS are required. Missing dependencies require separately
authorized environment maintenance.

```sh
tools/.venv/bin/python -B tools/runner.py --tool tool-url-validate \
  --input '{"input_text":"https://example.com/article"}'
```

For either webpage tool, supply `url` and `page_id` from the validator's saved
JSON. Markdown defaults to balanced extraction, tables included, images and link
destinations excluded. Use `mode: "precision"`, `"recall"`, or `"compare"` only
when needed; compare performs three extractions. Allow a 60-second worker timeout
for Markdown with `--timeout 60`; network operations have a separate 15-second
budget. The runner default is 20 seconds, maximum 300 seconds.

## Execution and storage

1. Parent verifies the environment, discovery files, source signature and input.
2. Every invocation executes, including repeated identical inputs.
3. A separate worker applies the sandbox before importing tool code.
4. Worker checks resolved types (including defaults), calls the function and
   validates the result; parent validates it again before recording success.
5. Parent saves result records and captured diagnostics, then emits compact JSON.

Tool-local `output/<page_id>.json` or `.md` files are atomically replaced on
success. Different page IDs are retained. Failed runs preserve previous payloads
where possible. Concurrent same-ID writes use last replacement wins.

Each tool's `logs/run.log` contains append-only JSON Lines; `logs/runner.log`
contains diagnostics and timings. See the [logging contract](AGENTS.md#production-logging).
Repeated invocations replace the saved output on success without confirmation.

## Verification

Run the offline infrastructure regressions without fetching pages or importing
tool implementations:

```sh
tools/.venv/bin/python -B tools/test_runner.py
```

Behavioral checks of tool implementations must use the runner. Real webpage
fetches depend on publisher availability and content; they are smoke checks,
not reproducible fixtures. Identical input hashes reproduce identity, not a
snapshot of a mutable website or dependency environment.

The sandbox denies worker process creation and writes outside its declared
output directory. It permits network access; public-address restrictions belong
to the webpage tools. This is a macOS-specific boundary, not a portable execution
service or a tamper-proof audit system. See [policy](AGENTS.md) for exact limits.

Production `run_id` equals `page_id`; it is null until a page ID is available.
Historical log identifiers are preserved.
