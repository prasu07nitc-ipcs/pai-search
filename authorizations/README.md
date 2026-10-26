# Authorisation components

| Component | Definition | Consumer |
| --- | --- | --- |
| authorization-git-commit-and-push | [AUTHORIZATION.md](authorization-git-commit-and-push/AUTHORIZATION.md) | data/tx-commit-and-push |

Follow [policy](AGENTS.md). Trusted local grants record explicit human approval.
Only tasks execute authorisations. Consumers declare names in `## authorisations`
only when grants are required; otherwise omit the section. Omission means no grants.
tasks deduplicate that list, execute it in preflight and pass canonical file paths
and expected grant IDs. Consumers validate locally with no authorisation callbacks.

## Execute from the repository root

```sh
python3 -B authorizations/runner.py execute --task task-webpage-index --authorization authorization-git-commit-and-push
```

The platform CODEX_THREAD_ID supplies chat identity. All permission terms and expiry
are fixed at definition time. No runtime overrides are accepted. An active grant for
the same chat returns without asking. Another chat is rejected until expiry/revocation.
On approval_required, read and present the complete pending Markdown file. After an
explicit human decision repeat the command with --decision JSON containing exactly
request_id, token, decision (approve or decline), approved_by and source.
A pending request reserves the authorisation for 15 minutes; decline/timeout frees it.
Never interpret an implementation request as approval for any operational grant.

## Grant-file contract

Each sub-component owns one canonical `.runtime/grant.md`, updated atomically.
The file starts with `# Authorisation grant`, a blank line, then one bullet per field
in this exact order. Each bullet is `- **Field label**: <JSON-encoded value>`.
This is human-readable Markdown with deterministic values, not free-form prose.
Strings use JSON quotes, booleans/null/numbers use JSON literals and roots use a list.

| Fields, in order | Meaning |
| --- | --- |
| Schema version; Authorisation; Grant ID; Status | Protocol 1, component name, issuance ID, pending/active/declined/revoked |
| Project; Session ID | Exact local project and owning platform chat |
| Requested at; Approval deadline | UTC ISO timestamps; pending reservation deadline |
| Granted at; Expires at; Revoked at | UTC ISO timestamps, or null before the corresponding event |
| Approved by; Approval reference; Decision reference | Human identity/context and exact chat/message references; null before decisions |
| Request token | Exact pending challenge token; matching it does not itself prove consent |
| Definition fingerprint | Informational issuance fingerprint; never compared with today's definition |
| Duration seconds; Consumer; Operation | Fixed approved lifetime and permitted component/action |
| Branch; Remote URL; Author name; Author email | Exact granted Git settings |
| Create branch; Base commit; Page scope | Creation policy, base and approved page coverage |
| Allowed roots; Message prefix; Reuse | Approved output roots, canonical message rule and session reuse policy |

The file contains the full permission snapshot. Existing grants retain those terms
after definition changes. Consumers check path, expected grant ID, project, platform
session, active status, approval, expiry and actual operation coverage. They never
write the file, decrement uses, consult a grant database or execute authorisations.
Validity is checked immediately before dispatch; dispatched work may finish later.

## Revoke

On an explicit human revocation request, the task runs:

```sh
python3 -B authorizations/runner.py revoke --task task-webpage-index --authorization authorization-git-commit-and-push --grant-id '<expected-id>' --source '<human-message-reference>'
```

The respective authorisation updates its canonical file to revoked. Subsequent
consumer validations fail; already accepted work is unaffected. Tasks always pass
the canonical path, never a copy or an in-memory permission snapshot.

## State and migration

Component-local `.runtime/` holds grant.md, lock and append-only history.jsonl.
The lock serializes reservations and decisions. Readers see complete atomic file
replacements. Local files, process identity and wall time are trusted; no signatures
or authenticated caller boundary is claimed. Consumers keep ordinary execution
records, and permission does not override their retry/recovery policies.
The old authorizations/.runtime/grants.sqlite3 stays intact as historical data and
is never consulted for permission. The old find/request/approve/verify CLI and use
accounting have been retired. Runtime files are private and ignored.

## Verification

```sh
python3 -B -m unittest discover -s authorizations -p 'test_*.py' -v
```

Tests use temporary stores, mocked Git/SSH and competing local test processes. They
never issue production grants or execute Git operations.
