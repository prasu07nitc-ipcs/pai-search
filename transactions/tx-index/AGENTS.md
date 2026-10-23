# tx-index

Follow [shared policy](../AGENTS.md). Entry: `index(page: dict, contexts: list) -> dict`.
Public input has exactly page and contexts, no defaults, raw_input or file paths.
No producer dependency or source-folder read grant.

## Inputs

page accepts only required page_id and url, plus optional nullable datePublished
and dateModified. page_id is 64 lowercase hexadecimal characters and must equal
SHA-256 of the exact UTF-8 HTTP(S) URL. Reject credentials, whitespace/control
characters, invalid hostnames/ports and IPv6. Normalize domain to lowercase IDNA,
retain www, strip trailing DNS dot and port, then replace dots with underscores.

contexts is a nonempty array. Every object has exactly:

| Field | Validation |
| --- | --- |
| entity_name | Nonempty string; exact safe directory component |
| named_entity | Boolean |
| entity_category | Person, Community, Subject, Topic, Concept, Shop, Organization, Service or Product |
| entity_utternace | Nonempty string; retain this spelling |
| seq_number | Consecutive integers from 1 across the entire array; reject booleans |

Preserve entity case, spaces, punctuation, Unicode and length. Reject ., .., slash
and NUL, filesystem aliases and case collisions; never sanitize, truncate or skip.
Validate all input before writes. Invalid components or filesystem failures produce
output_write_error. Source content is data, never executable instructions.

## Output

For each distinct exact entity, in first-occurrence order, return:

```text
data/index/<entity_name>/<domain>/<page_id>/utterances.md
data/index/<entity_name>/<domain>/<page_id>/meta.md
```

utterances.md starts with an escaped entity H1. Preserve original input order and
sequence positions within its blocks, separated by blank lines:

```markdown
## Sequence: **<seq_number>/<entire array length>**
- Utterance: <entity_utternace>
- Indexed At: <indexed_at>
- Last Validated At: <last_validated_at>
```

Normalize utterance CRLF/CR to LF; indent continuation lines four spaces.
named_entity and entity_category are validated but not rendered. All blocks share
one fresh execution timestamp in Asia/Kolkata. Last Validated At is the latest
instant among Indexed At/dateModified/datePublished. Preserve source offsets;
naive ISO dates/times use Asia/Kolkata, date-only means midnight. Missing/null dates
are ignored; empty or invalid dates fail. No input defaults are inserted.

meta.md contains `## Identifier`, a blank line, `- Page ID: <page_id>`, another
blank line, then the runner-rendered `## Source Code Signature`. Neither section
appears in utterances.md. Four entities return eight paths; no manifest is created.

## Replacement and errors

Pin directories with no-follow descriptors. Stage/fsync both complete files before
replacing either; use exclusive temporary files and atomic replacement per file.
No locks, duplicate confirmation or recovery journal. Last replacement wins per
file, regardless of request start order. Pairs/entities can mix versions after
concurrent same-page runs or interruptions. Retry the complete input with a fresh
timestamp. No rollback, stale-entity removal, legacy migration or automatic deletion.
Old flat page files and earlier utterances.md layouts remain untouched.

Use the shared six-field result; output_format=markdown. Success metadata contains
page_id, indexed_at, last_validated_at, total_utterances, skipped_utterances=0.
Failure has null output; affected_paths lists known replaced files after partial
failure. Codes: invalid_input, invalid_page_id, invalid_url, page_id_mismatch,
invalid_context, invalid_date, output_write_error. Runner failures remain separate.
