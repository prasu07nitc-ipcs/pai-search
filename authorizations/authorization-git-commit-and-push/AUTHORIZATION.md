Name: authorization-git-commit-and-push

Description: Obtain or reuse a chat-session grant for canonical webpage-index Git commit and push.

Entry point: `python3 -B authorizations/runner.py execute --task <task-name> --authorization authorization-git-commit-and-push` (repository root)

Instructions: [AGENTS.md](AGENTS.md)

## Defined permission

The executable source of these fixed terms is [authorization.py](authorization.py).
All terms are chosen at definition time; runtime has no overrides or scope selectors.

| Term | Permission |
| --- | --- |
| Consumer | data/tx-commit-and-push |
| Operation | commit-and-push |
| Repository | This project; absolute identity recorded at issuance |
| Remote | git@github.com:prasu07nitc-ipcs/pai-search.git |
| Branch | data-test; existing target only |
| Author | pai-search-agent; psa@sayujai.com |
| Branch creation / base | Prohibited / null |
| Pages | All valid webpage IDs |
| Files | Explicit data-relative bookmark/, index/ or articles/ paths shaped <root>/<folders>/<page_id>/<file> |
| Message | Exactly data: index webpage <page_id> |
| Duration | 86400 seconds (24 hours) from approval |
| Reuse | Repeated execution in the owning chat until expiry or revocation |
| Approval | All terms or none; no partial grants |
| Pending reservation | 900 seconds (15 minutes) |

No force pushes, arbitrary messages, standalone recovery, reruns, credential changes
or runtime installation. Consumer validation and recovery requirements remain in force.
Existing target advancement is allowed; branch disappearance is not covered.

## Input

Only the canonical task and authorisation names. Session identity comes from
CODEX_THREAD_ID. No --input, scope, TTL, use count or caller-supplied session override.
After the task obtains a human decision, repeat execution with --decision JSON:
request_id, token, decision (approve/decline), approved_by, source.

## Output

The shared six-field envelope has input, output, output_format=markdown, status,
error and meta_data. output is a one-element array of the canonical repository-relative
Markdown path, not a JSON permission payload:
`authorizations/authorization-git-commit-and-push/.runtime/grant.md`.
meta_data contains grant_id, session_id and cache_hit. Tasks pass the exact file path
and grant_id to consumers. A pending file is not permission to execute.

| Outcome | Status | Error | File |
| --- | --- | --- | --- |
| Granted or cached | ok | null | Active approved grant |
| Awaiting human decision | error | approval_required | Complete pending request |
| Declined | error | authorization_declined | Declined request |
| Other active/pending session | error | authorization_session_conflict | output=null; existing owner preserved |
| Invalid request or file failure | error | authorization_error | output=null |

Only approval_required is resumable within this task stage. Same-session hits do not
extend expiry or rewrite the file. Consumers must read the canonical file afresh.

## Revocation

Only an explicit human request allows the task to execute:
`python3 -B authorizations/runner.py revoke --task <task-name> --authorization authorization-git-commit-and-push --grant-id <expected-id> --source '<human-message-reference>'`.
This updates the same file to revoked. Cross-session revocation is allowed; stale
IDs are rejected. It cannot cancel already accepted dispatches.

## Definition changes

Existing grants keep their complete issued permission terms until expiry/revocation.
The stored fingerprint is informational; current definition changes do not invalidate
them. New grants use the latest definition. Consumers require issued terms to cover
the actual operation and current component configuration.
