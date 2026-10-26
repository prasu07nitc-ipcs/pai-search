# Task recipe template

Authoring only. Replace placeholders and follow [project policy](AGENTS.md).
Do not restate shared scheduling, failure, cache, or timing rules.

```markdown
# task-<name>

One sentence describing the outcome. Follow the task library policy (link ../AGENTS.md).

## Input

Required input and exact selection rule; missing-input response.

## Setup

Required component policies/rules; existing runner templates, working directory,
and argument serialization. Agent stages use component instructions directly.
Resolve prerequisite lists from dependent definitions’ optional `authorisations`
sections; an omitted section means no authorisations are needed;
execute fixed authorisations through their runner as this task before dependent
effects. Pass returned canonical grant-file paths and expected IDs to consumers.
Never override permission terms; use platform chat identity and explicit human consent.

## Stages

Define producer references and path bases. Use one row per invocation.

| ID | Component / instructions | Execution / timeout | Named inputs |
| --- | --- | --- | --- |
| <id> | <exact component with instruction link> | <runner template + timeout, or agent> | <exact arguments from task input or producer values/paths> |

## Groups

| Group | Stage IDs in order | Mode | Concurrency |
| --- | --- | --- | --- |
| <name> | <IDs> | serial / parallel | <integer> |

## Result

Component-provided identity; main deliverables and relevant supporting links.
List only task-specific exceptions to shared rules, if any.
```
