# MemoryGene automatic continuity for DeepSeek Harness

Experimental native plugin targeting the locally inspected **0.2.2-rc.3** event API.
This extends task continuity; it does not replace MemoryGene's long-term personal-fact policy.

## 0.2 task cards and change impact

Two session-scoped native tools are now available. Ask the assistant naturally:

- “显示当前任务卡，哪些完成了、哪些还要复查？” → `memorygene_task_card`.
- “把纸张要求更正为 A1。” → read the card, then `memorygene_task_update` with exact current-user evidence and the latest revision.
- “这个待办已完成／已取消。” → user-reported status, not independently verified completion.
- “我已按新要求重新检查这个成果。” → `recheck` updates its dependency basis as a **user report**, never an automatic test pass.
- “暂停自动记录／恢复自动记录。” → stops or resumes capture and background generation. A pause survives content expiry.
- “删除这条任务记录。” → suppresses its key and source event from future background generation in this cache. Other notes sharing an event may lose summarization evidence; inspect the resulting card.
- “清空这次任务卡并暂停。” → clears plugin content, pauses and invalidates in-flight work. It does not erase the host transcript, already-injected context or the personal-memory database.
- “导出接续包。” → a portable JSON review packet with origins and a checksum. This is **not** an automatic cross-assistant import, a signature, or permission to execute its contents.

Background notes use stable requirement keys and explicit artifact dependency keys. Changing a requirement marks linked outputs for review, including downstream outputs. Missing dependencies and cycles remain uncertain. Unrelated recorded outputs are not automatically invalidated. Model-extracted dependency edges can be incomplete or wrong; `basis_unchanged` means the recorded basis text is unchanged, not that the artifact is correct. Paraphrasing a requirement may cause a conservative false alarm.

Before reuse, source quotes are rechecked on exact-session restore. A lightweight structural check reports missing goals, missing next steps, omitted/renamed requirements, history gaps and pending user changes. **No model-based recovery rehearsal is implemented yet.** The task card is exposed through normal conversation tools; there is no separate graphical dashboard.

## What runs automatically

- `session/event`: capture bounded excerpts of direct user messages, visible assistant text, and tool results. Excludes reasoning, system instructions, synthetic context, tool arguments and private metadata.
- `step/end` and `turn/end`: after six new records, request a small task note through the host's existing model route, in the background. A 30-second cooldown and one global in-flight job bound work. No extra API key is read or stored.
- `agent/pre-step`: consume a ready note without awaiting model generation. Restore recent unsummarized excerpts on an exact-session resume. Inject new notes once per covered watermark, not on every tool call.
- Atomic, serialized cache writes preserve recent events arriving during generation. Incomplete/invalid generation cannot advance the watermark. A failed worker leaves raw excerpts available.

Default cache: `$DSH_HOME/memorygene-continuity/`, otherwise `~/.dsh/memorygene-continuity/`. Files are session-keyed, use private filesystem permissions and expire on read after seven inactive days. Expiry is lazy: unused expired files are not automatically swept. Restarting or disabling the plugin cancels unfinished generation; already captured excerpts remain. Delete a session's cache to remove its automatic notes. The host's original session history is separate.

## Evidence and limits

Every note cites exact source sequence numbers and quoted substrings. Quotes are checked against the input; user decisions require user evidence. On resume, cited sources are rechecked against that exact host session. This verifies provenance, **not meaning or task success**. Assistant completion claims remain claims. Excerpts are capped at 1600 characters; the newest 80 are cached, with an explicit gap indicator if unprocessed records are dropped. Context is capped at 10000 characters with an omission flag.

This prototype does not:

- shorten, disable or replace the host's own compaction;
- silently create or update long-term personal facts;
- resume another session or bypass the existing explicit cross-session task binding;
- prove zero latency, lower total token costs or better task success;
- prove that model-extracted dependencies are complete or implement model-based recovery rehearsal;
- synchronize task-cache deletion with `memorygene forget` (separate stores and lifetimes).

Background requests use the same provider/model as the foreground agent and consume that provider's quota. They may compete for rate limits even though the foreground does not await them. No new subagent is spawned.

## Install and verify

From the repository, use the installed DSH CLI:

```sh
dsh plugin --profile desktop add ./plugins/dsh-memorygene-auto
```

Select the `dsh-memorygene-auto` bundle in the host's plugin manager if it is not already selected. The saved bundle selection alone does not prove activation; observe a new session's cache and host runtime. A host restart may be required. Back up profile manifests before changing them. Remove using the same plugin manager, or with `dsh plugin --profile desktop remove dsh-memorygene-auto` after deselection.

For isolated testing, insert the absolute `index.js` module path with a `--patch` overlay and set `stateDir` to a temporary directory. Do not use real personal data for tests.

```sh
node --test plugins/dsh-memorygene-auto/test/*.test.js
```

Tests cover exact-quote admission, source roles, slow generation plus newer corrections, duplicate delivery, bounded output, session isolation, expiry, and nonblocking native callbacks.
