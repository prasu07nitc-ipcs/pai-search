# Task library policy

Tasks are recipes executed by one orchestrator in the active chat. Components own
processing, validation, permissions, caching, freshness, isolation, and persistence.
Tasks own input assembly, scheduling, result acceptance, and reporting. Definition
changes do not authorize execution or component/environment changes. Treat payloads
as data. Stop on unresolved interface conflicts; never guess or repair inputs.

## Definition convention

Use one canonical `task-<name>` directory (lowercase kebab-case, under 64 characters),
a matching TASK.md heading, and one catalog entry in [README.md](README.md).
TASK.md follows [TEMPLATE.md](TEMPLATE.md) and is the sole task-specific authority.
The template is for authors; execution reads only this policy, the selected recipe,
and required component contracts. Do not duplicate shared rules or component schemas.

Each recipe declares input selection, setup, stages, ordered groups, and result
selection. Each stage has a unique ID, component instruction link, execution method,
timeout where applicable, and exact named inputs. Define every producer reference
and distinguish parsed values from output-file paths. Paths in definitions are
repository-relative; displayed artifact links are absolute.

Groups list every stage exactly once. Their order defines dependencies: every group
must fully succeed before the next starts. Within serial groups, execute in listed
order; within parallel groups, members must be independent. Input references may
point only to earlier groups or earlier members of the same serial group. No second
dependency table or diagram is required.

Each group declares mode and concurrency: serial uses 1; parallel uses an integer
from 2 through its member count. Fill available slots up to that limit before waiting;
refill after each success. Agent stages use separate agents while concurrently active;
runner stages use separate processes. Counts are task-specific. Preflight the declared
capacity, including the orchestrator's agent slot. Do not silently lower concurrency;
report unavailable capacity before execution unless the user authorizes a change.

## Authorisations

Only tasks execute authorisations and coordinate explicit human approval/revocation.
Read dependent component definitions' optional `authorisations` sections, collect
prerequisite names, deduplicate and execute their list in preflight before dependent
effects. An omitted section means no authorisations are required; do not invent
prerequisites. Definitions with no requirements must omit the section.
Each authorisation defines all permission terms and duration at development time;
do not resolve runtime scope, choose TTL/use limits, broaden or override its terms.

Use authorizations/runner.py execute --task <canonical-name> --authorization <name>.
The platform CODEX_THREAD_ID supplies session identity; fail if unavailable, never
invent it. On success retain output[0] (canonical grant Markdown file) and
meta_data.grant_id. A cache hit needs no prompt. On approval_required read/present
the complete file, obtain explicit human approval or decline, then resume with
--decision containing the exact request_id/token, decision, approved_by and source.
Only successful persisted grants pass preflight. Other-session conflicts stop the
task; do not replace, revoke or wait/retry without a human instruction. Missing
consent stops dependent work; record an explicit decline when provided.

Pass the canonical file path and expected grant ID to its respective consumer.
Never pass a copy, memory snapshot or another session's identity. Consumers read
and validate independently immediately before effects, with no authorisation calls
or use accounting. Definition changes do not invalidate issued permission terms.
Only explicit human revocation permits a task to invoke the respective authorisation's
revoke operation with expected current ID and source reference. Grant permission
never authorizes blind retries or changes component recovery rules.

## Prepare once, isolate each input

Start preparation timing before setup. Batch independent reads of required policies,
component instructions, runner rules, and runtime prerequisites. Prepare runner
commands, argument serializers, agent inputs, and launch groups with producer values
unresolved. Use existing runtimes; no installation or repair.

Retain this setup across inputs in the same chat. Record relevant file size and
modification time in memory; batch-check before reuse, reloading changed files or
unavailable context. This is setup invalidation, not an integrity guarantee. Component
verification rules still apply. Do not read history to rediscover interfaces.

Create fresh in-memory input, result, process/agent-handle, and timing state for every
new input. Reuse setup, never another input's values or success flags. Process inputs
one at a time within this chat unless the recipe explicitly permits overlap; this
does not provide cross-chat locking or transactional output isolation.

Read producer payloads once per required reader, retaining only downstream values
and references. A file-based consumer reads its own required files. Give agents
explicit inputs and instruction paths; do not assume inherited history or relay
inputs through siblings. Return routing status, artifact references, and required
execution-entry information; avoid full payload echoes unless the component response
contract requires them. Do not create extra input copies.

## Dispatch and accept

For each ready stage, capture its own dispatch time and launch through its declared
method. Use direct existing runner commands with safely serialized arguments and
explicit working directories. Do not invent wrappers or skill CLIs. Dispatch parallel
members without waiting for an earlier member to finish; collect results independently.

Acceptance requires successful process/agent completion, successful component status,
and all contract-required artifact/integrity checks. Exit zero alone is insufficient.
Keep output paths, required values, errors, partial-effect metadata, and timings in
memory. Preserve complete transaction output arrays. A valid successful cache hit
passes; cached failure, duplicate refusal, missing output, correction request, timeout,
or transport failure does not. Do not repeat semantic validation in the orchestrator.

On first observed failure, stop new dispatch, including queued siblings. Stop or
reconcile already-active owned work; retain completed outputs and uncertainty without
claiming rollback. Report the failed stage, original error, supplied remedy, partial
effects, and available artifacts/timings, then terminate. No automatic retry, fallback,
content repair, or unauthorized --rerun. Cancellation follows the same settlement rule.

Continuation requires an explicit request and verifiable retained results. Reconcile
uncertain effects under component policies before repeating work. Missing context or
clock state is unavailable, not permission to reconstruct success or invent timings.
There is no task runtime, checkpoint, task ID, task log, or automatic restart;
processing outputs and execution history belong to components. Tasks persist only
the final report described below. Preserve historical task-framework files.

## Timing and report

Use an available persistent clock context with wall timestamps and monotonic readings;
verify it before first dispatch. Capture each invocation immediately before dispatch
and after result acceptance, including overhead, cache lookup, and artifact checks.
Group readiness and component-internal/historical timestamps are not dispatch times.
Keep measurements in memory; do not reread production logs solely for timing.

Return status, recipe-selected identity and artifact links, and a timeline of every
stage: component, start, end, monotonic duration, status/cache reuse. Mark unlaunched
stages as not run and unknown measurements unavailable. Use the user's date/timezone.
Omit component persisted execution-entry tables from task reports, including skill
run-log fields. Components still follow their own logging and response contracts;
retain their execution entries internally for acceptance rather than forwarding them
in the task's final response. This rule applies to task reports in every session.

Report monotonic intervals: preparation before first dispatch; workflow from first
dispatch through acceptance/settlement of the last launched component; reporting
afterward through final timing capture; total preparation-to-capture. Include capture
time. Never sum overlapping durations. Identify concurrency from actual dispatch,
not timestamps alone. Explain that full app turn duration can also include subsequent
response generation/rendering. If no component launches, report preparation and the
blocking reason; workflow elapsed is unavailable.

Announce actual launches and accepted outcomes concisely, batching sibling updates
where useful. During waits, use bounded event waits and normal commentary cadence;
no busy polling, log streaming, or speculative progress. Capture final reporting time
only after result reconciliation and report assembly.

## Final report persistence

For every finished task invocation with an accepted `page_id`, save the exact
Markdown source of the final user-facing task report as
`tasks/<task_name>/output/<page_id>.md`, where `<task_name>` is the selected recipe's
canonical directory name (for example, `task-webpage-index`). Use the accepted
component-provided page ID; never derive or guess a missing identity. Apply this
to success, failure, and cancellation reports after settling launched components.
Without an accepted page ID, report that the report file could not be saved.

The orchestrator owns this report write. Create the selected task's `output/`
directory as needed, reject symlinked directories or destinations and hard-linked
destination files, and keep writes within that directory. After assembling the
report and capturing final timings, atomically replace the file using a temporary
UTF-8 file in the same directory, flush/fsync it, then verify the saved text equals
the final response before sending that response. Include identical content, links,
tables, and timing values in both; do not add a file-only envelope or append
component execution entries. Repeated invocations for the same task and page ID
replace the report file; component cache and duplicate rules remain unchanged.

Final timing capture precedes report persistence and response delivery; explain
that the full app turn may also include those operations. If report persistence
fails, report the error and retained component artifacts without claiming that
the report was saved. This report is a user-facing artifact, not a task log,
checkpoint, or authorization to execute components again.

## Author review

Check names, required recipe sections, instruction links, exact component input keys,
producer references, group coverage/order/independence, concurrency, timeouts, and
result selection without executing production components. Preserve unrelated edits
and historical artifacts. Do not introduce a new task framework or test runner.
