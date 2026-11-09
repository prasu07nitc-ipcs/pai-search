# Repository Git policy

Git operations are prohibited for all agents except:

- Transaction agents may perform read-only Git operations through
  transactions/runner.py as required by [transactions policy](transactions/AGENTS.md)
  to capture source signatures. This exception does not authorize Git writes.
- `transactions/tx-git-commit` is the sole exception for Git writes. It may
  commit on any branch while that branch is checked out and push it to the
  same branch name on the remote. It must use its own policy and the
  Git-specific execution path in `transactions/runner.py`.
  Commits and outgoing history are scoped to `data/articles/`, `data/index/`,
  and `data/queries/`.
