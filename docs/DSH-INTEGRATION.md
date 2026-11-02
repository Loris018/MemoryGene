# 接入 DeepSeek Harness

我平时用 DeepSeek Harness（桌面版 0.2.1-rc.2）跑本地 Agent，所以第一个接入对象选了它。下面的结论只在这个版本上验证过，换版本要重新跑一遍检查。

## Harness 怎么发现 Skill

Harness 会按优先级扫描这几个目录，每个目录只看一层：

| 优先级 | 目录 |
| --- | --- |
| 100 | `<项目根>/.dsh/skills` |
| 200 | `<项目根>/.agents/skills` |
| 300 | 配置里的 `customSkillDirs` |
| 400 | `~/.dsh/skills` |
| 500 | `~/.agents/skills` |

Skill 必须放成 `<目录>/<名字>/SKILL.md`，frontmatter 里要有 `name` 和 `description`。项目根是离会话目录最近、带 `.git` 的那一级目录，找不到就用会话目录本身。

## 安装

```sh
.venv/bin/python scripts/install_dsh_skill.py                  # 项目级：只在这个项目里生效
.venv/bin/python scripts/install_dsh_skill.py --target user    # 用户级：所有工作区都能用
.venv/bin/python scripts/install_dsh_skill.py --check          # 只检查，不改动
.venv/bin/python scripts/install_dsh_skill.py --uninstall      # 恢复安装前的状态
```

安装脚本只写三样东西：Skill 文件、适配器配置（`.memorygene/dsh.json` 或 `~/.memorygene/dsh.json`），以及一份卸载用的清单。它不会碰 Harness 的 profile、插件、账号或计费设置。

## 实际怎么工作

流程是：Harness 把 Skill 列进目录 → 模型需要时调用 `skill(memorygene)` 读说明 → 按说明调用 `memorygene-dsh` → 适配器读写 SQLite → 模型根据返回结果回答。

这是**显式调用**：模型可以选择不用，Harness 不会在每一轮强制执行。如果想让模型在任何项目里都主动用记忆，可以运行 `scripts/install_global_auto.py`，它会往 `~/.dsh/AGENTS.md` 里加一段提示（`--uninstall` 移除）。但这只是提示词约定，模型不一定照做。

我也研究过能不能做成宿主强制的自动记忆（每轮前读、对话后写）。这个版本没有 hooks，插件只能通过 profile 加载，而桌面版的 profile 由应用独占。所以目前没有做插件，也不建议去改桌面 profile。

## 验证过的情况

- 项目级和用户级 Skill 都能被 Harness 发现并载入，桌面 GUI 里也确认过。
- 4 个独立的 headless 会话依次完成了：写入 → 换会话读取 → 明确修改 → 遗忘。记录在 `evidence/01-e2e/`。
- 任务接续功能在两个独立会话里跑通（保存 → 新会话恢复），记录在 `evidence/08-tasks/`。
- 用户级全局提示开启后，在两个不同项目里，用户没提 Skill 名字，模型也会自动写入和召回记忆。

## 数据和身份

- 数据库默认是 `<项目>/var/memorygene.db`，按 `--db`、`MEMORYGENE_DB`、配置文件的顺序查找；找不到就报错，不会偷偷新建一个。
- `namespace` 默认 `dsh`，`subject` 默认 `owner`。不同的人要用不同的 subject。
- 会话内的临时记忆自动使用 Harness 的 `DSH_SESSION_ID`。
- `namespace` 和 `subject` 只是逻辑分区，不是权限控制。

## 复查命令

```sh
python3 tools/dsh/probe_skills.py --cwd "$PWD" --skill "$PWD/.dsh/skills/memorygene/SKILL.md"
.venv/bin/python scripts/install_dsh_skill.py --check
.venv/bin/python scripts/e2e_harness.py      # 会真的调用模型
.venv/bin/python scripts/acceptance.py       # 库级验收，不调用模型
```
