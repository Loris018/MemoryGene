# MemoryGene

Research prototype for the project *Bioinspired Adaptive Memory Systems Based on Neural Reconsolidation and DNA Repair*.

MemoryGene is a long-term memory layer for LLM agents, implemented in Python on top of SQLite with no runtime dependencies. The current version is 0.2.0.dev2 and needs Python 3.10 or later.

中文简介在[文末](#中文简介)。

## Research questions

1. Some things are repeated many times but are not worth remembering, while others are said once and matter for years. How should an assistant decide what to keep?
2. How can it tell a stable preference from a passing thought, a hesitation or a firm decision?
3. When the user changes their mind or corrects a fact, how should memory be updated while the history is kept?
4. Can the assistant notice, during a conversation, that something it remembers is outdated or contradicted, without interrupting all the time?
5. Do ideas from biology, namely memory reconsolidation and DNA complementarity and repair, give any measurable benefit when translated into software?

The project originated in the setting of long-term companion chat, where shared history and changing preferences are central. The design is not specific to that setting and applies equally to personal assistants, learning companions and collaborative agents.

## How it works

Each statement the agent wants to remember becomes a *candidate* with separate fields: certainty (explicit, uncertain, inferred), intent (assert, change, correct, supplement), importance, scope (this session or across sessions) and the user's own words as the source.

A small state machine decides what happens to the candidate:

| Condition (first match wins) | Result | Stored | Becomes current |
| --- | --- | --- | --- |
| sensitive and no explicit consent | rejected_sensitive | no | no |
| long-term and importance below 0.5 | discarded | no | no |
| already expired | expired | no | no |
| explicit retraction of the current value | retracted | yes | current becomes empty |
| uncertain or inferred | pending | yes | no |
| same value as the current one | duplicate | yes | no |
| older evidence with a different value (or older than a retraction) | conflict | yes | no |
| supplement ("X is nice too") | pending | yes | no |
| different value, plain assertion | conflict | yes | no |
| empty slot, or an explicit change or correction | confirmed | yes | yes |

This conservative rule suits agents that can ask the user. For unattended use, an optional `latest` update mode accepts a newer explicit statement as the current value without asking, marks it in the history and notifies the agent. Supplements, uncertain statements and older evidence are still held back in this mode.

Every event is kept, so the full history of a memory can be read back. A newer version never erases an older one, expiry never brings an old value back, and forgetting a topic removes all of its versions together with any task notes that depend on it.

On top of this state machine there are two newer components.

**Reconsolidation support** (`reconsolidate.py`). Before writing, the agent can look up which existing memory a statement touches, even when the topic was named differently (for example `liked_flower` and `favorite_flower`). After writing, the system may return a short suggestion: ask whether this is a change, point out that two topics look like the same attribute, or note that the same hesitation has come up again. These are only suggestions. Memory changes only through an explicit write.

**Two-strand pairing** (`strands.py`). Every memory holds two pieces of information: the condensed value and the user's original sentence. The system checks that the value can be found in the sentence and is not negated there. If it cannot, the memory is flagged, never silently repaired. This is where the DNA analogy turned out to be useful: two strands that carry independent information can check each other, and damage shows up as a mismatch.

## Results so far

All data used here is fictional. Each experiment can be reproduced from this repository; see the linked reports for details and raw outputs.

| Experiment | Result | Report |
| --- | --- | --- |
| Policy scenarios (24 scenarios, 47 inputs) | MemoryGene 24/24 correct; overwrite and append-latest baselines 12/24 | [RESULTS](experiments/RESULTS.md) |
| Uncertain inputs wrongly confirmed | 0/7 (baselines 7/7) | same |
| Independent LLM extraction on new dialogues (30 dialogues) | write decisions 36/40; exact topic names only 11/27 | [held-out](experiments/heldout-2026-10-29/RESULT.md) |
| Finding the right existing memory despite a renamed topic | 11/23 with exact names, 20/23 with the new matching, no wrong matches | [RECONSOLIDATION](experiments/RECONSOLIDATION.md) |
| Suggestions in 14 test scenarios | all 5 needed suggestions given; 1 unneeded interruption in 9 | same |
| Meaning-level damage written through the normal path (381 cases, 5 types) | checksum and backup detect 0; value-source pairing detects 4 of 5 types | [STRANDS](experiments/STRANDS.md) |
| Same inputs under re-implemented Mem0-style, Graphiti-style and latest-explicit policies (100 cases) | the certainty filter explains most differences; against the strongest baseline MemoryGene differs in 7 cases: 4 supplements kept from replacing a favourite, 3 unmarked changes held for one confirmation question | [BASELINES](experiments/BASELINES.md) |
| LongMemEval knowledge-update, first 20 questions (external benchmark, small sample) | MemoryGene 14/20 without confirmation vs 16/20 for the best baselines; 16/20 with one confirmation question per detected change (2 questions in total), and 16/20 with no questions in the optional `latest` mode (designed after seeing this sample) | [LongMemEval](experiments/longmemeval-ku-2026-11-02/REPORT.md) |
| Simulated timelines with gold by construction (400 per seed, 10 event types, zh/en) | revealed two rule gaps (retraction, supplements filling an empty slot), now fixed; on a fresh seed MemoryGene matches the gold in 400/400 with perfect labels; the rule-based extractor gets about half right | [simulator](experiments/simulator/REPORT.md) |
| LongMemEval knowledge-update, 58 unseen questions (pre-registered held-out test) | `latest` mode 51/58, equal to the strongest baseline with a certainty filter; default mode 36/58 without confirmation (51/58 with 19 questions); policies without a certainty filter 53/58 | [held-out](experiments/longmemeval-ku-heldout-2026-11-07/REPORT.md) |
| Simulated timelines paraphrased by an LLM, then labelled by an independent LLM extractor (120 timelines, fresh seed) | `latest` mode 118/120 on paraphrased text vs 116 for the strongest baseline; the extractor labelled a third of unmarked changes as changes, which undermines the default `confirm` mode; paraphrasing barely hurt LLM extraction | [LLM run](experiments/simulator/llm-2026-11-07/REPORT.md) |
| Cross-session use inside a real agent host | write, read in a new session, revise and forget all work | [integration](docs/DSH-INTEGRATION.md) |
| Unit and integration tests | 193 pass on Python 3.10 to 3.14 | CI |

## Limitations and negative results

Several of the findings below are negative. They are documented here because they informed the design as much as the positive results.

- **Complementary encoding gave no benefit.** The initial DNA-inspired design stored lookup keys as complementary base sequences and kept a complementary backup copy. Both turned out to be equivalent to ordinary storage: identical results, four times larger keys, slower lookups, and recovery exactly the same as a plain copy. Both are retained only as baselines.
- **The pre-registered pairing rule underperformed the simplest baseline.** The hypothesis and thresholds were fixed before the two-strand experiment was run. A tolerant rule that accepted partial matches did worse than plain substring matching on two damage types. The stricter rule now in use was chosen after seeing those results and still needs fresh data.
- **Selective memory is not yet learned.** Importance is still supplied by the calling model. Repeated low-importance remarks are dropped and leave no trace.
- **No single policy wins everywhere.** The certainty filter is the largest advantage on simulated timelines with frequent hesitations, but on the LongMemEval held-out set it cost two questions, because real updates were sometimes worded approximately ("close to 1300 followers") and labelled as hedged.
- **The conservative update rule has a cost when no one confirms.** On a 20-question LongMemEval sample, MemoryGene scored 14/20 without confirmation and 16/20 with it, the same as the best baseline. Extractors often label real updates as plain statements, and they do so inconsistently.
- **Matching is lexical.** It cannot know that tea is a kind of drink. Equal values can be mistaken for the same attribute.
- **Extraction is the bottleneck.** On simulated timelines the rule-based extractor gets about half of the cases right whatever the policy. An LLM extractor does much better, but it labels intent inconsistently, and an LLM paraphraser tends to erase hedges.
- **The data is small and fictional.** Labels were written by the project authors, and no user study has been conducted yet. These results show that the prototype behaves as designed. The comparison with other designs is at the policy level only (no real Mem0 or Graphiti runs), and the external benchmark run so far is a 20-question sample.

## Getting started

```sh
git clone https://github.com/Loris018/MemoryGene.git && cd MemoryGene
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e .
python examples/lifecycle.py
python -m unittest discover -s tests
python experiments/run.py --out /tmp/mg-results
python experiments/nl_eval.py
python experiments/reconsolidation_eval.py --out /tmp/mg-results
python experiments/strand_eval.py --out /tmp/mg-results
python experiments/baselines_eval.py --out /tmp/mg-results
python experiments/simulator/evaluate.py --out /tmp/mg-results
```

```python
from memorygene import Candidate, MemoryStore

with MemoryStore(":memory:") as memory:
    memory.ingest(Candidate(
        namespace="demo", subject="fictional-user",
        topic="preference.favorite_flower", value="rose",
        source="I like roses best.", at="2026-10-01T00:00:00Z",
    ), event_id="demo-1", now="2026-10-24T10:00:00Z")
    print(memory.current("demo", "fictional-user", "preference.favorite_flower"))
```

MemoryGene also runs as an MCP server (`memorygene-mcp`) for clients such as Claude Desktop, Cursor and Cherry Studio, and as a skill for Claude Code and Codex; see [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md). There is also a command-line tool for agents, `memorygene-dsh`, with the commands `remember`, `current`, `history`, `recall`, `locate`, `review`, `forget` and `verify`. It never guesses the meaning of a sentence, never invents consent or sources, and never creates a database unless asked. Usage is described in [docs/USAGE.zh.md](docs/USAGE.zh.md).

## Repository structure

```
src/memorygene/   core.py           state machine and storage
                  reconsolidate.py  locating related memories, suggestions, self-check
                  strands.py        value and source pairing
                  recall.py         budgeted keyword recall
                  tasks.py          task notes that can be resumed across sessions
                  extract.py        rule-based extractor used as a baseline
                  adapter.py        command-line tool for agents
tests/            unit and integration tests
experiments/      experiment scripts, datasets and reports
docs/             design, usage, related work, agent integration
skills/, tools/   agent skill template and host integration files
```

## Related work

The design was informed by a review of Mem0, Letta, Graphiti, MemoryBank and several agent memory plugins. A summary is in [docs/RESEARCH-2026-10-28.zh.md](docs/RESEARCH-2026-10-28.zh.md). The design contract is in [docs/DESIGN.md](docs/DESIGN.md), and the experiment plan is in [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

## Privacy

The database is not encrypted, and namespaces are logical partitions rather than access control. Stored text is treated as data and never as instructions. All datasets in this repository are fictional. The software makes no network calls. See [SECURITY.md](SECURITY.md).

## 中文简介

MemoryGene 是面向大语言模型助手的长期记忆研究项目，研究以下问题：哪些信息值得长期保存；如何区分稳定偏好、临时想法、犹豫与明确决定；用户改变主意时如何更新记忆并保留历史；以及神经记忆再巩固、DNA 互补与修复等生物学原理转化为软件机制后能否带来可测量的收益。

当前原型包括：

- 证据状态机：不确定的陈述不会被确认为事实，出现冲突时保留证据并等待确认；无人确认的场景可启用可选的 `latest` 模式，自动接受更新的明确陈述并在历史中标记。
- 完整的版本历史；按主题遗忘时同时删除相关依赖。
- 再巩固支持：写入前定位相关的已有记忆，必要时提示助手向用户确认，其余情况下不打扰用户。
- 值与原话的"双链配对"检查：识别经由正常写入流程产生、校验和无法发现的语义错误。

项目同时记录了负面结果：最初的"互补编码"与"互补备份"与普通存储完全等价，未带来额外收益；预先登记的宽松配对规则不及最简单的子串匹配。与 Mem0 式、Graphiti 式更新策略的对比显示，差异主要来自确定性过滤；与最强基线相比，MemoryGene 仅在 100 个用例中的 7 个上结论不同。在 LongMemEval 知识更新题的 20 题小样本上，不向用户确认时 MemoryGene 得分 14/20，低于最佳基线的 16/20；每次检测到变化时确认一次（共 2 次）可达到 16/20。为缓解数据不足，项目加入了场景模拟器：自动生成带标准答案的虚构对话时间线，标准答案由事件语义直接推出、不依赖被测系统；它发现并促成修复了两处规则缺陷（无法表达撤回、补充陈述会填入空槽位）。在经大模型改写、再由独立大模型抽取的 120 条模拟时间线上，`latest` 模式答对 118/120，高于最强基线的 116/120；抽取模型把约三分之一“没标明的改口”标成了“改变”，使默认的确认模式难以成立，改写模型则倾向于抹去犹豫语气。在事先登记的 LongMemEval 留出测试（58 道未用过的题）中，`latest` 模式答对 51 道，与带确定性过滤的最强基线持平；不做确定性过滤的策略为 53 道，因为真实的更新有时带有估计语气，被标成了不确定。这说明确定性过滤的价值取决于数据，没有一种策略在所有数据上都最好。数据规模仍然较小，抽取环节是目前的主要瓶颈。

## License

MIT. See [LICENSE](LICENSE).
