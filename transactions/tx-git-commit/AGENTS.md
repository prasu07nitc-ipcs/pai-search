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
Force-add ignored files only within the three allowed directories.
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
new commit. Query filenames identify queries. After pushing the new commit,
run [tool-webpage-gc](../../tools/tool-webpage-gc/TOOL.md) through its shared
runner and environment with the same list. Each newly pushed commit requests
fresh cleanup. Skip cleanup for empty lists and push-only retries. If cleanup
fails, preserve the commit ID, push status, and page IDs in the result so the
same list can be supplied directly to the cleanup tool after a successful push.
Use the checkout machine's local date in dd-mm-yy format as the entire
commit message. Discard any supplied message text.
Git commands time out individually after 60 seconds. After a timeout, check
the checkout and remote before retrying because the operation may have completed.
