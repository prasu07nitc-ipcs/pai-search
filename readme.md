# PAI Search

Local webpage extraction, article indexing, and search.

| Component | Entry point | Saved artifacts |
| --- | --- | --- |
| Tools | [Tool library](tools/README.md) | Tool-local `output/<page_id>.json` or `.md` and `logs/` |
| Skills | [Skill policy](skills/AGENTS.md) and the selected `skills/skill-*/SKILL.md` | Skill-local outputs and execution logs |
| Transactions | [Transaction library](transactions/README.md) | Catalog files under `data/` and transaction-local logs |
| Tasks | [Task library](tasks/README.md) | Component-owned artifacts and task timing |

Run tools and transactions from the repository root using their documented
macOS runners and existing Python environments. The runners isolate worker
writes and enforce worker timeouts. Component instructions specify dependencies,
cache validation, and rerun behavior.

Load only the selected component instructions and the inputs needed for the
current stage. Pass artifact paths between stages. Read payloads when needed
for validation, extraction, or synthesis. Use the Markdown tool's default
single-pass mode for indexing and reserve compare mode for explicit comparisons.

The catalog and execution history are local and have no automatic retention.
