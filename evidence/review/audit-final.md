# MemoryGene 0.2.0.dev1 最终独立复审（候选交付物）

**结论：GO（候选版通过，可交接）。** P0 = 0，P1 = 0（上一轮报告的 2 项新 P1 已由 Lead 在 `98722de`/`30267a0` 修复并经本审计独立复核），P2 = 12（均为文档/证据措辞与少量边界加固，不阻塞交接；建议在最终重建 ZIP 时顺手修掉）。最终 ZIP 重建后**哈希以 `../MemoryGene-0.2.0.dev1-dsh-MANIFEST.json` 为准**；本报告中的候选 ZIP 哈希 `ded07ec8…` 只是审计时点值。

- 审计对象（候选）：git **30267a0**（基线 4bb7306）＋ 候选 ZIP `../MemoryGene-0.2.0.dev1-dsh.zip`（sha256 `ded07ec8b226d9e0ab5fcfc4f584bb96aa6e04ab05aab5a8ac3993568718494d`，918218 B，167 files）＋ `dist/` wheel `6439a91c…`、sdist `b72c5bb6…` ＋ MANIFEST（sha256 `acc2a99a…`，`final_commit=30267a0`，`zip.files=167`，`unit_tests=88`）。
- 审计方式：`git archive 30267a0` 导出树 + ZIP 解包 + 干净 Python 3.12 venv 独立安装验证；只读源码，只写 `evidence/review/`；未安装/卸载 Skill；未发起模型调用或网络请求；所有写库测试都在 `/tmp` 虚构库中完成。
- 注：审计窗口内 Lead 仍在做最终重建（工作树 `docs/VALIDATION.json` 的 `checked_at` 为等待重建的 07:50:03，候选 ZIP 内为 07:48:50；其余字段一致）。本报告结论适用于 30267a0 + 候选 ZIP；最终 ZIP 只应再增加 `audit-final.md`、最新审计日志与 VALIDATION 时间戳。

---

## 1. 上一轮 2 项新 P1 的修复复核（全部通过）

### P1-新-2：`verify` 漏检 head 回滚 / 缺失 head —— **已修复并复核**
- 代码：`src/memorygene/core.py:440-556`。新增 `latest_confirmed` 不变量：每个有 confirmed 事件的 route 必须有 head（`core.py:533-545`），head 必须等于该 route seq 最大的 confirmed 事件（`core.py:520-532` 报 `head is not the latest confirmed event of its route (rolled back or inconsistent)`）；保留原有 payload/digest/身份/路由、head 指向缺失/未确认/路由不符检查。
- 回归测试：`tests/test_memorygene.py:409 test_verify_detects_head_rollback_and_missing_head`（单跑 OK）。
- 独立复现（`evidence/review/scripts/repro_verify_head_rollback.py` 重跑，日志 `logs/final-p1-verify-gap.log`、`logs/final-f1-lead-fixes.log`）：
  - head 回滚到旧 confirmed 后：`verify() = {ok: False, problems:[{kind:"head", problem:"head is not the latest confirmed event of its route (rolled back or inconsistent)"}]}`（脚本按旧行为写的 `assert ok is True` 如预期失败，证明检测生效）；
  - `DELETE FROM heads` 后：`verify() = {ok: False, problem:"route has confirmed evidence but no head (missing head or silently dropped current version)"}`。
- 文档措辞已收窄且明确排除项：`README.md:97`、`SECURITY.md:24`、`DESIGN.md:87`、`AUDIT.md:16,37,57` 均写明“head 回滚、缺失 head 可检测；**不检测被删除的非 head 历史事件**（seq 空洞也可能来自合法回滚事务）”。**不再过度承诺**。
- 结论：**修复有效，文档与实现一致。**

### P1-新-1：发布验证记录与随包日志矛盾（ruff）—— **已修复并复核**
- `98722de` 重新生成 `evidence/release/final-verification.log`：`ruff_exit=0`、`Ran 88 tests ... OK`、lifecycle/experiments/nl/acceptance 全 exit 0；候选 ZIP 内该 log 与 HEAD 哈希一致（`git show HEAD:...` 对比 MATCH），不再含 `F841/F401/ruff_exit=1`。
- `docs/VALIDATION.json`：`checked_at`、`source-tests.tests=88`、`clean-wheel-venv-install.tests=88` 已更新；我独立运行 `.venv/bin/ruff check ...` = `All checks passed!`，`unittest` = `Ran 88 tests ... OK`。
- `MANIFEST.verification.lint.status="All checks passed"` 与随包 log 现在一致；新增 `verification.verify_head_invariants` 记录。
- 结论：**修复有效。**

## 2. 原 4 项 P1 状态（回归确认）

| 编号 | 状态 | 本轮复核证据 |
| --- | --- | --- |
| P1-1 误路径静默建库 | 已修复 | 原 repro 重跑：`current/history/topics/forget/repair/verify` 在缺失库上 `exit=2`、**不创建文件**；仅 `ingest` 建库（`logs/final-a-p1-repros.log`） |
| P1-2 外来 SQLite 纳管 | 已修复（表级） | 原 repro 重跑：`ValueError: Not a MemoryGene database; refusing to adopt a foreign SQLite file with tables ['invoices']`，表集合不变；残留 views-only 边界见 P2-13 |
| P1-3 fail-closed 范围 | 已修复（文档+检测） | 单主题读仍按文档静默（限制），`verify` 现在覆盖 route/head-route/head 回滚/缺失 head；文档明确排除非 head 历史事件（见 §1） |
| P1-4 证据链不一致 | 已修复 | 候选 ZIP/sdist 的 `experiments/results/results.json` 与 HEAD 字节一致；`RESULTS.md` 语义计数一致（计时/运行时间仍有 P2-2） |

---

## 3. 候选交付物验证（C）

| 检查 | 结果 |
| --- | --- |
| ZIP sha256 / bytes / 文件数 | `ded07ec8… / 918218 B / 167`，与 MANIFEST、Lead 声明一致 |
| `unzip -t` | `No errors detected` |
| ZIP 内容 vs git HEAD | 167 = HEAD 跟踪 165 + `packages/` 下 wheel/sdist 2 份；**无缺失**，内容除 `packages/` 外全部与 HEAD 字节一致（当前候选 ZIP 内 `docs/VALIDATION.json` 与 HEAD 一致；工作树有等待重建的 checked_at 更新） |
| `packages/` 副本 vs `dist/` | wheel/sdist 哈希完全一致（`6439a91c…` / `b72c5bb6…`） |
| 禁止内容 | `.venv/.git/.dsh/.memorygene/var/dist/build/__pycache__/*.egg-info/*.pyc/.DS_Store/local-memory.db/*.db` 均为 0 |
| ZIP 内测试（ZIP src，3.11.7） | `Ran 88 tests … OK` |
| ZIP 内测试（干净 Python 3.12 venv + dist wheel） | `Ran 88 tests … OK` |
| ZIP 内 core.py / final-verification.log / VALIDATION / tests / README / SECURITY / SKILL | 与 HEAD MATCH |
| wheel/sdist 模块 | 6 个运行时模块均与 HEAD 字节一致；sdist 含 docs/tests/scripts/tools/packages 与 VALIDATION |
| `twine check dist/*` | wheel + sdist 均 PASSED（重新执行） |
| MANIFEST 自洽 | zip/wheel/sdist sha256+bytes+files、`unit_tests=88`、`clean_python_3_12_wheel_install.tests=88`、`zip_extraction.tests=88 + head_core_sha_matches_zip=true`、`verify_head_invariants` 均与实际一致 |
| ZIP 遍历安全 | 145/167 全部位于 `MemoryGene/` 下，无绝对路径/`..` |

日志：`logs/final-c-zip-manifest.log`、`logs/final-g-candidate-artifacts.log`、`logs/final-h-candidate-full.log`、`logs/final-j-candidate-residual2.log`。

## 4. 功能、测试与实验验证（A/B）

- **ruff**：`.venv/bin/ruff check src tests experiments examples scripts tools` → `All checks passed!`（exit 0）。
- **测试**：`unittest discover -s tests` → **Ran 88 tests, OK**（3.11.7）；同一套测试在干净 3.12 wheel venv 与 ZIP 解包后亦 88/88；`test_verify_detects_head_rollback_and_missing_head` 单跑 OK。
- **lifecycle**：exit 0；current=栀子花、confirmed history=玫瑰→栀子花（与 README/DESIGN 一致）。
- **结构化实验**：重跑结果与 HEAD 的 `experiments/results/results.json` **语义完全一致**（24/24、24/24、plain/complement 相同；recovery 100/100；route bytes 17890/71560，db bytes 286720/606208）；计时数字随运行浮动（文档已声明）。
- **NL 评估**：重跑与 HEAD `nl_results.json` **逐字段相同**（47 cases / 79 turns；L1 decision 77/79、topic 57/57、value 56/57、certainty 57/57、source 57/57；L2 extractor current 44/47；extraction-only 5、storage-only 0；6 组配置语义摘要一致、copy=complement 冗余 27163 B、complement 路由键 4.0×）。
- **库级验收**：重跑 `scripts/acceptance.py` → **12/12 scenarios、47/47 checks、failed=[]**（独立进程调用适配器 + 直接 SQLite 复核）。
- **回归 fuzz**：500 步 plain/complement 差分 0 分歧、500 步不变量 0 违例、300 次随机损坏 0 次返回错字节（`logs/final-fuzz-regression.log`）；`extract()` 400 条随机文本 + 79 轮 fixture：source 逐字子串不变量 0 违例（`logs/final-extract-fuzz.log`）。
- **未复跑**：真实 headless Harness 4 会话（会发起真实模型调用/外部消息，本轮禁止）；核验其证据 JSON：4 sessions、4 个不同 session id、所有 checks passed、tool_calls 非空（`evidence/01-e2e/harness-results.json`）。

日志：`logs/final-ruff.log`、`final-unittest.log`、`final-lifecycle.log`、`final-experiments.log`、`final-experiments-compare.log`、`final-nl-eval.log`、`final-acceptance.log`、`final-clean-wheel-install.log`。

## 5. 对抗性检查（D，均只报可复现问题）

- 适配器参数优先级/配置解析：`--db` > `MEMORYGENE_DB` > 向上查找 `.memorygene/dsh.json` > `~/.memorygene/dsh.json` 行为与 USAGE 一致；不存在的 `--config` 报错。
- `--allow-create`：缺失库默认拒绝且不建文件；显式开关建库且 **mode=0600**；前后位置均可；对外来 SQLite 仍拒绝。
- 同意：敏感无同意 → `rejected_sensitive`、不落库；`--consent` 无 `--consent-evidence` 拒绝；空同意原话拒绝；`--consent` 无 `--sensitive` 拒绝；任意非空同意原话被接受并追加到 source（P2-10/§7 记录为“存在性校验，来源不可验证”）。
- topic 校验：大写/`a..b`/`café`/首字符非字母/超 120 字符均拒绝；`a_b-c.d` 与 120 字符接受。
- session：`--scope session` 自动取 `DSH_SESSION_ID`；空白 session 拒绝；`remember` 对 persistent+显式 session 报错；查询命令对 persistent+`--session` 静默忽略（P2-9）。
- `topics()`：损坏 route 失败关闭（现有测试）；`verify()`：route/head-route/head 回滚/缺失 head 均可检测；`verify()` 对健康库、仅 pending 库、plain index 均 OK；**不检测备份列损坏**（文档未承诺，见残留风险）。
- `extract()`：source 逐字子串、skip 不产生 candidate、确定性、`source_span` 越界报错，全部通过。
- ZIP 路径遍历：167 条目全部在 `MemoryGene/` 下，无 `..`/绝对路径。
- 残留边界：`normalize_argv` 会把作为 value 出现的 flag 形 token 重排（如 `--source --allow-create x` → `ok:true`、source 变为 `x` 且静默开启建库；未发现可静默改写 DB 的路径）；`--now` 测试时钟在生产 CLI 可用，可写出未来 `recorded_at`（P2-11/12）。

日志：`logs/final-d1-adapter-core.log`、`logs/final-d2-verify-foreign-extract-zip.log`、`logs/final-extract-fuzz.log`。

## 6. 文档诚实性与披露（E）

- **已核实为真**：88/88 测试（README:38,105；ACCEPTANCE:32；AUDIT:43；RELEASE:24/36/76；MANIFEST/VALIDATION）；24 组结构化结果；47/79、77/79、extraction-only 5/storage-only 0（README:108、AUDIT:45、EXPERIMENTS、NL_RESULTS 一致）；acceptance 12/47；headless 4/4、4 个不同 session id；GUI catalog/载入/自测声明与其证据 md 一致（但见 P2-15 证据层级）；“自动每轮记忆未实现、仅显式 Skill 调用”与仓库实现一致；“安装器不改 DSH profile/插件/凭据/全局记忆设置”与脚本实现一致。
- **用户级安装已披露且可卸载**：`SECURITY.md:25`、`USAGE.zh.md:12/298-309`、`DSH-INTEGRATION.md:34/98/113` 明确说明 `~/.dsh/skills/memorygene/` 与 `~/.memorygene/dsh.json` 属用户范围安装；`install_dsh_skill.py --target user --uninstall`、`--purge-db` 存在；我实际运行 `--check`（不改动）两种目标均 `ok:true`，安装清单 `.memorygene-install.json` 记录了 created_paths。
- **`headless-account.patch.yml`**：仅 4 条 `--patch` overlay（credentials/deepseek-account/authorization/agent-default-model），无密钥；文档声明“只对 headless 验证生效、不改桌面 profile/计费”与实现一致。
- **未过度宣称**：AGENTS.md 提示词约定、GUI 人工验收、NL 留出集、多平台、v0.1 兼容性均有明确“未实现/未验证”声明（README/AUDIT/EXPERIMENTS/RELEASE/MANIFEST.unverified）。
- 残余问题为措辞/计数不一致（见 §7）与主机绝对路径（P2-14）。

---

## 7. P0 / P1 / P2 汇总

### P0（破坏集成或记忆正确性）
**无。** 依据：88/88 + 干净 venv/ZIP 测试；状态机/表示/损坏回归 fuzz 0 违例；原 4 项 P1 全部验证修复；两项新 P1 修复经复现确认。

### P1（误导性文档/安全）
**无（本轮两项 P1 已修复并复核）。** 上一轮报告的两项新 P1（stale verification log、verify 漏检 head 回滚/缺失 head）在 30267a0 中均已修复，见 §1。

### P2（不阻塞交接；建议在最终重建 ZIP 时修掉）

| 编号 | 问题 | 位置 | 证据 / 建议 |
| --- | --- | --- | --- |
| P2-1 | VALIDATION 中 zip 文件数仍写 142，实际候选 ZIP 为 167 | `docs/VALIDATION.json:176` | 候选/MANIFEST 均 167；改为实际值或引用 MANIFEST（不改命令本身） |
| P2-2 | `RESULTS.md` 运行时间/计时数字仍来自更早一次运行，与随包 `results.json`（07:48:39、19.21/61.53 μs）不一致 | `experiments/RESULTS.md:3,37-38` | 语义计数一致；用最终 `results.json` 更新 summary，或注明“计时数字随时间浮动，原始记录见 results.json” |
| P2-3 | NL_RESULTS 的语义摘要写 `sha256 f43e8833…`，实际为 `8d12163d…` | `experiments/NL_RESULTS.md:120` | 用 `nl_results.json.fairness.main_l2_extractor_digest` 更新 |
| P2-4 | USAGE 还写 “87 项”，其他文档均为 88 | `docs/USAGE.zh.md:276` | 改为 88 |
| P2-5 | ZIP 内仍包含旧构建时期的 `zip-install-verification.log`（两条 `Ran 87 tests`，且引用旧 ZIP） | `evidence/release/zip-install-verification.log:20,36` | 标注为“历史上旧构建日志”或删除/重生成，避免与 88 混淆 |
| P2-6 | `VALIDATION.verify-head-invariants` 引用 `final-verification.log`，但该 log 只含整套 unittest，没有该单测命令/输出 | `docs/VALIDATION.json:180-187` | 将 command 输出追加到 log，或改 log 指向含该命令的日志 |
| P2-7 | RELEASE/MANIFEST 称 evidence 不含二进制 / 只有 logs/json/md，但 ZIP 内 evidence 含 5 个 `session.v4.jsonl.zstd`（及 PNG） | `docs/RELEASE.md:25`；MANIFEST `contents.included` | 措辞改为“含压缩会话归档与图片，不含数据库/安装副本” |
| P2-8 | 生产库 `var/memorygene.db` 权限 0644，与 SECURITY“新建数据库 0600”不一致；GUI evidence 称由 `--allow-create verify` 创建，但 selftest log 第 1 步已 `db_exists=True`，第 2 步只是 verify | `SECURITY.md:21`；`evidence/00-install/gui-session-evidence.md:45-46`；`gui-live-selftest.log:5-12` | 说明该库实际创建方式并 `chmod 600`，或把证据改为实际命令 |
| P2-9 | 适配器 persistent 查询静默忽略显式 `--session`（remember 却报错），与 DESIGN“persistent 禁止 session”不一致 | `src/memorygene/adapter.py:202-203,263-274`；`docs/DESIGN.md:39` | 查询命令同样拒绝 persistent+session，或文档说明忽略 |
| P2-10 | 适配器对 `rejected_sensitive/discarded/expired/conflict` 仍返回 `ok:true`（status 在 result 中），依赖模型读懂 status | `src/memorygene/adapter.py:148-150` | 令 `ok` 仅表示命令执行、并在响应中加 `persisted:false`，或文档明确“ok≠已保存” |
| P2-11 | `normalize_argv` 会把价值参数中的 flag 形 token 重排：`remember ... --source --allow-create x` 会以 `source="x"` 成功并静默开启建库；`--value --db=...` 会报参数错 | `src/memorygene/adapter.py:342-370` | 只重排子命令之前的全局 flag，或使用 `--` 终止；不要对 value 位置做全局 flag 匹配 |
| P2-12 | `--now`（testing-only clock）保留在生产适配器 CLI，可写未来 `recorded_at` 并绕过“未来证据拒绝”；SKILL/USAGE 未提及 | `src/memorygene/adapter.py:337,384` | 用环境变量/子命令隔离该测试开关，或在 SECURITY/USAGE 写明仅测试、禁止对话使用 |
| P2-13 | 外来 SQLite 仅当含“非 MemoryGene **表**”时拒绝；只有 view/trigger（无表）的库仍会被纳管并注入 schema | `src/memorygene/core.py:142-155`；`SECURITY.md:20` | 打开既有非空库时同时检查 `view/trigger/index`，或仅允许全新空文件/已含合法 config 的库 |

**残留风险/未列缺陷（记录备查，不建议现在改）**：① `verify()`/`topics()` 多 SELECT 未包在只读事务中，并发写入时可能产生瞬时误报（未复现）；② `verify()` 不检测备份列损坏（文档未承诺）；③ 直接 `MemoryStore` API 仍会隐式建库（CLI/adapter 已加门槛，文档已限定）；④ 证据与文档中含主机绝对路径（见 §8）；⑤ GUI catalog 声明依赖自报 md（见 §8）。

---

## 8. 无法验证 / 限制

1. **未复跑真实 headless Harness 4 会话**：会真实调用 DeepSeek 模型（外部消息），本轮明确禁止；仅核验其 JSON/日志证据内部一致性。4 个不同 session id、全部 checks passed、tool_calls 非空可核。
2. **GUI catalog 注入**：GUI 会话证据为 md + selftest log（自报“catalog 出现/载入”），ZIP 内**没有**类似 headless 的原始 catalog 事件文件；文档已声明“未由用户人工逐项验收”，但 “L4 真实 GUI” 标签强于随包证据（建议保存原始事件或降级措辞）。
3. **联网/远端项**：GitHub/PyPI/远端 CI 未执行（`git remote` 为空，与文档一致）；`actions/checkout@v7`、`actions/setup-python@v7` tag 无法离线确认；`PROVENANCE` 的 PDF 哈希无法复核；未读真实个人数据。
4. **运行环境**：本机仅 macOS；Python 3.10 仅 AST 语法检查（3.11.7/3.12.10/3.13.3 实测通过）；Windows/Linux 未验证。
5. **真实损坏场景**：未做 SQLite 页/文件级损坏、恶意重写 digest、同主题历史头指针回滚之外的攻击模型验证（`verify` 明确不检测被删除的非 head 历史事件）。
6. 审计窗口内 Lead 仍在做最终重建：本报告基于 30267a0 + 候选 ZIP；最终 ZIP 重建后仅应变化 audit-final/最新日志/VALIDATION 时间戳，哈希以 MANIFEST 为准。

---

## 9. 交接前最终重建清单（给 Lead）

1. 把 `evidence/review/audit-final.md`、本轮新增 `evidence/review/logs/final-*.log`（g/h/i/j 等）与 `evidence/review/scripts/repro_verify_head_rollback.py` 加入版本库/最终 ZIP；
2. 提交工作树中 `docs/VALIDATION.json` 的 `checked_at`（07:50:03）更新；
3. 重新构建 wheel/sdist，并重建 ZIP（仍排除 `.venv/.db/.dsh/.memorygene/.git/var/build/dist`；`packages/` 与 `dist/` 保持一致）；
4. 更新 MANIFEST 的 zip 文件数/sha256/bytes、wheel/sdist sha/bytes、`final_commit`、`checked_at`、tests=88；
5. 建议顺手修 P2-1（142→实际）、P2-2（RESULTS.md 时间/计时）、P2-3（digest）、P2-4（USAGE 87）、P2-5（历史 87 日志）即可，其余 P2 可留作后续；
6. 最终 ZIP 哈希不要写进本报告/README，以 MANIFEST 为唯一权威。

**给 Lead 的最终判定：GO（候选版通过）。** 剩余 12 项 P2 均为文档/证据措辞与边界加固，不构成交接阻塞；无 P0/P1 遗留。

---

## 10. 证据索引（本轮新增）

```
evidence/review/audit-final.md                         # 本文件
evidence/review/logs/final-00-identity.log             # HEAD/产物哈希/文件数
evidence/review/logs/final-a-p1-repros.log             # 原 3 个 P1 repro 重跑
evidence/review/logs/final-p1-verify-gap.log           # verify 修复前缺口复现（历史）
evidence/review/logs/final-f1-lead-fixes.log           # 98722de 两项 P1 修复独立复核
evidence/review/logs/final-ruff.log / final-unittest.log
evidence/review/logs/final-lifecycle.log / final-experiments.log / final-experiments-compare.log
evidence/review/logs/final-nl-eval.log / final-acceptance.log
evidence/review/logs/final-clean-wheel-install.log
evidence/review/logs/final-d1-adapter-core.log / final-d2-verify-foreign-extract-zip.log
evidence/review/logs/final-extract-fuzz.log / final-fuzz-regression.log
evidence/review/logs/final-g-candidate-artifacts.log   # 候选 ZIP/MANIFEST 全量校验
evidence/review/logs/final-h-candidate-full.log        # ZIP vs HEAD、干净 venv、P2 残留
evidence/review/logs/final-i-candidate-residual.log
evidence/review/logs/final-j-candidate-residual2.log
evidence/review/scripts/repro_verify_head_rollback.py  # P1-新-2 最小复现
evidence/review/scripts/repro_{silent_create,foreign_sqlite_adoption,metadata_corruption_not_fail_closed}.py
```
