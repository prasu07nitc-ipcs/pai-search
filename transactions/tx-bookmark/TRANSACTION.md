Name: tx-bookmark

Description: Read same-project tool-webpage-og-crawler output JSON and format its metadata as an agent-readable Markdown bookmark stored by hostname and page ID in data/bookmark/. Use to create or replace persistent bookmarks without fetching webpages.

Entry point: `transaction.py:bookmark(page_file: str, raw_input: str) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Data directory: data/bookmark/

## Source Code Signature

Bookmark Markdown ends with `## Source Code Signature`, containing Git repository URL,
Git branch, full Git commit SHA, and Local changes. The parent runner captures this
snapshot immediately before launching the worker and supplies it through runner-owned
`PROJECT_TRANSACTION_SOURCE_SIGNATURE` JSON configuration, never caller arguments.
The repository is resolved from the selected transaction directory. The origin URL is
converted from SSH to HTTPS where possible and stripped of credentials, query, fragment,
and trailing .git. No repository-name field is included. Missing remote URLs use
`Unavailable`; detached branches use `Detached HEAD`. Outside Git all Git fields use
`Unavailable`. Git repositories without a resolvable HEAD or with failed snapshot commands
fail execution rather than falsely report a clean snapshot.

Local changes include only the selected transaction directory, staged, unstaged, and
untracked files, excluding Git-ignored files (including tracked files matching current
ignore rules). Paths are repository-relative; entries retain Git porcelain two-column
status codes (index then working tree; `.` represents an unchanged column; `??` means untracked). Renames appear as deletion
and addition. Empty changes render `- Local changes: None`. Changes elsewhere, including
the shared runner, are excluded. This snapshot lists paths and statuses, not file contents
or diffs, and does not guarantee an atomic snapshot against concurrent source edits.
The public six-field result, inputs, metadata, and output path remain unchanged.
