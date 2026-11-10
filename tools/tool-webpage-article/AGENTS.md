# Article writer

Call `write_article(raw_input, markdown_file)` with two paths relative to
`tools/`. The metadata JSON path serves as the unchanged `raw_input` identity.
Use `tool-webpage-metadata/output/<page_id>.json` and
`tool-webpage-markdown/output/<page_id>.md`. Both files must be regular,
unaliased UTF-8 files with the same lowercase SHA-256 page ID in their filenames.
The metadata must be a JSON object containing that page ID and string or null
values. The Markdown body must contain non-whitespace text.

Write `tool-webpage-article/output/<page_id>.md` with Title, Description, Body,
and Meta Data headings. Preserve the body text and include every metadata
attribute other than title and description under Meta Data. Display missing or
null values as “Not provided”. Indent metadata continuation lines so embedded
text cannot introduce footer fields or headings. Replace the article atomically.

Return the shared tool result envelope with output format `markdown`, the
Markdown path argument in `input.processed_input`, and the validated page ID
in `meta_data` on success. Expected error codes are `invalid_source_path`,
`source_read_error`, `invalid_metadata`, `empty_body`, and
`output_write_error`. Failures return a null output.

Use the [shared runner](../AGENTS.md#execution-environment) and existing
environment. No additional dependencies or network requests are required.
The runner writes `logs/run.log` and `logs/runner.log` under this tool.
For cache lookup, resolve historical successful records with an output of
`tool-article-writer/output/<page_id>.md` to the corresponding
`tool-webpage-article/output/<page_id>.md`. Use the resolved path when comparing
records, validating the artifact, and returning a cache hit. Preserve log records
as written.
