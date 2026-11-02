# 跨项目自动记忆：启用与验证

目标：在**任意项目**里，模型不需要用户说“请使用 memorygene skill”，也能自动召回/写入长期记忆。

本版本 DSH（0.2.1-rc.2）没有项目级代码插件/hooks 通道，因此实现分两层：

1. **用户级 Skill**（`~/.dsh/skills/memorygene/`）：DSH 的 `dsh-skill-filesystem` 在每个工作区都会
   扫描 rank 400 用户根，所以 skill 会**自动出现在每个项目的 catalog**（已实测，见 §1）。
2. **用户级全局指令**（`~/.dsh/AGENTS.md`）：DSH 的 `dsh-agent-instructions` 会在每个会话自动注入
   user-global 指令（源码规则见 `@deepseek-ai/dsh-agent-instructions` README；本机实测见 §2）。
   这段指令要求模型在涉及本人长期信息时先 `skill(memorygene)` 再读写。

这是一层**提示词约定**，不是宿主强制；若模型没执行，用户直接要求即可。真正的“每轮强制”必须自研
Host 插件装进某个 profile（本轮未构建、未安装）。

启用/关闭（一条命令）：

```sh
cd "<repo>"
.venv/bin/python scripts/install_global_auto.py            # 启用
.venv/bin/python scripts/install_global_auto.py --check    # 检查
.venv/bin/python scripts/install_global_auto.py --uninstall # 关闭（会保留用户级 Skill）
```

当前已启用：`~/.dsh/AGENTS.md`（0600，含 `memorygene:global-auto` 标记段）、
`~/.dsh/skills/memorygene/`、适配器配置 `~/.memorygene/dsh.json`（数据库
`<项目>/var/memorygene.db`，namespace `dsh`，subject `owner`）。

## 1. 任意项目自动发现 Skill（L1）

在临时 git 项目 `/tmp/mg-crossproj`（与 MemoryGene 无关）运行 headless 会话，未提 skill 名称：

- 输出：`memorygene`、`WORKSPACE_INSTRUCTIONS=no`（当时尚未启用全局指令）
- session：`session-b6e4e5a2-0200-4c8e-b6f2-0b676fd488ee`
- 结论：用户级 Skill 在所有项目自动出现在 catalog。

## 2. 全局指令自动注入（L1，GUI）

启用 `~/.dsh/AGENTS.md` 后，**当前 GUI 会话**立刻收到宿主注入的 user-global instructions
（内容即 `AGENTS.user-global.md` 渲染结果，见回合上下文）。这证明 desktop profile 也挂载了
`dsh-agent-instructions`。

## 3. 首次跨项目测试：发现两个真实边界

会话 A（`/tmp/mg-proj-alpha`，未提 skill）：模型自动加载 memorygene 并执行 `doctor`，但发现
测试库不存在，**拒绝隐式建库**，明确报告未保存（安全行为正确）。
会话 B（`/tmp/mg-proj-beta`）：自动召回成功，读到当时库里已有的用户记忆「桂花」。

随后改用真实生产配置重试写入：headless 默认 `DSH_PERMISSION_MODE=workspace-write`，而数据库在
另一个目录，于是 `remember` 报 `attempt to write a readonly database`；模型如实报告失败，没有伪造成功。
说明：**headless/受限会话需要 `DSH_PERMISSION_MODE=danger-full-access` 才能写工作区外的固定库**；
GUI 当前会话文件策略是 `danger-full-access`，因此正常。

### 意外与恢复（如实记录）

在清理第一次测试数据时，我执行了 `forget --topic preference.favorite_flower`，**误删了用户此前
自己写入的记忆“桂花”**（该记录不是本轮测试数据）。已立即用相同 topic/value/source/certainty/importance
重新写入恢复：`current=桂花`，`verify ok`。但原事件的 `at`/`recorded_at`/`event_id` 已丢失，
恢复记录使用新的接收时间；这是不可完全还原的损失。后续清理只针对本轮测试主题 `preference.favorite_tea`。

## 4. 最终跨项目验证（L1，full-access）

环境：`DSH_PERMISSION_MODE=danger-full-access`，生产配置（`dsh` / `owner`），两个不同 git 项目。

| 会话 | 项目 | 用户话术（未提 skill） | 结果 |
| --- | --- | --- | --- |
| A3 | `/tmp/mg-proj-alpha` | “请记住我的长期偏好：我最喜欢喝的茶是乌龙茶…” | 自动加载 skill，`remember preference.favorite_tea=乌龙茶` → `confirmed` |
| B3 | `/tmp/mg-proj-beta` | “我最喜欢喝什么茶？请结合记忆回答。” | 自动加载 skill，回答“乌龙茶”，并说明来源与 confirmed |

- session id：A3 `session-9e938c2f-6486-4fca-8712-ebc8a4656fe7`，B3 `session-c30a1edc-fd43-40c6-b3be-3b59d1362711`
- 独立数据库复核：`current tea=乌龙茶`；清理 `forget preference.favorite_tea` 后 tea=null，
  用户记忆 `flower=桂花` 保留，`verify ok`。
- 原始事件流：`A3-write-events.jsonl`、`B3-recall-events.jsonl`；更早尝试：
  `A-write-*`、`B-recall-*`、`A2-write-*`、`B2-recall-*`。

## 5. 结论

- **自动召回**：跨项目可用（skill 自动广告 + 全局指令），实测 L1。
- **自动写入**：跨项目可用，前提是会话文件策略允许写固定库路径（GUI 当前 full-access；受限会话需
  放宽策略，或把库放在该工作区内）。
- **不是强制机制**：模型仍可能跳过；本轮未构建 Host 插件，也未修改 DSH profile/凭据。
- 关闭：`scripts/install_global_auto.py --uninstall`（移除全局指令）+
  `scripts/install_dsh_skill.py --target user --uninstall`（移除用户级 Skill）。
