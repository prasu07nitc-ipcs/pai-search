# tx-git-commit

The [repository Git policy](../../AGENTS.md) authorizes this transaction.
Use the common transaction runner and existing virtual environment from
the root of the target checkout. It requires Python 3.11+ and Git.
It may read all of data/. Git commits and outgoing
history may touch only data/articles/, data/index/, and data/queries/.

Run only when authorized to commit and push. Use the checked-out branch and
the same branch name on the remote. Use the branch's configured remote when
available, otherwise origin or the sole remote. Detached HEAD and a missing
repository or remote fail validation.
Stop before contacting the remote if Git reports any staged, unstaged, or
untracked path outside the three allowed directories. Recheck before staging.
Git-ignored untracked files are excluded from this check.
Use a full checkout with an existing local commit so the runner can validate
outgoing history.

Use git-config.json for the commit identity. Do not switch branches or run
concurrent Git operations in the same checkout during execution. An error
after staging can leave eligible changes staged. If a commit was created,
the result reports its ID. Re-run with the same message to retry a push.
