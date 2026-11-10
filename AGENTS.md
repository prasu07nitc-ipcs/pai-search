# Project intents

Follow the workflows in the [root README](readme.md) for these three intents:

1. Index a webpage from a supplied URL.
2. Execute a search query against the local index.
3. Publish saved search results.

## Repository Git policy

Git operations are prohibited for all agents except:

- Transaction agents may perform read-only Git operations through
  transactions/runner.py as required by [transactions policy](transactions/AGENTS.md)
  to capture source signatures. This exception does not authorize Git writes.
- `transactions/tx-git-commit` is the sole exception for Git writes. It may
  commit on any branch while that branch is checked out and push it to the
  same branch name on the remote. Invoking this transaction directly or
  invoking a workflow that includes it authorizes both the scoped commit and
  push without separate project confirmation. It must use its own policy and the
  Git-specific execution path in `transactions/runner.py`.
  Commits and outgoing history are scoped to `data/articles/`, `data/index/`,
  and `data/queries/`.
