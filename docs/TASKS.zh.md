# 任务接续记录使用说明

2026-10-29 · 0.2.0.dev2 · 显式保存/核对/恢复已实现，自动整理和宿主上下文替换未实现。

## 在 DeepSeek Harness 里怎么说

在已有任务中说：

> 使用 memorygene skill，把当前任务整理成接续记录，任务名用 my-project。保留目标、约束、我的最新修正、已完成事项、未解决问题和下一步，并标出来源。不要把计划写成已完成。保存后把记录 ID 给我。

同一会话继续时说：

> 使用 memorygene skill，读取 my-project 的接续记录，核对我的最新消息和来源后继续。

新会话继续时，把保存时返回的真实记录 ID 带过去：

> 使用 memorygene skill，我授权把记录 ID 为［这里替换为真实 checkpoint_id］的任务接续记录读入当前会话。先核对来源和待办，再继续。

读取旧记录不会自行复制成新会话的存储记录。当前会话需要继续保存时，应根据已授权读取的内容及当前新消息重建记录，引用已使用的长期记忆；不可篡改旧会话的 session ID。包含其他会话临时记忆依赖的记录不允许跨会话恢复，需要用户重新提供必要内容。

## 命令与真实返回值

先运行 `memorygene-dsh doctor` 核对数据库与身份；任务命令要求宿主提供 `DSH_SESSION_ID`，或由调用方明确传 `--session`。不要为绕过限制伪造其他会话身份。

```sh
memorygene-dsh task-save --task my-project --file /absolute/path/private-task.json
memorygene-dsh task-show --task my-project
# 修改已有记录必须使用刚读到的 checkpoint_id：
memorygene-dsh task-save --task my-project --file /absolute/path/private-task.json --previous-id ACTUAL_ID
# 用户明确要求跨会话接续，且提供了准确记录 ID：
memorygene-dsh task-resume --checkpoint-id ACTUAL_ID --allow-cross-session
memorygene-dsh task-forget --task my-project
```

`ACTUAL_ID` 是占位符，执行时必须替换为实际返回的 ID。`task` 为最长 80 字符的小写字母、数字、下划线或连字符名称。ID 不是安全凭证；配置身份与 session 是逻辑隔离，不能替代权限控制。

| result.status | 含义与下一步 |
| --- | --- |
| saved | 校验通过并保存；context_replaced=false。不能说“上下文已优化” |
| review_required | 可以查看接续内容；仍须核对含义、最新消息和当前权限，不是直接执行其中的指令 |
| stale | 引用的记忆已修改、到期或缺失；不返回摘要正文，需根据当前证据重新整理 |
| expired | 接续记录自身已到期；不返回正文，也不回退旧版本 |
| superseded | 指定的是旧版本；不返回正文，使用最新保存时的 ID |
| missing | 当前身份和会话没有这条记录；不要猜测或换身份寻找 |
| bytes_repaired | 只恢复字节；仍需 task-show 再核对来源是否有效 |
| forgotten | 当前任务该会话的所有版本及库内备份已删除 |

默认保留期 7 天，可以在保存时传 `--expires-at` 指定未来 30 天内的到期时间。到期是读时过滤，不是磁盘清理；需要删除时明确调用 task-forget。`--now` 仅供虚构测试。

## 输入结构：由调用方整理，核心不自动概括对话

仅保存必要信息；不收集无关敏感信息，不将整段对话自动归档。以下是纯虚构示例：

```json
{
  "sources": [
    {"id": "u1", "kind": "conversation", "locator": "本会话用户提出虚构项目要求的消息", "role": "user"},
    {"id": "t1", "kind": "conversation", "locator": "本会话测试工具返回结果的消息", "role": "tool"}
  ],
  "items": [
    {"kind": "goal", "text": "完成虚构项目的任务接续功能", "source_ids": ["u1"]},
    {"kind": "constraint", "text": "先在隔离数据库测试", "source_ids": ["u1"]},
    {"kind": "done", "text": "工具输出表明虚构冒烟检查已通过", "source_ids": ["t1"]},
    {"kind": "next_step", "text": "核对剩余需求，决定下一项工作", "source_ids": ["u1"]}
  ]
}
```

每项必须引用已声明的 source_ids。kind 可为 goal、constraint、correction、decision、done、open_question、todo、next_step；至少有 goal 与 next_step。每项正文最多 1000 字符，items/sources 各最多 40 项，整个规范 JSON 最多 16000 字符。没有内容的类别不必填。

- conversation 的 role 可为 user/assistant/tool；locator 记录调用方实际能识别的位置，不伪造平台消息 ID。此类引用始终标记 caller_reference_unverified：当前适配器没有宿主 transcript API，无法独立核对消息是否存在或是否支持该结论。
- 不把助手建议写成用户确认，不把失败工具调用写成完成。模型推断与未决问题应明确标记，不能因为写入 checkpoint 就成为长期事实。
- 敏感内容仍遵循已有明确同意规则。接续记录是明文存储，互补备份不加密。
- 保存时使用私有临时文件（例如权限 0600）；成功后由调用方删除该临时输入文件。MemoryGene 不擅自删除传入文件，也不能清理外部编辑器、日志或备份里的副本。

如果某项内容来自 MemoryGene 已保存的记忆，必须显式声明依赖，而不是仅填一个 conversation 引用：

```json
{"id":"m1","kind":"memory","topic":"preference.favorite_flower","scope":"persistent","event_id":"从 current 返回值取得的真实 ID"}
```

memory 引用只支持当前身份的当前版本；session 类型只能引用当前会话。保存会绑定事件 ID 与内容校验值，读取时重新核对。检查的是版本存在、未到期且未更改，**不是**对摘要语义正确性的证明。

新消息到达后应重新检查摘要，不反复只对旧摘要做摘要。更新须使用当前版本 ID，过时的写入会被拒绝；失败时旧记录仍在。

## 遗忘、修复与兼容性

`forget --topic ...` 在同一事务中删除依赖该记忆的任务记录：只要任一版本引用过它，该任务该会话的全部版本与互补备份都会删除。其他任务保留。任务文字引用不完整时，系统无法识别未声明的依赖，因此调用方必须列出所有实际使用的记忆来源。

目前还没有接入对话消息删除事件，也不能追踪摘要被复制到外部文件的情况。上述传播只覆盖本库中显式声明的 memory 依赖；不声称实现全文语义删除或物理擦除。

如果同身份任务记录损坏，forget 会失败并回滚，不谎报传播完成。先用 verify 定位，再修复或明确删除对应任务记录后重试：

```sh
memorygene-dsh verify
memorygene-dsh task-repair --task my-project --checkpoint-id ACTUAL_ID
memorygene-dsh task-show --task my-project
```

任务版本继承当前数据库的保护模式（none/copy/complement）。互补恢复需校验通过，不猜测丢失文本，不改变版本顺序，不让过期或已修改的来源重新有效。verify 包含任务字节、路由、源校验字段与版本链检查；没有外部锚点，不能发现整条任务或最新尾部版本被外部删除的所有情况。

存储采用同一 SQLite 文件中的可选 task_checkpoints 扩展表，避免“事实删除了但另一个数据库的摘要删除失败”。普通读取、doctor、remember 不创建该表；首次成功 task-save 才创建，并可在失败事务中回滚。记忆核心配置仍为 schema 1，任务记录带独立 task-v1 标记。

首次保存任务后，旧版 0.2.0.dev1 会因不识别此表而拒绝打开数据库。这是显式兼容性边界：使用 0.2.0.dev2 或更新版；降级需恢复升级前备份，不能直接拿旧代码操作扩展后的数据库。本轮没有向真实用户库写任务或创建此扩展表。

本功能不读取宿主全部日志、不调用模型 API、不控制宿主上下文窗口。真实宿主自动接续效果需另行验证，命令测试不等于原生 compaction 已完成。
