# task-index-web-page

Orchestrate the component graph in [flowchart.md](flowchart.md). Forward designated
input unchanged to tool-url-validate. On success, run two extraction tools in parallel,
then two skills in parallel, then all three transactions in parallel. Every group
must fully succeed before the next begins. Any failure stops dispatch, preserves
execution state, forwards the component error/remedy and terminates.

The task agent reads upstream artifacts and assembles downstream inputs according
to [the wiring table](AGENTS.md#2-wire-inputs). Components own validation and processing.

## Dependencies

| Group | Components |
| --- | --- |
| Validation | [tool-url-validate](../../tools/tool-url-validate/AGENTS.md) |
| Parallel extraction | [tool-webpage-metadata](../../tools/tool-webpage-metadata/AGENTS.md), [tool-webpage-markdown](../../tools/tool-webpage-markdown/AGENTS.md) |
| Parallel skills | [skill-context-encoder](../../skills/skill-context-encoder/SKILL.md), [skill-article-writer](../../skills/skill-article-writer/SKILL.md) |
| Parallel persistence | [tx-bookmark](../../transactions/tx-bookmark/AGENTS.md), [tx-index](../../transactions/tx-index/AGENTS.md), [tx-save-article](../../transactions/tx-save-article/AGENTS.md) |

Use existing tools/transactions runtimes and skill infrastructure. One active
orchestrator owns task state; two skill agents execute the skill group. No separate
runner, environment, form, scheduler or remote publication is introduced.

## Instructions

- [Task instructions and wiring](AGENTS.md)
- [Workflow diagram](flowchart.md)
- [Shared orchestration and recovery](../AGENTS.md)
- [Library and usage](../README.md)
