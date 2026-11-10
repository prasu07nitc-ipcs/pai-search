# tx-git-commit

- Name: tx-git-commit
- Description: Commit selected data files and push the existing paired data branch.
- Entry point: `transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '{"file_paths":["data/queries/example.md"],"commit_message":"Save query"}'`
- Instructions: [AGENTS.md](AGENTS.md)
- Data directory: data/articles/, data/index/, and data/queries/ (Git write scope)

Supply inline JSON with exactly `file_paths` and `commit_message`. Paths must
be unique, literal repository-relative paths to regular, unaliased files in the
allowed directories. Include all paths touched by pending commits when retrying
a push. An empty list is valid when there are no pending file changes.
The message must be a nonblank UTF-8 string without NUL characters.

The runner accepts only `--transaction` and `--input`. If the local paired
branch is missing, it names the branch and stops before contacting the remote.

The runner prints JSON and exits nonzero on error. Successful results identify
`branch`, `remote`, and `verified_file_paths`. The result includes the new
`commit` ID if one was created, whether a push completed in `pushed`, and
`page_ids` for article and index files changed by the new commit.
