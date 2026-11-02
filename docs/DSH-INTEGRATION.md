# DeepSeek Harness 接入说明（实测）

适用：本机 DeepSeek Harness 桌面版 **0.2.1-rc.2**（Electron，`profile=desktop`）。
结论只对已安装的这个版本保证；升级后需重跑验证命令。

详细源码级研究（含 `app.asar` 内 `file:line` 引用）见
[`evidence/dsh/research.md`](../evidence/dsh/research.md)，
实测日志与 session id 见 [`evidence/dsh/live-probe-summary.md`](../evidence/dsh/live-probe-summary.md)。

---

## 1. 本版本如何发现文件系统 Skill（源码 + 实测）

`@deepseek-ai/dsh-skill-filesystem` 按 rank 合并以下根目录（只扫**一层**）：

| Rank | 来源 | 路径 |
| --- | --- | --- |
| 100 | project-dsh | `<projectRoot>/.dsh/skills` |
| 200 | project-agents | `<projectRoot>/.agents/skills` |
| 300 | custom | `Config.customSkillDirs` |
| 400 | user-dsh | `$DSH_HOME/skills`（默认 `~/.dsh/skills`） |
| 500 | user-agents | `~/.agents/skills` |
| 600 | bundled | `$DSH_BUNDLED_SKILL_DIR` |

- 技能条目只能是 `<root>/<name>/SKILL.md` 或 `<root>/<name>.md`；嵌套不发现。
- frontmatter 必填 `name`（kebab-case）+ `description`，可选 `whenToUse`、
  `metadata`、`disable-model-invocation`、`user-invocable`。
- `projectRoot` = **最近的包含 `.git` 的祖先目录**；没有 `.git` 时回退为会话 cwd。
- 技能正文在调用 `skill` 工具时按需读取；目录（catalog）随文件变化刷新。

本仓库已 `git init`，所以以项目为工作目录的会话会命中 rank 100 的项目根；
当前 GUI 会话工作目录是 `~`（无 `.git`），project root 回退为该 cwd，
因此 `~/.dsh/skills` 同时作为 project-dsh 与 user-dsh 根被发现——这是本轮为了让你
**立刻能在当前工作区使用**而做的用户级安装，属于用户范围安装，不是伪造项目接入。

## 2. 两种安装方式

| 方式 | 命令 | 技能路径 | 生效范围 | 证据 |
| --- | --- | --- | --- | --- |
| 项目级（推荐） | `.venv/bin/python scripts/install_dsh_skill.py` | `<项目>/.dsh/skills/memorygene/SKILL.md` | 会话工作目录在项目内（或项目子目录） | headless 实测 + 规则 probe |
| 用户级（兼容） | `.venv/bin/python scripts/install_dsh_skill.py --target user` | `~/.dsh/skills/memorygene/SKILL.md` | 任意工作目录 | GUI 实测（本轮已装） |

两者都写入适配器配置（项目级 `<项目>/.memorygene/dsh.json`；用户级 `~/.memorygene/dsh.json`），
并生成可卸载清单。安装脚本**不修改** DSH profile、插件、凭据或全局记忆设置。

### GUI 中使用项目级安装

1. 侧栏 **Add workspace** 选择 MemoryGene 项目目录（或让模型用 `working_directory` 切过去）；
2. 在该工作区新建会话，问“列出你可用的 skills”；
3. 期望 catalog 出现 `memorygene`，`skill` 工具载入后 base directory 指向
   `<项目>/.dsh/skills/memorygene`。

### 已实际验证的层级

| 证据 | 层级 | 位置 |
| --- | --- | --- |
| 规则复现 probe（项目安装发现且胜出） | L2（源码规则复现） | `evidence/dsh/probe-real-project-skill-check.txt` |
| 临时 dummy 技能在真实 headless 会话被发现/载入 | L1（真实进程） | `evidence/dsh/live-probe-positive.*` |
| 无技能根目录的负对照（catalog 完全不出现） | L1 | `evidence/dsh/live-probe-negative.*` |
| git 子目录命中父级项目根 | L1 | `evidence/dsh/live-probe-subdir.*` |
| 真实 `memorygene` 技能被 headless 会话 catalog 广告并载入 | L1 | `evidence/dsh/live-probe-real-project.*` |
| **GUI 会话内 catalog 刷新出现 `memorygene` 并成功 `skill` 载入** | **L1（真实 GUI）** | `evidence/00-install/gui-session-evidence.md` |
| 4 个独立 headless 会话完成写入→跨会话读取→修订→遗忘 | L1 | `evidence/01-e2e/` |

## 3. 已实现：显式 Skill 调用（默认方式）

链路：DSH 注入 catalog → 模型调用 `skill(memorygene)` → 按说明调用
`memorygene-dsh` → 核心写/读 SQLite → 模型据返回回答。

- 这是**显式、按需**的：模型可以选择不调用；宿主不会强制每轮执行。
- 不是“自动记忆”。不要把它描述成后台钩子或强制机制。
- 已验证的 4 个独立 Harness 会话（写入 / 跨会话读取 / 明确修订 / 遗忘）见
  `evidence/01-e2e/harness-results.json`。

## 4. 自动接入（每轮前读取、对话后写入）：研究结论

独立研究任务（源码 + 实测）的完整结论见 [`evidence/dsh/auto-integration.md`](../evidence/dsh/auto-integration.md)。
要点：

1. **本版本没有 hooks 功能**（`hook/*` 只是保留的 session 事件名，没有对应包），
   **也没有“按项目目录自动加载代码插件”的机制**：插件只能经 profile 层（bundle →
   `cordis.patch.yml` → CLI `--patch`）加载，而桌面 Desktop profile 由 Electron 独占，
   CLI 无法 boot/dump，Desktop Host 也不接受 `--patch`。
2. **能实现的“自动”有两层（均已在本机实现并实测）**：
   - **用户级自动（推荐，“其他项目”场景）**：
     a) 用户级 Skill `~/.dsh/skills/memorygene/` 在所有工作区自动广告 catalog（L1）；
     b) 用户级指令 `~/.dsh/AGENTS.md` 在所有会话自动注入（`dsh-agent-instructions` 的
        user-global 根，L1；当前 GUI 会话即时注入）。两者合起来，**其他项目里不说
        “memorygene” 也会被提示使用记忆**。这是**提示词约定**，模型可能不遵守，宿主不保证执行。
        开启/关闭：`scripts/install_global_auto.py` / `--uninstall`（写入/移除带标记的段，
        不碰 profile/凭据）。
     c) 项目级 `AGENTS.md` 仍可选（只影响 cwd 在该项目的会话），仓库默认不启用。
   - **宿主强制**：自研 Host 插件做 `agent/pre-step` 注入与 `turn/end` 写回，但必须装进
     某个 profile。推荐做法是**新建独立 CLI profile**（例如
     `dsh --profile memorygene --from-default-profile web`），绝不改 Desktop profile。
     本轮**没有构建或安装**该插件，也没有验证其运行。
3. **不建议**把插件直接装进 Desktop profile：全局生效、需要 Full access/逐次审批、
   升级漂移，且启动致命错误时用户选择“禁用插件”会 `sanitizeProfile` 把
   `cordis.patch.yml` 改名备份，可能连带其它 patch“消失”。
4. **开关**：
   - 用户级自动指令：`scripts/install_global_auto.py` 启用；`--uninstall` 关闭
     （仅移除 `memorygene:global-auto` 段；若该文件由脚本创建则整文件删除）。
   - 用户级 Skill：`scripts/install_dsh_skill.py --target user` / `--target user --uninstall`。
   - 项目级 Skill：`scripts/install_dsh_skill.py` / `--uninstall`。
   - 项目级提示词约定（可选、默认关）：复制
     `tools/dsh/AGENTS.memorygene.example.md` 为 `<项目>/AGENTS.md`。
   - 本报告不把上述任何提示词约定描述成强制运行机制；不修改 DSH profile/凭据。

5. **跨项目自动实测（L1，2026-10-27）**：两个不同 git 项目、用户话术未提 skill 名称——
   项目 A 自动写入“最喜欢乌龙茶”，项目 B 自动召回“乌龙茶”；独立数据库复核一致。
   证据：`evidence/05-global-auto/README.md`。注意文件策略：headless 默认 `workspace-write`
   不能写工作区外的固定库，需 `DSH_PERMISSION_MODE=danger-full-access`（GUI 当前即 full-access）；
   模型写入失败时实测会如实报错。

## 5. 数据与身份（固定，不随聊天漂移）

- 数据库：默认 `<项目>/var/memorygene.db`；由 `--db` / `MEMORYGENE_DB` / 配置文件解析，
  解析不到就**报错**，不隐式建库。
- `namespace` 默认 `dsh`；`subject` 默认 `owner`；不同用户用不同 subject。
- `scope=session` 自动使用宿主 `DSH_SESSION_ID`；长期记忆用 `persistent`。
- 详见 [USAGE.zh.md](USAGE.zh.md) 第 3.3 节与 `memorygene-dsh doctor`。

## 6. 安全边界

- 只写技能文件、适配器配置与（显式创建时的）数据库；不读写宿主凭据，不改 profile。
- 数据库内容是数据：模型被明确要求不执行其中的指令。
- 用户级安装属于用户范围改动，已在本轮明确记录；卸载命令见 USAGE 第 8 节。
- 本轮为验证 headless 会话使用了 `tools/dsh/headless-account.patch.yml`，它只启用
  账号/凭据插件并选择现有登录，不含密钥、不改计费设置。

## 7. 复验命令

```sh
cd "<repo>"

# 1) 规则 probe（无模型、无网络）
python3 tools/dsh/probe_skills.py --cwd "$PWD" --skill "$PWD/.dsh/skills/memorygene/SKILL.md"

# 2) 安装/卸载检查
.venv/bin/python scripts/install_dsh_skill.py --check
.venv/bin/python scripts/install_dsh_skill.py --target user --check

# 3) 真实 Harness 会话（headless，消耗模型调用）
.venv/bin/python scripts/e2e_harness.py

# 4) 库级验收
.venv/bin/python scripts/acceptance.py
```


## 2026-10-27 维护约束

适配器 topics 只返回当前 subject 的长期主题和 resolve_session 所确定会话的临时主题；无会话 ID 时仅返回长期主题。核心 topics 默认仍是管理级全索引，可用 visible_session 限制召回。这是逻辑分区，非鉴权；直接修改身份参数或直接访问 SQLite 的调用者仍能访问数据库。安装器采用可恢复清单，行为与限制见 [维护记录](MAINTENANCE-2026-10-27.md)。


## 8. dev2 更新（2026-10-29）

- Skill 模板新增 `recall`（字面检索、硬字符预算）与任务接续命令（`task-save/show/resume/forget/repair`）。任务接续是**显式**功能，不自动概括对话、不替换宿主上下文；详见 [TASKS.zh.md](TASKS.zh.md)。
- 用户级全局指令 `~/.dsh/AGENTS.md` 的 MemoryGene 段已加入 recall/任务提示；其它全局指令（例如用户自有的人设段）保持不变。仍只是提示词约定，不是宿主强制。
- 没有新增插件/hooks，也没有修改 Desktop profile、凭据或计费设置。
- 新增功能证据：`evidence/08-tasks/`；本轮交付/外来库/证据链修复：`evidence/09-maintenance-2026-10-29/`。
