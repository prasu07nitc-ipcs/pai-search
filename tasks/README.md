# Task library

| Recipe | Input | Saved outputs |
| --- | --- | --- |
| [task-webpage-index](task-webpage-index/TASK.md) | URL or text containing one | Researched article, bookmark, entity indexes, commit-and-push receipt |

Run `task-webpage-index: https://example.com/article`.
Components own their input resolution, user interaction, and authorization.
Subsequent inputs in the same active chat reuse setup. Reports include status,
artifact links, component outcomes, and measured timings.
Components retain their cache and duplicate-execution rules.
After URL validation, webpage indexing queries the local configured Git branch by
page ID. Any matching artifact, including a partial pair, ends the task with
“Page already processed.” No match continues processing; query errors stop the task.

[AGENTS.md](AGENTS.md) defines execution and authoring policy.
[TEMPLATE.md](TEMPLATE.md) defines the single-file recipe convention.

Task timing uses [clock.mjs](clock.mjs), with a separate in-memory clock per input.
Run its isolated regression checks with `node tasks/clock.test.mjs` from the repository
root using an existing Node runtime; no component executes and no production files
are written.
