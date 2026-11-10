Name: tool-webpage-markdown

Description: Accept a URL and its independently validated SHA-256 page_id. Extract the main content of a public HTTP(S) webpage as reader-style Markdown using Trafilatura and write Markdown directly to output/<page_id>.md. Return its path relative to tools/ and output_format markdown. Use for clean article content, preserving supported formatting and tables, with links rendered as plain text and images excluded, with balanced, precision, recall, or comparison modes.

Entry point: `tool.py:extract_markdown(url: str, page_id: str, mode: Literal["balanced", "precision", "recall", "compare"] = "balanced", include_images: Literal[False] = False, include_links: Literal[False] = False, include_tables: bool = True) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
