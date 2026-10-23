Name: tx-save-article

Description: Read metadata JSON and Markdown, verify both URL hashes and save the article locally.

Entry point: `transaction.py:save_article(page_id: str, meta_data_file_path: str, context_file_path: str | None, article_file_path: str) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Data directory: data/articles/
