# 代码、测试与审计记录

> 本文主体是 2026-10-24/27 的历史审查记录，保留供追溯；旧 GO 不代表当前版本的再次独立审计。
> **当前（2026-10-29 dev2）证据**：139 项源码测试、12 场景/52 检查、dev2 任务接续 2 个 + dev1 链路 4 个真实 headless 会话；
> 本轮维护修复见 [ACCEPTANCE §7](ACCEPTANCE.md) 与 [evidence/09-maintenance-2026-10-29](../evidence/09-maintenance-2026-10-29/README.md)。

审查对象：重建的 0.2.0.dev1 基线（git 提交 `4bb7306`）与本轮 DSH 接入改动。
审查方式：本地代码路径检查、自动测试与实验、独立只读审计（另一代理，基线导出树 + 发布 ZIP 复核）、以及真实 Harness 会话验收。没有独立外部安全审计。

## 基线独立审计结论（4bb7306）

独立审计对 `core.py`/`codec.py` 做了 500 步 plain/complement 差分 fuzz、500 步不变量 fuzz、300 次随机损坏 fuzz、8 线程并发、配置守卫矩阵：**未发现错误值或状态机裂缝（P0 = 0）**。36 项基线测试在 Python 3.11.7 / 3.12.10 / 3.13.3、发布 ZIP 与 wheel 内均通过；实验语义计数与 git/ZIP/sdist 一致（计时数字除外）。完整报告与复现脚本：`evidence/review/audit-initial.md`、`evidence/review/logs/`、`evidence/review/scripts/`。

审计发现 4 项 P1，本轮处理如下：

| 编号 | 问题 | 本轮处理 | 状态 |
| --- | --- | --- | --- |
| P1-1 | 读/删命令在不存在的工作路径上静默新建空库，`forget` 可返回“删除成功”假象 | CLI 的 current/history/topics/forget/repair/verify 要求库已存在；适配器全部命令默认拒绝隐式建库，只接受显式 `--allow-create` | 已修复，含回归测试 |
| P1-2 | 指向其它应用的非空 SQLite 文件会被静默纳管并注入表 | 打开时检查既有表集合；出现非 MemoryGene 表立即报错并关闭，不写任何表 | 已修复，含回归测试 |
| P1-3 | “损坏 fail-closed”承诺过宽：route/heads 元数据损坏会让单主题读取静默返回空/缺事件 | 新增只读 `verify()` 全库扫描检测元数据损坏（含 head 回滚与缺失 head）；README/SECURITY/AUDIT 明确限定“payload/digest 字节损坏严格失败关闭；元数据损坏需 verify 检测” | 已修复（检测）并收紧文档；单主题读路径不做全库扫描，属明确限制 |
| P1-4 | 仓库 `results.json` 与 ZIP/sdist 内数字/环境不一致，`RESULTS.md` 只对 ZIP 成立 | 最终环境统一重跑实验，更新 `RESULTS.md`/`results.json`/VALIDATION，重建 wheel/sdist/ZIP | 已修复 |

P2 处理：value 做 NFC（核心 `Candidate.__post_init__` + 适配器）；新建数据库 0600；适配器配置 0600；`local-memory.db` 不再进入发布包；`--index/--protection` 需重复的用法已写入说明；幂等重试返回历史事件状态的语义已写入 DESIGN。`scenarios.json` 中两案例共用 topic `health` 的风险已消除（拆成独立主题）。

## 已落实的关键不变量（本轮扩展）

| 风险 | 实现与验证 |
| --- | --- |
| 将犹豫、推测或“也喜欢”误作已改变 | certainty 优先于 change/correct；supplement 保持 pending；测试 current 不变 |
| 无标记冲突覆写旧值 | 已有不同值的 assert 进入 conflict；显式确认才创建新版本 |
| 恢复把合法的新偏好改回旧偏好 | 每个事件独立摘要和冗余；repair 不操作 heads；损坏最新版本后仍恢复最新值 |
| 不同用户/会话混用 | 五维规范 JSON routing；查询与写入相同分区；跨 subject 的 resolves 拒绝；错误跨分区头指针失败关闭 |
| 重试或并发重复更新 | event_id 幂等及内容检查；BEGIN IMMEDIATE 锁住比较与更新 |
| 来源时间错序 | 时区必须明确；未来证据拒绝；更早且不同值不覆盖；过期 head 的同值重述按“无有效旧值”确认 |
| 到期后旧偏好复活 | current 只检查当前头的到期状态，不搜索历史替代；过期候选不落库 |
| 无同意的敏感信息泄漏到副本 | 拒绝前不写事件，不生成冗余；测试数据库事件数为零；适配器要求同意原话，布尔值不足 |
| 删除后副本重建私密数据 | forget 原子删除头与同主题全部事件/backup；repair 已删 ID 报不存在 |
| 副本损坏无法判断真实值 | SHA-256 必须通过；两份数据或摘要丢失则报错；主数据健康可重建备份 |
| 配置丢失或错读编码版本 | 非空库缺失 config、schema/index/protection 不匹配拒绝打开 |
| 误建新库 / 纳管外来数据库 | 读/删命令要求库存在；适配器默认拒绝建库；已存在的文件必须含 config/events/heads 核心表且无未知表，否则拒绝（含只有 task_checkpoints 的库；2026-10-29 修复回归并加测试） |
| 单主题读取漏掉元数据损坏 | `verify()` 全库扫描报告 route/heads 异常、head 回滚与缺失 head；单主题热路径不做全库扫描（明确限制） |
| 合法新版本被“恢复”回滚 | repair 只改 payload/backup 字节，不改 heads；测试确认 head 不变 |
| 输入无上限 / Unicode 规范化差异 | 适配器限制 topic/value/source/event_id 长度并做 value NFC；核心 Candidate 对身份与值做 NFC，source 保持原话 |

## 历史验证（2026-10-24 dev1，Python 3.11.7）

- 测试：当时 **92/92 通过**（历史 dev1 数字；当前 dev2 为 139/139）。
- 结构实验：24 组场景规则配置 24/24 当前与 24/24 历史；普通/互补索引一致；等预算恢复普通/互补相同。
- 自然语言原型评估：47 组虚构多轮 / 79 轮，写入决策 77/79、topic 57/57、value 56/57、certainty 57/57、source 57/57；提取错误 5 例、存储策略错误 0 例（案例与规则同期开发，不是留出集）。
- 库级验收：当时记录 12 场景 / 47 项；其中存在判定假通过，已被 2026-10-27 的 52 项严格验收取代。
- 真实 Harness 跨会话验收：4 个独立 headless 进程 / 4 个不同 session id，写入→读取→修订→遗忘 4/4 通过（`evidence/01-e2e/harness-results.json`）。
- GUI 会话：catalog 实际出现 `memorygene` 并由 `skill` 工具载入；虚构自测全流程通过（`evidence/00-install/gui-session-evidence.md`）。
- 包构建与安装：`ruff check` 0 问题；`python -m build` 产出 wheel/sdist；`twine check` 通过；在独立干净 venv 中安装 wheel 后 import、CLI、测试通过（详见 `docs/VALIDATION.json`）。

## 尚未解决或尚未验证的范围

- 没有自然语言提取器的独立留出集实测：`experiments/nl_eval.py` 是规则原型回归/质量检查，不是 NLU 基准。
- 没有在 GUI 桌面对话中由人工逐项点选完成 11 项验收；GUI 侧只验证了 catalog/载入与一次虚构自测，跨会话强证据来自 4 个独立 headless 进程。
- 相同值不新建当前版本，但重复证据仍占存储；没有物理去重或容量上限。
- 没有自动会话清理、后台 TTL 清理、按记录自适应冗余预算或 subject 一键全删。
- 同文件副本不是灾备；不支持 SQLite 页损坏、全文件丢失、防恶意重写摘要；`verify` 可发现 route/heads 元数据异常、head 回滚与缺失 head，但不检测被删除的非 head 历史事件，单主题读取也不会主动全库扫描。
- 逻辑删除不是物理安全擦除；没有加密、鉴权、网络服务或多租户权限系统。
- 实际运行验证为 Python 3.11.7（另由独立审计在 3.12/3.13 验证基线）；远端 CI 矩阵及 Windows/Linux 尚未执行。
- 自动接入（每轮强制 recall/write）未实现；本项目只提供显式 Skill 调用与可选提示词约定，见 `docs/DSH-INTEGRATION.md`。

本轮测试、静态检查、包构建和安装验证的实际命令与结果由 `docs/VALIDATION.json` 记录；验收证据索引见 `docs/ACCEPTANCE.md`。


## 交接后补丁（2026-10-27，跨项目自动指令）

交接后新增“跨项目自动”开关：`scripts/install_global_auto.py` 写入用户级
`~/.dsh/AGENTS.md`（提示词约定，非宿主强制），并复用已安装的用户级 Skill。改动范围仅新增脚本/
模板/测试/文档，**核心记忆逻辑与 0.2.0.dev1 包代码未改**；测试 92/92，ruff 通过。验证证据见
`evidence/05-global-auto/README.md`（两个不同项目、未提 skill 名称的写入与召回，L1）。
最终 ZIP 在该补丁后重建；独立审计 GO 结论针对核心与 0.2.0.dev1 主发布内容，
`../MemoryGene-0.2.0.dev1-dsh-MANIFEST.json` 记录最终哈希与补丁说明。


## 2026-10-29 dev2 维护审查（本轮）

在 GPT 完成 0.2.0.dev2（recall + 任务接续）后，本轮做了只读复核与交付修复：

- **复核通过**：139 项测试、ruff、12 场景/52 检查；dev2 任务接续 2 个真实 headless 会话的原始事件与 13 项检查一致；dev2 wheel 与解压 ZIP 在干净 Python 3.12 环境复跑 139 项通过；生产库仍为 4 条用户记忆、无 task_checkpoints 表，逻辑摘要 `9a9618…`（sqlite iterdump）未变。
- **修正**：旧 47/47 的假通过已由 GPT 的守卫测试修复并记录在 `MAINTENANCE-2026-10-27.md`；本轮把交付物/文档统一到 dev2、重建 dev2 ZIP/MANIFEST，修复“只有 task_checkpoints 的外来库被纳管”的回归，并澄清 VALIDATION 的 base commit 与生产库逻辑摘要算法。
- **未解决/边界**：任务接续不自动概括或替换宿主上下文；conversation locator 未独立验证；首次建任务表后 dev1 不兼容；recall 是字面检索；GUI 人工验收仍未完成；远端 CI/Windows/Linux 未验证；自动每轮提示仍是提示词约定，不是宿主强制。
- **独立审计状态**：2026-10-29 的最终独立审计 GO 针对 dev1 核心发布；dev2 新增功能由维护者复核 + GPT 已记录的证据支撑，尚未由独立第三方重新审计。
