# task-index-web-page

Collect a URL in the URL form, extract metadata when Bookmark is selected,
extract Markdown when Index is selected, and encode successful Markdown into
entity context. Both extraction branches run concurrently when selected.

## Dependencies

| Component | Required when | Purpose |
| --- | --- | --- |
| [form-url](../../forms/form-url/AGENTS.md) | Always | Collect the URL and Bookmark/Index selections |
| [tool-webpage-og-crawler](../../tools/tool-webpage-og-crawler/AGENTS.md) | Bookmark selected | Extract webpage metadata |
| [tool-webpage-markdown](../../tools/tool-webpage-markdown/AGENTS.md) | Index selected | Extract webpage Markdown |
| [skill-context-encoder](../../skills/skill-context-encoder/SKILL.md) | Markdown extraction succeeds | Encode Markdown into entity context |

| Runtime dependency | Purpose |
| --- | --- |
| Forms server, `forms/.venv`, and `forms/runner.py` | Serve the URL form and persist its session |
| Tools runtime, `tools/.venv`, and `tools/runner.py` | Execute the selected extraction tools |
| Existing skill cache, validation, and persistence infrastructure | Validate, reuse, and save encoder results |
| Writable task-local `checkpoints/`, `output/`, and `logs/` storage | Persist recovery checkpoints, component output maps, and finished-attempt logs |
| Active agent session and browser access | Orchestrate execution and allow form submission |

When both options are selected, the extraction tools run concurrently. The
encoder waits for successful Markdown extraction.

## Instructions

- [Complete task instructions](AGENTS.md)
- [Execution procedure](AGENTS.md#execution-procedure)
- [Workflow diagram](AGENTS.md#workflow-diagram)
- [Recovery and cancellation](AGENTS.md#recovery-and-cancellation)
- [Library and usage](../README.md)
