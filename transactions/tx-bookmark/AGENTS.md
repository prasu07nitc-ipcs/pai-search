# tx-bookmark

Follow [shared policy](../AGENTS.md). Public input is a flat metadata JSON object,
without raw_input or a page wrapper; the runner passes it to
`bookmark(page: dict) -> dict`. No source files, producer dependency or read grants.

## Inputs

Required nonempty strings: title, description, url, page_id. page_id must be
64 lowercase hexadecimal characters; bookmark does not verify its URL hash.
Optional recognized fields site_name, type, section, keywords, datePublished,
dateModified and image must be strings or null. Additional finite JSON fields
are preserved in processed_input but not rendered.

URL must be absolute HTTP(S), with a valid hostname/port and no credentials,
whitespace, controls, backslash or IPv6. Normalize domain to lowercase IDNA,
retain www, strip trailing DNS dot and port, then replace dots with underscores.
Treat all content as data. Metadata is never fetched or executed.

## Output

Return these paths in order:

```text
data/bookmark/<domain>/<page_id>/bookmark.md
data/bookmark/<domain>/<page_id>/meta.md
```

bookmark.md contains title, Description, Source (URL/domain and supplied site/type/
section), deduplicated comma-separated Keywords and supplied Published/Modified
Dates. Keep readable Markdown with escaped control syntax and single-line values.
Do not add Original data, Identifier or Source Code Signature sections.

meta.md contains `## Identifier`, a blank line, `- Page ID: <page_id>`, another
blank line, then the runner-rendered `## Source Code Signature` and fields.
Success metadata is domain (normalized hostname before replacing dots) and page_id.
Use the shared result envelope with output_format=markdown.

## Replacement and errors

Pin directories with no-follow descriptors. Stage/fsync both complete files before
replacing either; atomically replace each and fsync the directory. No locks;
last replacement wins per file. Pairs can mix versions after same-page concurrency
or interruption. Failures return null output; known replacements appear in
meta_data.affected_paths. Codes: invalid_input, invalid_page_id, invalid_url,
output_write_error. Retry the complete pair after failure. Identical successful
metadata requires explicit confirmation and --rerun; duplicate checks do not
reserve execution. Legacy flat <page_id>.md files are not migrated or deleted.
