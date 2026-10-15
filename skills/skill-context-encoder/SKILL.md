---
name: skill-context-encoder
description: Extract context from a complete text blob into a JSON array of entity utterances, preserving facts, attribution, uncertainty, and source order.
---

# Context encoder

Read [AGENTS.md](AGENTS.md) and follow its input validation, entity extraction, utterance reconstruction, and output rules. Return the specified five-field JSON array for valid input, including the exact `entity_utternace` spelling, or the prescribed plain-text validation message for invalid input.
