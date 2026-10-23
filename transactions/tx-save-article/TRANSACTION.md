Name: tx-save-article

Description: Read a supplied Markdown article file from any absolute or repository-relative path, verify its linked title URL against the supplied page_id, save article.md and meta.md under data/articles/<domain>/<page_id>/. Metadata contains references, source page ID, and the source code signature; each file is replaced atomically. Saving here means local persistence.

Entry point: `transaction.py:save_article(page_id: str, article_file: str) -> dict`

Instructions: [AGENTS.md](AGENTS.md)

Data directory: data/articles/
