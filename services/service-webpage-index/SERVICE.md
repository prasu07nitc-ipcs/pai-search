# service-webpage-index

Apply [shared policy](../AGENTS.md). Execute
[task-webpage-index](../../tasks/task-webpage-index/TASK.md) sequentially.

## Permitted intent

| ID | Meaning |
| --- | --- |
| `index_webpage` | Index a webpage from a URL supplied in the message |

Accept `Index https://example.com/article`, an explicit request to save that URL
to the index, or a bare URL submitted to this service (including a Markdown link).
Reject summarization, search, deletion, explanation, or indexing mixed with an
unrelated action. Clarify missing URL/reference or unclear intent before forwarding.
Malformed candidate URLs retain indexing intent; the task validates them.

## Receiver

Use the shared explicit-submit fast path. Load only the shared/service contracts
on acceptance; task policies and component discovery belong to the worker.
After shared provenance/transport checks, submit the unchanged payload with
`--intent index_webpage`. Do no technical prevalidation. After durable acceptance,
dispatch a separate drain worker; return the shared receipt without waiting for
execution. This contract authorizes worker delegation within accepted job scope.
Use no inherited conversation history or model override. Supply repository root,
this policy's path, shared policy's path, a fresh worker_id and authorized scope.

Dispatch on every acceptance: a processing record alone cannot guarantee a worker
will drain new arrivals. A redundant worker exits on busy/empty. If dispatch fails,
retain the accepted job and report Activation failed; never resubmit. A later valid
submission dispatches another worker. No scheduled retries or background listener.

## Worker

1. Load both policies; claim with the assigned unique worker_id. Exit on busy or
   empty; on processing, use the exact claimed input as the task's designated input.
2. Execute the complete task as its orchestrator: task/component policies, URL
   validation, capacity checks, parallel groups and approval boundaries all apply.
   Git only through the task's designated data component. Unavailable approval or
   capacity fails the job with an actionable reason and known partial effects.
3. Save the task report under its policy. Finish completed for normal success or
   documented `Page already processed`, with result keys `task`, `page_id`,
   `outcome` (`indexed` / `already_processed`), and repository-relative `report_path`.
   Add receipt/artifact references only after verification. On failure finish failed
   with error `{ "code": "...", "message": "..." }` and available partial result,
   report reference and known effects. No rollback is implied.
4. Persist completion before claiming again; a failed job does not stop drainage.
   Never reclaim interrupted processing automatically. Worker IDs establish queue
   ownership, not authentication or liveness.

Result rendering: state outcome, link verified report, and include verified
commit/push or artifact details when present. Failure results may expose recorded
partial effects, clearly labeled Partial. Management remains at root; receiver
handles only verified forwarded work. Initial admission is closed.
