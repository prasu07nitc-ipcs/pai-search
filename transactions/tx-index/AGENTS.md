# tx-index

Inherit [shared policy](../AGENTS.md). Entry:
`index(page_id: str, meta_data_file_path: str, context_file_path: str, article_file_path: str | None) -> dict`.
Consumes metadata and contexts; article_file_path is ignored.

## Validation

Metadata requires url; optional page_id must match. Optional datePublished/dateModified
accept valid ISO dates/times or null; other fields are ignored. Missing/null dates
are ignored; empty/invalid dates fail. Naive values use Asia/Kolkata; date-only means
midnight. Preserve source offsets. Apply shared source-file, URL and ID rules.

Contexts are a nonempty finite JSON array; each object contains exactly:

| Field | Validation |
| --- | --- |
| entity_name | Nonempty exact safe directory component |
| named_entity | Boolean |
| entity_category | Person, Community, Subject, Topic, Concept, Shop, Organization, Service or Product |
| entity_utternace | Nonempty string; retain this spelling |
| seq_number | Consecutive integers from 1 across the array; reject booleans |

Preserve entity case, spaces, punctuation, Unicode and length. Reject ., .., slash,
NUL, filesystem aliases and case collisions; never sanitize, truncate or skip.
Validate all input before writes. Invalid components/filesystem failures use
output_write_error.

## Rendering

For each distinct exact entity in first-occurrence order, return utterances.md then
meta.md at the shared index layout. No manifest. utterances.md begins with escaped
entity H1, followed by blocks in original array order, separated by blank lines:

```markdown
## Sequence: **<seq_number>/<entire array length>**
- Utterance: <entity_utternace>
- Indexed At: <indexed_at>
- Last Validated At: <last_validated_at>
```

Normalize utterance CRLF/CR to LF; indent continuation lines four spaces. Do not render
named_entity/entity_category. All blocks share one fresh Asia/Kolkata execution
timestamp; Last Validated At is the latest instant among that and both metadata dates.

meta.md contains `## Identifier`, blank line, `- Page ID: <page_id>`, blank line,
then the runner-rendered H2 Source Code Signature. Neither section goes in utterances.md.
Success metadata: page_id, indexed_at, last_validated_at, total_utterances,
skipped_utterances=0. Shared durability/result rules apply; duplicate runs are allowed.

Errors: invalid_input, invalid_page_id, invalid_url, page_id_mismatch, invalid_context,
invalid_date, invalid_input_source, input_read_error, output_write_error.
