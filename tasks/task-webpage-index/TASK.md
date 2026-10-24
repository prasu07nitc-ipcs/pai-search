# task-webpage-index

Save a researched article, bookmark, and entity indexes for a webpage.
Follow the [task library policy](../AGENTS.md).

## Input

Supply a URL or text containing one. Pass the input body unchanged when explicitly
separated from the command; otherwise pass the complete triggering message. Ask for
the URL if absent. The validator owns URL extraction and page identity.

## Setup

Logical context: tools. Working directory for all runners: repository root.
Load [tools policy](../../tools/AGENTS.md), [skills policy](../../skills/AGENTS.md),
[transactions policy](../../transactions/AGENTS.md),
[tool rules](../../.codex/rules/tools.rules), and
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
`D`, `M`, `C`, `W`: accepted markdown, metadata, context, and article output paths.
Preserve V.url and V.page_id. Resolve tool paths from tools/ and skill paths from
the selected skill directory to repository-relative paths. Transactions receive
paths, not payloads; unused fields are null. Skills also receive paths as documented.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| validate | [tool-url-validate](../../tools/tool-url-validate/AGENTS.md) | tool runner / 20s | {"input_text": I} |
| markdown | [tool-webpage-markdown](../../tools/tool-webpage-markdown/AGENTS.md) | tool runner / 60s | {"url": V.url, "page_id": V.page_id} |
| metadata | [tool-webpage-metadata](../../tools/tool-webpage-metadata/AGENTS.md) | tool runner / 30s | {"url": V.url, "page_id": V.page_id} |
| context | [skill-context-encoder](../../skills/skill-context-encoder/SKILL.md) | component agent | {"page_id": V.page_id, "markdown_file_path": D} |
| article | [skill-article-writer](../../skills/skill-article-writer/SKILL.md) | component agent | {"page_id": V.page_id, "metadata_file_path": M, "markdown_file_path": D} |
| bookmark | [tx-bookmark](../../transactions/tx-bookmark/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": null, "article_file_path": null} |
| index | [tx-index](../../transactions/tx-index/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": C, "article_file_path": null} |
| save_article | [tx-save-article](../../transactions/tx-save-article/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": null, "article_file_path": W} |

Omitted tool options use component defaults. Timeout values bound runner workers,
not total invocation time. Agent stages have no invented timeout or runner.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Validate | validate | serial | 1 |
| Extract | markdown, metadata | parallel | 2 |
| Generate | context, article | parallel | 2 |
| Save | bookmark, index, save_article | parallel | 3 |

## Result

Identity: V.page_id as page_id. Link the article saved by save_article, the bookmark,
and relevant index/context artifacts. All eight stages must succeed, including valid
successful cache hits; duplicate refusals terminate with partial effects reported.
Saving is local, not remote publication. Use the shared timing/report contract.
