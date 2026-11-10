# Task library

| Recipe | Input | Saved outputs |
| --- | --- | --- |
| [task-webpage-index](task-webpage-index/TASK.md) | URL or text containing one | Saved article and per-entity Markdown indexes |
| [task-webpage-publish](task-webpage-publish/TASK.md) | Follow-up chat reply of Search, Index, or Skip | Selected query or webpage index files published to the paired data branch |

Run `task-webpage-index: https://example.com/article`.
Components own their input resolution, user interaction, and authorization.
Subsequent inputs in the same active chat reuse setup. Reports include status,
artifact links, component outcomes, and measured timings.
Components retain their cache and duplicate-execution rules.

[AGENTS.md](AGENTS.md) defines execution and authoring policy.
[TEMPLATE.md](TEMPLATE.md) defines the single-file recipe convention.

Task timing uses [clock.mjs](clock.mjs), with a separate in-memory clock per input.
Run its isolated regression checks with `node tasks/clock.test.mjs` from the repository
root using an existing Node runtime; no component executes and no production files
are written.
