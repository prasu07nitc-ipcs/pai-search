Name: tool-url-validate

Description: Extract the first structurally valid absolute HTTP(S) URL from raw text without fetching or resolving it. Save the extracted URL as plain text for downstream processing. Use as a URL validation gate before webpage tools.

Entry point: `tool.py:validate_url(raw_input: str) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
