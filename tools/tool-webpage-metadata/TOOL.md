Name: tool-webpage-metadata

Description: Fetch a public HTTP or HTTPS webpage and return six Open Graph properties (including og:type), article:section, keywords, datePublished, dateModified, and page_id (validated SHA-256 of the input url, preserved unchanged) as JSON text in output/<page_id>.json. Use when inspecting a link's social preview metadata, keywords, publication and modification dates, or URL identifier.

Dates are normalized to timezone-aware ISO 8601; missing time uses midnight UTC.
Assumptions and invalid/ambiguous date diagnostics are recorded in meta_data.

Entry point: `tool.py:crawl_open_graph(url: str, page_id: str) -> CrawlResult`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
