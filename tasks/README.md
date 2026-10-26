# Task library

| Recipe | Input | Saved outputs |
| --- | --- | --- |
| [task-webpage-index](task-webpage-index/TASK.md) | URL or text containing one | Researched article, bookmark, entity indexes, Git commit/push receipt |

Run `task-webpage-index: https://example.com/article`.
Components own processing and grant validation. Only tasks execute authorisations
and obtain human consent through the authorisation component interaction.
Subsequent inputs in the same active chat reuse setup. Reports include status,
artifact links, component outcomes, and measured timings.
Components retain their cache and duplicate-execution rules.
Tasks collect dependent components' `authorisations` lists and execute their fixed
permissions in preflight. The authorisation returns its canonical Markdown grant
file, reusing a same-session grant or obtaining explicit human approval. Tasks pass
the file path and expected ID to consumers, which validate locally without callbacks.
One chat owns each authorisation until expiry/revocation; no runtime terms are changed.

[AGENTS.md](AGENTS.md) defines execution and authoring policy.
[TEMPLATE.md](TEMPLATE.md) defines the single-file recipe convention.
