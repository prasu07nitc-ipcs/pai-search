# tx-bookmark

Inherit [shared policy](../AGENTS.md). Entry:
`bookmark(page_id: str, meta_data_file_path: str, context_file_path: str | None, article_file_path: str | None) -> dict`.
Consumes metadata and optional context JSON; article_file_path is ignored.
A null context_file_path retains metadata-only behavior. A supplied context path
must satisfy shared consumed-source rules.

## Metadata

Required strings: title, description, url. Optional strings/null: site_name, type,
section, keywords, datePublished, dateModified, image. Additional finite JSON fields
are accepted but not rendered. Apply shared source-file, URL and page-ID validation.

## Context

A supplied context file must contain a finite JSON array. Each entry must be an
object with a nonempty string entity_name; other fields are ignored. Include every
category and named_entity value. Trim entity names and deduplicate exact names in
first-seen order, without case folding. An empty array is valid.

## Rendering

bookmark.md contains title, Description, Source (URL/domain and supplied site/type/
section), Keywords and supplied Published/Modified Dates. Split keywords on commas,
trim and deduplicate in first-seen order; render as bullets. Escape Markdown controls
and keep supplied values on one line. Append `## Entities` after the existing sections when names are present, with one
escaped, single-line bullet per unique entity, like Keywords. Omit it for null
context or an empty array. No Original data, Identifier or signature here.

meta.md contains `## Identifier`, blank line, `- Page ID: <page_id>`, blank line,
then the runner-rendered H2 Source Code Signature. Return bookmark.md then meta.md
at the shared bookmark layout. Success metadata: domain (hostname before dot
replacement), page_id. Shared durability, duplicate and result rules apply.

Errors: invalid_input_source, input_read_error, invalid_input, invalid_page_id,
invalid_url, invalid_context, page_id_mismatch, output_write_error.
