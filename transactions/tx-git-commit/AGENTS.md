# tx-git-commit

The [repository Git policy](../../AGENTS.md) authorizes this transaction.
Use the common transaction runner and existing virtual environment from
the root of the target checkout. It requires Python 3.11+ and Git.
It may read all of data/. Git commits and outgoing
history may touch only data/articles/, data/index/, and data/queries/.

Use the checked-out branch and
the same branch name on the remote. Use the branch's configured remote when
available, otherwise origin or the sole remote. Detached HEAD and a missing
repository or remote fail validation.
Stop before contacting the remote if Git reports any staged, unstaged, or
untracked path outside the three allowed directories. Recheck before staging.
Git-ignored untracked files are excluded from this check.
Require an explicit nonempty list of unique repository-relative file paths.
Reject directories, symlinked paths, traversal, and missing untracked files.
Treat paths literally. Stage and commit only the selected paths, including
selected ignored files and tracked deletions. Preserve other staged changes.
Use a full checkout with an existing local commit so the runner can validate
outgoing history.
An existing remote branch must be an ancestor of local HEAD. For a new remote
branch, history reachable from other advertised remote branches is excluded
from the scope check. On an empty remote, the check covers the entire local history.
The push requires the remote branch to still match the observed tip.

Use git-config.json for the commit identity. Do not switch branches or run
concurrent Git operations in the same checkout during execution. An error
after staging can leave eligible changes staged. If a commit was created,
the result reports its ID. Re-run the transaction to retry a push.
Report unique page IDs from added or modified article and index files in the
new commit. Query filenames identify queries.
Require a nonblank UTF-8 string in `commit_message`, without NUL characters.
Use the supplied message for any new commit.
Git commands time out individually after 60 seconds. After a timeout, check
the checkout and remote before retrying because the operation may have completed.
