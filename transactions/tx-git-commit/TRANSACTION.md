# tx-git-commit

- Name: tx-git-commit
- Description: Commit selected data files and push the existing paired data branch.
- Entry point: `transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '{"file_paths":["data/queries/example.md"],"commit_message":"Save query"}'`
- Instructions: [AGENTS.md](AGENTS.md)
- Data directory: data/articles/, data/index/, and data/queries/ (Git write scope)

Supply inline JSON with exactly `file_paths` and `commit_message`. Paths must
be unique, literal repository-relative paths to regular, unaliased files in the
allowed directories. An empty list is valid when there are no files to commit.
The message must be a nonblank UTF-8 string without NUL characters.

The runner accepts only `--transaction` and `--input`. For read-only setup
validation, supply `{"check_only":true}` instead of the commit input. The result
reports the branch, remote, and whether the branch exists locally and at the
push destination. Both branches must exist for validation to succeed.
Publishing also checks for both branches before making changes.

The runner prints JSON and exits nonzero on error. Successful results identify
`branch`, `remote`, and `verified_file_paths`. The result includes the new
`commit` ID if one was created, whether a push completed in `pushed`, and
`page_ids` for article and index files changed by the new commit.
