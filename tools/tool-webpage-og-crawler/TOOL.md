Name: tool-webpage-og-crawler

Description: Fetch a public HTTP or HTTPS webpage and return five Open Graph properties, keywords, datePublished, and dateModified as JSON text in output/<run_id>.txt. Use when inspecting a link's social preview metadata, keywords, or publication and modification dates.

Entry point: `tool.py:crawl_open_graph(url: str, raw_input: str) -> CrawlResult`

Instructions: [AGENTS.md](AGENTS.md)

Output directory: output
