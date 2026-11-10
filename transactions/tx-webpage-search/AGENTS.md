# tx-webpage-search

Follow the [shared transaction policy](../AGENTS.md). Call `export_searches()`
with the empty JSON object `{}`. Discover reports directly in
`skills/skill-webpage-search/output/`, without recursing.

Select filenames with a 64-character lowercase SHA-256 run ID and an `.md`
suffix. Ignore other names. Skip any run whose destination
already exists. Require each remaining report to
be a regular, unlinked UTF-8 file with nonempty Query, Response, Index Files
Analysed, Execution time, and Query ID sections in that order. Accept a trailing
colon on Index Files Analysed and Execution Time as an alternate capitalization.
The final Query ID must match the filename. Reject duplicate IDs and validate every pending report
before publication. Hold the destination directory lock from discovery through
publication so concurrent exports skip reports already written.

Export each selected report to `data/queries/<run_id>.md` with Query,
Entities, Webpages, Execution time, and Query ID sections. Under Entities, list
only entity headings from utterance citations in Response, omitting sequence
numbers and deduplicating in first-citation order. Under Webpages, list the
page IDs as links to their original URLs in first-reference order, deduplicated
by URL. Use the referenced article filename stem as the page ID. For each article
link in References, read the linked regular, unaliased file under
`data/articles/` and extract its `url` field from `## Meta Data`. Reject missing
or invalid references and URLs. Leave either list empty if it has no entries.
Omit the response prose, References, and the reviewed index files list.
Validate retained file paths as repository-relative paths under `data/`, rewriting
absolute paths within the repository's `data/` directory. Preserve web URLs.

The scan includes saved handled failures because the source scope contains
reports without execution statuses. Stage all destinations before replacing
any. Return output paths in run ID order and `meta_data.report_count` on
success. When no reports are missing, return success with an empty output
array and a report count of zero.
