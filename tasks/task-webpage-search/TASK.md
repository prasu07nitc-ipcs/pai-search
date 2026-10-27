# task-webpage-search

Interpret a query, search saved webpage bookmarks and entity indexes, and answer
from relevant saved articles with local file citations.
Follow the [task library policy](../AGENTS.md).

## Input

Accept a query string or an object containing `query` and optional `context`,
using the query interpreter's input contract. When a query body is explicitly
separated from the task command, preserve that body verbatim as `query`;
otherwise use the complete triggering message. A command with no query body
requires a query before execution. For structured input, preserve supplied
strings and pass only the supplied fields unchanged. Bind context only when
explicitly supplied for this invocation; do not borrow conversation or browser
state. The interpreter owns input validation and requests for correction.

## Setup

Logical context: tasks. Working directory: repository root.
Load [skills policy](../../skills/AGENTS.md),
[tools policy](../../tools/AGENTS.md), and
[tool rules](../../.codex/rules/tools.rules).
Read each linked component's instructions, including the AGENTS.md linked from
each skill's SKILL.md. Use the existing tools runtime; no environment changes.

Agent stages use their linked component instructions directly, with explicit
named inputs. Serialize each agent's named-input object once as compact JSON
with Unicode preserved and no trailing newline; supply that exact text as its
invocation and `raw_input` for the component-owned identity and cache contract.
Retain each accepted execution entry and actual artifact path internally.

Apply the shared minimal-context dispatch and event-driven collection rules. Prepare
both agent launch messages and the search command template during setup, leaving
producer paths unresolved. The interpreter receives I and its skill/shared skill
policies; the answer agent receives only its named report path and its skill/shared
skill policies, plus required repository and reference-date context. Neither agent
inherits chat history or needs the task's other component contracts.

Accept interpret by its component status, execution entry, and required artifact
checks, then pass R directly to search. Accept search by its result envelope and
required artifact checks, then pass S directly to answer. The orchestrator does not
read either Markdown payload to repeat the consumer's validation. Read A once for
the final answer body; omit any historical embedded Execution Logs section and
keep the returned execution entry internal under shared task policy. Required
component checks, exact-input cache behavior, and sequential dependencies still apply.

Prepare this runner template, substituting the complete JSON arguments and
timeout. POSIX single-quote JSON, replacing each apostrophe with `'"'"'`.
Do not use shell interpolation or temporary input files.

```sh
tools/.venv/bin/python -B tools/runner.py --tool tool-index-search --input '<JSON>' --timeout 20
```

## Stages

`I`: designated interpreter input object; a query string becomes `{"query": I}`
before dispatch, with its exact string preserved. Below, `I` denotes that final
object. `R`: accepted interpreter output-file path, resolved from its skill root
to a repository-relative path. `S`: accepted search output-file path, resolved
from tools/ to a repository-relative path. `Q`: the accepted search result's
`meta_data.page_id`, used as this task's `page_id`; it is a search identifier,
not the identity of a retrieved webpage. `A`: accepted answer output-file path,
resolved from its skill root to a repository-relative path. Do not substitute
inline payloads for paths or derive component execution IDs in the orchestrator.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| interpret | [skill-query-interpreter](../../skills/skill-query-interpreter/SKILL.md) | component agent | I: `query`, and `context` only if supplied |
| search | [tool-index-search](../../tools/tool-index-search/AGENTS.md) | tool runner / 20s | {"raw_input": R} |
| answer | [skill-index-rag](../../skills/skill-index-rag/SKILL.md) | component agent | {"file_path": S} |

Search uses the component's default exact entity matching. No task-level fuzzy
settings or web retrieval are introduced. Agent stages have no task-imposed
timeout. An accepted historical interpreter cache artifact with an incompatible
extension is an interface conflict: stop rather than copying, renaming, or
regenerating it to satisfy the search contract.

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| Interpret query | interpret | serial | 1 |
| Search saved webpages | search | serial | 1 |
| Answer from articles | answer | serial | 1 |

Empty search results still proceed to answer; the answer component owns the
supported response and any insufficient-evidence explanation.

## Result

Lead with the accepted answer body, preserving its supporting article citations
and material evidence gaps. Keep the component execution entry internal; omit any
historical embedded Execution Logs section without modifying the component artifact.
Follow with task
status, the original query, `page_id=Q`, and absolute links to R, S, and A.
Label Q as the search identifier. Keep the interpreter's retrieval specification
and search report available through links rather than echoing their payloads.

Include the shared timeline for all three stages and the required preparation,
workflow, reporting, total and capture measurements. State the actual sequential
execution and apply the shared timing caveat for persistence and response delivery.
Use component cache outcomes; a fresh search does not imply a fresh answer.

Use the accepted Q for shared final-report persistence at
`tasks/task-webpage-search/output/<page_id>.md`, including after a later failure
or cancellation. Before search yields an accepted page ID, no task report file
can be saved; report that limitation rather than deriving an ID from a filename
or upstream skill entry. Apply shared failure settlement and retain accepted
artifacts. An accepted insufficient-evidence answer is a completed task.
