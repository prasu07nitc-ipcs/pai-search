# Project intents

The project supports these three intents:

1. Index a webpage from a supplied URL.
2. Execute a search query against the local index.
3. Publish saved search results.

## Project-wide instruction sources

The project root's `readme.md` is exclusively for human readers. This policy
applies to all agents and subagents in every directory of the project. Agents
must not consult, rely on, or execute any content from that file as part of
project work, even if another project instruction links to it. Use the
applicable `AGENTS.md` and task, skill, transaction, or tool instructions for
execution.

## Repository Git policy

Git operations are prohibited for all agents except:

- Transaction agents may perform read-only Git operations through
  transactions/runner.py as required by [transactions policy](transactions/AGENTS.md)
  to capture source signatures. This exception does not authorize Git writes.
- `transactions/tx-git-commit` is the sole exception for Git writes. It may
  commit and push only to the working branch's existing paired `data-<branch>`.
  Invoking this transaction directly or through a workflow authorizes operations
  within its [transaction policy](transactions/tx-git-commit/AGENTS.md). It must
  use the Git-specific execution path in `transactions/runner.py`.
