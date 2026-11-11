# tx-git-commit

Follow the [repository Git policy](../../AGENTS.md) and the
[transaction contract](TRANSACTION.md). Use the Git-specific path in the common
runner and the existing transaction virtual environment from the repository root.
Git commands time out individually after 60 seconds.

Resolve the paired `data-<branch>` from the checked-out working branch. Use the
working branch's configured remote, otherwise origin or the sole remote. Resolve
a single push destination and use that destination for inspection and pushes.
Require a named working branch and an existing paired branch both locally and
at the push destination. For `check_only`, report both checks and return before
any writes. Reject a
paired branch checked out in another worktree. Use a private index, preserve the
working checkout and its index, and use git-config.json for commit identity.

Require an explicit caller-supplied `file_paths` list. The permitted directories
are `data/articles/`, `data/index/`, and `data/queries/`. Compare the new commit
with its parent and reject any changed path outside the supplied list. Existing
branch files and earlier commits are outside this path check.

Update the local paired ref with its expected previous value. Use a normal push
so Git rejects non-fast-forward updates, then verify the advertised tip. A failed
push may leave a local commit for a later invocation to push.
