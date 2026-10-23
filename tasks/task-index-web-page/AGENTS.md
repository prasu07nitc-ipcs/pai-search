# Index web page

Follow [shared orchestration policy](../AGENTS.md). Read component contracts only
for the stages being dispatched. [flowchart.md](flowchart.md) defines execution
order, parallel groups and failure termination; the mappings below define edge data.

## Purpose and scope

Orchestrate URL validation, parallel extraction, parallel skills, and parallel
transactions. Read artifacts and construct declared inputs; all validation, content
processing, research and persistence belong to components. Editing this task does
not execute it or change component implementations, environments or dependencies.

## Inputs and outputs

Forward the designated task input verbatim to the validator. When the triggering
request explicitly separates task input from its command, use that input body;
otherwise use the complete triggering message. Do not extract, trim or normalize it.
Keep the original trigger separately for task identity under shared policy.

| Stage ID | Type | Component | Format |
| --- | --- | --- | --- |
| validate_url | tool | tool-url-validate | json |
| bookmark | tool | tool-webpage-metadata | json |
| markdown | tool | tool-webpage-markdown | markdown |
| encode | skill | skill-context-encoder | json |
| article | skill | skill-article-writer | markdown |
| save_bookmark | transaction | tx-bookmark | markdown |
| save_index | transaction | tx-index | markdown |
| publish_article | transaction | tx-save-article | markdown |

Use these stable stage IDs in the shared checkpoint/output-map contract. Tool output
paths resolve relative to tools/; skill output paths follow their contracts; transaction
paths resolve from repository root and remain arrays. Store repository-relative paths
and recovery hashes. Display absolute links. No task-level content outputs are created.

## Execution procedure

### 1. Initialize

Obtain trusted chat identity, reconcile prior attempts, acquire run ownership and
initialize all stages under shared policy. Record exact argument/source references
and intent before each invocation; checkpoint each returned result. Before launching
a parallel group, record intent for every member. Read producer artifacts only after
successful execution and transport/integrity checks; do not revalidate their content.

### 2. Wire inputs

Let V be the parsed JSON artifact returned by validate_url; M the metadata file
returned by bookmark; D the Markdown file returned by markdown; C the context JSON
file returned by encode; W the article file returned by article. These names are
references, not additional task artifacts. Retain V.url and V.page_id unchanged.

| Component | Constructed input |
| --- | --- |
| tool-url-validate | {"input_text": exact designated task input} |
| tool-webpage-metadata | {"url": V.url, "page_id": V.page_id} |
| tool-webpage-markdown | {"url": V.url, "page_id": V.page_id}; omit optional settings to use component defaults |
| skill-context-encoder | Separate page_id=V.page_id and exact UTF-8 contents of D as the text blob |
| skill-article-writer | Separate page_id=V.page_id, metadata JSON read from M, and exact Markdown contents of D; keep the three inputs separately identifiable |
| tx-bookmark | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": null, "article_file_path": null} |
| tx-index | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": C, "article_file_path": null} |
| tx-save-article | {"page_id": V.page_id, "meta_data_file_path": M, "context_file_path": null, "article_file_path": W} |

Paths in transaction inputs are repository-relative source paths, not file contents
or envelopes. Reading/parsing and argument serialization are mechanical assembly;
missing/unreadable inputs terminate orchestration. Never infer missing values, compute
URL hashes, inspect article structure, repair payloads or duplicate component validation.
Do not construct raw_input for tools/skills that do not accept it or save input copies.

### 3. Dispatch parallel groups

Follow the shared user-facing execution-update rules: announce each launch group
with exact component names, then report each accepted completion/failure with its
human-readable total invocation time and any still-running siblings. Checkpoint persistence alone is not a user-facing update.

1. Invoke tool-url-validate alone.
2. After validator success, launch metadata and Markdown tools concurrently; wait
   for both successful results before dispatching skills.
3. Launch encode and article in two parallel skill agents. Each agent follows the
   selected SKILL.md, AGENTS.md and shared skills policy, including cache/persistence
   and display requirements. They never write task state. The orchestrator receives
   their outcome, artifact reference and execution-entry information.
4. After both skills succeed, launch all three transactions concurrently through
   their runner. Inspect/checkpoint each result independently.
5. After all transactions succeed, publish completion under shared policy.

Use existing runtimes from repository root and safely serialize/shell-quote JSON:

```sh
tools/.venv/bin/python -B tools/runner.py --tool tool-url-validate --input '<JSON>'
tools/.venv/bin/python -B tools/runner.py --tool tool-webpage-metadata --input '<JSON>' --timeout 30
tools/.venv/bin/python -B tools/runner.py --tool tool-webpage-markdown --input '<JSON>' --timeout 30
transactions/.venv/bin/python -B transactions/runner.py --transaction tx-<name> --input '<JSON>'
```

Read .codex/rules/transactions.rules before transaction execution; follow its exact
command format. Component permissions, duplicate confirmation and cache rules apply.
No automatic retries or bypasses. Skills are executed by agents, not invented CLIs.

### Failure termination

Any component failure, correction request, timeout, transport/integrity error or
orchestration/storage error stops new launches. Stop owned active processes/agents
where possible; reconcile returned results and uncertain effects before finishing.
Parallel siblings may already have committed outputs; retain them without rollback.
Leave unstarted stages pending. Publish the failed checkpoint/output/log when storage
allows; report unavailable publication honestly. Forward the failed component's
original error and supplied correction/remedy without analysis; if none is supplied,
say so. For orchestration errors identify the failed operation or missing prerequisite.
Return status, IDs and available links, then terminate. No further processing occurs
without an explicit resume/new request.

## Workflow diagram

See [flowchart.md](flowchart.md). Composite boxes are parallel groups; outgoing data
edges do not bypass the requirement that the entire preceding group succeeds.

## Recovery and cancellation

Follow shared ownership, integrity, publication and recovery rules. Reuse successful
stages and saved arguments; reconcile uncertain effects before considering retries.
Do not rerun successful components, bypass duplicate/cache policies, or change source
artifacts to force progress. On cancellation, stop dispatch, reconcile active siblings,
preserve artifacts and publish the cancelled attempt when possible.

Historical runs retain their recorded stage sets and arguments; do not migrate,
backfill, expand scope or rewrite old records during management. New invocations of
unfinished stages must satisfy current component contracts; unresolved legacy input
mapping requires explicit clarification, not guessed conversion. No form polling.

## Acceptance criteria

- Task logic is limited to wiring, declared input assembly, scheduling, routing,
  checkpoint/recovery infrastructure and forwarding component outcomes.
- Original validator input and upstream values are preserved.
- Both extractions precede both skills; both skills precede all three transactions.
- Every group runs in parallel and its full success gates the next group.
- Components own semantic validation, processing, caching and their output persistence.
- Failure reports forward component errors/remedies, then terminate without retries.
- All eight stages succeed before completion; output maps/logs follow shared policy.
- Editing/discovery creates no production state or component executions.
