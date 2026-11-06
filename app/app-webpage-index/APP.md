# app-webpage-index

Save a researched article, bookmark, and entity indexes locally for a webpage.
Exit early when the local filesystem
already contains any recognized artifact for the page.
Follow the [app library policy](../AGENTS.md).

## Input

Supply a URL or text containing one. Pass the input body unchanged when explicitly
separated from the command; otherwise pass the complete triggering message. Ask for
the URL if absent. The validator owns URL extraction and page identity.

## Setup

Logical context: app. Working directory for all runners: repository root.
Load [tools policy](../../tools/AGENTS.md), [skills policy](../../skills/AGENTS.md),
[transactions policy](../../transactions/AGENTS.md),
[data policy](../../data/AGENTS.md),
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

For the read-only local_artifacts stage, load `app/local-artifacts.mjs` into the
persistent Node REPL and call `checkLocalPage({page_id: V.page_id}, repoRoot)`.
Use the existing Node context used for the clock; no shell runner or agent is needed.
The utility owns filesystem validation. It reads directory/file metadata only and
never uses Git, network, configuration, component logs, or saved tool/skill outputs.
Missing data roots mean absence; filesystem/alias errors stop the app. This local
utility is an explicit execution method for this recipe. Include its file size and
modification time in setup invalidation checks, reloading changed modules with a
versioned import URL before reuse.

Recognized layouts beneath `data/` are `articles/<domain>/<page_id>/{article,meta}.md`,
`bookmark/<domain>/<page_id>/{bookmark,meta}.md`, and
`index/<entity>/<domain>/<page_id>/{utterances,meta}.md`. Only regular, unaliased
files count. Any recognized file triggers presence; metadata alone is sufficient.
Unknown files and empty page directories do not count. The checker creates nothing.
Its successful object contains `status: "ok"`, `page_id`, `source: "local-filesystem"`,
boolean `found`, and `groups`. Accept only successful return with matching page ID;
exceptions are stage failures. Each group reports files, observed artifact directories
and absent/partial/complete pair status; completeness does not prove that every
intended entity was indexed. Results describe local observations, not an atomic
snapshot against concurrent writers, and are never cached.

## Stages

`I`: designated input. `V`: parsed successful validator artifact, read once.
`Q`: accepted local_artifacts inline output object, not an output-file path.
`D`, `M`, `C`, `W`: accepted markdown, metadata, context, and article output paths.
Preserve V.url and V.page_id. Resolve tool paths from tools/ and skill paths from
the selected skill directory to repository-relative paths. Transactions receive
paths, not payloads; unused fields are null. Skills also receive paths as documented.
`B`, `X`, `A`: complete accepted output arrays from bookmark, index, and save_article.
| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| validate | [tool-url-validate](../../tools/tool-url-validate/AGENTS.md) | tool runner / 20s | {"input_text": I} |
| local_artifacts | [Local artifact checker](../local-artifacts.mjs) | persistent Node REPL utility, `checkLocalPage` | {"page_id": V.page_id} |
| markdown | [tool-webpage-markdown](../../tools/tool-webpage-markdown/AGENTS.md) | tool runner / 60s | {"url": V.url, "page_id": V.page_id} |
| metadata | [tool-webpage-metadata](../../tools/tool-webpage-metadata/AGENTS.md) | tool runner / 30s | {"url": V.url, "page_id": V.page_id} |
| context | [skill-context-encoder](../../skills/skill-context-encoder/SKILL.md) | component agent | {"page_id": V.page_id, "markdown_file_path": D} |
| article | [skill-article-writer](../../skills/skill-article-writer/SKILL.md) | component agent | {"page_id": V.page_id, "metadata_file_path": M, "markdown_file_path": D} |
| bookmark | [tx-bookmark](../../transactions/tx-bookmark/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": C, "article_file_path": null} |
| index | [tx-index](../../transactions/tx-index/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": C, "article_file_path": null} |
| save_article | [tx-save-article](../../transactions/tx-save-article/AGENTS.md) | transaction runner / 20s | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": null, "article_file_path": W} |

Omitted tool options use component defaults. Timeouts bound runner workers, not
total invocation time. Agent stages have no app-imposed timeout or invented runner.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Validate | validate | serial | 1 |
| Check local artifacts | local_artifacts | serial | 1 |
| Extract | markdown, metadata | parallel | 2 |
| Generate | context, article | parallel | 2 |
| Save | bookmark, index, save_article | parallel | 3 |

After accepting local_artifacts, inspect Q.found before dispatching Extract:

- If true, terminate successfully with the comment **Page already processed.**
  Any recognized local artifact triggers this exit, including partial artifact pairs;
  do not require all groups to be complete or attempt to fill missing artifacts.
  Leave every subsequent stage not run.
- If false, continue to Extract and the remaining groups in order.
- Local check failure or missing/invalid result stops the app under shared
  failure rules. Never interpret an error as found=false or fall back to processing.

## Result

For the already-processed exit, report page_id=V.page_id, **Page already processed.**,
the returned artifact-group counts and completeness.
Link paths beneath `data/` as local artifacts. Presence includes uncommitted files
and does not certify commit or remote state. Include the timeline with
validate and local_artifacts succeeded and all later stages not run. Capture timings
and persist the exact final report under the shared report-persistence rules.

For normal processing after Q.found=false:

Identity: V.page_id as page_id. Link the saved article, bookmark, and relevant
index/context artifacts. Completion means local persistence only.
All nine stages must succeed; accepted successful cache
hits count, while duplicate refusals terminate the app.

Any component failure or missing result stops the app under shared failure rules.
Report the original error, retained data, and known partial effects without retry or
rollback. Save the final app report afterward. Use shared timing, reporting and
report-persistence rules.
