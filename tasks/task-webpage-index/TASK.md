# task-webpage-index

Save a webpage article and one Markdown index file per entity in the local data directory.
Follow the [task library policy](../AGENTS.md).

## Input

Supply a URL or text containing one. Pass the input body unchanged when explicitly
separated from the command; otherwise pass the complete triggering message. Ask for
the URL if absent. The validator owns URL extraction and page identity.

## Setup

Logical context: tasks. Working directory for all runners: repository root.
Load [tools policy](../../tools/AGENTS.md), [skills policy](../../skills/AGENTS.md),
[transactions policy](../../transactions/AGENTS.md),
[tool rules](../../.codex/rules/tools.rules),
[transaction rules](../../.codex/rules/transactions.rules).
Read each linked component's instructions; skill SKILL.md links to its AGENTS.md.

Prepare these runner templates; substitute the stage's exact component, complete JSON
arguments, and timeout before dispatch. POSIX single-quote JSON, replacing each
apostrophe with `'"'"'`. No shell interpolation or temporary input files.

```sh
tools/.venv/bin/python -B tools/runner.py --tool <component> --input '<JSON>' --timeout <seconds>
transactions/.venv/bin/python -B transactions/runner.py --transaction <component> --input '<JSON>' --timeout <seconds>
```

## Stages

`I`: designated input. `V`: parsed successful validator artifact, read once.
`Markdown`, `Metadata`, `Article`, and `Context` are the accepted output paths for those stages.
Resolve tool output paths from `tools/` and skill output paths from the selected
skill directory to repository-relative paths. Preserve V.url and V.page_id.
`W` is the complete accepted output array from webpage_index, in returned order.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| validate | [tool-webpage-validator](../../tools/tool-webpage-validator/AGENTS.md) | tool runner / 20s | {"input_text": I} |
| markdown | [tool-webpage-markdown](../../tools/tool-webpage-markdown/AGENTS.md) | tool runner / 60s | {"url": V.url, "page_id": V.page_id} |
| metadata | [tool-webpage-metadata](../../tools/tool-webpage-metadata/AGENTS.md) | tool runner / 30s | {"url": V.url, "page_id": V.page_id} |
| article | [tool-webpage-article](../../tools/tool-webpage-article/AGENTS.md) | tool runner / 20s | {"raw_input": Metadata relative to tools/, "markdown_file": Markdown relative to tools/} |
| context | [skill-webpage-context](../../skills/skill-webpage-context/SKILL.md) | component agent | {"article_file_path": Article} |
| webpage_index | [tx-webpage-index](../../transactions/tx-webpage-index/AGENTS.md) | transaction runner / 20s | {"context_file_path": Context, "article_file_path": Article} |

Omitted tool options use component defaults. Timeouts bound runner workers, not
total invocation time. Agent stages have no task-imposed timeout or invented runner.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Validate | validate | serial | 1 |
| Extract | markdown, metadata | parallel | 2 |
| Generate | article, context | serial | 1 |
| Save | webpage_index | serial | 1 |

## Result

Report V.page_id and link the saved article and entity index files from W.
The article is the first path in W, followed by any entity index files. Report
the number of entity files and link the encoder output Context. Use the shared timing,
failure reporting, and report persistence rules.
