# tx-commit-and-push

Sole role authorized to perform repository Git operations, exclusively through
`data/runner.py`. Run in the active chat from the parent repository root; do not
create another chat. Implementation or setup requests never authorize Git effects.
Read `.codex/rules/data.rules` once per chat; reread instructions when changed.
Requires macOS, Python 3.11+, and the existing `data/.venv`. No runtime installation,
dependency changes, direct worker invocation, Git commands, or API/UI bypass.

## Public contract

Input is exactly `{page_id, files, message}`. The component owns configuration,
approval, state refresh, execution and result acceptance; callers supply no internal
Git fields. Do not discover files or expand directories.

- `page_id`: 64 lowercase hexadecimal characters.
- `files`: unique, nonempty data-relative paths shaped `<folders>/<page_id>/<file>`.
  Require a folder before the exact ID directory and a file below it. Regular,
  unaliased sources only; missing paths must be tracked deletions on the target/base.
  Reject traversal, absolute paths, hidden components, controls, backslashes,
  logs/receipts/credentials/__pycache__, .key/.pem and runtime/tooling paths.
- `message`: nonblank string without NUL; preserve it and the supplied file list.

Return exactly `{input, output, output_format, status, error, meta_data}` with
`input` equal to the original public request. Forward the accepted runner's other
five fields unchanged. `output_format` is `json`; `status` is `ok` or `error`.
Success has `error=null` and one data-relative receipt path. Failure has
`output=null` and `error={code,message}`. Inspect status even when process exit is 0.
Do not echo file contents or internal JSON unless requested.

Before dispatch, decline yields `authorization_declined`; unavailable approval yields
`authorization_required`. Other setup failures preserve their reported code. Include
a concrete remedy and `meta_data={committed:false,pushed:false,push_attempted:false}`.
After dispatch, preserve known effects; absent output means uncertain state, never
proof of no effects. Failure does not roll back.

## Configuration and approval

`git-config.json` is the only settings source. Exactly five keys are required:
`author_name`, `author_email`, `branch`, `remote_url`, `create_branch`.
No environment, local/global/system Git config, CLI branch selection, chat defaults
or inline overrides may supply these settings. Edit the file to change them.
Author fields may be null during setup, but commits require nonblank values without
NUL, CR, LF or angle brackets. Branch must be data-dev, data-test or data-prod;
remote must be `git@github.com:<owner>/<repo>.git`; creation policy is boolean.
The runner rejects missing/malformed files, aliases, extra keys and conflicting inputs.
Repository origin is read only to validate the configured remote.

Inspect settings and live local branch state:

```sh
data/.venv/bin/python -B data/runner.py --inspect-settings
```

Inspection does not fetch or certify remote state. Present repository, configured
remote/branch/author/creation policy and current target SHA in one approval request.
Ask directly through an available native form or grouped chat prompt. No default
selection or silence grants permission. Existing target: use its refreshed SHA,
`create_branch=false`, `base_commit=null`. Missing target: require configured creation
permission and explicit approval of a full existing base SHA; never infer it from HEAD.

Offer approval for this invocation, or subsequent webpage-index commit-and-push runs
in this chat. Session approval covers only the canonical repository, configured
settings, webpage-index files beneath each supplied page ID and message
`data: index webpage <page_id>`. Other messages/actions need separate approval.
Store authorization only in chat memory. Revocation, changed settings/scope, a new
chat or lost approval context requires fresh approval. One-run approval is consumed
on dispatch, including failure. Branch disappearance or a changed creation base
requires fresh creation approval.

Immediately before dispatch, inspect again and compare settings with approved scope.
Use the refreshed expected_head; do not ask again solely because an existing branch
advanced. Never automatically refresh/retry a compare-and-swap failure.

## Dispatch

Build exactly these internal fields; public input values remain unchanged:

| Field | Value |
| --- | --- |
| action | `commit-and-push` |
| page_id, files, message | Original public inputs |
| branch, remote_url, author_name, author_email | Approved configuration |
| expected_head | Refreshed target SHA, or null for approved creation |
| create_branch | false for existing target; true for approved missing target |
| base_commit | null for existing target; approved full SHA for creation |

```sh
data/.venv/bin/python -B data/runner.py --input '<complete JSON>'
```

Use POSIX single-quote escaping, including embedded apostrophes. Default worker
timeout is 20 seconds; approval interaction is outside it. The runner also accepts
`--timeout` (>0, <=300 finite seconds) and `--rerun` only after explicit approval
and reconciliation of an identical successful input. No automatic retries.

Internal recovery actions require separate explicit authorization: `commit` uses
remote_url=null; `push` requires files=[], message/author fields=null, an existing
target SHA and base_commit=null. All actions retain the configured branch; supplied
settings must match the file. Omitted branch resolves from configuration and omitted
create_branch is false. The public operation remains commit-and-push.

## Execution guarantees and limits

The worker validates the primary repository, safe local config, origin, target and
paths. Reject nested/linked repositories, shallow/alternate history, metadata aliases,
active operations and checked-out commit targets in any registered worktree.
A private index starts from the target/base and stages only explicit files, including
ignored outputs. Compare-and-swap advances the target; working files, HEAD and normal
index stay unchanged. External writers can race; observed checkout changes stop push.
Do not force-push, switch branches, reset, stash, roll back or remove others' locks.

Sandboxing precedes component import. Commit-only denies network; pushing permits
outbound access. Push uses the fixed `ssh.py` transport, a previously authorized key
in an accessible SSH agent and verified GitHub known_hosts. No key loading/generation,
SSH configuration changes, host-key acceptance, credential fallback or prompts.
Dependencies remain pinned in `data/requirements.txt`; no install/repair during a run.

## Results and recovery

The runner validates the six-field envelope and exact regular, unaliased receipt,
including equality of receipt input/effects with the returned result. Accept success
only after these checks. Receipt path is
`tx-commit-and-push/receipts/<run_id>.json`; run_id is SHA-256 of UTF-8
`json.dumps(internal_input,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)`.
Default expansion happens before hashing. File order is preserved. Commits use real
execution timestamps, so repeat execution does not promise the same commit SHA.

After target validation metadata records branch, previous_head, commit_sha,
committed, pushed, push_attempted, staged_paths and remote_url. Additional fields
report creation, candidate SHA, checkout preservation and uncertainty. staged_paths
are parent-relative `data/` paths. Preserve all metadata; do not infer omitted effects.
Failed push can leave a local commit and uncertain remote state; reconcile before a
separately approved recovery. Timeout or missing worker output requires reconciliation
of repository/index/remote. Never automatically delete leftover locks or temp files.

Audit/receipt failures do not undo Git effects. Audit failures retain known effects,
mark audit_incomplete and may include saved_receipts/operation_error. Logs append
with fsync but are not transactional with Git or receipts; do not repair history tails
automatically. Report the original error, known effects and receipt when available.
