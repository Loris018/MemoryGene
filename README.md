# MemoryGene

Research prototype for the project *Bioinspired Adaptive Memory Systems Based on Neural Reconsolidation and DNA Repair*.

MemoryGene is a long-term memory layer I'm building for LLM agents. It's plain Python on top of SQLite, with no runtime dependencies. The current version is 0.2.0.dev2 and needs Python 3.10 or later.

中文简介在[文末](#中文简介)。

## Research questions

1. Some things are repeated many times but are not worth remembering, while others are said once and matter for years. How should an assistant decide what to keep?
2. How can it tell a stable preference from a passing thought, a hesitation or a firm decision?
3. When the user changes their mind or corrects a fact, how should memory be updated while the history is kept?
4. Can the assistant notice, during a conversation, that something it remembers is outdated or contradicted, without interrupting all the time?
5. Do ideas from biology, namely memory reconsolidation and DNA complementarity and repair, give any measurable benefit when translated into software?

I started from long-term companion chat, where shared history and changing preferences matter a lot. Nothing in the design is tied to that, though, and it should work just as well for personal assistants, study buddies or agents that collaborate on a project.

## How it works

Each statement the agent wants to remember becomes a *candidate* with separate fields: certainty (explicit, uncertain, inferred), intent (assert, change, correct, supplement), importance, scope (this session or across sessions) and the user's own words as the source.

A small state machine decides what happens to the candidate:

| Condition (first match wins) | Result | Stored | Becomes current |
| --- | --- | --- | --- |
| sensitive and no explicit consent | rejected_sensitive | no | no |
| long-term and importance below 0.5 | discarded | no | no |
| already expired | expired | no | no |
| uncertain or inferred | pending | yes | no |
| same value as the current one | duplicate | yes | no |
| older evidence with a different value | conflict | yes | no |
| different value, plain assertion | conflict | yes | no |
| different value, supplement | pending | yes | no |
| empty slot, or an explicit change or correction | confirmed | yes | yes |

Every event is kept, so the full history of a memory can be read back. A newer version never erases an older one, expiry never brings an old value back, and forgetting a topic removes all of its versions together with any task notes that depend on it.

On top of this state machine there are two newer components.

**Reconsolidation support** (`reconsolidate.py`). Before writing, the agent can look up which existing memory a statement touches, even when the topic was named differently (for example `liked_flower` and `favorite_flower`). After writing, the system may return a short suggestion: ask whether this is a change, point out that two topics look like the same attribute, or note that the same hesitation has come up again. These are only suggestions. Memory changes only through an explicit write.

**Two-strand pairing** (`strands.py`). Every memory holds two pieces of information: the condensed value and the user's original sentence. The system checks that the value can be found in the sentence and is not negated there. If it cannot, the memory is flagged, never silently repaired. This is where the DNA analogy turned out to be useful: two strands that carry independent information can check each other, and damage shows up as a mismatch.

## Results so far

All data used here is fictional. Each experiment can be reproduced from this repository; see the linked reports for details and raw outputs.

| Experiment | Result | Report |
| --- | --- | --- |
| Policy scenarios (24 scenarios, 47 inputs) | my rules 24/24 correct; overwrite and append-latest baselines 12/24 | [RESULTS](experiments/RESULTS.md) |
| Uncertain inputs wrongly confirmed | 0/7 (baselines 7/7) | same |
| Independent LLM extraction on new dialogues (30 dialogues) | write decisions 36/40; exact topic names only 11/27 | [held-out](experiments/heldout-2026-10-29/RESULT.md) |
| Finding the right existing memory despite a renamed topic | 11/23 with exact names, 20/23 with the new matching, no wrong matches | [RECONSOLIDATION](experiments/RECONSOLIDATION.md) |
| Suggestions in 14 test scenarios | all 5 needed suggestions given; 1 unneeded interruption in 9 | same |
| Meaning-level damage written through the normal path (381 cases, 5 types) | checksum and backup detect 0; value-source pairing detects 4 of 5 types | [STRANDS](experiments/STRANDS.md) |
| Cross-session use inside a real agent host | write, read in a new session, revise and forget all work | [integration](docs/DSH-INTEGRATION.md) |
| Unit and integration tests | 162 pass on Python 3.10 to 3.14 | CI |

## Limitations and negative results

Some of these are negative results. I'm keeping them here because they shaped the design as much as the things that worked.

- **Complementary encoding gave no benefit.** My first DNA-inspired design stored lookup keys as complementary base sequences and kept a complementary backup copy. Both turned out to be equivalent to ordinary storage: identical results, four times larger keys, slower lookups, and recovery exactly the same as a plain copy. They're kept only as baselines now.
- **My pre-registered pairing rule lost to the simplest baseline.** I fixed the hypothesis and thresholds before running the two-strand experiment. A tolerant rule that accepted partial matches did worse than plain substring matching on two damage types. The stricter rule now in use was chosen after seeing those results and still needs fresh data.
- **Selective memory is not yet learned.** Importance is still supplied by the calling model. Repeated low-importance remarks are dropped and leave no trace.
- **Matching is lexical.** It cannot know that tea is a kind of drink. Equal values can be mistaken for the same attribute.
- **The data is small and fictional.** I wrote the labels myself, and there has been no user study yet. These results show that the prototype behaves as designed. They do not show that it is better than existing memory systems; a fair comparison is the next step.

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

There is also a command-line tool for agents, `memorygene-dsh`, with the commands `remember`, `current`, `history`, `recall`, `locate`, `review`, `forget` and `verify`. It never guesses the meaning of a sentence, never invents consent or sources, and never creates a database unless asked. Usage is described in [docs/USAGE.zh.md](docs/USAGE.zh.md).

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

I looked at Mem0, Letta, Graphiti, MemoryBank and a few agent memory plugins before settling on this design. A summary is in [docs/RESEARCH-2026-10-28.zh.md](docs/RESEARCH-2026-10-28.zh.md). The design contract is in [docs/DESIGN.md](docs/DESIGN.md), and the experiment plan is in [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md).

## Privacy

The database is not encrypted, and namespaces are logical partitions rather than access control. Stored text is treated as data and never as instructions. All datasets in this repository are fictional. The software makes no network calls. See [SECURITY.md](SECURITY.md).

## 中文简介

MemoryGene 是我在做的一个大语言模型助手长期记忆项目。我想搞清楚这几件事：哪些信息值得长期保存；怎样区分稳定偏好、临时想法、犹豫和明确决定；用户改变主意时怎样更新记忆并保留历史；以及神经记忆再巩固、DNA 互补与修复这些生物学思想，转化成软件机制后是否真的有用。

目前的原型包括：

- 证据状态机：不确定的话不会被当成事实，有冲突时保留证据、等待确认。
- 完整的版本历史，按主题遗忘时连同依赖一起删除。
- 再巩固支持：写入前先找到相关的旧记忆；在需要时提醒助手向用户确认一次，平时保持安静。
- 值与原话的"双链配对"检查：发现那些走正常写入流程、因而校验和发现不了的语义错误。

负面结果我也都留着。最初的"互补编码"和"互补备份"与普通存储完全等价，没有带来任何好处。事先登记的宽松配对规则也不如最简单的子串匹配。数据规模小、全部为虚构，目前还没有与现有记忆系统做公平比较，这是下一步的工作。

## License

MIT. See [LICENSE](LICENSE).
