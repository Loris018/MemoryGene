# 自动集成可行性研究：回答前 recall / 每轮后 write

> 目标：判断能否给 MemoryGene 做一个**可靠的、可选的自动适配层**（每轮回答前自动召回、
> 每轮结束后自动写入），优先做成“项目级集成”，且**不破坏**用户现有 Desktop 环境。
>
> 适用版本：本机 DeepSeek Harness `0.2.1-rc.2`（Electron Desktop）。
> 证据等级见 `research.md` §1.3。本文所有关于 Desktop 组合的描述基于
> `app.asar` 源码 + Web profile dump + 本会话活观测；Desktop composed config 不能直接 dump。

---

## 0. 结论（先看这个）

**排名推荐（从推荐到不推荐）**

| # | 方案 | 能否“每轮强制” | 安装/审批 | 影响范围 | 证据等级 | 风险 |
|---|---|---|---|---|---|---|
| **0（推荐）** | 项目级 **Skill**（`<repo>/.dsh/skills/memorygene/`，已装）+ 建议再加 **`<repo>/AGENTS.md`** 协议段 | 否（提示约定，模型需遵守） | **零安装**，不写 profile，不需要审批 | 仅在 cwd 在项目内（或子目录且项目有 `.git`）的会话自动生效 | **L1**（skill + AGENTS.md 均实测） | 低：纯文件，随仓库走；只是“模型可能偷懒” |
| 1 | **独立 CLI profile** `memorygene`（`dsh --profile memorygene --from-default-profile web`）+ 自研 Host 插件做 pre-step 注入 / turn-end 写回 | 是（宿主强制执行） | 在**该 profile** 里安装 bundle（审批），Desktop profile 完全不动 | 只影响用该 profile 启动的会话 | L2（源码/文档）+ 未构建实测 | 中：需自己写/维护插件；独立入口（另一个 app URL），用户要记得用它 |
| 2 | 直接把 Host 插件装进 **Desktop profile**（`plugin_manager install_bundle`） | 是 | 需要 Full access 或逐次审批；写 `~/.dsh/profiles/desktop` | **所有** Desktop 会话（即使运行期按 cwd gate，代码也在每个会话的 Host 进程里跑） | L2 | 较高：profile 级持久化、升级漂移、崩溃恢复可能把用户 patch 层备份清掉（§4.4） |
| 3 | **headless/CI 专用** `dsh --profile headless --patch <project>/dsh/patch.yml` + 外层脚本 | 是（但只对脚本发起的 run） | 无需审批（`--patch` 是启动参数） | 仅该进程 | L2 | 低；但**不覆盖 GUI 聊天**，且每次 run 还是一次性任务 |
| 4 | MCP server / 适配器 CLI 暴露为工具（profile patch 注册 `dsh-mcp-client`） | 否（仍是模型主动调用） | profile 级配置 | profile 内所有会话 | L2 | 中低：只提供工具，不提供“自动” |

**一句话**：
- 若接受“**项目级、零安装、提示约定**”：方案 0 是当前唯一既项目级又零风险的路，
  而且 0.2.1-rc.2 已经把两个自动通道做好——**每次会话自动广告 skill catalog**
  （L1 实测）和**首次请求自动注入 `AGENTS.md`**（L1 实测）。
- 若要求“**宿主强制执行**每轮 recall/write”：必须写 Host 插件，而 DSH **没有项目级
  插件加载机制**（见 §2），只能装到某个 profile；代价最小的是**方案 1（独立 profile）**，
  而不是动 Desktop profile。
- **不存在**“只靠项目目录就把代码插件加载进 Desktop GUI”的官方通道；也**没有** hooks
  功能（`hook/*` 只是保留的 session 事件名，本版本没有对应包）。

---

## 1. 判定标准：什么叫“自动 / 可靠”

分三层，强度递增：

1. **提示约定层**（skill catalog、AGENTS.md、系统提示）：每会话/每请求自动进入模型上下文，
   但“照不照做”由模型决定。**不会**因为模型没调用就失败——它会看到指令；但仍可能跳过。
2. **工具层**（`skill` 工具、bash 执行适配器、MCP tools）：工具是自动注册/暴露的，
   但**调用**由模型发起（`/name` 例外，见 §3.2）。
3. **宿主层**（Cordis Host 插件挂 `agent/pre-step`、`turn/end`、`tools/*` 等事件）：
   由 DSH 主进程代码执行，**不经过模型决策**，可以做到“每步注入召回上下文”“每轮结束写回”，
   这才是真正意义上的“强制自动”。代价是必须安装代码到 profile。

MemoryGene 当前实现（`src/memorygene/adapter.py` + 安装脚本）属于第 2 层 + 第 1 层：
skill 指令让模型显式调用 `memorygene-dsh` CLI；skill 自己也写明了“不含自动每轮召回/写入”。

---

## 2. Q(i)：能不能“项目级”加载插件，而不改全局 Desktop profile 配置？

**不能。** DSH 的插件加载面只有 profile 这一层，证据：

- `@deepseek-ai/dsh/README.md`（Profiles 节）：一个 profile 目录 = `package.json`
  （`dsh.profile.bundles` 有序列表）+ `cordis.patch.yml`（用户 patch 层）；组合顺序是
  **每个 bundle 的 patch → profile 的 `cordis.patch.yml` → `$DSH_HOME/cordis.patch.yml`
  → `--patch` overlay**。没有“项目目录提供 loader 行”的入口。
- `@deepseek-ai/dsh-plugin-manager/README.md:14`：“Changes affect every session using the
  profile.”；`:31`：plugin 操作需要 Full access 或审批，且 “installed Host code executes
  in-process outside the workspace sandbox”。
- `@deepseek-ai/dsh-agent-preset/skills/editing-cordis-compositions/SKILL.md`：preset 也是
  “由 bundle patch 声明/覆盖，安装 bundle 才能改；不能原地编辑 preset 组合”。
- Desktop 侧更封闭：`/lib/main.js:12051` 把 Host 的 `projectDir`/cwd 固定为
  `~/.dsh/profiles/desktop`；`dsh-desktop-host/lib/index.js:233` 给 `runProfile` 传
  `patchFiles: []`（Electron 不注入任何额外 patch 文件）；CLI 实测
  `dsh --profile desktop --dump-config` → `error: profile "desktop" is managed exclusively
  by the Electron application`。
- `dsh --patch` 只存在于 **CLI 启动路径**（launcher 参数），GUI 会话没有这个入口。

**能绕开“改 Desktop 配置”的三种做法**：

1. **项目文件**：`<repo>/.dsh/skills/*`（skill）+ `<repo>/AGENTS.md`（指令）+ 仓库内脚本。
   这些**不需要任何 profile 写入**，且只对 cwd 在项目内的会话生效。
2. **另起一个 CLI 拥有的 profile**（如 `memorygene`）：`dsh --profile memorygene
   --from-default-profile web` 初始化，再往这个 profile 装插件。Desktop profile 原封不动。
3. **headless 脚本**：`dsh --profile headless --patch <项目 patch.yml>`，
   `--patch` 是进程级 overlay，不写任何 profile。适合 CI/批处理，不影响 GUI。

结论：**“项目级 + 不写 profile + 代码级自动”三者不可兼得**；只能取“项目级 + 提示约定”
（方案 0），或“强制自动 + 写某个 profile”（方案 1/2），或“强制自动 + 仅 CLI 进程”（方案 3）。

---

## 3. 现有可用扩展面盘点（含源码证据）

### 3.1 项目级、零安装

| 面 | 机制 | 自动性 | 证据 |
|---|---|---|---|
| `skill`（`.dsh/skills` / `.agents/skills`） | 每步 `agent/pre-step` snapshot → catalog 消息；`skill` 工具按需载入 | 每会话自动广告；载入是模型决定 | **L1**：`live-probe-positive`（dummy）、`live-probe-real-project`（真 skill）、GUI `gui-live-catalog-evidence.md` |
| `AGENTS.md` / `CLAUDE.md`（`dsh-agent-instructions`） | 首个 eligible pre-step 把“项目根→cwd”链上的文件作为 `source.kind=agent-instructions` 的 user message 注入；`read/write/edit` 命中更深目录时追加 | **每次会话首次请求自动注入**；内容刷新是 touch-driven | **L1**：`live-probe-agents-md`（marker 被原样答出，seq 9）；源码 `dsh-agent-instructions/lib/index.js:1222,1406,673-674`；README `:28-42` |
| 仓库内 CLI/脚本 | 模型用 bash 调 `memorygene-dsh`（skill 已规定流程） | 模型决定 | L1（skill 正文 + 适配器已存在） |

> 注意：`AGENTS.md` 与 skill 的**触发条件都依赖会话 cwd**。cwd 不在项目内时两者都不出现。
> 想让 GUI 里生效，必须把会话 cwd 放进项目（Add workspace 或 `working_directory` cd，
> 见 `research.md` §4.3）。

### 3.2 工具/命令级

- `skill` 工具：本项目 L1 实测可在 GUI 与 headless 两边载入。
- `/name` 手势：用户消息里的 `/memorygene` 会把 skill 正文**直接注入该步**，无需模型先调用
  （`dsh-tool-skill/lib/index.js:1101-1121,896-930`；README `:56,227`）。这是用户侧的
  “手动自动”，适合把“先召回再回答”变成用户习惯。
- 适配器 CLI（`memorygene-dsh topics/current/remember/...`）：任何 profile/界面都能用，
  是“工具层”的实体。
- MCP：`dsh-mcp-client` 可以把适配器包成 MCP server 的工具，但 server 配置是
  **profile 的插件行 config**（`dsh-mcp-client/README.md` 配置节），仍是 profile 级；
  且不提供自动 recall/write（只是工具）。

### 3.3 宿主级（真正的自动）

`@deepseek-ai/dsh-agent` + `dsh-system-prompt` + session 事件给了这些插槽
（`dsh-agent/README.md:65-67,83-113`；`cordis-plugin-development/references/practices.md:16-22`）：

| 需求 | 可用插槽 | 说明 |
|---|---|---|
| 每步（回答前）注入召回内容 | `agent/pre-step` waterfall（返回 `{...decision, messages}` 追加 user message）或 `ctx.systemPrompt.section()` | `tool-skill` 的 catalog 就是这么做的；`agent.inject()` 只在本步被 admit 时进入 |
| 每轮结束后写回 | durable 事件 `turn/end`（或 `assistant/message`、`tools/result`）；`agent/turn-stopping` 可在回合关闭前 steer | 等待落盘事件，不要轮询 `agent/status` |
| 仅对某项目生效 | 在 pre-step 里读 `workingDirectory.ensure(agent)` / session header cwd，按 realpath 前缀 gate；不匹配就 `return next()` | 这是“project-scoped 行为 + profile 级安装”的唯一实现方式 |
| 后台任务 | jobs/插件 timer；`agent.followup()` 会唤醒 agent，`agent.inject()` 不会 | 自动 write 用 `followup` 或事件里直接写库 |
| 配置 | 插件 `Config`（用户可在 `cordis.patch.yml` 覆盖） | 升级保留用户 patch 层 |

**没有 hooks 功能**：`dsh-tool-skill/lib/index.js:684-685` 的事件类型表里出现了
`hook/invoked`、`hook/result`，但 `app.asar` 的 307 个包中没有任何 hooks 包
（`grep hook` 无 `dsh-*hook*` 包），`dsh/package.json` 依赖清单也没有。所以“写个 hooks 配置文件”
这条常见思路在本版本不存在。

---

## 4. Q(ii)：如果只能靠插件，具体要做什么、安全吗、风险在哪

### 4.1 要做什么（最小可行 Host 插件）

1. 在工作区写一个 **bundle 包**：`package.json`（`type: module`、`exports`、
   `dsh.bundle.patch: "./cordis.patch.yml"`）+ `cordis.patch.yml`（`- insert: [{id, name, config}]`）
   + `index.js`（`export function apply(ctx, config)`，`export const inject = [...]`，
   可选 `export const Config`）。模板与清单：`cordis-plugin-development/references/host-plugin.md`。
2. 安装：`plugin_manager install_bundle`（`target` = 绝对包目录），或
   `dsh plugin --profile <profile> add <spec>`（Desktop 安装自带的 CLI 可以管理该 profile）。
   **都需要 Full access 或明确审批**；`install_bundle` 会自己写 profile 的 `package.json` /
   `cordis.patch.yml` / 跑 pnpm，不要手工改这些文件。
3. 逻辑（以 MemoryGene 为例）：
   - `inject = ["agents", "workingDirectory", "systemPrompt"]`；
   - `agent/created` → `agent.ctx.effect(...)` 注册 per-agent 监听（agent 销毁自动清理）；
   - `agent/pre-step`（waterfall，必须 `return next()` 保留其他贡献）：
     取 `cwd = await ctx.workingDirectory.ensure(agent, signal)`；若 cwd 不在配置的
     `<MemoryGene>` 根下（realpath 前缀）→ 直接 `next()`；
     否则以短超时（如 2–3s）调用 `memorygene-dsh topics/current --…`，
     把结果包装成带 `source: {kind: "memorygene-recall"}` 的 user message 追加进 decision，
     或 `ctx.systemPrompt.section()` 渲染；**失败要降级为无召回**（不能阻塞回答）。
   - 监听 `turn/end`：从本回合 user message 抽取候选，调用 `remember`；需要幂等
     （用 session id + turn seq + topic 去重），失败只 warn。
   - 不要在 session 里 append 新的事件类型（`practices.md:21`：未知 type 会导致会话无法重开）；
     插件私有的去重状态放 projection 或 storage service。
4. 验证：先装在**独立 profile**（方案 1）里跑通，再讨论是否值得进 Desktop profile。
   验证清单：新会话是否每步都有召回消息（看 session log `user/message` 的 source）、
   关掉/不在项目 cwd 的会话是否零影响、模型回答是否引用召回、写回是否幂等。

### 4.2 安全吗

- 插件代码**在 Host 进程内、以宿主用户权限、在 workspace 沙箱之外**执行
  （`dsh-plugin-manager/README.md:31`）。一旦装上，它能读所有会话、所有文件。
  对 MemoryGene 这种“保存个人长期事实”的组件，这是**显著扩大的攻击面**：
  召回内容是模型上下文的一部分，若 DB 内容被污染，等于向每轮对话注入不可信文本；
  插件必须把记忆内容当**数据**（skill 已有这条安全边界，插件要沿用）。
- 安装动作本身需要用户批准（Full access/审批），这是唯一的人为闸门；
  批准后代码持久化、随 profile 启动自动执行。

### 4.3 风险 / 缺点清单

| 风险 | 说明 / 证据 |
|---|---|
| **不是项目级** | 插件按 profile 生效，同一 profile 的所有会话都会加载它（只能运行期按 cwd gate） |
| **Desktop profile 是 app 管理的** | CLI 拒绝 boot/dump desktop profile；Electron 更新/重装会重建/迁移 profile（`/lib/main.js:3410-3430` `initProfile` 不覆盖已有文件，但恢复流程例外） |
| **崩溃恢复会动用户 patch 层** | Desktop 启动致命错误时有一键“禁用全部插件”恢复：`/lib/main.js:11827-11840`（`disablePlugins` 在 `:11834-11835`）→ `:3585` `DesktopProjectManager.disableAllPlugins()` → `:3531-3560` `sanitizeProfile()`，会把 `cordis.patch.yml` **重命名备份**并把 bundles 重置为 Web 模板。一个坏插件可能触发这条路径，让用户其它 patch（模型/UI 设置）一起“消失”（有 `.bak` 备份） |
| **版本漂移** | 插件要声明 `engines.dsh`/peer 范围；版本不匹配安装会被拒，豁免需显式接受风险（`dsh-plugin-manager/README.md:66-75`）；DSH 升级后插件 API 可能变 |
| **升级/替换需重启** | 已加载模块的替换要重启 Host（`plugin-manager` “restart-required”）；Desktop 下意味着重启 App |
| **引入延迟/成本** | 每步 recall = 每步一次本地 CLI/DB 调用；插件必须短超时、失败降级，否则拖慢每次回答 |
| **上下文膨胀 / KV cache** | 每步追加召回消息会进历史；需要“只有相关时注入/去重/摘要”，否则 token 成本上升（catalog 的模式可参考） |
| **无法按项目卸载** | 反安装只能改 profile（关 bundle/删包）；仓库自身不带插件 |
| **测试面窄** | 装进 Desktop profile 才能在 GUI 里真验证，但这一步已影响全局；应先在独立 profile 验证 |
| **没有 hooks 捷径** | 本版本无 hooks 包，不能靠配置文件声明式实现 |

---

## 5. Q(iii)：是不是只有“提示约定”一条路？

不是。可行路径按“可靠自动性”排序：

1. **提示约定（项目级、零安装）**：skill + `AGENTS.md`；自动进入上下文，但不强制模型执行。
2. **工具约定（项目级、零安装）**：适配器 CLI / 未来的 MCP 工具；模型主动调用。
   可以配合 `/memorygene` 手势与 `AGENTS.md` 里的“先调用、后回答”规则提高命中率。
3. **宿主插件（profile 级）**：唯一能做到“每步注入、每轮写回不依赖模型”的方式。
4. **外部编排（headless/CI）**：把 `dsh --profile headless --patch …` 当成自动化任务，
   外层脚本在 run 前后直接调 MemoryGene CLI —— 这其实是“在 DSH 外面做自动”，
   对 GUI 聊天不生效，但对批处理/后台场景可靠且零侵入。

---

## 6. 对 MemoryGene 的具体建议（分阶段）

### Phase 0（已具备，P0 已完成）

- 项目级 skill：`<MemoryGene>/.dsh/skills/memorygene/SKILL.md`（L1 已验证发现与载入）。
- 用户级 skill：`~/.dsh/skills/memorygene/SKILL.md`（让 cwd 不在项目内的 GUI 会话也能用，
  L1 已验证：GUI catalog 热替换 + GUI `skill` 载入）。
- `tools/dsh/probe_skills.py` 可在**不调用模型**的情况下检查任意 cwd 下 skill 是否会被发现
  （L2 规则复现，与 L1 实测一致）。

### Phase 1（建议做，零安装、低风险）

在仓库根加 `<MemoryGene>/AGENTS.md`（≤ 64 KiB 预算内，建议 30–80 行），用**项目级、
每次会话首个请求自动注入**的通道写协议：

- 回答涉及用户本人长期偏好/事实前：先 `memorygene-dsh topics` / `current` 定位；
- 用户明确陈述长期事实后：按 skill 第 2 节规则 `remember`（status 语义照 skill）；
- 不确定/推断 → `pending`，不得冒充当前事实；冲突不覆盖；
- 敏感信息必须有明确同意（沿用 skill 的安全边界）。
- 明确写“本文件是工作区指令，不覆盖系统/用户指令”。

验收（不需要写 profile）：`dsh --profile headless --json "…"` 的会话日志里能看到
`source.kind="agent-instructions"` 的消息；GUI 里则需会话 cwd 在项目内（Add workspace）。
注意 `AGENTS.md` 是**首次请求注入 + touch 刷新**，不是每轮重注入（README `:28-42,212-226`）。

### Phase 2（可选，需要用户明确同意；推荐“独立 profile”，不碰 Desktop）

- `dsh --profile memorygene --from-default-profile web` 初始化专用 profile；
- 在其上安装自研 Host 插件（§4.1），实现 pre-step recall + turn/end write（cwd gate 到
  MemoryGene 根）；
- 用户需要打开该 profile 的入口（或用 `dsh --profile memorygene`）来获得强制自动；
  Desktop 的日常入口不受影响；
- 验收：新会话 session log 每步都有 `memorygene-recall` 消息；非项目 cwd 会话零影响；
  写回幂等；插件卸载 = 删 profile 依赖/bundle，随时可回滚。

### 不建议

- 把插件直接装进 Desktop profile（除非用户明确接受“全局生效 + 恢复流程风险 + 升级维护”）。
- 期待“项目目录里放个文件就让 Desktop 加载代码插件”——本版本没有这个机制。
- 用 hooks 配置：本版本无 hooks 包。

---

## 7. 现实中“自动”的天花板（如实）

- **提示层**：catalog 自动出现、AGENTS.md 自动注入，但模型可以忽略；`skill` 的载入与
  `/name` 之外的工具调用仍由模型决定。AGENTS.md 的刷新是 touch/resume 驱动，不是实时。
- **工具层**：模型不调用就没有 recall/write；`/memorygene` 手势是用户可用的确定性入口
  （注入等价于 `skill` 工具结果）。
- **宿主层**：能做到真自动，但只能装进 profile（全局），不是项目级；Desktop 环境还要
  用户批准且承担 §4.3 的风险。
- **外部编排**：对 headless/CI 可靠且零侵入，但不改变 GUI 聊天的行为。

---

## 8. 证据索引

- skill 发现/载入 L1：`live-probe-positive.*`、`live-probe-real-project.*`、
  `live-probe-catalog-evidence.md`、`gui-live-catalog-evidence.md`
- AGENTS.md 注入 L1：`live-probe-agents-md.*`
- 规则与 GUI 语义：`research.md`
- 源码位置：`research.md` §1.2/§2/§3/§4，`tools/dsh/extract_asar.js`
- profile/plugin 行为：`@deepseek-ai/dsh/README.md`（Profiles）、
  `@deepseek-ai/dsh-plugin-manager/README.md:14,31,66-75`、
  `@deepseek-ai/dsh-agent-preset/skills/cordis-plugin-development/SKILL.md` 与
  `references/host-plugin.md`、`references/practices.md`
- Desktop 恢复流程：`/lib/main.js:3531-3560`（sanitizeProfile）、
  `:3585-3590`（disableAllPlugins）、`:11827-11840`（recovery 接线，`disablePlugins` 在 `:11834-11835`）
