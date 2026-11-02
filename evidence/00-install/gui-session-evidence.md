# GUI 会话内的 Skill 发现、加载与执行证据

会话：本轮 DeepSeek Harness 桌面 GUI 会话（`DSH_SESSION_ID=session-8b5a3864-e699-4b7f-aee4-a72899e6f0e8`，
profile `desktop`，工作目录 `~`）。

## 1. 发现（catalog）

安装用户级 Skill 到 `~/.dsh/skills/memorygene/` 后，**同一个 GUI 会话**收到宿主下发的完整
available-skills 目录替换，其中第一条为：

```
- `memorygene`: 用 MemoryGene 本地 SQLite 记忆库保存用户明确陈述的长期事实与偏好，
  支持跨会话查询、明确修订、历史、到期过滤与遗忘。数据只写本地库，不联网。
```

说明：本项目工作目录 `~` 没有 `.git`，DSH 的 project root 回退为该 cwd，
所以 `<cwd>/.dsh/skills`（即 `~/.dsh/skills`）与用户级根目录重合；这也是当前 GUI 工作目录下
能被发现的原因。证据层级：**L4 真实 GUI 会话**（宿主实际注入）。

## 2. 加载

在同一 GUI 会话调用 `skill(name="memorygene")`，工具返回了完整的 `<skill_content>`，
包含安装后的绝对路径、数据库/身份值和全部操作规则（见本会话工具调用记录）。

## 3. 执行（隔离的虚构测试库）

命令与完整输出：`evidence/00-install/gui-live-selftest.log`

摘要（`namespace=dsh-gui`，`subject=gui-selftest`，数据库
`evidence/00-install/gui-live/gui-test.db`，全部为虚构数据）：

| 步骤 | 结果 |
| --- | --- |
| 显式创建测试库 | `verify` → ok，events=0 |
| 记住“最喜欢玫瑰” | `confirmed` |
| “栀子花也好看”不确定补充 | `pending` |
| 查当前 | 玫瑰（未被改变） |
| 明确说“现在最喜欢栀子花” | `confirmed` |
| 查当前 | 栀子花 |
| 查历史 | confirmed 玫瑰、pending 栀子花、confirmed 栀子花 |
| 完整性扫描 | ok，events=3，heads=1 |
| 遗忘该主题 | forgotten=3 |
| 遗忘后 current / verify | `null` / ok，events=0 |

另外：安装配置指向的生产库 `<项目>/var/memorygene.db` 在“用户明确建库”步骤中被显式创建为空库
（`--allow-create verify`），不是隐式创建；未写入任何测试数据。

## 4. 证据层级说明

- 本节是**真实 GUI Harness 会话**中的发现、加载与执行，但执行者是本轮代理，不是独立人类对话。
- 更独立的证据是 `evidence/01-e2e/`：4 个**独立 headless Harness 进程**（4 个不同 session id），
  完成写入 → 跨会话读取 → 明确修订 → 遗忘，全部 4/4 通过。
- 尚未完成的：由用户在 GUI 中亲手完成一轮对话验收（见 `docs/USAGE.zh.md` 第 6.1 节步骤）。
