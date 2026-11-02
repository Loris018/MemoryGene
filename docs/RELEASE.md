# 本地预发布与 GitHub 发布准备

本地预发布名称：**MemoryGene 0.2.0.dev2**（DSH 接入 + recall + 任务接续）。
**本轮未创建或推送 GitHub 仓库，未发布 PyPI，未发送任何外部消息；不要把本地 CI 配置当作远端运行证据。**

## 1. 当前交付物

| 交付物 | 路径 | 说明 |
| --- | --- | --- |
| 项目源码（当前） | 本项目目录 | git 基线 `4bb7306`；dev2 功能提交 `d8475c0`，维护修复提交见 `git log` |
| 最终 ZIP（dev2） | `../MemoryGene-0.2.0.dev2-task-checkpoints.zip` | 源码 + 文档 + 测试 + 实验 + 精选证据 + dev2 wheel |
| 清单（dev2） | `../MemoryGene-0.2.0.dev2-task-checkpoints-MANIFEST.json` | 最终 sha256/大小/文件数/验证结论；哈希以该文件为准 |
| wheel（dev2） | `dist/memorygene-0.2.0.dev2-py3-none-any.whl` | 运行核心 + CLI + 适配器 + recall + 任务接续 |
| sdist（dev2） | `dist/memorygene-0.2.0.dev2.tar.gz` | 源码分发包 |
| 安装前备份 | `../memorygene-backups/MemoryGene-prechange-*.tar.gz` | 最早交接前完整快照 |
| 历史快照（不要当当前版） | `../MemoryGene-0.2.0.dev1-dsh.zip`、`../MemoryGene-tasks-2026-10-29/release/` | dev1 / GPT 生成的 dev2 原始候选包；内容已被本目录新包取代 |

打包内容：

- `src/memorygene/`：`codec.py`、`core.py`、`cli.py`、`adapter.py`、`recall.py`、`tasks.py`、`extract.py`（规则原型）
- `skills/memorygene/SKILL.md`：DSH 技能模板（安装器渲染后使用）
- `scripts/`：`install_dsh_skill.py`、`install_global_auto.py`、`acceptance.py`、`e2e_harness.py`、`task_harness.py`
- `tools/dsh/`：`probe_skills.py`、`extract_asar.js`、`headless-account.patch.yml`、AGENTS 模板
- `docs/`：使用说明、任务接续、DSH 接入、验收、设计、审计、实验、发布、来源、VALIDATION
- `tests/`（139 项）、`experiments/`（含独立留出 NL `heldout-2026-10-29/`）、`examples/`
- `evidence/`：历史验收 + dev2 任务接续证据 + 本轮维护修复证据（不含数据库、原始会话流与凭据）
- LICENSE（MIT）、CONTRIBUTING、SECURITY、CI 配置

**明确排除**：`.venv/`、`build/`、`dist/`、`var/`（生产库）、`*.db`、`.memorygene/`、`.dsh/skills/` 安装副本、
`~/.dsh` 内容、原始 Harness 会话流（`evidence/08-tasks/harness/`）、真实聊天记录、任何密钥/凭据。

## 2. 构建与验证命令（本地实际执行）

```sh
cd "<repo>"
.venv/bin/ruff check src tests experiments examples scripts tools
.venv/bin/python -m unittest discover -s tests -v          # 139 项
.venv/bin/python examples/lifecycle.py
.venv/bin/python experiments/run.py
PYTHONPATH=src .venv/bin/python experiments/nl_eval.py
.venv/bin/python scripts/acceptance.py                     # 12 场景 / 52 检查
.venv/bin/python -m build                                  # dist/*
.venv/bin/python -m twine check dist/*
# 干净虚拟环境安装 dist wheel 后再跑 tests；详见 docs/VALIDATION.json 与 evidence/09-maintenance/
```

真实 Harness 验收（消耗模型调用，复用现有登录）：

```sh
.venv/bin/python scripts/e2e_harness.py     # dev1 链路：4 个独立 headless 会话
.venv/bin/python scripts/task_harness.py    # dev2 任务接续：2 个独立 headless 会话
```

结果：`evidence/06-maintenance/`、`evidence/08-tasks/`、`evidence/09-maintenance/`、`experiments/heldout-2026-10-29/`、`docs/VALIDATION.json`。
GUI 人工验收准备：`../MemoryGene-GUI-test-2026-10-27/` + `scripts/gui_acceptance_verify.py`（仅 preflight 已通过，after-a/b/c 待人工）。

## 3. 配置依据

[PyPA pyproject 规范](https://packaging.python.org/en/latest/specifications/pyproject-toml/)、
[GitHub Python 构建测试指南](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)、
[setup-python](https://github.com/actions/setup-python)、[checkout](https://github.com/actions/checkout)。
Actions 主版本按本轮官方文档使用 v7；远端仍须执行验证（本轮未运行远端 CI）。

## 4. 实际公开前

1. 确定 GitHub owner、仓库名、可见性与维护者署名；确认团队对 MIT 发布和项目名称的权利。PyPI 包名可用性未查询，不宣称已占用。
2. 若取得原 v0.1，先补原型审查与差异说明，不跳过兼容性判断。
3. 只提交当前源码、虚构 fixtures、结果与文档。不要提交本地数据库、真实对话、内部 PDF、venv、缓存、`.memorygene/`、`.dsh/skills/` 安装副本、原始 Harness 会话或密钥。
4. 推送后检查 CI 各 Python 版本真实运行结果（本机只实测 3.11.7，独立审计另测 3.12/3.13 基线），再建立对应预发布 tag/release；不要提前把多平台支持写成已验证。
5. 发布页保留：“结构化开发样例验收，不是大模型能力基准；自然语言评估是规则原型回归检查、不是留出集；recall 是字面检索不是语义检索；任务接续是显式记录，不是自动上下文替换；互补表示尚未显示独立收益；自动每轮记忆未实现”。
6. 指定私密漏洞反馈渠道。若计划 PyPI 发布，另行完成包名、身份与供应链配置；当前 workflow 不含上传权限。
7. 发布前清理文档/证据中的本机绝对路径（当前 `docs/USAGE.zh.md`、`README.md` 等含 `~/...` 示例，属本地候选；公开前替换为占位符）。
8. 不要发布 `evidence/` 里的真实用户数据——当前全部为虚构；若沿用目录结构，发布前重新检查。

## 5. 发布说明草稿（dev2）

MemoryGene 0.2.0.dev2 是团队设计稿重建的本地记忆研究核心与 Agent Skill。本版在 dev1 的
DeepSeek Harness 接入基础上新增：`recall` 字面召回（硬字符预算，返回线索后再 `current` 核对）、
显式任务接续记录（保存/读取/授权跨会话恢复/遗忘传播，带来源与版本检查）、会话主题过滤、
验收与工具证据加固、安装/卸载回滚保护。提供 139 项测试、12 场景/52 项库级验收、2 个真实
headless Harness 任务接续会话与独立 wheel 任务测试。当前结果显示规则配置在开发集上通过全部预期；
普通与互补机制结果一致；不声称 DNA 编码带来压缩、加密、语义理解或更强恢复能力；recall 不是语义检索；
任务接续不自动压缩或替换宿主上下文；原 v0.1 源码未取得，未验证升级兼容性；首次创建任务扩展表后，
旧版 dev1 将拒绝打开该数据库。

## 6. 撤销与恢复

- 卸载 Skill：`scripts/install_dsh_skill.py --uninstall`（用户级加 `--target user`）。
- 源码恢复：`git reset --hard 4bb7306` 或解压 `../memorygene-backups/MemoryGene-prechange-*.tar.gz`；
  维护前后快照见相邻 `MemoryGene-maintenance-2026-10-27/`、`MemoryGene-tasks-2026-10-29/`。
- 删除生产库（会丢记忆）：`scripts/install_dsh_skill.py --uninstall --purge-db`，或手工删除 `var/memorygene.db`。
- 任务扩展表降级：若已 `task-save`，旧版 dev1 会拒绝该库；只能恢复升级前备份，不能直接降级操作。
