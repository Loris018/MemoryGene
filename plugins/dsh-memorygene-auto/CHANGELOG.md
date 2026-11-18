# Changelog

## 0.2.0 — 2026-11-17

First public repository version of the optional native DeepSeek Harness plugin. This version is separate from the Python core's 0.2.0.dev2 version.

- Background, evidence-linked task notes from bounded visible session excerpts, with same-session restoration and nonblocking use of ready notes.
- Task-card tools for viewing, correcting, removing, user-reported progress, artifact rechecks, pausing, resuming and clearing.
- Recorded dependency changes propagate review flags to dependent outputs; missing dependencies and cycles remain uncertain.
- Structural checks for missing goals, next steps, omitted requirements and history gaps.
- Manual corrections survive background rewrites; control revisions reject older in-flight summaries. Clearing also pauses capture, including after session restoration.
- Portable JSON review export with source quotes and a checksum; no automatic import.


Limits: source/structure checks are not semantic verification or proof of completion. Dependency extraction is model-generated. No independent recovery rehearsal, automatic cross-assistant migration, comparative latency result or product-superiority claim.
