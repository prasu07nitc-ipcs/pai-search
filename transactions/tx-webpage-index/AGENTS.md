# tx-webpage-index

Follow the [shared transaction policy](../AGENTS.md). Call
`index_webpage(context_file_path: str, article_file_path: str)` with exactly
two paths. The first is `skills/skill-webpage-context/output/<page_id>.json`.
The second is the encoder's article input,
`tools/tool-webpage-article/output/<page_id>.md`. Accept absolute or
repository-relative paths. Apply shared file safety checks.

Validate matching lowercase SHA-256 filename IDs against the article footer's
`page_id` and exact HTTP(S) `requested_url`. For historical articles without
`requested_url`, use `url`. Read `dateModified` from the same footer.
Use its ISO timestamp, preserving its offset and defaulting naive times to
Asia/Kolkata. Display “Not provided” when the modification date is unavailable.
Reject malformed dates. Contexts follow the four-field encoder schema with
consecutive sequences from 1. Accept and ignore the additional Boolean
`named_entity` field in historical inputs. An empty array saves the article alone.

Write the input article verbatim to `data/articles/<domain>/<page_id>.md`.
Write one file per distinct entity to
`data/index/<domain>/<normalized_entity>/<page_id>.md`. Derive the domain from the identity URL using the shared URL rules. Lowercase the entity and replace each character
outside ASCII a–z and 0–9 with an underscore. Reject normalized names longer
than 255 characters and collisions between distinct entity names.

Each entity file starts with its original entity name as a Markdown H1.
Write one block per utterance in input order with the original sequence and
the total across the input array. Render each entry's category in its own block,
so the same entity file can contain different categories.
Indent continuation lines four spaces.

```markdown
## Sequence: **2/13**
- Utterance: <utterance>
- Entity Category: <entity_category>
- Indexed At: <Asia/Kolkata runtime timestamp>
- Last Validated At: <article dateModified>
```

Stage all files before publishing. Return the article first, followed by entity
files in first-occurrence order. Writes are atomic per file. Report any known
partial replacements in `meta_data.affected_paths`. Duplicate runs may replace
the same files. Success metadata includes `page_id`, `indexed_at`,
`last_validated_at`, and `total_utterances`.
