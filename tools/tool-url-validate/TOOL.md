Name: tool-url-validate

Description: Extract the first structurally valid absolute HTTP(S) URL from raw text without fetching or resolving it. Save JSON containing the exact extracted url and its SHA-256 page_id for downstream processing. Use as a URL validation gate before webpage tools.

Entry point: `tool.py:validate_url(raw_input: str) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
