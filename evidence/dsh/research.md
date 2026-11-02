# DSH 0.2.1-rc.2：项目级 Skill 发现 与 GUI 工作区语义 研究报告

> 适用对象：本机安装的 DeepSeek Harness Electron 桌面版 `0.2.1-rc.2`
> （`dsh --version` 实测输出即此值）。
> 结论只对**这个已安装版本**保证；升级后需重跑 `evidence/dsh/` 中的命令。
>
> 引用格式：`@deepseek-ai/<pkg>/lib/index.js:行号` 指向 **app.asar 内**该文件
> （`/Applications/DeepSeek Harness.app/Contents/Resources/app.asar` 的
> `/dsh/node_modules/...` 条目）。用 `tools/dsh/extract_asar.js` 可把这些文件原样
> 取到本地再对照，§7.1 给了命令。
>
> 事件/日志类证据在 `evidence/dsh/`，索引见 `live-probe-summary.md`。

---

## 0. 结论速览

1. **规则（L2，源码级）**：本版本 `dsh-skill-filesystem` 只扫描 5 类根目录，按 rank
   从 100（`<projectRoot>/.dsh/skills`）到 600（bundled）合并；技能条目只能是
   `<root>/<name>/SKILL.md` 或 `<root>/<name>.md`，且只扫一层；`projectRoot` =
   **最近的包含 `.git` 的祖先目录**，没有则等于会话 cwd。frontmatter 必须有
   `name`+`description`，name 必须 kebab-case。
2. **headless 实测（L1）**：以 `/tmp/mg-probe-project` 为 cwd 的真实
   `dsh --profile headless` 会话发现了放在 `.dsh/skills/dsh-probe-dummy/` 的临时技能，
   `skill` 工具成功载入（session `session-510a6e7c-...`）；同 prompt 在无根目录的 cwd
   下报 `unknown or no longer available` 且**完全没有** catalog（`session-08abee69-...`）；
   从 git 仓库子目录 `/tmp/mg-probe-project/sub` 启动也通过父级 `.git` 命中了项目根
   （`session-a9843874-...`）。
3. **生产路径实测（L1）**：在真实 MemoryGene 项目目录为 cwd 的 headless 会话中，
   Lead 安装的 `memorygene` 技能被 catalog 广告并通过 `skill` 工具完整载入
   （`session-c7af3dac-...`，base dir 指向 `<MemoryGene>/.dsh/skills/memorygene`）。
   **即：项目级 skill 在“会话 cwd 位于项目内（或项目子目录且项目有 `.git`）”时会被发现。**
4. **GUI（L1 机制 + L2 项目根）**：桌面 GUI 就是 desktop-host 起的 Web 应用；新会话的
   cwd = `workspaceId` 对应工作区路径 > 请求里的 `cwd` > Host 进程 cwd
   （Desktop 下 Host cwd 固定是 `~/.dsh/profiles/desktop`）。GUI 有 “Add workspace…”
   文件夹选择器，可把 MemoryGene 注册为工作区；此后该工作区里新建的会话 cwd 就是
   MemoryGene，项目级 skill 会被发现。**可以直接观测到的事实**：本 GUI 会话
   （`DSH_PROFILE=desktop`，session `7fec6827-…`，cwd `~`）确实挂着
   `skill-filesystem` + `tool-skill`：Lead 在 15:32 安装 `~/.dsh/skills/memorygene` 后，
   该会话的 catalog 在**运行中**被 host watcher 替换为含 `memorygene` 的新 catalog
   （seq 986，`update: true`），并且 GUI 里的 `skill` 工具成功载入，返回
   `Base directory for this skill: ~/.dsh/skills/memorygene`
   （见 `gui-live-catalog-evidence.md`）。**结论：用户可以在 GUI 里打开一个以
   MemoryGene 为根的会话**（Add workspace / `working_directory` cd 两条路，§4.3）；
   项目根下的发现遵循同一 provider + 同一 cwd 规则，GUI 整体链路已 L1 验证，
   只缺“会话 cwd 真的设在 MemoryGene 里”的那一步人工验证（§7.6）。
5. **第二条项目级通道（L1）**：`AGENTS.md` / `CLAUDE.md` 由 `dsh-agent-instructions`
   自动注入（headless 全局挂载；Web/Desktop 在 standard preset 内），首次请求即把
   “项目根 → cwd”链上的文件作为 `source.kind="agent-instructions"` 的 user message
   注入。实测：`/tmp/mg-probe-project/AGENTS.md` 里的 marker 被自动带入并原样答出
   （`session-e4995f1e-...`）。这是**零安装、项目级、自动**的提示注入面，适合放
   “回答前先 recall / 每轮后 write”的协议约定；它仍是提示层而非宿主强制（详见
   `auto-integration.md`）。

---

## 1. 证据与复现方法

### 1.1 安装版本与关键路径

| 项 | 值 |
|---|---|
| 应用 | `/Applications/DeepSeek Harness.app` |
| asar（唯一源码真相） | `.../Contents/Resources/app.asar`（182,833,898 B；Electron 主进程 `/lib/main.js`，DSH runtime 在 `/dsh/`） |
| CLI | `.../Contents/Resources/runtime/cli/bin/dsh`（`--version` → `0.2.1-rc.2`） |
| DSH home | `~/.dsh`（`$DSH_HOME` 可覆盖） |
| profiles | `~/.dsh/profiles/{desktop,web,headless,node_modules}`；desktop = Electron 独占 |
| 会话持久化 | `~/.dsh/sessions/--<规范化 cwd>--/<session-id>/session.v4.jsonl.zstd` |

Electron 主进程证据：`/lib/main.js:79-84`（`resolveDesktopPaths()` → `~/.dsh/profiles/desktop`）、
`/lib/main.js:12051`（`const activeProject = paths.profile`）、
`/lib/main.js:12182`（`new DesktopHostProcess(..., activeProject, ...)`）、
`/lib/main.js:3803`（子进程 `cwd: this.projectDir`）。即 **Desktop Host 进程的 cwd 是
profile 目录，不是用户项目目录**。

### 1.2 从 app.asar 正确取源（重要：header padding 坑）

asar 的 JSON header 之后有 **4 字节对齐 padding**，文件数据从
`16 + headerSize + pad` 开始（本 archive：headerSize=4780386，pad=2，dataBase=4780404）。
常见的 `base = 16 + headerSize` 写法会让每个文件整体偏移 -2 字节：行号错位 1 行、末尾丢 2 字节。
本报告所有行号都基于修正后的提取结果；`tools/dsh/extract_asar.js` 已修正并验证与手工修正版
逐字节一致：

```sh
node tools/dsh/extract_asar.js --out /tmp/dsh-src \
  --prefix /dsh/node_modules/@deepseek-ai/dsh-skill-filesystem
cmp /tmp/dsh-src/dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/lib/index.js \
    /tmp/asar2/dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/lib/index.js   # identical
```

### 1.3 证据等级

| 等级 | 含义 | 本报告中的例子 |
|---|---|---|
| **L1 实测** | 真实 DSH 进程跑出来、有落盘日志/会话事件可查 | headless 5 次运行（`live-probe-*.log`、`*.session.jsonl`） |
| **L2 源码** | 直接读已安装的 `lib/index.js` / Electron `main.js` | 发现规则、GUI 会话 cwd 逻辑 |
| **L3 推断** | 由 README/组合 dump/间接观测推出 | Desktop GUI 的 preset 挂载（CLI 拒绝 dump desktop） |

---

## 2. 本地文件系统 skill provider 的发现规则

实现：`@deepseek-ai/dsh-skill-filesystem`。注册表/合并：`@deepseek-ai/dsh-skill`。
读取入口 `apply()`（`lib/index.js:46-61`）→ `FileSystemSkillProvider.list()`（`:93-108`）
→ `roots(cwd)`（`:149-188`）→ 每个根 `discoverRoot()`（`:584-617`）。

### 2.1 根目录与 rank 表

`lib/index.js:20-24` 定义 rank 常量，`:149-188` 组装（与
`README.md:44-56` 的表格一致）：

| rank | source | 路径 | 备注 |
|---|---|---|---|
| 100 | `project-dsh` | `<projectRoot>/.dsh/skills` | 项目级首选 |
| 200 | `project-agents` | `<projectRoot>/.agents/skills` | 项目级兼容 |
| 300 | `custom` | `Config.customSkillDirs`（按给定顺序） | 需显式配置 |
| 400 | `user-dsh` | `$DSH_HOME/skills`（默认 `~/.dsh/skills`） | 跳过其 `.system` 子目录（`:589`） |
| 500 | `user-agents` | `$DSH_AGENTS_HOME/skills`（默认 `~/.agents/skills`） | |
| 600 | `bundled` | `Config.bundledSkillDir`，缺省取 `$DSH_BUNDLED_SKILL_DIR`（`:83`） | 只在 includeDefaultRoots 时取 env |

`includeDefaultRoots`（默认 true，`:32`）为 false 时项目/用户根与 env 缺省全部消失，
只剩 custom/bundled。所有根目录**不存在是合法空集**（ENOENT/ENOTDIR → []，
`:625-630`/`:643-655`）。

### 2.2 项目根 = 最近的含 `.git` 的祖先

`lib/index.js:810-818`：

```js
async function findProjectRoot(cwd, fs) {
  let current = cwd;
  while (true) {
    if (await pathExists(join(current, ".git"), fs)) return current;
    const parent = dirname(current);
    if (parent === current) return cwd;   // 到文件系统根仍没有 .git → 退回 cwd
    current = parent;
  }
}
```

- `pathExists` 只判断“存在”（`access`/`fs.stat`），`.git` 是目录还是文件（worktree）都算。
- **没有 `.git` 时 projectRoot = cwd 本身**，不会向上找别的标记；因此
  “会话 cwd 在子目录 + 项目没有 `.git`” ⇒ 发现不到项目根的 `.dsh/skills`。
- 本仓库已是 git repo（`.git` 存在），所以 cwd 在任意子目录也会解析到仓库根。
- 同一规则也决定 `AGENTS.md` 链的起点（`dsh-agent-instructions/lib/index.js:673-674`）。

### 2.3 条目形态与 frontmatter 解析

`discoverRoot()`：对根的**直接子项**按 `name.localeCompare` 排序（`:587`），然后

- 目录 → `<root>/<name>/SKILL.md`（`:589-592`）；
- 文件且以 `.md` 结尾 → `<root>/<name>.md`（`:593-595`）；
- 其它一律忽略。**只扫一层**：`references/`、`scripts/`、嵌套 `**/SKILL.md` 都不会被发现
  （README 已知限制 `README.md:147`）。

`parseSkillFile()`（`:667-708`）+ `parseFrontmatter()`（`:783-796`）：

1. 首行必须是 `---`（允许 CRLF），必须有成对的闭合 `---` 行；否则“missing YAML frontmatter”。
2. YAML 必须是 mapping；`name`、`description` 必须是**非空字符串**（`:682-687`）。
3. `name` 必须匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$`（`dsh-skill/lib/index.js:17,29`；
   `my_skill`、`MySkill`、`my skill` 都会被丢弃并 warn）。
4. invocation 策略（`:852-880`）：只接受规范键 `disable-model-invocation` /
   `user-invocable`；出现旧键名（`disableModelInvocation`、`modelInvocable`、
   `userInvocable`）会让整个 skill 被丢弃（`:863-866`）。布尔值接受 YAML bool、
   `yes/no/on/off`、`true/false`、`1/0`（`:866-881`）。
5. 可选 `whenToUse`（字符串）、`metadata`（mapping）。未知键忽略。
6. 解析失败/校验失败 ⇒ **只 warn、该文件消失**；模型侧看不到任何 per-skill 诊断
   （README `README.md:85,149`）。

`dsh-skill/lib/index.js` 侧还会对 provider 返回的候选再校验一遍
（name/description/invocation/source/rank，`:452-464`）。

### 2.4 冲突与合并

- 同一 provider 内：候选先按 `candidate.rank` 升序，再按 provider 注册顺序，最后按扫描顺序
  （`dsh-skill/lib/index.js:312-330` + `compareIndexedCandidates` `:519-521`）；
  **同名先到先得，后来的记 warn `... ignored because a higher-priority skill already exists`**。
- 跨 provider / 跨 scope：`SkillRegistry` 是**分层注册表**（global 层 + agent preset 的
  scope 层，`:108-124`）；读时 global + 当前 scope 链合并，**就近 scope 的同名项直接赢**，
  rank 只在同一层内决定同名冲突（`:298-311`、`:331-375`）。
- 对用户可见的结论：`<projectRoot>/.dsh/skills`（rank 100）压过
  `~/.dsh/skills`（400）和 `~/.agents/skills`（500）；但 agent preset 若在 scope 层注册了
  同名 runtime skill，会覆盖所有文件系统 provider。

### 2.5 监听与刷新

`SkillWatchManager`（`:190-483`）：根存在则 chokidar depth=1 监听；根不存在则用
`fs.watchFile` 逐段探候（`:506-541`）。相关事件 = 直接条目 add/remove、直接 `.md`、
直接 `SKILL.md` add/remove/change（`:545-555`）；`references/` 等资源子树变更**不**触发刷新
（README `README.md:81`）。`write`/`edit` 工具命中潜在 skill 路径时会同步 invalidate
（`:57-60`、`:239-244`）。刷新后 `tool-skill` 会在下一次 pre-step 追加**完整替换 catalog**
（见 §3.2）。

---

## 3. 会话 cwd 如何决定发现范围，以及 `skill` 工具

### 3.1 各入口的 cwd 来源

| 入口 | 初始 cwd | 证据 |
|---|---|---|
| headless | `fs.resolve('.')` → `process.cwd()`（无 fs 服务时直接用 cwd） | `@deepseek-ai/dsh-headless/lib/index.js:316`；README `:68-80` |
| Web/Desktop 新建会话 | `workspace?.path ?? request.cwd ?? defaultCwd`；`defaultCwd = process.cwd()` | `@deepseek-ai/dsh-api-session-controller/lib/index.js:762`、`:2957` |
| Desktop Host 的 `process.cwd()` | `~/.dsh/profiles/desktop`（Electron 用 profile 目录 spawn Host 子进程） | `/lib/main.js:79-84,12051,3803`；`dsh-desktop-host/lib/index.js:221,224,228` |
| 会话内 | `working_directory` 工具可读/`cd`，变更写入会话并触发下一请求重发现 | `dsh-tool-working-directory/lib/index.js:16-42`；`dsh-working-directory/lib/index.js:26,34,76-78,113-152` |

会话 header 记录初始 cwd（`working-directory/lib/index.js:34` 的 projection `init:
(header) => header.cwd ?? null`；`defaultDirectory = config.defaultDirectory ?? process.cwd()` `:26`）。
`skill-filesystem` 每次 `list()` 都拿当前 cwd 重新解析项目根，所以**会话中途 `cd` 进项目目录
后，下一个 pre-step 就能看到项目技能**。

### 3.2 `tool-skill` 如何把 catalog 给模型

`@deepseek-ai/dsh-tool-skill/lib/index.js`：

- 注册模型工具 `skill`（`:787-895`）；`execute` 用
  `ctx.workingDirectory.ensure(agent)` 得到 cwd，再 `ctx.skills.list(lookup)` 找名字
  （`:866-885`）。SKILL.md 会以 `<skill_content name="...">` + `<skill_resources>` +
  `<skill_instructions>` 的形态作为工具结果返回（`dsh-skill/lib/index.js:57-70`；
  实测见 `live-probe-positive.stdout.log` 的 `tool_result`）。
- 另一个 `agent/pre-step` 监听器（`:931-964`）每步 `ctx.skills.snapshot({cwd: workingDirectory.ensure(agent)})`，
  按 `name+description` 的 sha256 digest 与 session 里最新可见的 `skill-catalog` 消息比较；
  变了就追加/替换一条**完整 catalog 的 user message**（`:966-989`）。catalog 只在
  “模型可调用 skill 非空或已发布过”时出现；**没有任何技能且从未发布过 ⇒ 完全不发消息**
  （`:955-958`），这正是 negative run 的现象。
- 每条 catalog 条目只含 name + 归一化截断到 500 字符的 description（`:768,1087-1090`），
  不渲染 `whenToUse`/source/provider（README `:244`）。
- 用户消息里的空白分隔 `/name` token 会触发 user-explicit 注入（`:1101-1121`、
  `:896-930`），与 `skill` 工具结果同形；这是 `disable-model-invocation` 技能的唯一入口。
- 重复加载的提示语与“catalog 只是摘要”的规则写在 catalog 模板里（`:966-989`）。

### 3.3 刷新时序（用户视角）

新建会话/`cd` 后：cwd → 下一 pre-step 重新 snapshot → digest 变化 → 追加 replacement catalog →
模型可 `skill` 加载。监听器还能在运行中捕捉文件增删；但**只改 SKILL.md 正文**不会改变
catalog digest（description 未变），只影响下一次 `skill` 加载的内容（README `:138,249`）。

---

## 4. GUI / Desktop 的工作区与“项目根”

### 4.1 进程结构

Electron 主进程（`/lib/main.js`）拉起两个东西：
1. 目录选择器 IPC：`installDesktopDirectoryPicker()`（`/lib/main.js:7028-7050`，
   `dialog.showOpenDialog({properties:["openDirectory"]})`）——GUI 的“Add workspace…”底层；
2. Desktop Host 子进程：`@deepseek-ai/dsh-desktop-host`，以 `~/.dsh/profiles/desktop` 为
   `projectDir` 和 cwd，`runProfile({profile:"desktop", args:["--no-open","--host","127.0.0.1","--port","0"]})`
   （`dsh-desktop-host/lib/index.js:219-250`），最后由 `runProfile` 起 Web 应用
   （`@deepseek-ai/dsh-web-app`）；本机 GUI 地址即该 Host 的 `127.0.0.1:<port>`。
   因此 **GUI 就是 Web 前端 + Host 服务**，“工作区/会话/技能”逻辑都在 DSH 侧，不在 Electron 侧。

### 4.2 工作区 = 已注册的规范化目录；会话按 cwd 归属

`@deepseek-ai/dsh-workspace/lib/index.js`：工作区记录 = 一个经 `realpath` 规范化的绝对目录
（`:48-51`），唯一性按规范化字符串；会话只有在 `session.header.cwd` 解析后**等于**该目录时
才能挂到该工作区（`:111-129`；`session.create` 的 `workspaceId` 路径随后
`workspace.attachSession`，`dsh-api-session-controller/lib/index.js:762-786`）。
首个工作区是 `${Documents}/deepseek-harness/default-workspace`
（`dsh-api-workspace-controller/lib/types/default-workspace.js:15`、
`default-directory.js:63`；README `:34`）。

工作区不是“项目根”；**项目根**始终由 §2.2 的 `.git` 规则从会话 cwd 推出。
工作区只是把“用户选择的目录”变成会话 cwd 的一种方式。

### 4.3 能否在 GUI 里打开以 MemoryGene 为根的会话？**能**，两条路：

1. **Add workspace → 选 MemoryGene 目录 → 在该工作区新建会话**
   （`dsh-client-ui-workspace/README.md:44`：“Choose **Add workspace** and select a directory
   to register it and open a Session”；`:100` 目录选择器 hole；侧栏/Hero 的快捷入口
   `README.md:30,62`）。新会话 cwd = 工作区 canonical 路径，`projectRoot` = 最近 `.git`
   祖先 = MemoryGene（本仓库已有 `.git`）。
2. **在已有会话里让 cwd 进入项目**：`working_directory(cd="/…/MemoryGene")`（模型可调，
   用户也可以直接要求“cd 到项目”），下一个 pre-step 就按新 cwd 重新发现；会话因此也变成
   该工作区的成员（cwd 相等）。实测 headless 的等价行为就是 §5 的 run 3。

注意：**只启动 App 不会自动把 cwd 放到项目**；Desktop Host 自己的 cwd 是
`~/.dsh/profiles/desktop`，若界面未选择工作区，新会话的默认 cwd 就是这个 profile 目录
（`defaultCwd = process.cwd()`，`api-session-controller:2957`）。此时项目 skill 不可见。

### 4.4 Desktop 组合里 skills 插件挂在哪一层

Web/Desktop 组合来自 `dsh-web-app` bundle 的 patch：它把全局的
`tool-fs`/`tool-fs-search`/`skill-filesystem`/`tool-skill`/`agent-instructions` 行
**置为 disabled**，改为在 `standard` agent preset 的 `plugins` 列表里按 agent 挂载
（`dsh --profile web --dump-config` 的 `preset-standard` 段，包含
`agent-instructions`、`skill-filesystem`、`tool-skill`）。Desktop profile 的 bundle 列表
（`~/.dsh/profiles/desktop/package.json`）包含 `dsh-web-app`，故同一 preset 定义生效；
`~/.dsh/profiles/desktop/cordis.patch.yml` 是用户 patch 层（本机只改 UI/模型配置）。

**L1 实测（Desktop GUI 会话本身，无模型调用）**：本 GUI 会话
（`DSH_SESSION_ID=7fec6827-6797-48ae-8b21-5c1006d1798e`，header cwd `~`，
`DSH_PROFILE=desktop`）的持久化日志里可以读到两条 `source.kind="skill-catalog"` 的
`user/message`：

- seq 11：初始 catalog = 只有 `office` 系列 7 条（来自 desktop-host mount 的
  `dsh-skill-office` provider，`dsh-desktop-host/lib/index.js:331-335`、
  `dsh-skill-office/lib/index.js:101`）；
- seq 986：`update: true` 的**完整替换** catalog = `memorygene` + office 系列。
  这条是 Lead 在 15:32 把技能装到 `~/.dsh/skills/memorygene`（user-dsh 根，rank 400）
  之后由 `SkillWatchManager` 的 watcher 触发、在**正在运行的 GUI 会话**里追加的。

随后在该 GUI 会话里真实调用 `skill({name:"memorygene"})`，工具结果给出
`Base directory for this skill: ~/.dsh/skills/memorygene`。
这说明：Desktop profile 的会话确实挂着 `skill-filesystem` provider 与 `tool-skill`，
且 watcher 刷新链路在此环境可用。证据：`gui-live-catalog-evidence.md`。

> 为什么这条是 user-dsh 根而不是项目根：该会话 cwd 是 `~`，没有 `.git`，
> 项目根就退化成 `~`，所以只会扫 `~/.dsh/skills`。若要验证“项目根 = MemoryGene”
> 的 GUI 路径，需要把会话 cwd 放进项目（§7.6）；headless 侧等价行为见 §5 run 4。

> **限制**：Desktop profile 的 composed config 无法用 CLI dump：
> `dsh --profile desktop --dump-config` → `error: profile "desktop" is managed
> exclusively by the Electron application`（实跑，exit 1）。所以“哪些行挂在哪一层”
> 仍是 “web-app bundle 同源 patch”（L2）+ “GUI 运行时行为”（L1）的组合结论。

---

## 5. 实测结果（详细日志与 session id 见 `live-probe-summary.md`）

| # | cwd | 临时/真实技能 | 结果 | 关键证据 |
|---|---|---|---|---|
| 1 | `/tmp/mg-probe-project`（git） | `.dsh/skills/dsh-probe-dummy` | 发现并载入，返回 nonce | `live-probe-positive.*`，session `session-510a6e7c-…` |
| 2 | `/tmp/mg-probe-control`（无根） | 无 | `skill` 报 unknown；**无 catalog 消息** | `live-probe-negative.*`，session `session-08abee69-…` |
| 3 | `/tmp/mg-probe-project/sub` | 同上（父级 `.git`） | 发现并载入 | `live-probe-subdir.*`，session `session-a9843874-…` |
| 4 | 真实 MemoryGene 项目（git） | Lead 安装的 `memorygene` | 发现并完整载入，base dir 正确 | `live-probe-real-project.*`，session `session-c7af3dac-…` |
| 5 | `/tmp/mg-probe-project` + `AGENTS.md` | — | `agent-instructions` 消息自动注入并原样答出 marker | `live-probe-agents-md.*`，session `session-e4995f1e-…` |
| 6 | **Desktop GUI 活会话**，cwd `~` | `~/.dsh/skills/memorygene`（Lead 运行中安装） | catalog 被 watcher 热替换（seq 986, `update:true`）；`skill` 工具从 GUI 载入成功 | `gui-live-catalog-evidence.md`，session `7fec6827-…`（0 次模型调用，读会话日志） |

结论因此是**实测**而非推断：
(a) 项目级 `.dsh/skills` 被真实 headless 会话发现；
(b) 没有根目录时 catalog 完全不出现（negative control 干净）；
(c) 项目根按最近 `.git` 祖先解析（子目录 run）；
(d) 真实安装的 `memorygene` skill 在生产 cwd 下可被 catalog 广告并载入；
(e) `AGENTS.md` 自动注入通道成立；
(f) Desktop GUI 会话确实挂着文件系统 skill provider + `skill` 工具，且运行中安装新技能会被
    host watcher 捕捉并追加替换 catalog（这一条是 GUI L1）。

---

## 6. 项目内已安装 skill 的确定性验证（无模型）

Lead 安装后的产物（本次只读，未改动）：

- `<MemoryGene>/.dsh/skills/memorygene/SKILL.md`（name=`memorygene`，
  description/whenToUse 齐全）
- `<MemoryGene>/.memorygene/dsh.json`（adapter/python/db/namespace/subject 配置）
- `<MemoryGene>/.dsh/skills/memorygene/.memorygene-install.json`（安装元数据；
  该文件不是技能条目，不影响发现）

同一次安装还写入了 **user-dsh 根**：`~/.dsh/skills/memorygene/SKILL.md` +
`~/.memorygene/dsh.json`（rank 400；这是 GUI 会话能直接看到 `memorygene` 的原因，
见 §4.4/§5 run 6）。两个副本同名同 description，按 rank 规则**项目根副本（100）胜出**；
catalog 摘要相同，所以 catalog digest 不会因 root 变化而重建。

用 `tools/dsh/probe_skills.py`（L2 规则复现）验证：

```sh
python3 tools/dsh/probe_skills.py --cwd "$PWD" \
  --skill "$PWD/.dsh/skills/memorygene/SKILL.md"
# discovered: True / winning: True / root: <MemoryGene>/.dsh/skills (rank 100, project-dsh)
# exit 0
```

输出见 `evidence/dsh/probe-real-project-catalog.txt`、
`probe-real-project-skill-check.txt`。这与 §5 run 4 的 L1 实测一致。

---

## 7. 精确验证命令

### 7.1 从 app.asar 取源码（修正 padding）

```sh
node tools/dsh/extract_asar.js                     # 打印 headerSize/pad/dataBase/top-level
node tools/dsh/extract_asar.js --out /tmp/dsh-src \
  --prefix /dsh/node_modules/@deepseek-ai/dsh-skill-filesystem
# 关键文件：
#   /dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/lib/index.js
#   /dsh/node_modules/@deepseek-ai/dsh-skill/lib/index.js
#   /dsh/node_modules/@deepseek-ai/dsh-tool-skill/lib/index.js
#   /dsh/node_modules/@deepseek-ai/dsh-agent-instructions/lib/index.js
#   /dsh/node_modules/@deepseek-ai/dsh-api-session-controller/lib/index.js
#   /lib/main.js（Electron 主进程）
```

### 7.2 确定性 probe（无 LLM、无网络，L2）

```sh
python3 tools/dsh/probe_skills.py --cwd /path/to/project          # 看会有什么 catalog
python3 tools/dsh/probe_skills.py --cwd /path/to/project \
  --skill /path/to/project/.dsh/skills/foo/SKILL.md               # 该文件是否会被发现且胜出
python3 tools/dsh/probe_skills.py --cwd ... --json                # 机器可读
```

它按 §2 的规则（rank 表、`.git` 项目根、一层条目、frontmatter/invocation 校验、同名先到先得）
实现，并会报告 `evidence_level: L2-rule-reimplementation`；它**不**加载真实 provider
（asar 内的包无法被普通 Node `import`）。

### 7.3 headless 实测模板（会消耗模型调用）

```sh
cd <session-cwd> && /Applications/DeepSeek\ Harness.app/Contents/Resources/runtime/cli/bin/dsh \
  --profile headless --patch /tmp/dsh-mg-headless.patch.yml --json \
  "Call the skill tool with name <skill-name>, then reply with exactly ..."
```

- 按 cwd 决定会话目录；`--json` 的首行给出 `sessionId` 和 `cwd`。
- 更硬的证据：把落盘 session log 解压后直接看 `user/message` 的 `source.kind`
  （`skill-catalog` / `agent-instructions`），见 §7.5。

### 7.4 组合 dump（Web/headless 可 dump，Desktop 不可）

```sh
/Applications/DeepSeek\ Harness.app/Contents/Resources/runtime/cli/bin/dsh \
  --profile web --dump-config | sed -n '/preset-standard/,/preset-ptc/p'
# 会看到 standard preset 里的 skill-filesystem / tool-skill / agent-instructions 行

dsh --profile desktop --dump-config
# → error: profile "desktop" is managed exclusively by the Electron application
```

### 7.5 解压会话日志（确定性证据）

```sh
# 目录名规则：--<规范化 cwd，路径分隔符换成 ->--
ls ~/.dsh/sessions/
zstd -d -c ~/.dsh/sessions/--private-tmp-mg-probe-project--/session-510a6e7c-4915-4e96-94d8-18f044897f02/session.v4.jsonl.zstd > session.jsonl
grep -o '"kind":"skill-catalog"[^}]*' session.jsonl
grep -o '"kind":"agent-instructions"' session.jsonl
```

### 7.6 GUI 侧验证步骤（给 Lead / 用户，需真实安装后做一次）

1. 点侧栏 **Add workspace** → 选 MemoryGene 仓库目录；
2. 在该工作区新建会话，发一句“列出你可用的 skills / 用 `memorygene` skill”；
3. 期望：会话 catalog 出现 `memorygene`，`skill` 工具能载入，
   `Base directory for this skill: /…/MemoryGene/.dsh/skills/memorygene`；
4. 若已有会话，先让模型 `working_directory(cd="/…/MemoryGene")` 再问一次。
   注意：**只改 SKILL.md 正文**不会让 catalog digest 变化（只影响下一次载入），
   改 name/description 才会触发 replacement catalog。

---

## 8. 未验证 / 限制（必须如实对待）

1. **GUI 的“项目根”会话尚未实测**：本任务禁止在真实项目外安装技能、禁止改
   `~/.dsh`/Desktop profile，所以没有把某个 GUI 会话的 cwd 设到 MemoryGene 再灌一个
   项目级 dummy skill。GUI 链路中“provider + skill 工具 + watcher + catalog 替换”已经
   由 `gui-live-catalog-evidence.md`（L1，user-dsh 根）证实；只差“cwd 在项目内时命中的是
   `<projectRoot>/.dsh/skills`（rank 100）”这一步，用 §7.6 的人工步骤一次即可闭环
   （headless 侧等价行为已由 §5 run 4 L1 证实）。
2. **Desktop composed config 无法 dump**（CLI 明确拒绝），所以“desktop 的 standard preset
   确实挂了 skill-filesystem/tool-skill”仍属“同源 patch + 运行时行为”推断（L2+L1 行为，
   非 dump 直证）；如果将来 Desktop 组合改挂载位置，需重跑 §7.4 + §7.6。
3. `probe_skills.py` 是规则复现（L2），不是加载真实 provider；差异点见脚本 docstring
   （localeCompare 排序、仅建模 filesystem provider、frontmatter 用 PyYAML/扁平回退）。
4. 监听刷新语义只按源码/README 说明，没有对“watcher 在 Desktop 沙箱下是否总能 attach”
   做运行态观测；`watch` 失败只会让 catalog 不完整（provider 返回 `complete:false`，
   registry 不缓存），不影响首次发现。
5. 会话 cwd 在**子目录**时依赖 `.git`；本仓库目前有 `.git`（修改它会影响此行为）。
6. 5 次 headless 预算已全部用完（4 次 + 1 次 AGENTS.md probe）。

## 9. 证据文件索引（`evidence/dsh/`）

| 文件 | 内容 |
|---|---|
| `research.md` | 本文件 |
| `auto-integration.md` | 自动集成（recall/write）可行性、排名建议、风险 |
| `live-probe-summary.md` | 5 次 headless 运行的命令、session id、落盘路径 |
| `live-probe-catalog-evidence.md` | 从 4 个 headless 会话日志提取的 `skill-catalog` 原始事件 |
| `gui-live-catalog-evidence.md` | Desktop GUI 活会话：初始 catalog / 安装后热替换 catalog / `skill` 载入 base dir |
| `live-probe-*.stdout.log` / `.stderr.log` | 每次运行的原始 stdout（`--json` 事件流）与 stderr |
| `live-probe-*.session.jsonl` | 解压后的会话日志（确定性证据） |
| `probe-*.txt` | `probe_skills.py` 的确定性输出（scratch 正/负/子目录 + 真实项目） |
| `../tools/dsh/probe_skills.py` | L2 规则复现探测工具（仓库根下 `tools/dsh/`） |
| `../tools/dsh/extract_asar.js` | 修正 asar header padding 的源码提取工具 |
