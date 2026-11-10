# tx-git-commit

Follow the [repository Git policy](../../AGENTS.md) and the
[transaction contract](TRANSACTION.md). Use the Git-specific path in the common
runner and the existing transaction virtual environment from the repository root.
Git commands time out individually after 60 seconds.

Resolve the paired `data-<branch>` from the checked-out working branch. Use the
working branch's configured remote, otherwise origin or the sole remote. Resolve
a single push destination and use that destination for inspection and pushes.
Require a full checkout and a named working branch. Use the first commit on the
remote main branch's first-parent history as the seed.

Require an existing local paired branch and reject it if checked out in another
worktree. Use a private index, preserve the working checkout and its index, and
use git-config.json for commit identity. If the seed contains non-data files,
verify that the first paired-branch commit is its direct child and removes only
those inherited files.

Require an explicit caller-supplied `file_paths` list. The permitted directories
are `data/articles/`, `data/index/`, and `data/queries/`. Commit only supplied
files. Reject outgoing commits that touch any unlisted path after the verified
remote tip or, for the first push, after the verified branch baseline.

Validate selected paths and every outgoing commit after the remote tip or, for
a new remote branch, after the verified setup baseline. Reject remote divergence. Commit only supplied file content and update the
local paired ref with its expected previous value. Push with a lease against
the observed remote tip and verify the advertised tip after publication.
A failed push may leave a local commit. Retry with a list covering all paths touched by pending commits.
