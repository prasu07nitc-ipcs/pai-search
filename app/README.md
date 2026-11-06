# App library

| Recipe | Input | Saved outputs |
| --- | --- | --- |
| [app-webpage-index](app-webpage-index/APP.md) | URL or text containing one | Researched article, bookmark, and entity indexes saved locally |

Run `app-webpage-index: https://example.com/article`.
Components own their input resolution, user interaction, and authorization.
Subsequent inputs in the same active chat reuse setup. Reports include status,
artifact links, component outcomes, and measured timings.
Components retain their cache and duplicate-execution rules.
After URL validation, webpage indexing checks local data folders by page ID, without Git access.
Any recognized local artifact, including a partial pair, ends the app with
“Page already processed.” No match continues processing; filesystem errors stop the app.

[AGENTS.md](AGENTS.md) defines execution and authoring policy.
[TEMPLATE.md](TEMPLATE.md) defines the single-file recipe convention.

App timing uses [clock.mjs](clock.mjs), with a separate in-memory clock per input.
