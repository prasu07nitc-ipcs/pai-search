# Task library

| Recipe | Input | Saved outputs |
| --- | --- | --- |
| [task-webpage-index](task-webpage-index/TASK.md) | URL or text containing one | Researched article, bookmark, entity indexes, Git commit/push receipt |

Run `task-webpage-index: https://example.com/article`.
Components own their input resolution, user interaction, and authorization.
Subsequent inputs in the same active chat reuse setup. Reports include status,
artifact links, component outcomes, and measured timings.
Components retain their cache and duplicate-execution rules.

[AGENTS.md](AGENTS.md) defines execution and authoring policy.
[TEMPLATE.md](TEMPLATE.md) defines the single-file recipe convention.
