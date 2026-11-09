# tx-git-commit

- Name: tx-git-commit
- Description: Commit selected generated data files and push the checked-out branch to the same remote branch name.
- Entry point: `transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '{"file_paths":["data/queries/example.md"]}'`
- Instructions: [AGENTS.md](AGENTS.md)
- Data directory: data/articles/, data/index/, and data/queries/ (Git write scope)

Supply an inline JSON object with exactly one field, `file_paths`. It must
contain a nonempty list of unique repository-relative file paths under
`data/articles/`, `data/index/`, or `data/queries/`. Paths are literal.
Existing regular files and tracked deletions are accepted. The new commit
includes only changes to these paths. The commit message is the local date
in `dd-mm-yy` format.
The Git path
accepts only `--transaction` and `--input`.
The runner prints a JSON result and exits nonzero on error. A successful
no-op has a null commit and pushed=false. A push retry can succeed with a
null commit and pushed=true when an earlier run created the commit.
The result includes `page_ids` from added or modified article and index files
in the newly created commit.
