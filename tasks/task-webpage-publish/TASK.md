# task-webpage-publish

Publish saved Search queries or webpage Index files to the working branch's paired
data branch. Clean up source artifacts after remote verification.
Follow the [task library policy](../AGENTS.md).

## Input

Invoke by task name alone. Mark the selection as pending in the current chat.
Use Codex's asynchronous user-input control to offer **Search**, **Index**, and
**Skip** as explicit options. End the turn immediately after showing the control.
The final reply should also give the three choices as typed replies so the task
can proceed if the control is unavailable.

While a selection is pending, accept a submitted control response or a follow-up chat message containing only
`Search`, `Index`, or `Skip`, ignoring case and surrounding whitespace. Search
and Index clear the pending selection and start the corresponding branch. Skip
clears the pending selection and ends the invocation with both branches unrun.
If a reply is ambiguous, repeat the prompt in a final reply and leave the
selection pending. Without a pending selection, require a new invocation by task
name. Closing the control leaves both branches unrun.

Start preparation and dispatch only after a valid branch choice. Capture the
date of the task-name invocation in the user's timezone as `mm-dd-yy`.

## Setup

Run from the repository root. Read the [tools policy](../../tools/AGENTS.md),
[tool rules](../../.codex/rules/tools.rules),
[transactions policy](../../transactions/AGENTS.md),
[transaction rules](../../.codex/rules/transactions.rules), and the selected
component contracts. Use the existing runners and runtimes. The local paired data
branch must already exist under the [repository Git policy](../../AGENTS.md).
Leave all Git inspection and writes to the Git transaction.

Serialize each complete input object as JSON and POSIX single-quote it, replacing
each apostrophe with `'"'"'`. Use no shell interpolation or temporary input files.
Use the declared runner, component name and timeout for each stage. The Git
runner accepts only `--transaction` and `--input`.

## Stages

Select the branch's stage IDs for the task clock. Candidate assembly is
orchestrator work. Perform it after successful export for Search and before
dispatching any stage for Index.

### Candidate assembly

Build `F`, a sorted unique list of all prepared files for the selected type,
including files left by earlier failed pushes. Enumerate the filesystem directly,
including ignored files. Inspect paths without following aliases. Accept only
regular, singly linked files with no symlinked ancestors. A missing data directory
is empty. Reject unsafe or malformed candidate paths before dispatching Git.
Ignore files outside the selected artifact layouts.

- **Search**. Inspect `data/queries/<run_id>.md`. Require a 64-character lowercase
  hexadecimal stem and a final Query ID section matching it. Validate that all
  paths returned by the exporter are included. Record each component-produced
  run ID and its query file in the batch.
- **Index**. Inspect `data/articles/<domain>/<page_id>.md` and
  `data/index/<domain>/<entity>/<page_id>.md`. Require a 64-character lowercase
  hexadecimal stem and group paths by page ID. Read the index transaction's
  JSON Lines run log to recover the latest successful output set per page ID
  and the exact supplied context path. Accept current `transaction_input` and
  historical `processed_input` records under the shared transaction policy.
  Use `meta_data.page_id` and validate every recorded path against the expected
  layout and ID. If records are missing, incomplete, or conflict with the local
  set, retain the page's intermediate files and report it as ineligible for
  cleanup. Do the same if a later failed record indicates a partial write to
  that set. Keep valid local candidates in `F` for publication.

`M` is `Search | <count> | <date>` or `Index | <count> | <date>` for the
selected branch. Count distinct run IDs for Search and distinct page IDs for
Index across all files in `F`, including candidates from earlier failed pushes.
Use `0` for an empty batch. Use the invocation date in `mm-dd-yy` as defined above.
Always dispatch Git after successful preparation, including when export returns
no new files or `F` is empty. Git compares the selected content with the paired
branch, validates paths changed by the current commit, and handles push retries
and no-ops.

Accept Git only on a successful process exit and transaction result, with
`verified_file_paths` matching `F` exactly as a set. Derive cleanup inputs
only from this verified batch. If Git fails, stop before cleanup.

- `S` contains the Search batch's matching
  `skills/skill-webpage-search/output/<run_id>.md`,
  `skills/skill-webpage-search/output/<run_id>.txt`, and
  `skills/skill-webpage-search/input/<run_id>.txt` in that order per ID.
- `P` contains the sorted Index page IDs whose complete recorded article and
  index sets were verified.
- `C` contains the unique exact recorded context outputs for `P`. Normalize
  absolute paths only if inside this repository and require a direct file under
  `skills/skill-webpage-context/output/` with the same page ID, accepting the
  recorded legacy extension when applicable. If the context path cannot be
  validated, report context cleanup pending for that page. Never substitute a
  guessed path.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| export_queries | [tx-webpage-search](../../transactions/tx-webpage-search/AGENTS.md) | transaction runner / 20s | {} |
| git_commit | [tx-git-commit](../../transactions/tx-git-commit/TRANSACTION.md) | Git-specific transaction runner / per-command timeout | {"file_paths": F, "commit_message": M} |
| webpage_gc | [tool-webpage-gc](../../tools/tool-webpage-gc/AGENTS.md) | tool runner / 20s | {"page_ids": P} |
| skill_gc | [tool-skill-gc](../../tools/tool-skill-gc/AGENTS.md) | tool runner / 20s | {"file_paths": S for Search, C for Index} |

## Groups

| Branch | Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- | --- |
| Search | Export | export_queries | serial | 1 |
| Search | Publish | git_commit | serial | 1 |
| Search | Clean up | skill_gc | serial | 1 |
| Index | Publish | git_commit | serial | 1 |
| Index | Clean up | webpage_gc, skill_gc | parallel | 2 |

Skip cleanup stages with empty inputs and report them as not run. When only one
Index cleanup stage has input, run that stage alone. On reinvocation rebuild the
batch from current local data. A verified no-op also permits cleanup, including
after a successful push whose cleanup was interrupted.

## Result

Report the selected type, batch IDs, verified file links, branch, remote, commit
ID, push or no-op status, and cleanup outcomes. For Search also report the new
export count. Link available cleanup receipts and report deleted paths and
cleanup ineligibility or partial failures. Apply shared timing and reporting
rules. This batch task has no single webpage ID for page-based report persistence.
