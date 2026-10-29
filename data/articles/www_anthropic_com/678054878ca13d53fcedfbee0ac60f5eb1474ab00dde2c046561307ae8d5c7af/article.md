# [Anthropic extends long-running agent harnesses from coding handoffs to durable managed sessions](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)
*Updated: 2026-10-18T21:26:39.000Z*

Anthropic’s work on agents that operate for hours has expanded from preserving coding progress between context windows to separating implementation, evaluation and persistent execution infrastructure. Its later accounts show why the surrounding software must evolve with the model.

![Image accompanying the original article](https://www-cdn.anthropic.com/images/4zrzovbb/website/a6ad5022af5127422540a05592c8ff6e8c084f5d-1200x630.jpg)

## From saved progress to persistent execution

In a June 10, 2026 account, Anthropic described Claude Managed Agents as a service that separates the agent harness from its code-execution sandbox. A session log connects them and records model calls, tool calls and results. The company says sessions preserve event history, sandbox state and outputs, allowing work to pause, resume and be inspected afterward. These are Anthropic’s descriptions of its infrastructure, rather than an independent assessment of reliability. [Anthropic’s Managed Agents account](https://claude.com/resources/articles/building-with-claude-managed-agents) extends the continuity problem beyond a coding agent’s notes to the lifetime of the execution environment itself.

## The original problem: a new session loses the thread

The starting point was Anthropic’s November 26, 2025 report on the Claude Agent SDK. Its experiments found that context compaction alone did not reliably produce a finished application from a broad request: agents could attempt too much, leave incomplete work or declare completion too early. [The original report](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) proposed an initialization session followed by incremental coding sessions.

The initializer prepared a startup script, progress notes and a structured feature inventory. Later sessions selected unfinished work, checked the application and left artifacts for the next session. Features began as failing and were meant to pass only after verification. Browser-based testing helped expose failures that code inspection or narrower checks missed. This was an experimental approach focused on web applications; the report left broader applicability and the best agent architecture unresolved.

## Later experiments separate building from judging

A March 24, 2026 follow-up described a planner, generator and evaluator. The planner expanded a brief request into a product specification. The generator implemented bounded sprints, while the evaluator exercised the running application with browser tools. Before implementation, the generator and evaluator agreed on a sprint contract defining success. [Anthropic’s follow-up](https://www.anthropic.com/research/harness-design-long-running-apps) presents this separation as a response to overly generous self-evaluation.

The report also qualified a previous design choice: context resets had helped Sonnet 4.5, but the author removed them in the later Opus 4.5 harness and used automatic compaction. The practical inference is that a useful continuity mechanism for one model can become unnecessary overhead for another. These examples support adapting and evaluating the harness, rather than assuming one arrangement will remain optimal.

## Sources

- [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents), Anthropic, November 26, 2025 — original article.
- [Harness design for long-running application development](https://www.anthropic.com/research/harness-design-long-running-apps), Anthropic, March 24, 2026.
- [The evolution of agentic surfaces: building with Claude Managed Agents](https://claude.com/resources/articles/building-with-claude-managed-agents), Anthropic, June 10, 2026.

---
***Long-running agents, Claude Agent SDK, Agent harnesses, Context management, Browser testing, Claude Managed Agents***

*Published: 2025-11-26T00:00:00.000Z*
