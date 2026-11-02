# 验收记录（2026-10-24）

> 2026-10-27 接手复查纠正了旧验收（原 47/47）中的假通过问题；2026-10-29 dev2 又加入 recall 与任务接续。
> **当前证据**：139 项源码测试、12 场景/52 项库级检查、dev2 任务接续 2 个真实 headless 会话、dev1 链路 4 个真实会话。
> 见 [维护记录](MAINTENANCE-2026-10-27.md)、[dev2 验证](../evidence/08-tasks/validation.json) 与 [本轮维护修复](../evidence/09-maintenance-2026-10-29/README.md)。
> 以下旧记录保留供追溯；旧 GO 不代表本轮再次独立审计。

设备：本机 macOS / Python 3.11.7（项目 `.venv`）/ DeepSeek Harness 桌面版 0.2.1-rc.2。
所有人物、偏好、地址、号码均为虚构。证据层级：**L1** = 真实进程/真实宿主执行；**L2** = 基于安装源码的规则复现；**L3** = 单元/集成测试。

## 1. 需求 → 证据对照

| # | 要求 | 结果 | 证据（L1/L2/L3） |
| --- | --- | --- | --- |
| 1 | 一句话的重要信息能被保存 | `confirmed`，库中可查回 | `evidence/02-e2e/acceptance-results.json` S01；`evidence/01-e2e/A-write-events.jsonl`（真实 headless 会话） |
| 2 | 重复的无关内容不持续积累为长期事实 | 5 次 `discarded`，事件行数不增；重复重要事实只保留 1 个当前版本（重复证据按设计保留） | S02 |
| 3 | “最喜欢玫瑰”后说“栀子花也好看”，当前最爱仍为玫瑰 | 补充写入为 `pending`，current 仍玫瑰 | S03；真实会话 B（`harness-results.json`） |
| 4 | 明确说“现在最喜欢栀子花”，当前更新、历史保留玫瑰 | current=栀子花；confirmed 历史=玫瑰→栀子花 | S04；真实会话 C |
| 5 | 未明确确认的冲突不覆盖 | `conflict`，current 不变 | S05 |
| 6 | 新会话和重新打开数据库后仍能正确查询 | 每个适配器调用都是独立进程；3 次新进程读取一致 | S06；真实 4 个独立 Harness 会话（不同 session id） |
| 7 | 不同用户及不同会话隔离 | 其它 subject 读不到；session 记忆不出现在 persistent，其它 session 读不到 | S07 |
| 8 | 到期记忆不再被当作当前事实 | 到期后 current=null、history 过滤、topics 状态 expired | S08 |
| 9 | 用户要求遗忘后主题主记录/历史/冗余副本都从逻辑库删除 | forget 后 current=null、history=[]、topics 无该主题；按 payload/backup 字节扫描无残留 | S09；真实会话 D |
| 10 | 损坏恢复不会回滚合法新版本 | payload 损坏失败关闭；repair 后仍是最新值，heads 不变 | S10 |
| 11 | 无法校验恢复时明确报错、不猜测 | `No verified copy; refusing to guess`，退出码 2，字节未被改动 | S11 |

补充：敏感信息无同意不落库（S12；真实 headless 首次尝试还证明了“缺库时拒绝隐式建库”）。

## 2. 三层验收结果

### 2.1 单元/集成测试（L3）

```sh
.venv/bin/python -m unittest discover -s tests -v
```

**139/139 通过**。覆盖：编码/校验/等预算恢复、状态机、隔离、并发、损坏/修复、遗忘、
`topics` 索引、`verify` 全库扫描、适配器身份/建库/同意/会话规则、CLI 拒绝误建库与外来数据库、
`recall` 预算与作用域、任务接续（来源校验/版本链/跨会话/遗忘传播/备份恢复）、自然语言提取原型。
日志见 `docs/VALIDATION.json` 与 `evidence/09-maintenance-2026-10-29/`。

### 2.2 库级验收（L1，独立进程 + 直接 SQL 检查）

```sh
.venv/bin/python scripts/acceptance.py
```

**12 场景 / 52 项检查全部通过**（dev2 在 dev1 的 47 项基础上增加了会话主题隔离与更严格的判定）。每个检查都由脚本以独立进程调用真实
`memorygene-dsh`，再用只读 SQLite 连接独立复核数据库，不依赖模型或适配器自述。
结果：`evidence/02-e2e/acceptance-results.json`；完整命令记录：`evidence/02-e2e/acceptance-log.txt`；测试库：`evidence/02-e2e/acceptance.db`。
历史：dev1 的 47/47 含判定缺陷，不可采信，见 `docs/MAINTENANCE-2026-10-27.md`。

### 2.3 真实 Harness 跨会话验收（L1）

```sh
.venv/bin/python scripts/e2e_harness.py
```

4 个**独立 headless Harness 进程**（各自 session id），同一数据库：

| 会话 | session id | 任务 | 结果 |
| --- | --- | --- | --- |
| A | `session-403b2666-…` | 使用 memorygene skill 写入“最喜欢玫瑰” | `confirmed`，DB 当前值=玫瑰 |
| B | `session-15b3232d-…` | 跨会话读取；记录“栀子花也好看”为不确定补充 | 当前仍玫瑰，pending 证据存在 |
| C | `session-f92ee108-…` | 明确修订“现在最喜欢栀子花” | current=栀子花，confirmed 历史=玫瑰→栀子花 |
| D | `session-9d8e3503-…` | 遗忘该主题 | current=null，topics 无该主题 |

**4/4 通过**，session id 全不相同；每轮都由模型调用 `skill` 工具并执行适配器命令（见
`*-events.jsonl` 中的 `tool_call`）。结果：`evidence/01-e2e/harness-results.json`；
原始事件流：`evidence/01-e2e/*-events.jsonl`；持久化会话文件：`evidence/01-e2e/*-session/`；
完整命令：`evidence/01-e2e/harness-log.txt`。

证据层级说明：这是真实宿主进程与真实模型，但由脚本发起（headless），不是用户在 GUI 中手点。
GUI 侧的发现/加载/自测证据见 `evidence/00-install/gui-session-evidence.md`，其中记录了 GUI catalog
实际出现 `memorygene` 并成功载入，以及一次虚构自测全流程。

### 2.3.1 dev2 任务接续（L1，2 个真实 headless 会话）

```sh
.venv/bin/python scripts/task_harness.py
```

2 个独立 headless Harness 会话（隔离虚构库）：A 保存任务接续记录；B 用真实 checkpoint ID 显式跨会话读取，核对来源与待办。**13/13 检查通过**，两个 session id 不同，且每个会话都有完成的 `skill` 与 `memorygene-dsh` 工具调用（不是模型自述）。
结果：`evidence/08-tasks/harness-summary.json`；原始事件流在 `evidence/08-tasks/harness/`（本地、gitignored，不进 ZIP）。
限制：对话 locator 由调用方声明，未与宿主 transcript 独立核对；没有自动上下文替换/压缩；不是 GUI 人工验收。

### 2.4 GUI 会话内（L1，真实 GUI）

`evidence/00-install/gui-session-evidence.md` + `gui-live-selftest.log`：catalog 出现、skill 载入、
记住/补充/修订/历史/遗忘/verify 全流程通过。验收过程未写生产库；生产库 `<项目>/var/memorygene.db`
现有 4 条用户记忆（2026-10-28），本轮维护只做只读核对，逻辑摘要 `9a9618…` 与 dev2 验证记录一致。

## 3. 失败与拒绝记录（不隐藏）

| 记录 | 说明 |
| --- | --- |
| 首次 headless 会话 A 拒绝写入 | 测试库尚未显式创建时，模型按 skill 规则执行 `doctor`/`current` 得到 `Refusing to create a new database implicitly`，明确报告“未保存”。这是预期的安全行为，证据保留在 `evidence/01-e2e/refusal-missing-db/`；随后脚本显式创建测试库再验收 |
| 自然语言提取 7 个字段级失败 | 5 个错误案例（复合值、否定、第三人称、低重要性、口语“也”）；全部列出，且 L2 失败分类为 extraction-only 5、storage-only 0 — 见 `experiments/NL_RESULTS.md` |
| 单主题读取对 route/heads 元数据损坏不主动报错 | 已知限制；需要 `verify` 全库扫描才能发现。payload/digest 损坏仍严格失败关闭 |
| 未由用户亲手完成的 GUI 11 项验收 | 明确列为未完成项；提供第 1 节的手动步骤 |
| 无独立留出集 / 无统计显著性 | NL 案例与规则同期开发；结构化实验也是开发集 |

## 4. 证据目录

```
evidence/
├── 00-install/                 安装、GUI 会话证据、用户级安装清单
├── 01-e2e/                     4 个真实 headless 会话 + 首轮拒绝建库记录
├── 02-e2e/                     库级验收 12 场景 / 47 检查 + 测试库 + 日志
├── dsh/                        DSH 发现规则研究、自动接入研究、live probe
├── nl/                         提取器测试与评估日志
├── review/                     独立基线审计报告、日志、复现脚本
├── 06-maintenance/             2026-10-27 会话隔离/验收/安装修复证据
├── 07-recall/                  2026-10-28 recall 验证
├── 08-tasks/                   2026-10-29 任务接续验证（含原始 harness 会话，本地）
└── 09-maintenance-2026-10-29/  本轮文档/交付/外来库回归修复证据
```

## 5. 复现全部验收

```sh
cd "<repo>"
.venv/bin/python -m unittest discover -s tests -v        # 139
.venv/bin/python scripts/acceptance.py                   # 12/52
.venv/bin/python scripts/task_harness.py                 # dev2 任务接续（2 会话，消耗模型调用）
.venv/bin/python experiments/run.py
PYTHONPATH=src .venv/bin/python experiments/nl_eval.py
PYTHONPATH=src .venv/bin/python -m unittest tests.test_extract -v
# 真实 Harness 会话（消耗模型调用；使用现有账号登录）
.venv/bin/python scripts/e2e_harness.py
# Skill 安装/发现
.venv/bin/python scripts/install_dsh_skill.py --check
python3 tools/dsh/probe_skills.py --cwd "$PWD" --skill "$PWD/.dsh/skills/memorygene/SKILL.md"
```

注意：`e2e_harness.py` 与 headless 验证会真实调用 DeepSeek 模型；`scripts/acceptance.py`
使用独立虚构测试库，不会读取真实聊天历史。

## 6. 交接后补丁：跨项目自动（2026-10-27）

在“任意项目里自动使用记忆”需求下新增用户级自动层（提示词约定，非强制）：

- `~/.dsh/skills/memorygene/`：用户级 Skill，任何工作区自动出现在 catalog（L1，任意项目实测）。
- `~/.dsh/AGENTS.md`：用户级全局指令，任何会话自动注入（L1，当前 GUI 会话即时注入）。
- 开关脚本：`scripts/install_global_auto.py`（`--check` / `--uninstall` / `--force` 保留已有全局指令）。

L1 实测：两个**不同 git 项目**、用户话术**未提 skill 名称**——项目 A 自动写入
`preference.favorite_tea=乌龙茶`，项目 B 自动召回“乌龙茶”；独立数据库复核一致，测试主题已清理。
证据：[evidence/05-global-auto/README.md](../evidence/05-global-auto/README.md)。

已知边界：headless 默认 `workspace-write` 无法写工作区外的固定库（需
`DSH_PERMISSION_MODE=danger-full-access`；GUI 当前为 full-access）；模型写入失败会如实报错。
此补丁当时测试 92/92；当前 dev2 已增至 139/139。


## 7. 2026-10-29 dev2 维护修复（本轮）

在 GPT 完成 dev2 任务接续后，本轮做了一次完整复核并修复交付/证据问题（不改动生产记忆）：

1. **交付链**：把 `dist/`、最终 ZIP/MANIFEST、`docs/RELEASE.md`、`docs/USAGE.zh.md`、`docs/ACCEPTANCE.md`、`docs/AUDIT.md` 统一到 dev2；旧的 dev1 ZIP/dist 标注为历史快照。
2. **外来库检测回归**：`task_checkpoints` 被加入允许表后，只有该表的无关 SQLite 可能被纳管；已改为“已有表必须包含 config/events/heads 核心表”，并添加回归测试（139 项）。
3. **证据链**：`docs/VALIDATION.json` 的 `base_commit` 改为实际 dev2 提交；production DB 的 `sha256` 明确为 sqlite iterdump 逻辑摘要并给出算法；删除不存在的隔离环境路径引用。
4. **文档边界**：在 SECURITY/DESIGN/USAGE 补充 recall/任务接续的安全与兼容性边界；更新全局自动提示模板（仅 MemoryGene 段），保留用户已有其它全局指令。
5. 复验：139 项测试、ruff、12/52 验收、dev2 wheel/sdist/ZIP 构建、干净 Python 3.12 venv 与解压 ZIP 测试。证据见 `evidence/09-maintenance-2026-10-29/`。


## 8. 独立留出 NL 基准与 GUI 验收准备（2026-10-29）

- **独立留出 NL**：30 组全新虚构对话/40 轮，独立 DSH headless `deepseek-flash` 抽取（6 个会话，原始输出在
  `experiments/heldout-2026-10-29/raw/`）。L1：决策 36/40、value/certainty/intent 26/27、source 27/27、
  topic 精确仅 11/27；L2：oracle 30/30，独立模型 20/30，失败分类 extraction-only 10、storage-only 0。
  证据：[experiments/heldout-2026-10-29/RESULT.md](../experiments/heldout-2026-10-29/RESULT.md)。
  这是严格 exact-topic 结果，主要暴露适配层 topic 归一化缺口，不是核心存储策略失败。
- **GUI 人工验收**：`../MemoryGene-GUI-test-2026-10-27/` 工作区已准备；`scripts/gui_acceptance_verify.py`
  的 `preflight` 已通过（独立库为空、配置/namespace/subject/Skill 正确，`evidence/10-gui-acceptance/preflight.json`）。
  `after-a/b/c` 仍需用户在 GUI 中亲手发消息后运行；**未完成前不得声称 GUI 验收通过**。
