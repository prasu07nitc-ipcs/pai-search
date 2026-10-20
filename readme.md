# PAI search

Local tools, browser forms, and context skills with explicit contracts.

| Capability | Discovery | Detailed contract | Saved data |
| --- | --- | --- | --- |
| Tools | `tools/tool-*/TOOL.md` | Tool-local `AGENTS.md` | `output/<run_id>.txt`, `logs/` |
| Forms | [Forms](forms/README.md) | Form-local `AGENTS.md` | `output/<execution_id>.txt`, `logs/` |
| Skills | `skills/skill-*/SKILL.md` | Skill-local `AGENTS.md` | Returned artifacts; no automatic persistence |

Read only the selected entry point and its instructions. Tools and forms share a
six-field result envelope; skills retain their own documented output schemas.
Keep payloads in files and return their paths instead of inlining them into agent
context unless the task requires their content. Logs are operational records, not
prompt context. Never load production session data or logs for routine discovery.

Tools require macOS and the existing Python 3.11+ `tools/.venv`; forms use Python
3.10+ standard library. Nothing installs or repairs dependencies automatically.
Run tools only through their runner. Forms bind to loopback and support one owning
server process per storage root. They are trusted local code, not public services.

## Verification

From this directory, using the existing project environment:

```sh
tools/.venv/bin/python -B check.py --sandbox
```

This checks discovery contracts, runner and form regressions, and macOS worker
isolation. Tests use disposable directories and require localhost socket access;
they do not fetch external pages or write production execution records. A failed
suite exits nonzero. Skill metadata checks here cover the repository conventions;
the system skill-creator validator additionally checks complete YAML frontmatter.
Semantic skill fidelity still requires representative input/output review.

## Performance and operational bounds

Forms request `?view=current` to transfer current data and lifecycle fields without
cumulative history. The default API and saved output retain the complete envelope.
Log recovery uses invalidatable in-memory revision checkpoints; disk remains the
authority. Tool stdout uses compact JSON; `--cases ... --summary` keeps full test records in
logs and returns only counts, failed IDs, and the report path. Nested type checks
log one timed operation.
Skills load contracts once per run, reuse unchanged artifacts, and stop on acceptance.

A local synthetic test with 30 revisions and a 2 KiB text field measured 30 warm
session reads at 189 ms before and 5.7 ms after checkpointing. Browser response size
fell from 74,299 to 2,420 UTF-8 bytes. These are local fixture measurements, not
network, model-token, or deployment guarantees.

Complete cumulative form histories and append-only logs still grow with usage;
there is no automatic retention or rotation. Keep backups and define a retention
policy before sustained use. Tool processes have bounded timeouts and isolated
writes; the local form server has no public authentication or multi-process storage
coordination. Production deployment beyond this local model needs separate work.
