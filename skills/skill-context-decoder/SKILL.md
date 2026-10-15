---
name: skill-context-decoder
description: Reconstruct coherent plain text from a JSON array of entity utterance objects, preserving facts, attribution, uncertainty, and source order.
---

# Context decoder

Read [AGENTS.md](AGENTS.md) and follow its input validation, reconstruction, and output rules. Accept the five-field input schema defined there, including the exact `entity_utternace` spelling, and return only the reconstructed text for valid input.
