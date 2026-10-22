Name: tool-webpage-og-crawler

Description: Fetch a public HTTP or HTTPS webpage and return six Open Graph properties (including og:type), article:section, keywords, datePublished, dateModified, and page_id (SHA-256 of the output url, or null) as JSON text in output/<run_id>.txt. Use when inspecting a link's social preview metadata, keywords, publication and modification dates, or URL identifier.

Dates are normalized to timezone-aware ISO 8601; missing time uses midnight UTC.
Assumptions and invalid/ambiguous date diagnostics are recorded in meta_data.

Entry point: `tool.py:crawl_open_graph(url: str, raw_input: str) -> CrawlResult`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
