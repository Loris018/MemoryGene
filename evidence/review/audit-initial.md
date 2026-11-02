# MemoryGene 0.2.0.dev1 基线独立审计（初始轮）

- 审计对象：git commit **4bb7306**（`snapshot: pre-handover 0.2.0.dev1 baseline`，2026-10-24 15:22:41 +0800 / 07:22:41Z）导出的源码树 `/tmp/audit_baseline`，以及发布物 `../MemoryGene-0.2.0.dev1.zip`、`../packages/*`、`../RELEASE-MANIFEST.json`。
- 审计方式：只读审查 + 独立复现脚本。所有基线运行都显式使用 `PYTHONPATH=/tmp/audit_baseline/src`，不受 Lead 并发改动影响。
- 审计时间：2026-10-24 15:24–15:40（Asia/Shanghai）。环境：CPython 3.11.7（项目 `.venv`，macOS-27.0.1-arm64）、CPython 3.12.10、CPython 3.13.3。
- 结论速览：**P0 = 0；P1 = 4；P2 = 9**。核心 `core.py`/`codec.py` 的逻辑质量高（500 步差分 fuzz、500 步不变量 fuzz、300 次随机损坏 fuzz、8 线程并发、配置守卫矩阵均未发现错误值或状态机裂缝）。真正需要处理的问题集中在**集成边界（无显式建库/无库归属校验）**、**fail-closed 承诺范围**和**发布证据链一致性**。

---

## 1. 审计方法与可复现入口

1. 基线导出（只读，不触碰仓库工作树）：
   ```sh
   git -C <project> archive 4bb7306 | tar -x -C /tmp/audit_baseline
   ```
2. 后续所有“基线”命令统一：
   ```sh
   cd /tmp/audit_baseline
   PYTHONPATH=/tmp/audit_baseline/src <project>/.venv/bin/python <...>
   ```
3. 发布物解包到 `/tmp/audit_zip`、`/tmp/audit_pkg`，wheel 装入一次性 venv `/tmp/audit_wheel_venv`（3.13.3）。
4. 独立探测脚本全部保存在 `evidence/review/scripts/`（`hunt-*.py`、`repro_*.py`），原始输出在 `evidence/review/logs/`。
5. 未修改任何源码/测试/文档/git 状态；`forget`、`ingest` 等写操作只发生在 `/tmp` 临时库；未读取项目之外的聊天记录或个人数据。

---

## 2. 基线验证结果

### 2.1 测试（文档宣称 36 项）

| 运行对象 | 解释器 | 结果 |
| --- | --- | --- |
| 基线源码 `tests/`（`-v` 全量） | 3.11.7 | `Ran 36 tests ... OK`（0.259s） |
| 基线源码 `tests/` | 3.12.10 | `Ran 36 tests ... OK`（0.400s） |
| 基线源码 `tests/` | 3.13.3 | `Ran 36 tests ... OK`（0.308s） |
| 发布 ZIP 内 `tests/` + ZIP 内 `src` | 3.13.3 | `Ran 36 tests ... OK` |
| 发布 wheel 安装后 + ZIP 内 `tests/` | 3.13.3（全新 venv） | `Ran 36 tests ... OK` |

`36` 与 `docs/VALIDATION.json:15`、`RELEASE-MANIFEST.json` 的 `archive_tests: 36`、`docs/RELEASE.md:9` 一致。日志：`logs/01-baseline-unittest-3.11.log`、`01-baseline-unittest-3.13.log`、`01b-baseline-unittest-3.12.log`、`07-artifacts-and-manifests.log`。

### 2.2 示例与实验

- `examples/lifecycle.py`（3.11.7 / 3.13.3）：exit 0；`current.value=栀子花`，`history` 中 confirmed 依序 `玫瑰 → 栀子花`，`resolves="day-10"`。与 README/示例文档一致。日志 `logs/02-lifecycle.log`。
- `experiments/run.py`（基线源码，`--out /tmp/audit_out`，3.11.7）：重跑得到
  - policies：`overwrite 12/24 (50.0%), history 6/24`；`append_all 12/24, 7/24`；`rules_plain 24/24, 24/24`；`rules_complement 24/24, 24/24`；`false_activations 20/47` vs `0/47`；`uncertain_writes 7/7` vs `0/7`。
  - protection：18 个 (mode, damage) 组合全部与 `RESULTS.md:22-29` 表格一致（healthy/primary_loss/primary_bitflip/backup_loss/both_loss/checksum_loss）。
  - index：plain/complement 均 `2100/2100` 正确；`event_route_bytes = 17890 / 71560`（恰 4.00×）；`database_bytes = 286720 / 606208`。
  - trace：`188 = 4 modes × 47 inputs`，与基线及 ZIP 内 `trace.json` **逐条完全相同**。
  - 语义计数与 git 快照、ZIP、sdist 三方一致；只有计时数字随运行变化（文档已声明计时不可外推）。日志：`logs/baseline-experiments-3.11.log`、`logs/03-experiments-fresh-*.json`、`logs/repro-compare.log`。

### 2.3 计数与文档链接

- `experiments/scenarios.json`：**24 组 / 47 次输入**（README:66、RESULTS.md:7、EXPERIMENTS.md:5、RELEASE.md:9 一致）。
- uncertain/inferred 输入 **7 条**（5 uncertain + 2 inferred），与 “7 条 uncertain/inferred 输入” 一致（RESULTS.md:16、EXPERIMENTS.md:5）。
- 全部 Markdown 仓库内相对链接可解析（0 断链）；README 的 Python API 片段可直接运行并返回 `confirmed`。
- `local-memory.db` 内容仅虚构 demo（`source="虚构用户：我最喜欢玫瑰。"`），未发现任何真实个人数据；但该文件被 git 跟踪（见 P2-2）。

### 2.4 静态检查 / 构建 / 发布物

- `ruff 0.17.2 check src tests experiments examples`（对 4bb7306 导出树）：`All checks passed!`，exit 0 → 与 `VALIDATION.json:8-11` 的 ruff 记录一致（**注**：审计开始时 `.venv` 内无 ruff/build/twine，约 15:31 由并发工作装入后我才补做；导入路径见 `logs/00-environment.txt` 的 NOTE）。
- `twine check packages/*`：wheel 与 sdist 均 `PASSED` → 对应 `VALIDATION.json:37-41 metadata`、`RELEASE-MANIFEST.json final_metadata`。
- `python -m build --no-isolation`（基线导出树，离线）：成功产出 wheel/sdist → 构建配置可用。
- Python 3.10 语法：所有 `.py` 通过 `ast.parse(feature_version=(3,10))`（与 `VALIDATION.json:42-46` 自述的 “AST syntax only, not runtime validation” 一致；3.10 运行时未验证，见 §5）。
- 发布物完整性：
  - ZIP sha256 `e84906cb…286d`、wheel `b9ec5e42…1a11`、sdist `5c04d267…3083` **全部与 `RELEASE-MANIFEST.json` 相符**；`unzip -t` 无错误。
  - ZIP 共 29 个文件，与 git 4bb7306 文件集相比：除 `experiments/results/results.json` 外**所有文件字节相同**；ZIP 不含 `local-memory.db`（与发布清单一致）。
  - ZIP/sdist/wheel 中的 4 个运行时模块字节与 4bb7306 源码一致；wheel 安装后 `import memorygene` = `0.2.0.dev1`，`examples/lifecycle.py` 输出 `栀子花`，CLI ingest 正常。
  - ZIP 内测试 36/36、wheel 安装后测试 36/36 通过（`archive_runtime`、`archive_tests` 可复现）。
- 日志：`logs/04-ruff-baseline.log`、`05-twine-check.log`、`06-build-baseline.log`、`07-artifacts-and-manifests.log`。

### 2.5 独立缺陷探测（结果均为“未发现”）

| 探测 | 方法 | 结果 |
| --- | --- | --- |
| 状态机 | 500 步随机 (certainty/intent/importance/scope/expiry/sensitive/resolves) 差分：plain vs complement | **0 处分歧** |
| 不变量 | 500 步随机写入后检查 head/current/history 一致性 | **0 处违例** |
| 损坏恢复 | 300 次随机 payload/backup/digest 损坏，3 种 protection | **0 次返回错误字节**，全部“校验通过或拒绝” |
| 并发 | 8 线程独立连接：不同值 / 同值 / 同 event_id | 分别得到 1 confirmed+7 conflict / 1 confirmed+7 duplicate / 无错误 1 条事件 |
| 配置守卫 | index/protection/schema/多余 key/缺失 config | 全部拒绝打开 |
| repair | none/copy/complement × 主损/双损/健康主|坏备 | 与文档/测试一致；repair 不改 heads |
| 路由隔离 | 分隔符歧义、scope/session、引号、NFC 等探针 | 无碰撞（NFC 合并为文档声明的预期行为） |

日志：`logs/hunt-*.log`，脚本：`evidence/review/scripts/hunt_*.py`。

---

## 3. 发现清单

### 3.0 P0（破坏集成或记忆正确性）

**未发现可复现的 P0。** 对 `core.py`/`codec.py` 的错误值、越权读、状态机裂缝、损坏静默恢复尝试了上述 fuzz/并发/损坏矩阵，均未出现。若把“LLM Agent 直接使用基线 CLI、且 --db 可能写错”视为集成路径，则 P1-1 的后果接近 P0（错误路径 `forget` 会返回成功假象），建议按最高优先级处理。

### 3.1 P1 发现

| 编号 | 问题 | 位置（@4bb7306） | 复现/证据 | 建议最小修复 | 可测 |
| --- | --- | --- | --- | --- | --- |
| P1-1 | 读/删命令在不存在或写错的 `--db` 路径上**静默新建空库**；`forget` 于是返回 `0` 且 `current=null`，形成“已删除成功”假象 | `src/memorygene/cli.py:31`；`src/memorygene/core.py:113-149` | `logs/10-repro-silent-create.log`：`forget` exit 0 stdout `0`，新建 36864 B 文件；`current` 返回 `null` | 非 ingest 命令要求库已存在；或全命令 `--create` 显式开关（Lead 的 `doctor/--allow-create` 方向正确，需保证 CLI 层同样拒绝） | 是 |
| P1-2 | 指向**其它应用的 SQLite 文件**时静默纳管：在无关数据库中注入 `config/events/heads` 表，不报错 | `src/memorygene/core.py:113-149`（仅在 `events` 非空且无 config 时拒绝） | `logs/11-repro-foreign-sqlite.log`：foreign 库 `invoices` 保留，同时被注入 4 张表/config | 打开已存在的非空文件时要求 MemoryGene config 存在且匹配；或校验既有表名 ⊆ {config,events,heads,sqlite_sequence}，否则 `ValueError("Not a MemoryGene database")` | 是 |
| P1-3 | “损坏 fail-closed”承诺过宽：**route/heads 元数据损坏静默返回空**（`current=None`、`history` 少事件），而不是报错 | 声明：`README.md:61`、`SECURITY.md:11`；实现：`core.py:181-191`（`_head`）、`315-326`（`history`） | `logs/12-repro-metadata-failopen.log`：`heads.route` 改坏 → `current()` 返回 `None`；非 head 事件 `route` 改坏 → `history` 静默缺该事件；对照 payload 损坏 → `IntegrityError` | 二选一：① 收紧文档为“仅 payload/digest 字节级损坏 fail-closed；route/heads 元数据损坏不保证可检测”；② 在 `_head`/`history` 增加结构一致性检查（代价是额外读放大） | 是 |
| P1-4 | **发布证据链不一致**：仓库 4bb7306 的 `experiments/results/results.json`（04:50:27，Python 3.11.7，sha256 `25216b…0552`）与 ZIP/sdist 内的同名文件（04:40:00，Python 3.13.3，sha256 `2ef4a7…e581`）不同；`RESULTS.md:3,35-40` 的 21.73/69.63 µs 只与 ZIP/sdist 一致，仓库值为 18.58/59.31 µs | `experiments/results/results.json`、`experiments/RESULTS.md:3,33-40`、`docs/VALIDATION.json:3-4` | `logs/07-artifacts-and-manifests.log`、`logs/repro-compare.log`；基线提交时间 07:22:41Z 与其工作树 `results.json` 的 `generated_at 07:22:41.682877Z` 同秒，说明快照在 04:40 发布物之后重跑过实验 | 选定唯一规范记录：用最终验证环境重跑并同时更新 `RESULTS.md`+`results.json`+重建 ZIP/sdist；或在 RESULTS.md 注明两组数字的来源差异 | 是 |

### 3.2 P2 发现

| 编号 | 问题 | 位置 | 证据 | 建议 |
| --- | --- | --- | --- | --- |
| P2-1 | `DESIGN.md` 状态表与实现不完全一致：**已过期 head + 更早的同值 explicit 证据**，表按条件 6（“值不同”才 conflict）+ 条件 9（无有效旧值 → confirmed）应得 `confirmed`，代码得 `conflict`（`elif head and c.at < head.at` 未判值是否不同） | `docs/DESIGN.md:22,25`；`core.py:260-271`（266 行） | `logs/hunt-state-machine.log` 用例 A：`status=conflict`；对照修正后用例 B/C 行为正确 | 在 266 行补 “value 不同” 条件，或改表把它列为已声明行为并加测试 |
| P2-2 | `local-memory.db` 被 git 跟踪，违反自身 `.gitignore:8 (*.db)` 与 `RELEASE.md:19`（“不要提交本地数据库”）；README:43 的 CLI 示例直接写 `./local-memory.db`（会改动被跟踪文件）。数据为虚构 demo，**未发现泄露** | 仓库根 `local-memory.db`；`README.md:43-47` | `git ls-tree 4bb7306 local-memory.db`（blob `a1a69a2…`）；内容仅 `demo-1` 虚构花偏好 | `git rm --cached local-memory.db` 并保留 `.gitignore`；README 示例改用 `./demo-memory.db`（已被忽略） |
| P2-3 | `VALIDATION.json` 证据不可自包含：只有 `exit_code`/`evidence` 字符串，无命令行、工具版本、原始日志；“Skill is valid!” 无 validator 可复核；审计开始时 venv 没有 ruff/build/twine | `docs/VALIDATION.json:6-57`（尤其 `:18-21 skill`） | `logs/00-environment.txt`（15:24 缺工具、15:31 出现）；`04/05/06` 日志为我补装后的复核（ruff 0、twine PASSED、build OK） | 在 `docs/` 保存验证命令与输出版本/日志；或把 `VALIDATION.json` 降级为“人工记录，不构成第三方证据”并注明工具版本 |
| P2-4 | CLI 的 `--index/--protection` 是建库参数，但**后续每次命令都必须重复**，否则 `Database schema/config mismatch` exit 2；README CLI 示例从未提示 | `cli.py:12-16`（全局参数）、`core.py:128-140`；`README.md:40-48` | `logs/13-cli-config-papercut.log` | README/DESIGN 明确“建库参数必须重复”，或查询时从 config 读回（需 CLI 支持） |
| P2-5 | 无输入大小/分页上限：100 KB value、1000 字符 event_id 可直接入库（payload 101384 B）；`history` 返回无界列表 | `core.py:61-90`（validate 无长度）、`cli.py:33-38` | `logs/hunt-state-machine.log` 用例 M | 增加字段长度/事件数上限与 `history --limit`，写入文档的“研究原型”边界 |
| P2-6 | NFC 归一化仅作用于 routing key，不作用于 `value`：规范等价的 `café`(NFC) 与 `cafe\u0301`(NFD) 被判为不同值 → `conflict`；文档只声明“NFC 仅消除键的组合差异” | `core.py:93-101,264`；`DESIGN.md:7,43` | `logs/hunt-state-machine.log` 用例 K | 写入前对 value 也做 NFC，或在文档中明确 value 按原始字节比较 |
| P2-7 | DB 文件默认权限 `0644`（明文记忆库），SECURITY 仅建议用户自行限制 | `core.py:113-115`；`SECURITY.md:5` | `hunt` CLI 运行后 `mem.db` 为 `-rw-r--r--` | 建库时 `chmod 600`（或 `umask` 说明），并在 SECURITY 写明默认不加密 |
| P2-8 | fixture/实验隔离脆弱：`scenarios.json` 有两个 case 共用 topic `health`，而 `experiments/run.py` 每种 mode 只建一个共享 store（当前因第一个 case 被 `rejected_sensitive` 未落库而无害；`tests` 却是每 case 新 store） | `experiments/scenarios.json`（case 12/13）、`experiments/run.py:26-70` | 脚本统计：24 组 23 个唯一 topic；`repro-compare.log` | 让 topic 全局唯一，或 run.py 每 case 新 store，消除“靠数据巧合不互相污染”的隐患 |
| P2-9 | 幂等重试返回**插入时的历史事件**（`status=confirmed`），此时它可能已不是当前 head；baseline SKILL 说 “Only confirmed updates the current head” 易被误读为返回即当前 | `core.py:216-225`；`skills/memorygene/SKILL.md`（baseline 第 26 行附近） | 独立脚本：先 e1 确认 A，再 e2 change 为 B；重试 e1 返回 e1/`confirmed`，`current` 仍是 B | 文档说明重试返回的是原事件（历史状态），或返回值增加 `is_current` 标志 |

**其他观察（不列为缺陷）**：`scope=session` 允许空白 session（`routing` 只对前三字段 strip）；同一 `at` 时间戳的 `change` 可覆盖而不进 conflict（文档只要求“更早”才 conflict）；`forget` 后重放同 event_id 会重建记忆（无 tombstone，文档未承诺）；敏感+同意数据以明文写入主库与备份（SECURITY 已声明明文）。以上或为有意设计，或属文档未声明的边缘行为，供 Lead 判断。

---

## 4. 文档不一致清单（基线 4bb7306）

| 文档:行 | 声明 | 实际 |
| --- | --- | --- |
| `README.md:61` | “损坏读写失败关闭，调用者显式修复” | payload/digest 损坏严格失败关闭；`heads.route`、非 head 的 `events.route` 损坏时**静默返回空/少事件**（P1-3） |
| `SECURITY.md:11` | “无法恢复时返回错误，不猜测内容” | 同上；元数据损坏不会返回错误（但同段已声明 heads/索引“不保证可恢复”，两种表述互相拉扯） |
| `RESULTS.md:3,35-40` | 运行时间 04:40:00、plain 21.73 µs、complement 69.63 µs；`:46` 提示“完整结果见 results.json” | 这两个数字精确对应 **ZIP/sdist** 的 results.json；仓库 4bb7306 的 results.json 是 04:50 的另一次运行（18.58/59.31 µs）（P1-4） |
| `AUDIT.md:32` | “实际本地验证为 Python 3.13” | 发布物/ZIP 结果确为 3.13.3；但**仓库快照**的 results.json（3.11.7）与 `local-memory.db`（recorded_at 04:50）显示快照在 04:40 验证之后又用 3.11.7 重跑/写入过（P1-4 的时间线） |
| `RELEASE.md:19` | “不要提交本地数据库…” | 4bb7306 跟踪了 `local-memory.db`，且 `.gitignore:8` 是 `*.db`（P2-2） |
| `DESIGN.md:22,25` 状态表 | 条件 6 要求“值不同”才 conflict；无有效旧值 → confirmed | expired head + 更早同值证据被实现为 conflict（P2-1） |
| `docs/VALIDATION.json:8-11,18-21,37-41` | ruff exit 0 / Skill valid / metadata PASSED | ruff、twine（metadata）在补装工具后可复现为 PASS；`Skill is valid!` 无命令/输出/validator，不可复核（P2-3） |
| `README.md:43-47` | CLI 示例写 `./local-memory.db` | 该路径是 git 跟踪文件，跑示例会弄脏仓库（P2-2）；且未提示 `--index/--protection` 需重复（P2-4） |
| `README.md:66` / `RESULTS.md` 结论 | 24 组/47 次、plain/complement 一致、互补无独立收益、未证明压缩/加密/更强纠错 | 全部复核为真（§2.2、§2.4）；这部分诚实、可验证 |
| `VALIDATION.json:61-65` 限制 | 仅本机 3.13、无远端 CI、无 NLP 基准 | 与仓库状态一致（`git remote` 为空、`remote_ci_executed:false`）；属如实披露 |

---

## 5. 无法验证 / 限制

1. **PROVENANCE 的 PDF 哈希**（`docs/PROVENANCE.md:11-12`）：材料不在仓库内，且按任务约束不读取项目之外的个人材料、无网络 → 无法复核两个 sha256 与“未找到 v0.1”的检索结论。
2. **远端状态**：GitHub 仓库/PyPI/远端 CI（`RELEASE.md:3`、`VALIDATION.json:58-60`）无网络且 `git remote -v` 为空 → 无法验证；与文档自述“尚未发布”一致，属如实声明。
3. **CI Actions 版本**：`.github/workflows/ci.yml:12-13` 使用 `actions/checkout@v7`、`actions/setup-python@v7`；无网络，无法确认这些 tag 是否存在（`RELEASE.md:13` 亦自认“远端仍须执行验证”）。若 tag 不存在，首次推送 CI 会失败——建议 Lead 在有网环境首次验证。
4. **`Skill is valid!`**（`VALIDATION.json:18-21`）：本机无相应 skill validator 及输出记录，无法复核。
5. **Python 3.10 运行时**：本机只有 3.11.7 / 3.12.10 / 3.13.3；3.10 仅做了 AST 语法检查。注意 `datetime.fromisoformat` 在 3.10 比 3.11+ 更严格，`instant()` 对 `+00`、`+0000`、空格分隔等非规范格式的接受集合可能不同；仓库测试与文档示例使用的 `Z`/`+00:00` 在 3.10 可工作，但该差异未经运行时验证。
6. **Windows/Linux**、多进程/多主机并发（只测了同机多线程各自独立连接）、SQLite 页级/文件级灾难恢复（文档已声明不在范围）、matplotlib 重绘（`.venv` 无 matplotlib，未联网安装；仅确认两张 PNG 存在且为 1800×774）。
7. **自然语言/宿主集成效果**：本版不含抽取器与召回服务，文档亦未宣称；Lead 的 adapter/extract 属并发改动，未纳入本轮基线。

---

## 6. 给 Lead 的优先修复清单（按建议顺序）

1. **P1-1 + P1-2（集成边界，最高优先）**：显式建库门槛 + 库归属校验。两处都在 `MemoryStore.__init__`/CLI 入口，改一处即可覆盖 3 个命令与 API 调用者；建议补两个 subprocess/unit 回归测试（错误路径 `forget` 必须非 0；外来 SQLite 必须拒绝）。
2. **P1-3**：修文档或加元数据一致性检查。若时间紧，最小改动是 `README.md:61`/`SECURITY.md:11` 限定 “仅 payload/digest 校验为 fail-closed”，并在 `AUDIT.md` 的限制里补一条 route/heads 元数据损坏不可检测。
3. **P1-4**：统一 `results.json`/`RESULTS.md`/发布包的单一证据链；用最终环境重跑一次并同时更新三者（或明确 ZIP 为规范）。顺手清掉 `local-memory.db`（P2-2）与 README 的 `./local-memory.db` 示例。
4. **P2-1**：若 Lead 正在改 `core.py`，顺手在 266 行补“值不同”判断并加一个测试（当前文档/实现二者必居其一）。
5. **P2-4 / P2-6 / P2-9**：文档补三句话（建库参数需重复、value 不做 NFC、重试返回历史事件）即可，不必改代码。
6. **P2-3 / P2-5 / P2-7 / P2-8**：按发布节奏选做；P2-3 在最终 `VALIDATION.json` 中至少要记录命令与工具版本。

---

## 7. 证据索引

```
evidence/review/
├── audit-initial.md                         # 本文件
├── logs/
│   ├── 00-environment.txt                   # 审计环境、git 状态、工具可用性（含 15:31 工具补装 NOTE）
│   ├── 01-baseline-unittest-3.11.log        # 36 tests OK
│   ├── 01-baseline-unittest-3.13.log        # 36 tests OK
│   ├── 01b-baseline-unittest-3.12.log       # 36 tests OK
│   ├── 02-lifecycle.log                     # 3.11.7 / 3.13.3 示例
│   ├── baseline-experiments-3.11.log        # experiments/run.py 全量 stdout
│   ├── 03-experiments-fresh-results.json    # 独立重跑结果（语义与基线/ZIP 一致）
│   ├── 03-experiments-fresh-trace.json      # 188 条 trace
│   ├── repro-compare.log                    # git vs ZIP vs 重跑：语义一致、计时不同
│   ├── 04-ruff-baseline.log                 # ruff All checks passed（baseline 树）
│   ├── 05-twine-check.log                   # wheel/sdist metadata PASSED
│   ├── 06-build-baseline.log                # python -m build --no-isolation 成功
│   ├── 07-artifacts-and-manifests.log       # sha256/文件集/ZIP 内测试/wheel 安装验证/local-memory.db
│   ├── 10-repro-silent-create.log           # P1-1
│   ├── 11-repro-foreign-sqlite.log          # P1-2
│   ├── 12-repro-metadata-failopen.log       # P1-3
│   ├── 13-cli-config-papercut.log           # P2-4
│   ├── hunt-state-machine.log               # 状态机用例 A–M（含 P2-1/P2-5/P2-6）
│   ├── hunt-failclosing.log                 # 损坏/头指针/路由列
│   ├── hunt-concurrency-config-repair.log   # 并发/配置/repair/路由
│   ├── hunt-routing-time.log                # 路由碰撞、TTL、时间格式
│   └── hunt-foreign-db-fuzz.log             # 外来库 fuzz + 500 步状态机/不变量 + 300 次损坏 fuzz
└── scripts/
    ├── repro_silent_create_and_forget.py    # P1-1 最小复现
    ├── repro_foreign_sqlite_adoption.py     # P1-2 最小复现
    ├── repro_metadata_corruption_not_fail_closed.py  # P1-3 最小复现
    └── hunt_*.py                            # 独立探测脚本全集
```

---

## 8. 审计期间并发编辑说明（避免误读）

- 领取任务时（15:24）工作树已处于 Lead 的改动中：`pyproject.toml`、`skills/memorygene/SKILL.md`、`src/memorygene/{cli,core}.py`、`tests/test_memorygene.py` 被修改，新增未跟踪的 `adapter.py`、`extract.py`、`scripts/`、`tools/`、`.dsh/`、`.memorygene/`、`docs/USAGE.zh.md`、`experiments/nl_cases.json`、`tests/test_adapter.py`、`tests/test_extract.py` 等。
- 因此本报告的**代码级结论一律以 `git show 4bb7306:<path>` 导出的基线树为准**；工作树中的任何编辑都没有作为缺陷对象。若某个文件在审计中再次变化，我没有把瞬时状态写成缺陷。
- 15:31 左右 `.venv` 中被装入 ruff/build/twine（应为并发准备发布验证）；这不影响基线代码运行（所有基线命令显式 `PYTHONPATH=/tmp/audit_baseline/src`），但意味着 `.venv` 自身不是可复现的固定环境——见 P2-3。
- 本报告可原样用于**改动落地后的最终复审**：同样的脚本在最终提交/最终 ZIP 上重跑即可对比（重点复跑 P1-1/2/3 的三个 repro、`unittest`、`experiments/run.py` 语义比对、ZIP/wheel 哈希）。
