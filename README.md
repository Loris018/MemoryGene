# MemoryGene

**Bioinspired Adaptive Memory Systems Based on Neural Reconsolidation and DNA Repair** — a research prototype of long-term memory for LLM agents.

MemoryGene asks how an AI should decide *what* to remember, *when* to change an existing memory, and *how* to keep history without inventing facts. It is a local, dependency-free Python core (SQLite) plus an agent-skill adapter. Status: **research development version 0.2.0.dev2**, Python 3.10+.

> 中文简介见 [下方](#中文简介)。This repository reports negative results as well as positive ones; see [Honest status](#honest-status).

## Why

Saving more chat logs does not make an assistant remember well. Some facts are repeated often but are not worth keeping; others are said once and matter for years. Users hesitate, change their minds, correct mistakes and talk about other people. A memory system has to tell these apart, keep an auditable history, and never "restore" information it has no evidence for.

## What it does today

Every incoming statement becomes a **Candidate** with separate fields for *certainty* (`explicit` / `uncertain` / `inferred`), *intent* (`assert` / `change` / `correct` / `supplement`), *importance* in `[0,1]`, *scope* (`persistent` / `session`) and the user's verbatim `source` text. A deterministic state machine then decides what happens:

| Condition (first match wins) | Result | Stored / becomes current |
| --- | --- | --- |
| sensitive and no explicit consent | `rejected_sensitive` | no / no |
| persistent and importance < 0.5 | `discarded` | no / no |
| already expired | `expired` | no / no |
| uncertain or inferred | `pending` | yes / no |
| same value as current | `duplicate` | yes / no |
| older evidence with a different value | `conflict` | yes / no |
| different value, `intent=assert` | `conflict` | yes / no |
| different value, `intent=supplement` | `pending` | yes / no |
| empty slot, or explicit `change` / `correct` | `confirmed` | yes / yes |

On top of that: append-only version history with `previous_id` and `resolves` links, TTL expiry that never resurrects old versions, session vs. cross-session scopes, topic-level forgetting that also purges dependent task checkpoints, a fail-closed integrity layer (SHA-256, explicit `verify` / `repair`), lexical budgeted `recall`, and explicit task checkpoints for resuming work across sessions.

## Honest status

| Research goal | Status |
| --- | --- |
| Do not turn guesses into facts | **Working.** 0/7 uncertain inputs confirmed in the dev set; pending/conflict evidence is kept, never promoted silently |
| Separate legitimate updates from corruption | **Working.** Versioning handles updates; checksum + `repair` handles damage; repair never rolls back a valid version |
| Provenance, correction, deletion | **Working.** Verbatim source, consent evidence for sensitive data, dependent forgetting |
| Selective memory | **Not yet an algorithm.** Importance is supplied by the calling model; repetition is ignored (repeated low-importance mentions leave no trace) |
| Reconsolidation (find related old memory, decide update) | **Partly, new in this version.** Read-only `locate` finds the slot a statement touches; `advise` turns a silent `conflict` into one `confirm_change` question. The update itself still needs the user's explicit confirmation |
| Proactive self-checking | **Partly, new.** `recall` now lists unresolved evidence marked `not_a_fact`; `review` lists open evidence and duplicate-looking slots; `repeated_uncertain` asks once when a hesitation recurs. No user study yet |
| Memory identity | **Improved, still the main bottleneck.** On recorded outputs of an independent LLM, attaching statements to the right existing slot rose from 11/23 (exact topic) to 20/23 with lexical anchoring, 0 wrong attaches; the rest needs world knowledge (tea ⊂ drink). Exploratory, see [RECONSOLIDATION.md](experiments/RECONSOLIDATION.md) |
| DNA-inspired organisation | **Complement encoding: negative result.** The "complement index" is a reversible re-encoding of the lookup key (identical results, 4× key bytes, slower); the "complement backup" is `byte XOR 0xFF`, equivalent to a plain copy. **Two-strand pairing (new, P2): partly supported.** Checking the stored value against its verbatim evidence catches in-path semantic damage that byte protection misses entirely (0/381). However, our pre-registered partial-match rule lost to plain containment (H2c failed); the current rule was chosen afterwards and still needs fresh data. See [STRANDS.md](experiments/STRANDS.md) |

ATCG encoding is **not** compression, encryption, semantic understanding or stronger error correction.

## Results (reproducible)

| Experiment | Result | Details |
| --- | --- | --- |
| Unit / integration tests | 162/162 pass | `python -m unittest discover -s tests` |
| Structured dev set (24 scenarios, 47 inputs) | rules 24/24 current & history; overwrite baseline 12/24, append-latest 12/24; plain and complement index identical | [experiments/RESULTS.md](experiments/RESULTS.md) |
| Equal-budget recovery (100 payloads × 6 damage modes) | plain copy = complement copy in every mode | same |
| Rule extractor regression (47 fictional dialogues, 79 turns) | write decision 77/79, topic 57/57 — same authors wrote rules and cases, **not** a held-out benchmark | [experiments/NL_RESULTS.md](experiments/NL_RESULTS.md) |
| Held-out NL (30 new dialogues, independent `deepseek-flash` extractor) | decision 36/40, exact topic 11/27; end-to-end oracle 30/30 vs model 20/30 | [held-out result](experiments/heldout-2026-10-29/RESULT.md) |
| Slot recognition under topic drift (exploratory) | exact topic 11/23 → anchored lexical cues 20/23, 0 wrong; value/source cues added nothing over topic cues | [experiments/RECONSOLIDATION.md](experiments/RECONSOLIDATION.md) |
| Advice scenarios (14, dev) | should-advise 5/5; unneeded interruptions 1/9 | same |
| Two-strand pairing, pre-registered (87 gold pairs × 5 synthetic damage types) | byte protection 0/381 detected; pre-registered pairing beat containment only on negation loss and lost on embellish/merge (H2c failed); post-hoc strict rule 4/5 types, 0 false alarms; truncation undetectable | [experiments/STRANDS.md](experiments/STRANDS.md) |
| Real agent host (DeepSeek Harness, headless) | write → cross-session read → revise → forget; task resume across 2 sessions | [docs/DSH-INTEGRATION.md](docs/DSH-INTEGRATION.md) |

Limitations: baselines are weak (no certainty rules), datasets are small and fictional, labels have a single annotator, and there is no comparison yet with other memory frameworks. These results show the implementation behaves as designed, not that it is better than existing systems.

## Quick start

```sh
git clone https://github.com/Loris018/MemoryGene.git && cd MemoryGene
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e .
python examples/lifecycle.py                 # write, revise, history, forget
python -m unittest discover -s tests         # 162 tests
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
    print(memory.verify())
```

Structured CLI (`memorygene --db PATH ingest|current|history|topics|verify|repair|forget`) and the agent adapter (`memorygene-dsh doctor|recall|locate|review|topics|current|remember|history|forget|task-*`) are documented in [docs/USAGE.zh.md](docs/USAGE.zh.md). The adapter never guesses natural-language meaning, never fabricates consent or sources, and never creates a database implicitly.

## Repository layout

```
src/memorygene/   core.py (state machine, storage), codec.py (dna-v1 encoding),
                  recall.py, reconsolidate.py (locate / advice / review),
                  strands.py (value-vs-evidence pairing),
                  tasks.py, extract.py (rule-based baseline extractor),
                  adapter.py (agent CLI), cli.py
tests/            unit and integration tests
experiments/      dev-set policy/recovery/index experiments, NL evaluation, held-out benchmark
skills/, tools/   agent skill template and DeepSeek Harness integration files
scripts/          skill installer, acceptance and harness runners
docs/             design contract, experiments, audits, usage
evidence/         curated logs from real runs (raw host session logs are not published)
```

## Roadmap (not yet results)

1. **Memory identity beyond lexical cues** — first version done (`locate` / `advise` / `review`); next: a fresh held-out dialogue set, giving the extractor the existing topic catalogue, and optional embedding cues for world knowledge (tea ⊂ drink).
2. **Two-strand pairing on real data** — first pre-registered test done ([STRANDS.md](experiments/STRANDS.md)); next: validate the post-hoc strict rule on fresh dialogues and real LLM rewrites, and handle legitimate normalisation (dates, numbers, synonyms) without losing detection.
3. **Fair baselines** — LLM-chosen add/update/delete (Mem0-style) and bitemporal fact invalidation (Graphiti-style), plus the knowledge-update subset of LongMemEval.
4. **Cross-session evidence accumulation** for selective memory.
5. **Host-neutral interface** (JSON CLI / MCP) beyond DeepSeek Harness.

## Privacy and security

The database is plain text: ATCG and XOR hide nothing. `namespace`/`subject` are logical partitions, not authentication. Stored `source`/`value` are data and must never be executed as instructions. All datasets in this repository are fictional. No network calls or telemetry. See [SECURITY.md](SECURITY.md).

## Documentation

[Design contract](docs/DESIGN.md) · [Experiment plan](docs/EXPERIMENTS.md) · [Usage (zh)](docs/USAGE.zh.md) · [Agent integration](docs/DSH-INTEGRATION.md) · [Task checkpoints (zh)](docs/TASKS.zh.md) · [Related-work review (zh)](docs/RESEARCH-2026-10-28.zh.md) · [Audit](docs/AUDIT.md) · [Acceptance](docs/ACCEPTANCE.md) · [Provenance](docs/PROVENANCE.md) · [Contributing](CONTRIBUTING.md)

## 中文简介

MemoryGene 研究大语言模型 / AI Agent 的自适应长期记忆：如何区分稳定偏好、临时想法、不确定表达与明确决定；用户改口或纠正时如何更新记忆并保留历史；以及能否借鉴神经记忆再巩固与 DNA 互补修复机制，形成一种可验证的记忆组织方式。

**目前已经可靠的部分**：证据状态机（不确定不会被写成事实，冲突保留待确认）、版本历史、到期、会话与跨会话分区、按主题遗忘、完整性校验与修复、任务接续，以及在真实 Agent 宿主里跨会话验证过的接入。

**本版新增（再巩固支持）**：写入前可用 `locate` 找到这句话涉及的旧记忆；写入后 `advise` 在需要时给出一个建议（确认是否改变、可能是同一属性、反复出现的犹豫），从不自动改记忆；`recall` 会附带标明“不是事实”的未解决证据；`review` 做一次自检。在独立模型的抽取结果上，挂回正确旧槽位的比例从 11/23 提高到 20/23，没有挂错（探索性结果）。

**还没有做到的部分**：选择性记忆仍依赖调用方模型给出的重要性；主题识别是字面线索，不懂“茶属于饮品”这类常识；建议机制还没有做用户研究。

**DNA 部分**：现有"互补索引"和"互补备份"与普通索引、普通副本结果完全相同，没有显示出独立优势（负面结果）。新的预注册实验（P2）把"两条链"重新理解为信息独立的两部分：精简的值和用户原话，写入时让两者"配对"检查。字节级保护对走合法写入路径的语义损伤检出 0/381，配对检查能检出大部分；但我们事先登记的宽松配对规则不如最简单的子串匹配（假设 H2c 不成立），现行规则是看过结果后才选的，仍需新数据验证。

详细中文说明见 [docs/USAGE.zh.md](docs/USAGE.zh.md)。

## License

MIT. See [LICENSE](LICENSE).
