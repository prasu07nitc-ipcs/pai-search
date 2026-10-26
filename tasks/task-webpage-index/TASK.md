# task-webpage-index

Save a researched article, bookmark, and entity indexes for a webpage, then commit
and push the saved data.
Follow the [task library policy](../AGENTS.md).

## Input

Supply a URL or text containing one. Pass the input body unchanged when explicitly
separated from the command; otherwise pass the complete triggering message. Ask for
the URL if absent. The validator owns URL extraction and page identity.

## Setup

Logical context: tasks. Working directory for all runners: repository root.
Load [tools policy](../../tools/AGENTS.md), [skills policy](../../skills/AGENTS.md),
[transactions policy](../../transactions/AGENTS.md),
[data policy](../../data/AGENTS.md),
[tool rules](../../.codex/rules/tools.rules),
[transaction rules](../../.codex/rules/transactions.rules), and
[data rules](../../.codex/rules/data.rules).
Read each linked component's instructions; skill SKILL.md links to its AGENTS.md.
The Git component owns loading git-config.json and refreshing branch state; task
setup must not cache Git settings or approval.

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

`B`, `X`, and `A`: complete accepted `output` arrays from `bookmark`, `index`, and
`save_article`, respectively. After all Save stages succeed, concatenate B, X, A in
that order and remove exact duplicate paths, keeping first occurrence. Every path
must begin with the literal `data/`; remove that prefix exactly once to produce `F`.
Do not use character trimming, filesystem normalization, directory expansion or file
discovery. Include every returned file, including meta.md. An unavailable array or
path-base conflict stops dispatch; leave semantic/path-safety validation to the component.

`Q` is exactly `data: index webpage ` concatenated with accepted `V.page_id`, with
no extra whitespace, body or trailers. An unavailable validator identity stops dispatch.
`P = {"page_id": V.page_id, "files": F, "message": Q}` is the complete public request.
Keep P in memory for response matching; do not add Git settings or runner fields.

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
| commit_push | [tx-commit-and-push](../../data/tx-commit-and-push/AGENTS.md) | active-chat component role / component-owned 20s worker | P |

Omitted tool options use component defaults. Timeouts bound runner workers, not
total invocation time. Agent stages have no task-imposed timeout or invented runner.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Validate | validate | serial | 1 |
| Extract | markdown, metadata | parallel | 2 |
| Generate | context, article | parallel | 2 |
| Save | bookmark, index, save_article | parallel | 3 |
| Commit and push | commit_push | serial | 1 |

## Result

Identity: V.page_id as page_id. Link the saved article, bookmark, relevant
index/context artifacts and Git receipt. All nine stages must succeed; accepted
successful cache hits count, while duplicate refusals terminate the task.

Invoke commit_push once with P as a role in this active chat. The component owns
configuration, explicit approval, branch refresh, runner execution and receipt
verification. Do not add a prepare/approve exchange, internal Git inputs, direct data
runner calls or task-specific Git recovery. A task request alone grants no Git approval.

Accept its final six-field public result: input must equal P, status must be ok,
error must be null and output must contain its accepted receipt. Preserve the returned
output/error/meta_data; do not inspect the internal receipt request or recompute its
ID. Receipt paths are data-relative: prepend `data/` once before making absolute report
links. Transaction paths are already repository-relative.

Any component failure, declined approval or missing result stops the task under shared
failure rules. Report the original error, retained data, available receipts and known
partial effects without retry or rollback. Approval time counts toward stage elapsed
time, outside the component's worker timeout. Save the final task report afterward;
it is excluded from F. Use shared timing, reporting and report-persistence rules.
