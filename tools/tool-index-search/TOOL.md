Name: tool-index-search

Description: Search local bookmarks using a query requirement file's candidate domains, phrases and entities; return matching pages, ranked entities and indexed utterances. Exact entity matching by default; optional conservative fuzzy matching.

Entry point: `tool.py:search_bookmarks(raw_input: str, entity_match: str = "exact", fuzzy_threshold: float = 95.0) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
