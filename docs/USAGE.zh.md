# MemoryGene × DeepSeek Harness 使用说明

版本：MemoryGene 0.2.0.dev2（含 DSH 接入、recall 与任务接续）
适用：macOS 桌面版 DeepSeek Harness（本机实际版本 0.2.1-rc.2，profile `desktop`）

本文只描述**本机实际验证过**的行为。没有验证过的内容会明确标注。所有示例人物、偏好、地址均为虚构。

**当前本机状态（2026-10-29 dev2 维护后）**

- 当前源码为 0.2.0.dev2：新增 `recall` 字面召回与显式任务接续；项目级/用户级 Skill 已更新到 dev2 模板，`~/.dsh/AGENTS.md` 的 MemoryGene 段已加入 recall/任务提示（其它全局指令保留）。
- 生产库现有 4 条用户记忆（2026-10-28），未在本轮维护中改写；任务扩展表尚未创建。

- 项目 venv 已装好 `memorygene` / `memorygene-dsh`（editable，Python 3.11.7）。
- 项目级 Skill 已装：`<项目>/.dsh/skills/memorygene/`（工作目录在项目内时生效）。
- 用户级 Skill 也已装：`~/.dsh/skills/memorygene/`（当前 GUI 工作目录 `~` 无 `.git`，project root 回退为 cwd，因此该目录同时被当作 project/user 技能根；这样你现在这个工作区也能直接用）。
  它属于用户范围安装，不需要时用第 8 节卸载。
- 生产库 `<项目>/var/memorygene.db` 已有用户记忆，本轮完整保留。不要在此库上执行下面的虚构验收；使用单独测试工作区和数据库。
- **跨项目自动（提示词约定）已启用**：`~/.dsh/AGENTS.md` 已被写入 MemoryGene 约定，DSH 会在
  **每个项目的每个会话**自动注入；配合用户级 Skill，在别的项目里不说 "memorygene" 也会被提醒使用。
  它是提示词约定，不是宿主强制；用 `scripts/install_global_auto.py --uninstall` 关闭。见第 5 节。

---

## 1. 一分钟上手

前提：项目与环境已按第 2 节安装好。

1. 在 DeepSeek Harness 里新开一个对话，**工作目录选择 MemoryGene 项目根目录**
   `<repo>`。
2. 在对话里明确说：**“请使用 memorygene skill”**，再说要记的事。
3. 可靠的说法示例：

   > 请使用 memorygene skill，记住：我最喜欢玫瑰。记完告诉我你的实际执行结果。

4. 之后在新对话里（同一工作目录）问：

   > 请使用 memorygene skill，先查一下我最喜欢的花是什么。

5. 判断成功的标准不是模型说“记住了”，而是它真的执行了适配器命令，并且数据库能查回：

   ```sh
   <repo>/.venv/bin/memorygene-dsh current --topic preference.favorite_flower
   ```

---

## 2. 安装

### 2.1 Python 环境与包（项目内独立环境）

```sh
cd "<repo>"
.venv/bin/python -m pip install -e .
```

本机已装好：Python 3.11.7，`.venv/`，`memorygene` 与 `memorygene-dsh` 两个命令都在 `.venv/bin/` 下。
所有命令请写**绝对路径**，不要依赖桌面应用的 PATH。

### 2.2 安装 Skill（两种目标）

```sh
# 项目级（推荐）：装到 <项目>/.dsh/skills/memorygene/SKILL.md
.venv/bin/python scripts/install_dsh_skill.py

# 用户级：装到 ~/.dsh/skills/memorygene/SKILL.md，任意工作目录都能发现
.venv/bin/python scripts/install_dsh_skill.py --target user

# 只检查、不修改
.venv/bin/python scripts/install_dsh_skill.py --check
```

安装脚本会：

- 把 `skills/memorygene/SKILL.md` 模板渲染成安装副本（填入绝对路径、数据库、身份）；
- 写适配器配置 `<项目>/.memorygene/dsh.json`（用户级为 `~/.memorygene/dsh.json`）；
- 写权限 0600 的恢复清单，保存被替换文件的原始字节和权限；重复安装保留第一次备份；卸载只恢复/删除自己管理的文件，遇到后续用户编辑会拒绝覆盖。旧安装首次升级只能恢复到升级前，无法补造原安装前的备份；
- **不会**修改 DSH profile、插件、凭据或任何全局记忆配置。

### 2.3 验证 Harness 能发现并加载 Skill

方式一（GUI）：新开工作目录为项目根目录的对话，问“列出你可用的 skill”。当前会话的技能目录里应出现 `memorygene`。
方式二（真实 headless 会话，本机已实际执行）：

```sh
DSH="/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
cd "<repo>"
"$DSH" --profile headless --patch tools/dsh/headless-account.patch.yml --json \
  "不要调用任何工具，只列出当前可用的 skill 名称"
```

实测输出包含 `memorygene`；同一会话还实际调用了 `skill` 工具加载了本说明。
证据见 `evidence/01-e2e/` 与 `evidence/dsh/`。

> `tools/dsh/headless-account.patch.yml` 只是让 headless 复用你已登录的 DeepSeek 账号（不含密钥），用于验证，不影响桌面 GUI 的配置。

### 2.4 验证适配器

```sh
.venv/bin/memorygene-dsh doctor
```

`ready: true` 表示数据库可用。`db_exists: false` 时**不会**自动建库；确认要新建时：

```sh
.venv/bin/memorygene-dsh --allow-create remember --topic preference.favorite_flower --value "玫瑰" --source "我最喜欢玫瑰。"
```

---

## 3. 在 Harness 中使用

### 3.1 显式 Skill 调用（本轮已实现并验证）

机制：DSH 技能目录注入 `<available_skills>`，模型看到后调用 `skill` 工具加载本说明，再按说明调用 `memorygene-dsh`。这是**显式调用**，不是宿主强制的每轮记忆。

对话中的可靠姿势：

- 说“**请使用 memorygene skill** …”，给模型一个明确入口；
- 要它记住时，说清**这是长期事实**（避免被当成闲聊），必要时说“以后都记得”；
- 问“现在/以前”时分别对应 `current` / `history`；
- 让模型把**实际执行的命令和返回状态**告诉你，避免只回复“记住了”。

### 3.2 工作目录与数据库

- 项目级安装只有在“会话工作目录 = 项目根目录（或项目内子目录）”时才会被发现。
- 数据库路径固定在适配器配置里（默认 `<项目>/var/memorygene.db`），**与聊天窗口无关**：
  切换聊天不会新建库；新会话读同一个库，才能跨会话记忆。
- 用户级安装（`--target user`）在任意工作目录可用，但它是**用户级**安装，不是项目接入；不用时可用第 8 节卸载。

### 3.3 身份与隔离规则（重要）

| 概念 | 规则 |
| --- | --- |
| `namespace` | 逻辑分区，默认 `dsh`，固定使用，不随聊天变化 |
| `subject` | 记忆属于谁，默认 `owner`。不同真实用户必须显式用不同 subject；模型不得从对话内容猜测身份 |
| `session` | `scope=session` 时自动取宿主环境 `DSH_SESSION_ID`；长期记忆一律 `persistent` |
| 数据库 | 由 `--db` / `MEMORYGENE_DB` / 配置文件决定；优先级见下 |

配置优先级：

1. 命令行 `--db`、`--namespace`、`--subject`、`--session`、`--config`
2. 环境变量 `MEMORYGENE_DB` / `MEMORYGENE_CONFIG` / `MEMORYGENE_NAMESPACE` / `MEMORYGENE_SUBJECT` / `MEMORYGENE_SESSION`
3. 从当前目录向上查找 `.memorygene/dsh.json`
4. `~/.memorygene/dsh.json`
5. 都没有 → **报错退出，不建新库**

查看当前解析结果：`.venv/bin/memorygene-dsh doctor`。

---

## 4. 日常操作（模型执行的命令）

> 下列命令中的 `MG` 代表适配器绝对路径：
> `<repo>/.venv/bin/memorygene-dsh`

### 4.1 检索与读取

```sh
"$MG" doctor                              # 库/身份/会话
"$MG" recall --query "喜欢什么花" --limit 5 --budget-chars 2000  # 不确定 topic 时的字面召回
"$MG" topics                              # 该 subject 的长期主题及当前会话主题
"$MG" current  --topic preference.favorite_flower   # 现在的事实
"$MG" history  --topic preference.favorite_flower   # 历史（含 pending/conflict）
"$MG" verify                                        # 只读全库完整性扫描
```

- `current` 为 `null` = 没有当前事实，旧版本不会自动复活。
- `history` 里只有 `status=confirmed` 才能当历史事实。
- `recall` 是**字面**检索（中文 bigram/英文词），不是语义搜索；返回 ID/topic/scope/短预览，仍需 `current` 核对。预算以字符计、不是 token；读不会强化记忆。`omitted>0` 表示有匹配被预算或数量上限省略。

### 4.2 写入

```sh
"$MG" remember \
  --topic preference.favorite_flower \
  --value "玫瑰" \
  --source "我最喜欢玫瑰。" \
  --certainty explicit --intent assert --importance 0.8
```

- `--source` 必须是用户原话的最小子串，不得编造。
- `--certainty` 只有直接明确的陈述才是 `explicit`；“也喜欢/也好看/还不错”是 `uncertain`；“听说/可能/好像”是 `uncertain`/`inferred`。
- `--intent` 默认 `assert`；只有用户明确改主意才 `change`/`correct`；补充用 `supplement`。
- 闲聊/一次性内容不要写；或 `--importance 0.2`（persistent 下会被丢弃，不落库）。
- 相同值重复陈述返回 `duplicate`，当前事实不变。

### 4.3 明确修订

“现在最喜欢栀子花了”：

```sh
"$MG" remember --topic preference.favorite_flower --value "栀子花" \
  --source "现在最喜欢栀子花了。" --certainty explicit --intent change --importance 0.8
```

随后 `current` = 栀子花，`history` 中玫瑰仍在。

### 4.4 未确认冲突

同一主题出现不同值、但用户没有明确改变时，命令返回 `conflict` 或 `pending`，**当前事实不变**。需要用户确认后再用 `change/correct` 写入；可加 `--resolves <旧事件 id>` 记录确认关系。

### 4.5 到期

```sh
"$MG" remember --topic promotion.code --value "FICTIONAL-CODE" \
  --source "本次优惠码是 FICTIONAL-CODE，11 月 1 日前有效。" \
  --expires-at 2026-11-01T00:00:00Z
```

到期后 `current` 为 `null`、`history` 不再展示该事件。到期是**读时过滤**，不是后台删除。

### 4.6 遗忘

```sh
"$MG" forget --topic preference.favorite_flower
"$MG" current --topic preference.favorite_flower   # 应为 null
"$MG" topics                                        # 该主题应消失
```

`forget` 删除该主题的路由记录：当前头、全部历史事件、冗余副本列。**不是**物理安全擦除（SQLite 空闲页、文件系统快照、外部备份不在范围内）。没有一键删除整个 subject 的接口。

### 4.7 任务接续记录（dev2）

任务接续是**显式**功能，不自动压缩对话、不替换宿主上下文。用户明确要求时：

```sh
"$MG" task-save --task my-project --file /absolute/path/private-task.json
"$MG" task-show --task my-project
"$MG" task-save --task my-project --file /absolute/path/private-task.json --previous-id <刚读到的 checkpoint_id>
"$MG" task-resume --checkpoint-id <真实 ID> --allow-cross-session   # 仅用户明确要求跨会话时
"$MG" task-forget --task my-project
```

- 需要 `DSH_SESSION_ID` 或显式 `--session`；记录默认 7 天到期（最多 30 天）。
- 输入结构、source/memory 依赖、状态语义（saved/review_required/stale/expired/superseded/missing）和兼容性边界见 [TASKS.zh.md](TASKS.zh.md)。
- 首次 `task-save` 才创建 `task_checkpoints` 扩展表；此后旧版 0.2.0.dev1 会拒绝打开该库，降级需恢复升级前备份。
- 任务内容由调用方整理、是明文数据；conversation locator 未独立验证；checkpoint ID 不是安全凭证。

### 4.8 损坏与恢复

- 读到损坏事件会失败关闭（退出码 2，报 `IntegrityError`），不会返回猜测值。
- 用 `"$MG" repair --event-id <id>` 从校验通过的副本恢复字节；`repair` 不改 heads，**不会回滚合法的新版本**。
- 主数据与副本都无法校验时明确报错 `No verified copy; refusing to guess`。

### 4.9 敏感信息与同意

```sh
"$MG" remember --topic profile.address --value "虚构路1号" \
  --source "我住在虚构路1号。" --sensitive \
  --consent --consent-evidence "可以记住这个地址"
```

- 没有明确同意：核心拒绝（`rejected_sensitive`，不落库）。
- 只有布尔 `--consent` 没有同意原话：适配器直接拒绝。
- 用户同意原话会以“【用户同意原话：…】”追加进 `source`，便于审计。

---

## 5. 自动记忆：当前状态与开关

当前有**两层自动**（都已启用），但都**不是宿主强制机制**：

| 层 | 机制 | 作用范围 | 证据 |
| --- | --- | --- | --- |
| 1. 用户级 Skill | `~/.dsh/skills/memorygene/`，DSH 每工作区自动广告 catalog | 所有项目 | 任意项目 headless 实测出现 `memorygene` |
| 2. 用户级全局指令 | `~/.dsh/AGENTS.md`，DSH 每个会话自动注入 | 所有项目、所有会话 | 当前 GUI 会话即时注入 + 跨项目写入/召回实测 |

因此，在**其他项目**里你不需要再说“请使用 memorygene skill”：模型收到的全局约定会要求它在涉及
你的长期偏好/事实时先加载 skill 再读写。**但它仍可能跳过**——需要强制时直接明确要求，或使用下文的
Host 插件方案（未构建）。

### 5.1 启用 / 检查 / 关闭（一条命令）

```sh
cd "<repo>"
.venv/bin/python scripts/install_global_auto.py            # 启用（可重复执行，原地更新）
.venv/bin/python scripts/install_global_auto.py --check    # 检查
.venv/bin/python scripts/install_global_auto.py --uninstall # 关闭全局指令（保留用户级 Skill）
.venv/bin/python scripts/install_dsh_skill.py --target user --uninstall  # 再移除用户级 Skill
```

- 若你已有自己的 `~/.dsh/AGENTS.md`：脚本默认**拒绝覆盖**；加 `--force` 会先备份再追加 MemoryGene 段
  （卸载时只移除该段，保留你的内容）。
- 不修改 DSH profile、插件、凭据或其它全局记忆。

### 5.2 已知边界：文件写入权限

跨项目写入的数据库固定在 `<项目>/var/memorygene.db`。若某个会话的文件策略是
`workspace-write`（例如 headless 默认），写工作区外路径会被拒
（`attempt to write a readonly database`）。处理：

- GUI 当前策略是 `danger-full-access`，正常可写；
- headless/受限会话：启动时加 `DSH_PERMISSION_MODE=danger-full-access`，或把库放到该工作区内的路径；
- 模型在写入失败时必须如实报告，不能伪造成功（本机实测它会如实报错）。

### 5.3 为什么不做“宿主强制每轮”

本机 DSH 0.2.1-rc.2 没有 hooks，也没有“按项目目录加载代码插件”的通道；强制每轮只能自研 Host 插件
并装进某个 profile。推荐独立 profile（`dsh --profile memorygene --from-default-profile web`），不要动
Desktop profile。本轮**未构建、未安装、未验证**该插件。

### 5.4 关闭全部自动

1. 全局指令：`scripts/install_global_auto.py --uninstall`
2. 用户级 Skill：`scripts/install_dsh_skill.py --target user --uninstall`（本机属于旧安装升级，恢复的是升级前 Skill；不会凭空删除旧安装。关闭自动只需第 1 步。）
3. 项目级 Skill（如装过）：`scripts/install_dsh_skill.py --uninstall`
4. 数据库保留；删库用 `--purge-db` 或手工删除（先备份）。

## 6. 如何测试跨会话记忆/更新/历史/遗忘

### 6.1 手动（GUI，3 个会话）

**先切到独立验收工作区**，配置自己的虚构库/身份，并执行 `doctor` 确认没有指向生产库，再执行下列步骤。此次接手已准备本机 `../MemoryGene-GUI-test-2026-10-27/` 工作区；它未完成人工验收。下面的玫瑰/栀子花与遗忘仅适用于该测试库。

1. 会话 A（工作目录=项目）：请使用 memorygene skill，记住“我最喜欢玫瑰”。
2. 确认数据库：

   ```sh
   "$MG" current --topic preference.favorite_flower   # 应输出玫瑰
   ```

3. 新开会话 B（同一工作目录）：请使用 memorygene skill，先查我最喜欢的花；然后说“栀子花也好看”，要求只记为不确定补充；最后说“现在最喜欢栀子花了”，要求按明确修订写入。
4. 会话 B 里执行/让模型执行 `history`，应看到玫瑰与栀子花都是 confirmed；`current` 是栀子花。
5. 新开会话 C：要求忘记主题 `preference.favorite_flower`；`current` 应为 `null`，`topics` 不再包含该主题。

### 6.1.1 GUI 人工验收记录

`../MemoryGene-GUI-test-2026-10-27/` 工作区已备好（独立 DB、namespace、subject）。人工在 GUI 发消息后，
用脚本核对每一步的隔离库状态：

```sh
.venv/bin/python scripts/gui_acceptance_verify.py --phase preflight
.venv/bin/python scripts/gui_acceptance_verify.py --phase after-a
.venv/bin/python scripts/gui_acceptance_verify.py --phase after-b
.venv/bin/python scripts/gui_acceptance_verify.py --phase after-c
```

每个 phase 写 `evidence/10-gui-acceptance/<phase>.json`；当前只跑过 preflight（通过），
after-a/b/c 仍需你在 GUI 中亲手完成。详见 [GUI-ACCEPTANCE.md](GUI-ACCEPTANCE.md)。

### 6.2 自动（可复现证据）

```sh
cd "<repo>"
.venv/bin/python scripts/acceptance.py      # 库级 12 场景 52 项检查（新进程/重开库）
.venv/bin/python scripts/e2e_harness.py     # 真实 4 个独立 Harness 会话（dev1 链路）
.venv/bin/python scripts/task_harness.py    # 真实 2 个 headless 会话（dev2 任务接续）
.venv/bin/python -m unittest discover -s tests -v   # 139 项
PYTHONPATH=src .venv/bin/python experiments/nl_eval.py
```

结果写入 `evidence/02-e2e/`、`evidence/01-e2e/`、`evidence/08-tasks/`，汇总见 `docs/ACCEPTANCE.md`。
独立留出 NL 基准（30 组新虚构对话、独立模型）见 [experiments/heldout-2026-10-29/RESULT.md](../experiments/heldout-2026-10-29/RESULT.md)。

---

## 7. 当前限制与未验证项

- **未在 GUI 桌面对话中由你人工逐项点选验收**：GUI 侧已记录 catalog 出现 `memorygene`、`skill` 成功载入、一次虚构自测全流程；跨会话证据来自真实 headless 会话（dev1 4 个、dev2 任务接续 2 个），不是 GUI 人工点选。`../MemoryGene-GUI-test-2026-10-27/` 已备好独立测试工作区，按第 6.1 节执行即可补齐。
- 自然语言抽取由调用模型完成；项目内的 `src/memorygene/extract.py` 只是规则基线，用于离线可复现实验，不是生产提取器，也不代表语义理解。
- `recall` 是字面检索，不是语义/同义词搜索；主题归一化靠适配层约定。
- 任务接续只做显式保存/读取/核对，不做自动概括、不控制宿主上下文；conversation locator 未独立验证；首次建任务表后旧版 dev1 无法打开该库。
- 没有后台 TTL 清理、没有 subject 一键全删、没有多值集合语义、没有主动提醒。
- `forget` 是应用层逻辑删除，不保证物理擦除。
- 互补编码只是可逆表示（每个原始字节 4 个 ASCII 字符），**不是压缩、不是加密、不是语义理解**；等预算普通副本与互补副本恢复结果相同，未证明互补有独立优势。
- 仅本机 macOS + Python 3.11 实测；Windows/Linux、远端 CI、PyPI/GitHub 发布均未执行。

---

## 8. 停用、卸载与恢复安装前状态

### 8.1 卸载 Skill 与配置

```sh
# 项目级
.venv/bin/python scripts/install_dsh_skill.py --uninstall
# 用户级（如果你装过）
.venv/bin/python scripts/install_dsh_skill.py --target user --uninstall
# 连同数据库一起删除（会丢记忆，先备份）
.venv/bin/python scripts/install_dsh_skill.py --uninstall --purge-db
```

卸载只删除安装脚本创建的文件（技能目录、配置、清单）以及可选数据库，不触碰 DSH 自身配置。

### 8.2 恢复安装前代码状态

安装前已做两层版本记录：

1. Git 基线提交：`git log --oneline` 第一行为 `snapshot: pre-handover 0.2.0.dev1 baseline`；`git diff <baseline>` 查看本轮改动。
2. 完整 tar 备份（含 `.venv` 之外的全部文件）：

   ```sh
   ls ../memorygene-backups/MemoryGene-prechange-*.tar.gz
   # 恢复到空目录示例：
   mkdir -p /tmp/mg-restore && tar -xzf ../memorygene-backups/MemoryGene-prechange-*.tar.gz -C /tmp/mg-restore
   ```

### 8.3 只停用自动/项目适配

- 项目级：删除 `<项目>/.dsh/skills/memorygene/`（或跑 `--uninstall`），对话就不再发现该技能。
- 用户级：同上，路径 `~/.dsh/skills/memorygene/`。
- 不重装包也不影响：显式 CLI 仍可手工使用，只是模型不会自动看到技能说明。

---

## 9. 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 模型说没有 memorygene skill | 会话工作目录不是项目根目录；改用项目工作目录，或 `--target user` 安装 |
| `doctor` 报 `No MemoryGene database configured` | 没传 `--db`，且当前目录向上没有 `.memorygene/dsh.json`；到项目根目录运行，或显式传 `--db` |
| `Refusing to create a new database` | 预期保护；确认新建才加 `--allow-create` |
| `Database schema/config mismatch` | 库的 index/protection 与打开参数不同；不要自动迁移，检查创建配置 |
| `IntegrityError` | 数据损坏；`repair --event-id`，失败则如实报告 |
| `--consent-evidence` 报错 | 敏感信息缺少用户同意原话；先征得明确同意 |
| headless 报 `MISSING_CREDENTIAL` | 未加 `--patch tools/dsh/headless-account.patch.yml`；该 patch 复用现有登录 |
| 模型只回复“记住了” | 要求它展示实际命令与返回 JSON；或用 `current` 独立核验 |

---

## 10. 文件位置速查

| 内容 | 路径 |
| --- | --- |
| 项目 | `<repo>` |
| 生产数据库（已显式创建为空库） | `<项目>/var/memorygene.db` |
| 适配器配置 | `<项目>/.memorygene/dsh.json` |
| 项目级 Skill | `<项目>/.dsh/skills/memorygene/SKILL.md` |
| 用户级 Skill（已安装） | `~/.dsh/skills/memorygene/SKILL.md` |
| 用户级全局指令（已启用） | `~/.dsh/AGENTS.md`（含 `memorygene:global-auto` 段） |
| 全局自动启用/关闭脚本 | `<项目>/scripts/install_global_auto.py` |
| 验收测试数据库 | `<项目>/evidence/02-e2e/acceptance.db`、`<项目>/evidence/01-e2e/harness.db`、`<项目>/evidence/08-tasks/` 下测试库 |
| 验收证据 | `<项目>/evidence/` |
| 安装前备份 | `<outputs>/memorygene-backups/MemoryGene-prechange-*.tar.gz` |
| 最终交付 ZIP | `<outputs>/MemoryGene-0.2.0.dev2-task-checkpoints.zip`（清单 `../MemoryGene-0.2.0.dev2-task-checkpoints-MANIFEST.json`） |
