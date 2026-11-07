# 机制与数据契约

## 从证据到记忆

本核心接受 `Candidate`，不猜测自然语言含义。`source` 应保留最小必要原话和可追踪的证据位置；`at` 是证据时间，`recorded_at` 是系统接收时间，均须含时区。Agent 不得为了让更新成功而捏造 `intent=change` 或刷新旧证据的时间。

每个主题是单值槽位，例如 `preference.favorite_flower`；“也喜欢百合”不是“最喜欢百合”。多值偏好需要分别定义主题或在未来增加集合语义，不用字符串覆盖模拟集合合并。topic 的同义词归一化在外部适配器完成；NFC 仅消除 Unicode 组合差异，不能理解同义词。

独立维度是重要性、确定性和相关性。重要性在 `[0,1]`，持久记忆默认保留门槛为 0.5，属于可研究的启发式；确定性为 explicit/uncertain/inferred；相关性由调用者选择 topic，本核心没有已验证的自动召回排序。

## 状态机

先验证输入与证据时间，再在单个 `BEGIN IMMEDIATE` 事务中读取旧头、判断和写入：

| 条件（按优先顺序） | 结果 | 持久化 / 改当前头 |
| --- | --- | --- |
| 敏感且无同意 | rejected_sensitive | 否 / 否 |
| persistent 且重要性 < 0.5 | discarded | 否 / 否 |
| 输入已过期 | expired | 否 / 否 |
| intent=retract 且明确、等于当前值 | retracted | 是 / 是（当前值变为空） |
| intent=retract 但不等于当前值 | nothing_to_retract | 否 / 否 |
| uncertain 或 inferred | pending | 是 / 否 |
| 当前有效值相同 | duplicate | 是 / 否 |
| 证据时间早于当前版本（或撤回）且值不同（或当前为撤回） | conflict | 是 / 否 |
| intent=supplement | pending | 是 / 否 |
| 当前值不同且 intent=assert | conflict（`latest` 模式下为 confirmed） | 是 / 否 |
| 无有效旧值，或显式 change/correct | confirmed | 是 / 是 |

intent=supplement 在任何情况下都不直接成为当前值，包括空槽位（“X 也不错”不等于“最喜欢 X”）；该规则于 2026-11-06 由模拟器数据中“撤回后接补充”的错误发现并修改。撤回（retract）必须指明被撤回的当前值；撤回后 head 指向 status=retracted 的事件，`current` 返回空，历史保留；之后的新陈述可重新确立当前值，证据时间早于撤回的旧陈述进入 conflict。含撤回 head 的数据库不能被 0.2.0.dev2 之前的版本读取。相同值不会更新 head、延长 TTL 或改变确定性。event_id 重试必须对应同一候选和 resolves；同 ID 不同内容报错。被拒绝的输入不保存去重回执，因此重试它们会重新判定。

`resolves="pending-event-id"` 需要同主题、同值的 pending/conflict 证据，新输入必须能形成 confirmed 或 duplicate；它记录确认关系，保留原证据。不得把冲突内容自动当作用户确认。未提供 resolves 的新版本仍会更新，但不会声明已解决某个具体待确认项。

## 表结构与一致性

- config：schema=1、codec=dna-v1、index、protection；不匹配拒绝打开，不静默迁移。
- events：seq、全库唯一 id、route、不可变 JSON payload、SHA-256、可选 backup。payload 包含候选、状态、前一确认版本、接收时间和 resolves。
- heads：route -> 当前确认事件，外键约束。pending 和 conflict 不成为 head。修复不改 heads。

每个连接按事务串行比较和更新；测试覆盖独立连接并发。事件历史按写入序列排列，证据时间单独保留；这不是支持任意历史时点查询的双时间数据库。`history` 默认过滤到期事件，包含 pending/conflict/duplicate，不应直接作为“全部事实”输出。调用者可据 `resolves` 识别已处理证据。

scope=persistent 禁止 session 值；scope=session 必须携带 session ID。namespace、subject 由可信宿主提供；它们是逻辑分区，不是登录鉴权。API 调用者能读取整个文件，不应直接暴露成不受信任的网络服务。

## 续期与用户画像

相同值再次写入时，若新证据的到期时间晚于当前版本，记为一次续期：生成同值的新确认版本，事件带 `renewal: true`；否则仍为 duplicate。适配器对 `recent.*` 主题默认设置 30 天到期，因此用户再次提到近期状态时会自动续期。`profile` 按主题前缀把当前记忆分为 basic / preferences / recent / life / projects / other，只读，不改变记忆。

## 更新模式

`ingest(..., update="confirm")` 为默认值：当前值不同且未声明改变（intent=assert）时进入 conflict。`update="latest"` 用于无人确认的场景：证据时间不早于当前值的明确陈述直接成为当前值，事件记录 `policy: "latest"`，`advise` 返回 `auto_updated`。补充（supplement）、不确定或推断的陈述、证据时间更早的不同值，在两种模式下处理方式相同。该模式不写入数据库配置，按次调用指定；适配器支持 `--update latest` 或配置项 `"update_policy": "latest"`。

## 互补如何参与生命周期

`canonical([namespace,subject,topic,scope,session])` 的 UTF-8 字节按 `00=A,01=C,10=G,11=T` 编码，存储互补链为 route。检索生成原链再补成互补链，等值查询 SQLite B-tree。写入先通过同一键定位旧记忆，再判断状态；查询、版本更新和遗忘也按同一键定位。因此互补形式参与全流程，但不增加语义信息。

plain 消融配置直接存规范 JSON。二者都是一一映射、都使用同类 B-tree，预计正确性相同；ASCII ATCG 每原始字节变成 4 个字节。互补冗余以每字节四碱基打包，相当于 `byte XOR 0xff`，长度与普通副本相同。编码版本不兼容时应显式迁移。

重要性分级保护在本版仅通过选择不同保护配置的独立存储实例实现；尚未提供按记录动态冗余预算。互补副本和原数据在同一个 SQLite 文件中，不能抵御文件整体丢失。SHA-256 是完整性校验，不是带密钥的防篡改认证；头指针、索引、摘要元数据和数据库页不在可恢复范围内。

## 时间、遗忘与主动调用

到期状态不再作为 current；旧版本不复活。历史仍可能展示未过期的早期确认；回答“现在”只读 current。没有自动定时清理，长期运行者应明确设置 TTL 与会话清理策略。forget 删除当前主题的主记录、历史和冗余；若需要删除一个 subject 的全部信息，调用者必须枚举其全部主题和 scope，尚无一键 subject 擦除接口。

主动调用限于回答当前问题前检索相关主题，以及出现重大冲突时向用户确认。不要无关地提起私人记忆。当前版本没有后台主动提醒/推送，也没有经过用户研究的主动回忆策略。

## 对话适配层（0.2.0.dev1 + DSH 接入；dev2 扩展见文末）

自然语言到记忆的链路固定为：

```
用户对话 → 宿主模型抽取（topic/value/certainty/intent/importance/source）
         → memorygene-dsh（机械校验与 Candidate 组装）
         → MemoryStore（策略与持久化）
         → JSON 结果 → 模型据 status 回答
```

适配层不做语义理解，只做以下可检查的工作：

- **数据库解析**：`--db` > `MEMORYGENE_DB` > 从 cwd 向上找 `.memorygene/dsh.json` > `~/.memorygene/dsh.json`；都没有报错。数据库缺失时拒绝读写，只有显式 `--allow-create` 才创建（防止切换聊天误建新库）。
- **身份**：`namespace`、`subject` 由配置/显式参数决定，不从内容推断；`scope=session` 自动取 `DSH_SESSION_ID`；persistent 禁止 session。
- **字段校验**：topic 必须是稳定点分名（小写 ASCII），value/source 有长度上限；value 做 NFC 归一（source 保留原话，不改写）；`namespace/subject/topic/value` 在 `Candidate.__post_init__` 统一 NFC，避免规范等价字符串被误判为不同值。
- **来源与同意**：`source` 必须是用户原话的最小证据；敏感信息需要 `--sensitive --consent --consent-evidence "用户原话"`，布尔值单独不构成同意；同意原话以标记形式追加进 source 供审计。
- **时间**：`at` 缺省为适配器当前 UTC 时间；`recorded_at` 由核心写入；不伪造历史时间。
- **新库权限**：适配器显式创建的数据库设为 0600；适配器配置也写 0600。

## 状态机的补充约定

- 证据时间**严格更早**且值不同才按乱序冲突处理；过期 head 与更早的同值重新陈述不构成 conflict，而是 confirmed（与上表“无有效旧值”一致）。
- 证据时间相同、值不同且没有 change/correct：进入 conflict，不覆盖当前值。
- `duplicate` 保留证据行但当前 head 不变，也不延长 TTL。
- `event_id` 幂等重试返回**历史事件本身**（其 `status` 是当初写入时的状态，不重新解释）；要判断“现在是否 current”必须再查 `current`。
- 损坏的检测范围分两层：payload/digest 字节损坏在读写该事件时严格失败关闭；`route`/`heads` 元数据损坏可能让单主题读取看起来“为空/缺事件”，需要用只读的 `verify()` 全库扫描才能发现。`verify` 不修复、不改 heads。
- 打开已存在的 SQLite 文件时，若发现不属于 MemoryGene 的表，拒绝纳管（防止把无关数据库注入 schema）。

## 只读索引与完整性 API

- `topics(namespace, subject)`：按路由解码出主题、scope/session、当前状态与证据计数；用于回答前定位。解码失败或事件损坏时失败关闭。
- `verify()`：全库扫描 events 与 heads，报告字节/摘要/身份/路由不一致、head 指向未确认/缺失/路由不符事件、head 回滚（不是该 route 最新 confirmed）与「有 confirmed 却无 head」。只检测不修复；不检测被删除的非 head 历史事件。
- CLI 对应 `topics --namespace --subject`、`verify`；适配器对应 `memorygene-dsh topics`、`memorygene-dsh verify`。

## dev2：recall 与任务接续（设计边界）

- **recall**：对当前 head 做字面词项匹配（中文 bigram、英文/数字词，NFKC+casefold），按命中权重排序，返回数量上限与字符预算内的线索（id/topic/scope/短预览/命中字段）。它是检索提示，不是语义搜索；调用方必须用 `current` 复核完整值与来源。只读、不强化记忆；预算单位是 Unicode 字符，不是 token。
- **任务接续**：调用方把目标/约束/修正/已完成/未决/下一步整理成受约束的 JSON（`sources` + `items`），核心校验引用、长度与必填类别后保存为 `task-v1` 记录。每次保存读取当前最新版本并要求 `previous_id`，形成版本链；显式 memory 来源绑定 `event_id` 与内容摘要，读取时重新核对当前版本（变更/过期即 `stale`，不返回正文）。记录按 identity + task + session 路由；跨会话恢复必须精确 ID 且显式 `--allow-cross-session`，带 session 记忆依赖的记录不能跨会话。`task-forget` 删除该 route 全部版本；`forget --topic` 在同一事务清除显式依赖该记忆的所有任务版本。`verify` 增加任务字节/路由/摘要/版本链检查（不检测整条任务被外部删除）。
- **存储与兼容**：`task_checkpoints` 是同一 SQLite 文件中的可选扩展表，首次成功保存才创建；核心 config 仍为 schema 1。存在该表后 dev1 会拒绝打开数据库，属显式兼容边界。
- **外来库拒绝**：打开已存在的文件时必须有 `config/events/heads` 三张核心表且无未知表，否则拒绝纳管；不能仅凭表名（如 `task_checkpoints`）判断是 MemoryGene 库。
- **非目标**：recall 不做同义词/语义排序；任务接续不自动概括整段对话、不替换/压缩宿主上下文、不验证对话 locator；二者都不构成权限控制。

## 0.2.0.dev2+：再巩固支持（只读）

`reconsolidate.py` 不改表结构、不写库；状态机仍是唯一改变记忆的路径。

- **定位 `locate`**：识别线索 = 主题名词项 + 值与原话的中文双字/词项，按该用户各槽位中的稀有度加权。主题部分用加权 Dice，内容部分用重叠系数（避免证据越多越稀释）。**锚定**规则：任一主题的属性词（主题名最后一个词）出现在另一方，或两个值明显相关（相同、互相包含、或较短值的线索至少一半重合；长文本里偶然共享几个词不算）；只共享 `preference`/`favorite` 这类类别词不算。
- **未解决证据 `open_evidence`**：pending/conflict 且没有被 `resolves` 指向、之后没有任何 confirmed、不等于当前值、未到期。
- **建议 `advise`**：`confirm_change`（明确且更新的说法因未声明改变而进入 conflict）、`possible_same_slot`（新主题首次确认且与已有槽位锚定）、`repeated_uncertain`（同一不确定值在不同时间出现至少两次）。只是建议，执行仍需用户确认后的显式写入。
- **`recall.unresolved`** 与 **`review`**：把悬而未决的证据以 `not_a_fact` 标出，供宿主在相关时询问；不把它们当答案。
- **双链配对 `strands.pairing`**：值（精简链）必须能和原话（证据链）配对：被原话包含，且同一分句内值前没有否定词。配不上时 `advise` 给出 `unpaired_value`，`review` 列出 `unpaired_current`；只提醒，不自动修复。默认规则是看过预注册实验结果后选的，见 [experiments/STRANDS.md](../experiments/STRANDS.md)。
- 局限：字面线索，不懂上下位关系（茶⊂饮品）；相同值会被当成强线索（“计划吃火锅”与“最喜欢火锅”可能被误提示）。评估见 [experiments/RECONSOLIDATION.md](../experiments/RECONSOLIDATION.md)。
