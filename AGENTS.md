# Repository Git policy

Git operations are prohibited for all agents except:

- Transaction agents may perform read-only Git operations through
  transactions/runner.py as required by [transactions policy](transactions/AGENTS.md)
  to capture source signatures. This exception does not authorize Git writes.
- [data/tx-commit-and-push](data/tx-commit-and-push/AGENTS.md) may perform Git
  operations exclusively through data/runner.py according to its instructions.
