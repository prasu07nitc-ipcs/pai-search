# tx-save-article

Inherit [shared policy](../AGENTS.md). Entry:
`save_article(page_id: str, meta_data_file_path: str, context_file_path: str | None, article_file_path: str) -> dict`.
Consumes metadata and article; context_file_path is ignored.

## Validation

Metadata requires url; optional page_id must match; other fields are ignored.
article_file_path identifies UTF-8 Markdown, independent of extension/filename or
producer. Apply shared safe-source, URL and ID checks before reading/title validation.

After optional initial blank lines, the article starts with a nonempty linked H1:
`# [Title](absolute_http_url)`, and contains body text. Support nested parentheses
and escaped Markdown punctuation in the URL. The exact UTF-8 title URL must hash to
page_id before writes; never rewrite/normalize it to force identity. A trailing
Source Page ID label, if present, must match.

## Rendering

Return article.md then meta.md at the shared articles layout. article.md preserves
the supplied Markdown except removing its trailing Source Page ID label and normalizing
trailing line endings to one newline; no signature is added.

meta.md contains H1 References, Source Page ID and Source Code Signature sections.
References are valid HTTP(S) Markdown destinations in first-seen deduplicated order,
including the title; exclude image/code links. Never fetch or verify availability.
Success metadata: page_id, url (exact title URL). Saving means local persistence.
Shared durability, duplicate and result rules apply.

Errors: invalid_input, invalid_input_source, input_read_error, invalid_page_id,
invalid_article, invalid_url, page_id_mismatch, output_write_error.
