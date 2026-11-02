# DeepSeek Harness 接入说明

本文说明 MemoryGene 与 DeepSeek Harness（桌面版 0.2.1-rc.2）的接入方式。以下结论仅在该版本上验证，升级后需重新运行检查。

## Skill 发现机制

Harness 按以下优先级扫描 Skill 目录，每个目录仅扫描一层：

| 优先级 | 目录 |
| --- | --- |
| 100 | `<项目根>/.dsh/skills` |
| 200 | `<项目根>/.agents/skills` |
| 300 | 配置项 `customSkillDirs` |
| 400 | `~/.dsh/skills` |
| 500 | `~/.agents/skills` |

Skill 文件需位于 `<目录>/<名称>/SKILL.md`，frontmatter 中须包含 `name` 与 `description`。项目根为距会话工作目录最近、包含 `.git` 的上级目录；若不存在，则使用会话工作目录本身。

## 安装

```sh
.venv/bin/python scripts/install_dsh_skill.py                  # 项目级安装，仅在本项目内生效
.venv/bin/python scripts/install_dsh_skill.py --target user    # 用户级安装，对所有工作区生效
.venv/bin/python scripts/install_dsh_skill.py --check          # 仅检查，不做修改
.venv/bin/python scripts/install_dsh_skill.py --uninstall      # 恢复至安装前状态
```

安装脚本仅写入三类文件：Skill 文件、适配器配置（`.memorygene/dsh.json` 或 `~/.memorygene/dsh.json`）以及用于卸载的清单。安装过程不修改 Harness 的 profile、插件、账号或计费设置。

## 调用流程

Harness 将 Skill 列入目录 → 模型按需调用 `skill(memorygene)` 读取说明 → 依照说明调用 `memorygene-dsh` → 适配器读写 SQLite → 模型依据返回结果作答。

该流程为**显式调用**：模型可以选择不调用，Harness 不会在每一轮强制执行。如需模型在所有项目中主动使用记忆，可运行 `scripts/install_global_auto.py`，在 `~/.dsh/AGENTS.md` 中加入一段提示（使用 `--uninstall` 移除）。该方式属于提示词约定，不保证模型每次遵循。

宿主强制的自动记忆（每轮前读取、对话后写入）目前无法实现：该版本没有 hooks 机制，插件只能通过 profile 加载，而桌面版 profile 由应用独占。因此本项目暂不提供插件，也不建议修改桌面 profile。

## 验证结果

- 项目级与用户级 Skill 均可被 Harness 发现并载入，已在桌面 GUI 中确认。
- 4 个独立的 headless 会话依次完成写入、跨会话读取、明确修改与遗忘，记录见 `evidence/01-e2e/`。
- 任务接续功能在两个独立会话中完成保存与恢复，记录见 `evidence/08-tasks/`。
- 启用用户级全局提示后，在两个不同项目中，即使用户未提及 Skill 名称，模型也能自动写入并召回记忆。

## 数据与身份

- 数据库默认位于 `<项目>/var/memorygene.db`，依次按 `--db`、`MEMORYGENE_DB`、配置文件解析路径；无法解析时报错，不会隐式创建新库。
- `namespace` 默认为 `dsh`，`subject` 默认为 `owner`；不同用户应使用不同的 subject。
- 会话级记忆自动使用 Harness 提供的 `DSH_SESSION_ID`。
- `namespace` 与 `subject` 仅为逻辑分区，不具备访问控制功能。

## 复验命令

```sh
python3 tools/dsh/probe_skills.py --cwd "$PWD" --skill "$PWD/.dsh/skills/memorygene/SKILL.md"
.venv/bin/python scripts/install_dsh_skill.py --check
.venv/bin/python scripts/e2e_harness.py      # 将实际调用模型
.venv/bin/python scripts/acceptance.py       # 库级验收，不调用模型
```
