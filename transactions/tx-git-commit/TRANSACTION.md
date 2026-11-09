# tx-git-commit

- Name: tx-git-commit
- Description: Commit generated data and push the checked-out branch to the same remote branch name.
- Entry point: `transactions/.venv/bin/python -B transactions/runner.py --transaction tx-git-commit --input '{}'`
- Instructions: [AGENTS.md](AGENTS.md)
- Data directory: data/articles/, data/index/, and data/queries/ (Git write scope)

Supply an empty object as inline JSON. An optional string `message` is
accepted and discarded. The commit message is the local date in `dd-mm-yy` format.
The Git path
accepts only `--transaction` and `--input`.
The runner prints a JSON result and exits nonzero on error. A successful
no-op has a null commit and pushed=false. A push retry can succeed with a
null commit and pushed=true when an earlier run created the commit.
