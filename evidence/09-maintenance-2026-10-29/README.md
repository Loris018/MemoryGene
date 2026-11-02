# 2026-10-29 dev2 维护修复

本目录记录 GPT 完成 0.2.0.dev2（recall + 任务接续）后，本轮只读复核与交付修复的实际结果。
不是新的第三方独立审计；没有修改生产记忆、DSH profile、凭据或计费设置。

## 复核结果

- 139 项测试通过；ruff 通过；12 场景/52 项库级验收通过；生命周期与结构化/NL 实验通过。
- dev2 任务接续：2 个真实 headless Harness 会话、13 项检查通过（原始事件在 `evidence/08-tasks/harness/`，本地不进包）。
- dev2 wheel 在干净 Python 3.12 venv 安装后 139 项测试通过；adapter remember/recall/verify 冒烟通过。
- 生产库未被本轮验证改写：4 条用户记忆、3 个 head、无 `task_checkpoints` 表；
  文件 sha256 `c49aeb…`，sqlite iterdump 逻辑摘要 `9a9618…`（算法：`sha256('\n'.join(iterdump()))`）。
- `task_checkpoints` 兼容边界复核：旧提交 `c028f8d` 的代码拒绝打开已建任务表的 dev2 库。

## 修复

1. **外来库检测回归**（`src/memorygene/core.py`）：已存在的 SQLite 文件必须含 `config/events/heads`
   核心表，否则拒绝纳管；修复了“只有 task_checkpoints 表的无关库被纳管”的问题，新增回归测试
   （139 项）。见 `foreign-db-regression.log`。
2. **交付物/文档同步**：把 README、USAGE、ACCEPTANCE、AUDIT、RELEASE、SECURITY、DESIGN、
   DSH-INTEGRATION 统一到 dev2；dev2 wheel/sdist/ZIP 重建；旧 dev1 ZIP/dist 标注为历史。
3. **证据链**：`docs/VALIDATION.json` 改为实际 base commit，明确 production DB 的 iterdump
   逻辑摘要算法，删除不存在的隔离环境路径引用。
4. **全局提示**：更新 `~/.dsh/AGENTS.md` 的 MemoryGene 段（recall/任务接续提示），保留用户原有其它
   全局指令；仍是提示词约定，不是宿主强制。

## 文件

- `full-verification.log`：ruff/tests/lifecycle/experiments/NL/acceptance。
- `clean-wheel-verify.log`：干净 Python 3.12 venv 安装 dev2 wheel 后 139 项测试 + adapter 冒烟。
- `foreign-db-regression.log`：外来库拒绝（修复后）与旧版兼容性。
- `dev2-build.log`、`dev2-zip-check.log`：包构建与解压 ZIP 复验。
- `validation.json`：机器可读记录（与 `docs/VALIDATION.json` 同内容）。

## 未完成

GUI 人工验收、独立留出 NL 基准、远端 CI/Windows/Linux、自动上下文替换与强制每轮记忆仍未完成；
见 `docs/ACCEPTANCE.md` 与 `docs/VALIDATION.json` 的 limitations。
