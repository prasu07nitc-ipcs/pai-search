Name: tool-webpage-markdown

Description: Extract the main content of a public HTTP(S) webpage as reader-style Markdown using Trafilatura and write Markdown directly to output/output.txt. Return its path relative to tools/ and output_format markdown. Use for clean article content, preserving supported formatting, links, tables, and image references, with balanced, precision, recall, or comparison modes.

Entry point: `tool.py:extract_markdown(url: str, raw_input: str, mode: Literal["balanced", "precision", "recall", "compare"] = "balanced", include_images: bool = True, include_links: bool = True, include_tables: bool = True) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
