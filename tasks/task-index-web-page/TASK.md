# task-index-web-page

Accept a URL and Bookmark/Read/Index selections through the [input contract](INPUT.md).
Normalize JSON, Markdown, or plain text and validate before processing. Extract metadata for any
selection, and Markdown for Index or Read. Index enables context encoding; Read
enables article writing only after both extractions succeed. Required extraction
branches run concurrently. Save selected results through tx-bookmark, tx-index,
and tx-save-article using the saved producer output files.

## Dependencies

| Component | Required when | Purpose |
| --- | --- | --- |
| [tool-webpage-og-crawler](../../tools/tool-webpage-og-crawler/AGENTS.md) | Any selection enabled | Extract webpage metadata |
| [tool-webpage-markdown](../../tools/tool-webpage-markdown/AGENTS.md) | Index or Read selected | Extract webpage Markdown |
| [skill-context-encoder](../../skills/skill-context-encoder/SKILL.md) | Index selected and Markdown extraction succeeds | Encode Markdown into entity context |
| [skill-article-writer](../../skills/skill-article-writer/SKILL.md) | Read selected and both extractions succeed | Write a researched article from metadata and Markdown |
| [tx-bookmark](../../transactions/tx-bookmark/AGENTS.md) | Bookmark and metadata extraction succeeds | Save bookmark metadata |
| [tx-index](../../transactions/tx-index/AGENTS.md) | Index and metadata/encoding succeed | Save entity index files |
| [tx-save-article](../../transactions/tx-save-article/AGENTS.md) | Read and metadata/article writing succeed | Save the article locally |

| Runtime dependency | Purpose |
| --- | --- |
| Tools runtime, `tools/.venv`, and `tools/runner.py` | Execute the selected extraction tools |
| Transactions runtime, `transactions/.venv`, and `transactions/runner.py` | Persist selected results within transaction-owned data directories |
| Existing skill cache, validation, and persistence infrastructure | Validate, reuse, and save encoder and article results |
| Writable task-local `checkpoints/`, `output/`, and `logs/` storage | Persist recovery checkpoints, component output maps, and finished-attempt logs |
| Active agent session | Validate input and orchestrate execution |

When both extractions are required, the tools run concurrently. The encoder
requires Index and successful Markdown extraction. The article writer requires
Read and successful metadata and Markdown extraction. Each selected branch requires
its transaction to succeed before task completion; producer failures block dependent
transactions while independent branches retain their results.

## Instructions

- [Input contract](INPUT.md)
- [Complete task instructions](AGENTS.md)
- [Execution procedure](AGENTS.md#execution-procedure)
- [Workflow diagram](AGENTS.md#workflow-diagram)
- [Recovery and cancellation](AGENTS.md#recovery-and-cancellation)
- [Library and usage](../README.md)
