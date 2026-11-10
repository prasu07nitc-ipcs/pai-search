# Project intents

Follow the workflows in the [root README](readme.md) for these three intents:

1. Index a webpage from a supplied URL.
2. Execute a search query against the local index.
3. Publish saved search results.

Project exploration, development, maintenance, and any other open-ended
project-related request are permitted only on a verified branch other than
`main`. For any request outside the three listed workflows, verify the
current checkout's branch before responding to or acting on that request.
Read the checkout's HEAD metadata directly without running Git commands.
If `.git` is a worktree pointer file, resolve its `gitdir` relative to
the checkout root when the path is relative, then read that directory's
`HEAD`. A symbolic reference under `refs/heads/` identifies the branch.

On `main`, serve only the three listed workflows. For any other request,
ask the user to switch to a non-main branch or limit the request to the
three workflows, then stop. If HEAD is detached or the branch cannot be
verified, apply the same restriction. This restriction also applies to
mixed requests that combine a listed workflow with an open-ended intent.

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
