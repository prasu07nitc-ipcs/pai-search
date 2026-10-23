Name: tx-bookmark

Description: Accept a caller-supplied page metadata JSON object and format its metadata as an agent-readable Markdown bookmark stored by hostname and page ID in data/bookmark/. Use to create or replace persistent bookmarks without fetching webpages.

Entry point: `transaction.py:bookmark(page: dict) -> dict`

Public input: Flat page metadata JSON object, without raw_input or a page wrapper.

Instructions: [AGENTS.md](AGENTS.md)

Data directory: data/bookmark/
