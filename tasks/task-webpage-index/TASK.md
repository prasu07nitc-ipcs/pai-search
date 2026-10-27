# task-webpage-index

Save a researched article, bookmark, and entity indexes for a webpage, then commit
and push their transaction outputs. Exit early when the local configured branch
already contains any recognized artifact for the page.
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
[transaction rules](../../.codex/rules/transactions.rules),
[data rules](../../.codex/rules/data.rules).
Read each linked component's instructions; skill SKILL.md links to its AGENTS.md.

Prepare these runner templates; substitute the stage's exact component, complete JSON
arguments, and timeout before dispatch. POSIX single-quote JSON, replacing each
apostrophe with `'"'"'`. No shell interpolation or temporary input files.

```sh
tools/.venv/bin/python -B tools/runner.py --tool <component> --input '<JSON>' --timeout <seconds>
transactions/.venv/bin/python -B transactions/runner.py --transaction <component> --input '<JSON>' --timeout <seconds>
data/.venv/bin/python -B data/runner.py --input '<JSON>' --timeout <seconds>
```

For the read-only query stage, pass its exact named inputs directly to the data
runner without approval or rerun flags. The component owns local branch inspection;
do not fetch, inspect Git directly, or substitute local output/log checks.

The commit-and-push component owns settings inspection, authorization, target refresh,
and internal runner input assembly under its linked contract. Run it in this chat
through `data/.venv/bin/python -B data/runner.py`; do not create another chat or
invoke Git directly. Use `--implicit-approval` only when its configured grant covers
the complete request. The persistent grant covers the prescribed index, bookmark,
and article output paths. If the grant does not cover the complete request, obtain
runtime approval through the component without broadening the grant or dropping
files. Definition changes do not authorize Git execution.

## Stages

`I`: designated input. `V`: parsed successful validator artifact, read once.
`Q`: accepted query_page inline output object, not an output-file path.
`D`, `M`, `C`, `W`: accepted markdown, metadata, context, and article output paths.
Preserve V.url and V.page_id. Resolve tool paths from tools/ and skill paths from
the selected skill directory to repository-relative paths. Transactions receive
paths, not payloads; unused fields are null. Skills also receive paths as documented.
`B`, `X`, `A`: complete accepted output arrays from bookmark, index, and save_article.
`F`: concatenate B, X, A in that order, preserving each array's order, and remove
exactly one leading `data/` from each repository-relative output path to produce
data-relative paths. Keep every returned file; do not scan directories, infer extra
files, sort, or silently deduplicate. An unexpected path/interface conflict stops
execution under shared policy. `P`: accepted commit_push receipt path, relative to
data/.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| validate | [tool-url-validate](../../tools/tool-url-validate/AGENTS.md) | tool runner / 20s | {"input_text": I} |
| query_page | [tx-commit-and-push](../../data/tx-commit-and-push/AGENTS.md) | data runner, read-only query / 20s | {"action": "query-page", "page_id": V.page_id} |
| markdown | [tool-webpage-markdown](../../tools/tool-webpage-markdown/AGENTS.md) | tool runner / 60s | {"url": V.url, "page_id": V.page_id} |
| metadata | [tool-webpage-metadata](../../tools/tool-webpage-metadata/AGENTS.md) | tool runner / 30s | {"url": V.url, "page_id": V.page_id} |
| context | [skill-context-encoder](../../skills/skill-context-encoder/SKILL.md) | component agent | {"page_id": V.page_id, "markdown_file_path": D} |
| article | [skill-article-writer](../../skills/skill-article-writer/SKILL.md) | component agent | {"page_id": V.page_id, "metadata_file_path": M, "markdown_file_path": D} |
| bookmark | [tx-bookmark](../../transactions/tx-bookmark/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": null, "article_file_path": null} |
| index | [tx-index](../../transactions/tx-index/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": C, "article_file_path": null} |
| save_article | [tx-save-article](../../transactions/tx-save-article/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": null, "article_file_path": W} |
| commit_push | [tx-commit-and-push](../../data/tx-commit-and-push/AGENTS.md) | data runner via component contract / 20s | {"page_id": V.page_id, "files": F, "message": "data: index webpage " + V.page_id} |

Omitted tool options use component defaults. Timeouts bound runner workers, not
total invocation time. Agent stages have no task-imposed timeout or invented runner.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Validate | validate | serial | 1 |
| Query existing page | query_page | serial | 1 |
| Extract | markdown, metadata | parallel | 2 |
| Generate | context, article | parallel | 2 |
| Save | bookmark, index, save_article | parallel | 3 |
| Commit and push | commit_push | serial | 1 |

After accepting query_page, inspect Q.found before dispatching Extract:

- If true, terminate successfully with the comment **Page already processed.**
  Any recognized artifact triggers this exit, including partial artifact pairs;
  do not require all groups to be complete or attempt to fill missing artifacts.
  Leave every subsequent stage not run.
- If false, continue to Extract and the remaining groups in order.
- Query failure, timeout, or missing/invalid result stops the task under shared
  failure rules. Never interpret an error as found=false or fall back to processing.

## Result

For the already-processed exit, report page_id=V.page_id, **Page already processed.**,
Q.branch, Q.commit_sha, and the returned artifact-group counts and completeness.
Identify returned paths as committed artifacts at that local SHA; do not claim
they exist in the working checkout or certify remote state. Do not claim a new
commit/push or require a receipt from this invocation. Include the timeline with
validate and query_page succeeded and all later stages not run. Capture timings
and persist the exact final report under the shared report-persistence rules.

For normal processing after Q.found=false:

Identity: V.page_id as page_id. Link the saved article, bookmark, and relevant
index/context artifacts, and the receipt at data/P. Report the accepted commit/push
effects from component metadata. All ten stages must succeed; accepted successful cache
hits count, while duplicate refusals terminate the task.

Any component failure or missing result stops the task under shared failure rules.
Report the original error, retained data, and known partial effects without retry or
rollback. Save the final task report afterward. Use shared timing, reporting and
report-persistence rules.
