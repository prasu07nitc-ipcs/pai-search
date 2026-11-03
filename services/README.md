# Services

Message-driven project chats with durable FIFO queues. Start here:
[shared policy](AGENTS.md). Defined service:
[service-webpage-index](service-webpage-index/SERVICE.md).

Send commands to the services root chat:

| Command | Purpose |
| --- | --- |
| `services list` | List service states |
| `<service> start` | Confirm start and open admission |
| `<service> stop` | Confirm, drain and archive |
| `<service> status` | Inspect chat and queue |
| `<service> submit <payload>` | Submit an allowed intent |
| `<service> job <job_id>` | Inspect one job |
| `<service> queue` | Inspect pending work and counts |
| `<service> report` | Table of all successful and failed jobs |

Example: `service-webpage-index submit https://example.com/article`.
Start/stop use a confirmation form valid for 30 seconds. Acceptance returns a job
ID; inspect it for completion. Direct submissions to the service chat are rejected.
Explicit `submit` uses the fast path: verify registration, forward once, relay
durable acceptance. It skips root queue prechecks and task execution; the receiver
atomically enforces admission. Chat scheduling and worker dispatch still add latency.

## Operations

Use the existing `services/.venv` (Python 3.11+, standard library only):

```sh
services/.venv/bin/python -B services/runner.py --service service-webpage-index queue-status
services/.venv/bin/python -B -m unittest discover -s services/tests -v
```

No Git operations, package installs, lifecycle changes or live jobs are needed to
run tests. Back up each service's runtime directory while quiescent, using a
SQLite-aware backup if writes remain active. Preserve queue history and registration
together; verify chat identity before restoring admission. Never replay an
interrupted processing job until its external effects have been reconciled.

The queue provides transactional ownership, not exactly-once external effects.
Chat dispatch, sender provenance, lifecycle confirmation and worker liveness rely
on agent/platform evidence. No daemon, authenticated transport, automatic crash
recovery or distributed lifecycle transaction is provided. These are deployment
constraints, not guarantees of production availability. Large reports deliberately
include all terminal jobs and therefore have output cost proportional to history.
