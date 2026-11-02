# 独立留出自然语言基准（2026-10-29）

**性质**：全新虚构对话集 + 独立模型抽取 + 与既有规则原型不同的评估；用于检验“自然语言→Candidate→存储”链路，
不是产品 NLU 基准，也不是 MemoryGene 存储策略的独立正确性证明。
**没有用这批数据调整 MemoryGene 核心、`extract.py` 规则或 Skill 提示**；本文件只报告观察结果。

## 固定条件

- 30 组全新虚构中文对话 / 40 轮（`cases.json`），覆盖：明确偏好、明确改变、更正、犹豫、“也喜欢”、
  第三人称、否定/撤回、提问、闲聊、假设、未来计划、提示注入、敏感无同意、敏感有同意、到期、冲突、
  重复、同义词、无先前值的 change、历史陈述、补充后确认。
- 独立抽取器：DeepSeek Harness headless，模型 **deepseek-flash**（现有账号登录，provider `deepseek-account`）。
  没有给模型看标签、旧案例或 MemoryGene 规则；固定 now 与提示模板。
- 提示模板与哈希：`prompt.md`，sha256 `703acbec…ff6`。每 5 组一批，共 6 批；原始输出与 session id 在 `raw/`。
- 标签是我自己写的；标签驱动的 oracle 候选通过**同一套** MemoryGene 策略，oracle 最终结果与人工预期
  **30/30 一致**（只说明标签与现有策略自洽，不是外部金标准）。

## L1 抽取结果（分母公开）

| 指标 | 正确/分母 | 比例 | Wilson 95% |
| --- | --- | --- | --- |
| 写入/弃权决策 | 36/40 | 90.00% | 76.95%–96.04% |
| topic（精确字符串） | 11/27 | 40.74% | 24.51%–59.27% |
| value | 26/27 | 96.30% | 81.72%–99.34% |
| certainty | 26/27 | 96.30% | 81.72%–99.34% |
| intent | 26/27 | 96.30% | 81.72%–99.34% |
| importance 档位 | 16/27 | 59.26% | 40.73%–75.49% |
| source 逐字子串 | 27/27 | 100% | 87.54%–100% |
| sensitive | 23/27 | 85.19% | 67.52%–94.08% |
| consent | 27/27 | 100% | 87.54%–100% |
| 弃权理由精确匹配（诊断项） | 1/9 | 11.11% | 1.99%–43.50% |

**最突出的问题：topic 精确一致只有 11/27。** 模型倾向对同一主题使用细粒度/同义命名，例如
`preference.liked_flower` vs `preference.favorite_flower`、`personal.residence.city` vs `profile.city`、
`shopping.coupon_code` vs `promotion.code`、`health.allergy.penicillin` vs `health.allergy`。
当前 MemoryGene 没有语义主题归一化，所以这会直接造成存储层主题分裂或丢失。这是这次测试最有价值的发现。

其他失败：模型把“也喜欢/更喜欢”判成 `change`/`explicit`（h20）；把未来计划写成事实（h25）；
对“敏感无同意”直接弃权而不是生成待拒绝候选（h09/h27，端到端结果相同但 L1 决策不同）；
value 出现“对青霉素过敏” vs “青霉素过敏”的细微括写；importance 倾向高估（城市/生日/健康被判 high）。

## L2 存储结果（oracle 标签 vs 独立模型）

| 指标 | oracle 候选 | 模型候选（精确 topic） |
| --- | --- | --- |
| 最终 current 正确 | 30/30 | **20/30** |
| 确认历史正确 | 30/30 | **20/30** |

失败分类：**extraction-only 10、storage-only 0、both 0、neither 20**。
即：所有失败都能追溯到抽取（主要 topic 命名、少数决策/字段错误），没有观察到存储策略本身把正确抽取结果算错。

| 失败案例 | 现象 | 归类 |
| --- | --- | --- |
| h10 sensitive-consent | topic 写成 `location.home_address`，按金标 topic 查无结果 | 抽取（topic） |
| h13 correction | topic `personal.birthday` vs `profile.birthday` | 抽取（topic） |
| h14 unmarked-conflict | topic 改名 + 被标 sensitive/high；冲突语义无法按金标 topic 验证 | 抽取（topic/sensitive） |
| h15 explicit-change-city | topic 改名 + sensitive 误判 | 抽取（topic/sensitive） |
| h16 expired-coupon | topic 改名，且未抽取 `expires_at`，过期信息被当当前事实 | 抽取（topic/expiry） |
| h17 expiry-restate | topic 改名/到期字段不完整 | 抽取（topic） |
| h18 duplicate | 两轮 topic 不一致，第二轮被跳过 | 抽取（topic/decision） |
| h20 prefer-more | topic 改名；把补充误判为 explicit change | 抽取（topic/intent） |
| h25 future-plan | 把未来计划写成持久事实（多出 head） | 抽取（decision） |
| h26 health-consent | topic 更细 + value 括写 | 抽取（topic/value） |

## 与既有实验的关系

- 既有 `experiments/nl_eval.py` 是**同作者规则提取器**的回归/质量检查（47 组/79 轮，topic 57/57），
  不能与本基准直接比较：任务集、抽取器、分母和“是否留出”都不同。
- 本基准的独立模型没有被告知规范 topic 表，因此 exact-topic 40.74% 反映的是**当前真实接入缺口**，
  不是“模型能力”或“DNA 机制”的对比。也不声称本基准的标签是唯一正确解释。

## 失败与未验证

- 单一模型、单次运行，未控制 temperature/seed；没有多标注者一致性；提示与标签作者同期工作。
- 精确 topic 字符串评分对同义命名非常严格；这次**没有**修改适配层做别名归一，也没有把模型输出反哺到提示/规则。
- 只有 30 组，比例区间较宽；没有统计显著性结论。
- 仍未做 GUI 人工验收；没有远端 CI/跨平台运行。

## 复现

```sh
cd "<repo>"
# 首次运行会调用 6 个 headless 会话；已有 raw/*-final.txt 时会复用
.venv/bin/python experiments/heldout-2026-10-29/run_heldout.py
```

原始会话：`raw/batch-01..06-events.jsonl`；session id：
`session-b4384ef0…`、`session-b2d66b40…`、`session-edda3ab3…`、`session-ff09207a…`、
`session-a26131f1…`、`session-0b6d7958…`。结果：`results.json`、`cases.json`、`prompt.md`。

## 结论与下一步

1. 抽取的 **value/certainty/intent/source/consent 已经较好**（≥96%，source 100%），主要瓶颈是
   **稳定 topic 归一化** 与少数边界决策（未来计划、也喜欢/更喜欢、敏感无同意是否生成候选）。
2. 若要提升真实接入：由适配层维护**固定 topic 同义词表**，或在 Skill/提示中提供受控 topic 列表；
   改完后必须用**新的**留出集重测，不能拿本批数据调参后再称“留出”。
3. 存储策略层在本批次没有单独失败，但 oracle 30/30 只证明标签自洽；仍需独立标注与更大样本。
