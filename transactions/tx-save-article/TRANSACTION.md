Name: tx-save-article

Description: Validate the input files belong to the tool-webpage-og-crawler and skill-article-writer output folders, then read their JSON page_id and Markdown, verify the SHA-256 identity of a Markdown article's linked title URL, append its source page ID, and atomically save it in data/articles/<domain_with_underscores>/<page_id>.md. Saving here means local persistence.

Entry point: `transaction.py:save_article(page_id_file: str, article_file: str, raw_input: str) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Data directory: data/articles/
