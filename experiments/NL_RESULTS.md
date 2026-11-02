# 自然语言提取原型与独立虚构评估（回归/质量检查）

> 本评估是**规则原型 + 回归/质量检查**，不是留出集基准，也不是自然语言理解（NLU）能力声明。
> 实验里的提取规则与 47 组对话案例由同一作者同期开发，案例只覆盖本规则表涉及的虚构句式；
> 因此下面的准确率不能外推为“真实用户对话上的 NLU 准确率”。所有人物、对话、号码、地址均为虚构（虚构数据），
> 不含任何真实聊天记录或个人数据。

## 1. 新增内容

| 文件 | 作用 |
| --- | --- |
| `src/memorygene/extract.py` | 确定性、零依赖的中文规则提取原型：`extract(text, *, namespace, subject, at, session="", source_span=None) -> list[Extraction]` |
| `tests/test_extract.py` | 29 个 unittest：规则、来源子串不变量、确定性、同意不伪造，以及用真实 `MemoryStore` 验证犹豫/补充永不确认 |
| `experiments/nl_cases.json` | 47 组虚构对话（共 79 轮，其中 30 组包含至少两轮），每轮含人工标签：topic/value/certainty/intent/importance 档位/是否应写入，预期逐轮状态、最终当前值与确认历史 |
| `experiments/nl_eval.py` | 分层评估器：L1 提取 / L2 存储 / 公平性消融；输出 JSON 与完整 trace |
| `experiments/results/nl_results.json` | 本次运行全部指标、失败列表、公平性测量原始数据 |
| `experiments/results/nl_trace.json` | 逐案例逐轮：原文、人工标签、提取器输出、L1 判定、oracle 与提取器状态 |
| `experiments/NL_RESULTS.md` | 本文件 |
| `evidence/nl/` | 测试与评估命令的运行日志 |

## 2. 复现命令

在项目根目录执行：

```sh
PYTHONPATH=src .venv/bin/python -m unittest tests.test_extract -v
PYTHONPATH=src .venv/bin/python experiments/nl_eval.py
```

固定条件：`now=2026-10-24T10:00:00+00:00`，证据时间 `at=2026-10-01T00:00:00+00:00`，
`namespace="nl-fixture"`，`subject="fictional-user"`；每组对话单独建库，互不串证据。
运行耗时约 0.4 秒（本机），无网络、无第三方依赖、无 matplotlib。

## 3. 评估设计

- **L1 提取层**（与存储无关）：逐轮比较提取器的 topic、value、certainty、intent、importance 档位、
  是否写入（`should_write`）与 source 合法性。辅助指标：sensitive、consent、弃权理由。
  分母 = 57 个“应写入”轮（topic/value/certainty/intent/importance/source/sensitive/consent）；
  写入决策 = 全部 79 轮；弃权理由 = 22 个“应弃权”轮。
  提取器若错误弃权，该轮所有字段指标都记错（避免用“没提取就不算错”美化妆分）。
- **L2 存储层**：对同一批轮次用两套候选跑**完全相同**的 `Candidate -> MemoryStore.ingest` 规则：
  (a) oracle 候选 = 人工标签字段；(b) 提取器候选 = `extract()` 输出。
  比较逐轮状态、最终 current 值、确认历史序列是否与人工预期一致。
  每个失败案例归入 extraction-only / storage-only / both / neither。
- **来源最小性**：source 必须是原文的**连续逐字子串**；另报告“不比人工最小片段更长”
  与“归一化后完全等于人工片段”两个更严格的变体。本原型在 source 上 57/57 三种检查全通过。
- **公平性**：同一提取器/规则管线分别用 index=plain/complement、protection=none/copy/complement 共 6 组配置运行，
  copy 与 complement 都恰好增加一份 payload 长度（等冗余字节）；断言 6 组语义结果完全一致，
  并测量路由键字节、逻辑字节和 SQLite 文件大小。

## 4. L1 提取层结果（分母公开）

| 指标 | 正确/分母 | 准确率 |
| --- | --- | --- |
| 写入/弃权决策 | 77 / 79 | 97.47% |
| topic | 57 / 57 | 100.00% |
| value | 56 / 57 | 98.25% |
| certainty | 57 / 57 | 100.00% |
| intent | 56 / 57 | 98.25% |
| importance 档位 | 56 / 57 | 98.25% |
| source 为逐字子串 | 57 / 57 | 100.00% |
| source 不比人工片段长 | 57 / 57 | 100.00% |
| source 与人工片段完全一致 | 57 / 57 | 100.00% |
| sensitive（辅助） | 57 / 57 | 100.00% |
| consent（辅助） | 57 / 57 | 100.00% |
| 弃权理由分类（辅助） | 20 / 22 | 90.91% |

L1 共 7 条字段级失败（集中在 5 个轮次），全部列出如下（原始数据见 `nl_results.json` 的 `L1.failures`）：

| 案例 | 轮 | 字段 | 期望 | 实际 |
| --- | --- | --- | --- | --- |
| `nl-value-blue-rose` | 0 | value | `蓝色玫瑰` | `玫瑰`（词典最长匹配只截取到“玫瑰”） |
| `nl-also-usually` | 0 | intent | `assert` | `supplement`（把口语“也喜欢”误当补充标记；存储结果不受影响） |
| `nl-not-really-like` | 0 | decision | `skip` | `write`（“没有很喜欢”不在否定词表，被当成肯定陈述） |
| `nl-not-really-like` | 0 | skip_reason | `negation` | `write:assert` |
| `nl-casual-uncertain` | 0 | importance 档位 | `low` | `mid`（未识别“随口说一句”的低重要性线索） |
| `nl-spouse-third-party` | 0 | decision | `skip` | `write`（“配偶”不在固定第三人称词表，被归到本人） |
| `nl-spouse-third-party` | 0 | skip_reason | `third_party` | `write:assert` |

## 5. L2 存储层结果

### 5.1 oracle 候选（人工标签）vs 提取器候选

| 指标 | oracle 候选 | 提取器候选 |
| --- | --- | --- |
| 最终 current 值正确 | 47 / 47（100.00%） | 44 / 47（93.62%） |
| 确认历史序列正确 | 47 / 47（100.00%） | 44 / 47（93.62%） |
| 逐轮状态正确 | 79 / 79（100.00%） | 76 / 79（96.20%） |

说明：oracle 100% 只说明“人工标签与本核心规则一致”，**不能**当成对核心正确性的独立验证；
它主要用来把“提取错误”和“存储策略错误”分开。提取器 vs oracle 语义结果不同的案例共 4 个
（有 5 个案例存在 L1 失败，其中 `nl-also-usually` 因存储策略不变而结果相同）。

### 5.2 失败分类

| 分类 | 案例数 | 案例 |
| --- | --- | --- |
| extraction-only | 5 | `nl-value-blue-rose`, `nl-also-usually`, `nl-not-really-like`, `nl-casual-uncertain`, `nl-spouse-third-party` |
| storage-only | 0 | — |
| both | 0 | — |
| neither | 0 | — |

所有 L2 失败都能追溯到提取层错误；在本数据上未观察到纯存储策略失败。
逐轮状态混淆（期望→实际，提取器候选）：`skipped->confirmed` 2 次，`discarded->pending` 1 次；oracle 侧为 0。

逐案例观察（完整字段见 `nl_results.json` 的 `L2.failing_cases`）：

| 案例 | 期望（状态/current/history） | oracle（标签） | 提取器 |
| --- | --- | --- | --- |
| `nl-value-blue-rose` | confirmed / `蓝色玫瑰` / [`蓝色玫瑰`] | 同期望 | confirmed / `玫瑰` / [`玫瑰`] |
| `nl-also-usually` | confirmed / `跑步` / [`跑步`] | 同期望 | confirmed / `跑步` / [`跑步`]（仅 L1 intent 错） |
| `nl-not-really-like` | skipped / null / [] | 同期望 | confirmed / `蓝色` / [`蓝色`] |
| `nl-casual-uncertain` | discarded / null / [] | 同期望 | pending / null / [] |
| `nl-spouse-third-party` | skipped / null / [] | 同期望 | confirmed / `百合` / [`百合`] |

## 6. 公平性：plain/complement 索引与 copy/complement 副本

同一提取器 + 同一核心规则，6 组配置，写入的 56 个事件、payload 合计 27,163 字节；
copy 与 complement 各增加 27,163 字节冗余（**完全相等**）。所有 6 组配置的语义摘要
（逐案例状态 + current + 确认历史）完全相同（sha256 `8d12163d88585d702057c64f01262bc57941d52ba6d20b5f6b6df4784072be1e…`），并与主 L2 提取器运行结果一致。
因此本实验支持的说法只有：**规则管线在不同表示/副本配置下语义一致**；
不支持“ATCG 编码带来压缩、加密、语义或纠错收益”的说法。

| index | protection | 事件数 | payload 字节 | 冗余字节 | 路由键字节 | 逻辑字节合计 | SQLite 文件字节 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plain | none | 56 | 27,163 | 0 | 4,184 | 31,347 | 36,864 |
| plain | copy | 56 | 27,163 | 27,163 | 4,184 | 58,510（+86.7%） | 36,864 |
| plain | complement | 56 | 27,163 | 27,163 | 4,184 | 58,510（+86.7%） | 36,864 |
| complement | none | 56 | 27,163 | 0 | 16,736 | 43,899（+40.0%） | 36,864 |
| complement | copy | 56 | 27,163 | 27,163 | 16,736 | 71,062（+126.7%） | 45,056（+22.2%） |
| complement | complement | 56 | 27,163 | 27,163 | 16,736 | 71,062（+126.7%） | 45,056（+22.2%） |

- **索引成本**：complement 路由键字节 16,736 = plain 4,184 的 **4.0 倍**（ASCII A/C/G/T 每字节 4 个碱基字符），
  这是可逆表示的确定开销，不是压缩。
- **副本成本**：copy 与 complement 的冗余字节严格相等（各 27,163 字节），逻辑字节合计也相等；
  complement 副本没有额外语义收益。
- **数据库文件**：小样本下 SQLite 页分配/空闲页复用会掩盖部分逻辑差异（plain 的 copy 配置文件大小与 none 相同）；
  complement 路由键更大，触发页增长后 6 组中 complement 的 copy/complement 配置比基线多 8,192 字节（+22.2%）。
  这里报告的是单机实测文件大小，不推断大规模下的比例。

## 7. 已知提取器弱点（诚实清单）

1. **复合值**：固定词典最长匹配不做组合，`蓝色玫瑰` 提取成 `玫瑰`；颜色+物件、品牌+品类等会截断。
2. **“也”的歧义**：任何“也喜欢”都记为 supplement；口语“平时也喜欢跑步”应是普通偏好（assert），意图误判。
3. **否定覆盖窄**：只识别 `不再/不喜欢/不爱/没兴趣/戒了/讨厌/不要记住` 等字面式；“没有很喜欢”“不太喜欢”“说不上喜欢”会漏判成肯定。
4. **重要性线索局部分段**：高重要性词（“请记住”）只在同一逗号分段生效；“随口说一句”这类低重要性暗示未建模，句首“记住”与后续陈述分句时会丢高重要性。
5. **第三人称词表固定**：“妈妈/朋友/同事…”可跳过，但“配偶/对象他爸/我室友的朋友”等变体会被错误归到本人。
6. **相对时间不解析**：只识别显式 `YYYY-MM-DD`（约定按当日 `T23:59:59Z` 截止）；“下周/月底/一周后”不会生成 `expires_at`，也不会臆造时间。
7. **多记忆切分有限**：同一逗号分段内的多个记忆只按一个处理；评估每轮也只评首个提取结果。
8. **固定主题表**：主题必须命中固定映射，未覆盖偏好（天气、加班等）只能弃权；弃权是安全但并非“理解”了反讽。
9. **无指代/省略/疑问句处理**：不支持“那它呢？”、“还是原来那个”等跨轮指代；不支持英文（英文输入按超范围弃权）。
10. **单值槽位**：每个主题只有一个当前值；多值偏好需要多个主题，不能用字符串覆盖模拟集合语义。

## 8. 局限与结论

- 47 组案例是与规则同期开发的**开发/回归集**，不是留出集；没有标注者一致性、置信区间、模型多次采样或主动召回评估。
- 值/主题匹配采用字符串精确匹配，同义改写、数字格式差异都计为错误；结论只适用于本固定规则与这批虚构案例。
- oracle 100% 验证的是“人工标签与核心规则自洽”，不能替代独立存储策略验证；L2 的价值在于把 5 个失败案例全部定位到提取层。
- 公平性实验只比较表示与副本配置，样本小、单机运行、顺序固定；不构成编码性能、纠错能力或安全结论。
- 本轮结论：在这批虚构中文对话上，规则提取原型的 topic/value/certainty/source 表现稳定，
  主要残余风险是复合值、口语否定、“也”的意图歧义、低重要性线索与第三人称同义词；
  核心存储策略在 oracle 与提取器两条链路上均未出现独立失败。上述结论不延伸到真实自然语言场景。
