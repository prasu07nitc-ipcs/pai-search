# tx-git-commit

- Name: tx-git-commit
- Description: Commit generated data and push the checked-out branch to the same remote branch name.
- Entry point: `transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '{"message":"Update generated data"}'`
- Instructions: [AGENTS.md](AGENTS.md)
- Data directory: data/articles/, data/index/, and data/queries/ (Git write scope)

Supply exactly one string field, `message`, as inline JSON. The Git path
accepts only `--transaction` and `--input`.
The runner prints a JSON result and exits nonzero on error. A successful
no-op has a null commit and pushed=false. A push retry can succeed with a
null commit and pushed=true when an earlier run created the commit.
