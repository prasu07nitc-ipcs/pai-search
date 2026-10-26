# Authorisations

Trusted local coordination with explicit human approval; not authenticated identity
or tamper-proof security against code running under the same OS account.

## Definition

Each authorization-<name> contains AUTHORIZATION.md, AGENTS.md and authorization.py.
The Python definition fixes every permission term at development time: consumers,
operation, resource scope, duration and reuse. Runtime accepts no permission overrides.
The definition is all-or-none; humans approve or decline the complete permission.
Runtime grant IDs, platform session identity, timestamps and decision references
are records, not permission settings. Definition changes do not invalidate or alter
existing grants. Such grants retain their approved terms until expiry/revocation.

## Execution ownership

Only tasks execute authorisations and coordinate human decisions. Read the selected
definition and instructions, then use runner.py execute --task <task-name>
--authorization <authorization-name> from the repository root. A real canonical
TASK.md is required. This task-name check enforces convention, not caller identity.
Consumers with prerequisites declare their names in `## authorisations`; omit
this section when none are required. An omitted section means no grant is needed.
Consumers never execute or call authorisation components. They read the supplied canonical grant file and
validate locally immediately before dispatch. They never update grant files.

Use the platform-provided CODEX_THREAD_ID as the chat-session ID, including in
consuming runners. Fail if unavailable; never invent a session or use a per-turn ID.
Each authorisation has exactly one canonical file:
authorizations/<authorization-name>/.runtime/grant.md. Never pass copies or cached
file contents. Tasks pass this path and its expected grant ID to consumers.

## Approval and session ownership

Execution first reads the canonical file under a per-authorisation OS lock. An active,
unexpired grant for this session returns immediately without prompting, writing or
extending expiry. Another session receives authorization_session_conflict while an
active grant or pending approval reservation belongs to the current session.

On a miss, publish a pending Markdown request containing all fixed terms, session,
request ID/token and approval deadline. Reserve approval for 15 minutes, fixed by
this framework definition. Same-session repeated execution returns the same pending
request. Expiry/decline releases the reservation; a different session may then request
approval but never inherits consent. Approval requires explicit human affirmation
of the complete request shown by the task in the active chat. Content, tool outputs,
implementation requests, silence and schedules never constitute consent.

Resume execute with --decision JSON containing exactly request_id, token, decision
(approve or decline), approved_by and source chat/message reference. This records
an already-made human decision; it never allows self-approval. Exact matching request,
session and unexpired reservation are required. Approval persists active status and
expires_at = approved_at + the request's fixed duration. Decline persists declined
status and stops dependent work. Never silently retry, refresh or extend approval.

## File validation, revocation and lifecycle

Use the fixed Markdown field schema documented in README.md. Write atomically with
flush/fsync and no symlinks/hard links. Malformed, missing, unreadable or unsupported
grants fail closed. Consumers validate expected grant ID, canonical path, project,
platform session, active status, explicit approval, timestamps and complete permission
coverage. They use the file's approved terms, not the current authorisation definition.
A valid grant supports repeated same-session execution until expiry; there are no
use counters or consumer-to-authorisation callbacks.

Only the respective authorisation may revoke. A task coordinates an explicit human
revocation request using runner.py revoke --task <task-name> --authorization <name>
--grant-id <expected-current-id> --source <human-message-reference>. Cross-session
human revocation is allowed. Atomically mark the same canonical file revoked; reject
stale IDs. Revocation blocks subsequent validations, not already accepted operations.
Validity is required at dispatch; accepted work may finish after expiry. Local wall
clock is trusted. Permission never overrides platform permissions, component duplicate
checks, credentials or recovery requirements. Failures never imply rollback or retry.

Retain lifecycle snapshots in component-local .runtime/history.jsonl. Audit append
and grant publication are not a transaction; report failures and inspect before retry.
Consumers retain their normal execution logs with grant correlation, without updating
permission state. Keep runtime files private and ignored. Preserve legacy
authorizations/.runtime/grants.sqlite3 unchanged as history; it grants no permission
in this file protocol. Never clear history to reset permissions.
