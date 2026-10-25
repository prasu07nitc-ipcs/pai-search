# tx-commit-and-push

Authoritative instructions and input/output contract for this agent. Use only the
parent repository through data/runner.py → commit.py:commit; ssh.py stays separate.
Only explicitly authorized Git operations are permitted. Implementation, dependency
approval and SSH setup do not authorize a commit or push.

## Execution

Run from the parent project root using the configured data/.venv, Python 3.11+ and
macOS. Read .codex/rules/data.rules; retain setup within the chat and reread changed
instructions rather than rediscovering interfaces from logs.

```sh
data/.venv/bin/python -B data/runner.py --input '<complete JSON object>'
```

POSIX single-quote JSON, escaping embedded apostrophes safely. Optional trailing
flags: --timeout (finite seconds, >0 and <=300; default 20), --rerun (explicit
confirmation to repeat identical successful input after reconciliation). No direct
component/--worker invocation, Git-write commands, API/UI bypass or transactions/
Git writes. No force, branch switching, reset/stash, rollback, automatic retry or
removal of someone else's locks. Read-only inspection is allowed.

Preserve working files, checked-out branch and normal staging. The worker scans
metadata aliases before sandboxing/import; component checks cover paths, repository,
config, origin and target. A private index starts from the target/base; commit-tree
creates the commit and compare-and-swap update-ref advances the target. Locks,
checkout snapshots and sandbox denials protect HEAD/index. Independent host writers
can race and are not controlled by agent policy; report observed changes and stop.

## Environment and SSH

Use isolated Python imports; only standard-library imports are currently used.
Approved optional Git/GitHub packages and their entire dependency closure are pinned
with hashes in ../requirements.txt. Additions, removals, upgrades, hash changes,
environment creation and installation require explicit authorization. Install only
approved wheels with --require-hashes --only-binary=:all:; never install, resolve or
repair during execution. Reject unlisted/mismatched installed packages; future
third-party imports also require installed-artifact verification. Dependency approval
grants no additional access.

The worker reads data/ and parent Git metadata, writes only permitted Git metadata
and owned receipts, and executes approved Git/SSH/runtime binaries. The parent owns
logs. Commits deny network; push permits outbound access, not a GitHub-only firewall.
These grants do not extend to transactions/.

Automatic/chat pushes require a repository-authorized key already loaded in an
accessible SSH agent and verified GitHub entry in ~/.ssh/known_hosts. No runner key
loading/generation, SSH edits, host-key acceptance or interactive setup. The generated
launcher uses /usr/bin/ssh for GitHub receive-pack, ignores user SSH config and
disables prompts, forwarding, proxies and host-key writes. No tokens, private-key
file reads, shell, credential helpers, hooks or signing. Authentication can fail after
a local commit; never fall back or retry automatically.

## Input


Exactly eleven required fields, finite JSON, no defaults/extras. SHA means a full
40-character lowercase hexadecimal commit ID. Files are relative to data/.

| Field | Type | Requirement |
| --- | --- | --- |
| action | string | commit, push, or commit-and-push |
| page_id | string | Exactly 64 lowercase hexadecimal characters; required for every action |
| files | string[] | Unique selected paths; nonempty for commits, [] for push |
| message | string/null | Nonblank Git commit message without NUL; null for push |
| branch | string | data-dev, data-test or data-prod; same remote branch |
| expected_head | string/null | Existing target SHA; null only for creation |
| remote_url | string/null | null for commit; otherwise git@github.com:<owner>/<repo>.git matching origin |
| author_name | string/null | Explicit nonblank author/committer name; null for push |
| author_email | string/null | Explicit nonblank author/committer email; null for push |
| create_branch | boolean | true explicitly authorizes creating a missing target |
| base_commit | string/null | Explicit existing starting SHA for creation; otherwise null |

Existing target: create_branch=false, expected_head=<target SHA>, base_commit=null.
Missing target: create_branch=true, expected_head=null, base_commit=<starting SHA>.
Creation requires a commit action and a still-absent target. Push-only requires an
existing target and null message/author fields. No unborn-repository bootstrap.
Author fields forbid NUL, CR, LF and angle brackets.

Commit targets cannot be checked out in any registered worktree; push-only can use
a checked-out target. Only the parent repository is accepted: no nested data/.git,
linked checkout, active merge/rebase/cherry-pick/revert/bisect, shallow/alternate history
or metadata aliases. Unrelated inherited application history remains unchanged.

Paths reject absolute/traversal/empty components, backslashes, controls, aliases,
hidden components, logs/receipts/credentials/__pycache__ components, .key/.pem files,
and runtime/tooling: commit/, tx-commit-and-push/, runner.py, requirements.txt,
AGENTS.md, README.md. Sources are regular unaliased files;
missing paths must be tracked deletions in the target/base. Git sees literal data/<path>.

Each selected path must have the form <folders>/<page_id>/<file or nested file>:
one or more folder components before an exact page_id directory, and a file below it.
Examples: bookmark/<page_id>/meta.md, articles/domain/<page_id>/article.md,
index/category/domain/<page_id>/nested/context.md. Substrings and matching filenames
do not qualify. Mixed page IDs are rejected before Git effects; no automatic discovery
or directory expansion. Push-only keeps files=[]; page_id labels the request and
does not filter or certify the contents/history of the explicit SHA being pushed.

Local Git config accepts only core.{repositoryformatversion,filemode,bare,
logallrefupdates,ignorecase,precomposeunicode}, user.{name,email}, remote.origin.{url,
fetch}, and branch.<name>.{remote,merge,vscode-merge-base}. Branch-name matching uses
[A-Za-z0-9._/-]+. VS Code metadata is ignored; ambiguous multiple origin URLs fail.
Push normalizes GitHub HTTPS/ssh:// origins for repository comparison but uses SSH.

## Output

Exactly six top-level fields; valid handled failures can exit 0. Always inspect status.
Report concise status, target/SHA, receipt or original error and known partial effects.
Do not echo file contents or full input/output JSON unless requested.

| Field | Requirement |
| --- | --- |
| input | Complete supplied eleven-field object, directly |
| output | Success: ["tx-commit-and-push/receipts/<run_id>.json"] relative to data/; failure: null |
| output_format | json |
| status | ok or error |
| error | null on success; otherwise exactly {code:nonempty string,message:nonempty string} |
| meta_data | Available effect/progress fields; may be empty before target validation |

run_id is SHA-256 of UTF-8 json.dumps(input, sort_keys=True, separators=(",", ":"),
ensure_ascii=False, allow_nan=False). A receipt contains {input:<supplied input>,
...meta_data}, never file contents or credentials. Logs are agent-local, append-only;
historical records/old receipt paths remain unchanged.

After target validation metadata includes branch, previous_head, commit_sha,
committed, pushed, push_attempted, staged_paths and remote_url. Commit progress can
add commit_attempted, candidate_commit_sha, base_commit, branch_created,
checkout_preserved, index_updated=false. staged_paths use parent-relative data/ paths.
Push progress adds remote_state_uncertain=true, cleared after reported success.
Push-only returns committed=false, requested commit_sha and staged_paths=[].

Failure is not rollback. A failed push may have committed=true and uncertain remote
state; reconcile before a separately authorized push-only recovery. Concurrent external
changes after a commit set checkout_preserved=false and stop push. Worker failure or
timeout reports repository_state_uncertain/remote_state_uncertain when effects are
unknown. Termination may leave locks/temp files; never auto-delete stale locks.

Audit append failure returns audit_write_failed with known effects retained,
audit_incomplete=true and available saved_receipts/operation_error. Diagnostic-log
failure also marks audit_incomplete. Receipt failure does not undo Git effects.
Invalid CLI/input/runtime/storage or corrupt history rejected before invocation can
exit nonzero without JSON. Process termination can prevent any result; missing output
never proves that Git state is unchanged. History appends are single writes with fsync,
not transactional with Git or receipts; partial tails are not automatically repaired.
