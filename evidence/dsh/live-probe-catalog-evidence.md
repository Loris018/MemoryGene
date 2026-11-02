# Live headless probe: raw skill-catalog evidence

Decompressed from the persisted session logs (`session.v4.jsonl.zstd`) that each run wrote,
so this is deterministic: the catalog is a durable `user/message` event whose source carries
`kind: skill-catalog`. No model output is involved in this extraction.

## positive — throwaway dummy skill, cwd=/tmp/mg-probe-project (invoking dir)

- session id: `session-510a6e7c-4915-4e96-94d8-18f044897f02`
- header cwd: `/private/tmp/mg-probe-project`
- skill-catalog user messages: 1
- catalog seq: 10
- entries: `[{"name": "dsh-probe-dummy", "description": "Fictional throwaway probe skill used once to prove that a project-scoped DSH skill is discovered by a real headless session."}]`

```text
<system-reminder>
A skill is a reusable set of task-specific instructions. The following skills are available in this session:

<available_skills>
- `dsh-probe-dummy`: Fictional throwaway probe skill used once to prove that a project-scoped DSH skill is discovered by a real headless session.
</available_skills>

If the user names a skill, or the task clearly matches a skill's description, call the `skill` tool with the exact skill name before taking task actions. Load all applicable skills, then follow their full instructions. This catalog contains summaries only; do not infer or follow a skill's instructions until it has been loaded.
A user may also invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool again for that skill.
</system-reminder>
```

## negative — same prompt, cwd=/tmp/mg-probe-control (no scanned root)

- session id: `session-08abee69-2213-4211-8730-8a3a2ada6f8e`
- header cwd: `/private/tmp/mg-probe-control`
- skill-catalog user messages: 0

## subdir — throwaway dummy skill, cwd=/tmp/mg-probe-project/sub (no .git in cwd)

- session id: `session-a9843874-ba91-437a-aec5-466210d20f3a`
- header cwd: `/private/tmp/mg-probe-project/sub`
- skill-catalog user messages: 1
- catalog seq: 10
- entries: `[{"name": "dsh-probe-dummy", "description": "Fictional throwaway probe skill used once to prove that a project-scoped DSH skill is discovered by a real headless session."}]`

```text
<system-reminder>
A skill is a reusable set of task-specific instructions. The following skills are available in this session:

<available_skills>
- `dsh-probe-dummy`: Fictional throwaway probe skill used once to prove that a project-scoped DSH skill is discovered by a real headless session.
</available_skills>

If the user names a skill, or the task clearly matches a skill's description, call the `skill` tool with the exact skill name before taking task actions. Load all applicable skills, then follow their full instructions. This catalog contains summaries only; do not infer or follow a skill's instructions until it has been loaded.
A user may also invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool again for that skill.
</system-reminder>
```

## real-project — installed MemoryGene skill, cwd=MemoryGene project (git repo)

- session id: `session-c7af3dac-422d-4659-9f85-65ff1b23442e`
- header cwd: `<repo>`
- skill-catalog user messages: 1
- catalog seq: 10
- entries: `[{"name": "memorygene", "description": "用 MemoryGene 本地 SQLite 记忆库保存用户明确陈述的长期事实与偏好，支持跨会话查询、明确修订、历史、到期过滤与遗忘。数据只写本地库，不联网。"}]`

```text
<system-reminder>
A skill is a reusable set of task-specific instructions. The following skills are available in this session:

<available_skills>
- `memorygene`: 用 MemoryGene 本地 SQLite 记忆库保存用户明确陈述的长期事实与偏好，支持跨会话查询、明确修订、历史、到期过滤与遗忘。数据只写本地库，不联网。
</available_skills>

If the user names a skill, or the task clearly matches a skill's description, call the `skill` tool with the exact skill name before taking task actions. Load all applicable skills, then follow their full instructions. This catalog contains summaries only; do not infer or follow a skill's instructions until it has been loaded.
A user may also invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool again for that skill.
</system-reminder>
```
