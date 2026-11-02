# Policy-level comparison with common memory designs (2026-11-02)

Reproduce: `python experiments/baselines_eval.py`. Raw per-case outcomes: [results/baselines.json](results/baselines.json).

## Setup

The comparison isolates the **update policy**. Every policy receives exactly the same candidate fields (value, time, certainty, intent, importance, sensitivity, consent, expiry) taken from the gold labels of three fictional datasets, so extraction quality plays no role.

| Policy | Description |
| --- | --- |
| `overwrite` | The last write wins; no filtering. |
| `append_latest` | Every write is kept; the latest is current. |
| `mem0_style` | ADD / UPDATE / NONE in arrival order, with importance, consent and expiry filters; no certainty filter. Modelled on Mem0's public description. |
| `graphiti_style` | Bitemporal: the fact with the latest valid time is current and history is kept; same filters, no certainty filter. Modelled on Graphiti's public description. |
| `latest_explicit` | `graphiti_style` plus a certainty filter: the latest explicit statement wins regardless of intent. This is the strongest baseline. |
| `memorygene` | The MemoryGene state machine. |
| `memorygene_ask` | MemoryGene; whenever it returns `confirm_change`, a simulated user confirms once. |

The baselines are re-implementations of update policies, not the products. Real Mem0 and Graphiti use an LLM to decide operations and may behave differently on specific inputs.

**There is no policy-neutral ground truth.** The datasets' labels encode MemoryGene's conservative stance: a new value without an explicit change is held for confirmation. The LongMemEval "knowledge update" convention treats the latest explicit statement as true, and that convention is, by construction, identical to `latest_explicit`. Both views are reported.

## Results

Correct final current value per dataset. "Labels" = agreement with the dataset labels; "Latest" = agreement with the latest-explicit convention.

| Policy | Structured (24) labels / latest | NL dev (46) labels / latest | Held-out (30) labels / latest | Uncertain input became current | Questions asked |
| --- | --- | --- | --- | --- | --- |
| overwrite | 12 / 14 | 36 / 40 | 23 / 24 | 11 cases | 0 |
| append_latest | 12 / 14 | 36 / 40 | 23 / 24 | 11 cases | 0 |
| mem0_style | 16 / 18 | 40 / 44 | 26 / 27 | 10 cases | 0 |
| graphiti_style | 17 / 19 | 40 / 44 | 26 / 27 | 10 cases | 0 |
| latest_explicit | 22 / 24 | 42 / 46 | 29 / 30 | 0 | 0 |
| **memorygene** | **24** / 22 | **46** / 42 | **30** / 29 | 0 | 0 |
| memorygene_ask | 23 / 23 | 45 / 43 | 29 / 30 | 0 | 5 |

## Where the policies disagree

The first point at which each baseline's current value departs from MemoryGene's, by cause, summed over all 100 cases:

| Cause | overwrite | mem0_style | graphiti_style | latest_explicit |
| --- | --- | --- | --- | --- |
| uncertain or inferred statement | 14 | 14 | 14 | 0 |
| sensitive without consent | 5 | 0 | 0 | 0 |
| low importance | 4 | 0 | 0 | 0 |
| expired | 4 | 0 | 0 | 0 |
| older evidence arriving late | 1 | 1 | 0 | 0 |
| supplement ("X is also nice") | 5 | 5 | 5 | 5 |
| unmarked new assertion | 5 | 5 | 5 | 5 |

At the **final state**, `latest_explicit` and MemoryGene differ in 7 of 100 cases:

- **4 supplement cases**, e.g. "最喜欢爵士" followed by "古典也不错". `latest_explicit` replaces the favourite with 古典; MemoryGene keeps 爵士 and stores 古典 as pending. Most readers would side with MemoryGene: saying something is "also nice" does not change a favourite.
- **3 unmarked new assertions**, e.g. "我住上海" followed two weeks later by "我住北京". `latest_explicit` updates to 北京; MemoryGene keeps 上海 and returns `confirm_change`. Which outcome is right depends on the stance. With one confirmation question per case, MemoryGene reaches the latest-explicit outcome in all three.

## Findings

1. **The certainty filter accounts for most of the gap.** Without it, uncertain or inferred statements became the current value in 10 to 11 cases for every baseline. The filter is simple, and any system could adopt it; it is not unique to MemoryGene.
2. **Bitemporal ordering matters for late evidence.** The arrival-order policy (`mem0_style`) let an older statement overwrite a newer one; valid-time ordering did not.
3. **Against the strongest baseline, MemoryGene's distinct behaviour concerns 7 of 100 cases.** In 4 it avoids a likely semantic error (supplement treated as replacement). The other 3 are a deliberate trade-off: MemoryGene does not silently accept an unmarked change, at the cost of one question per change (5 questions over 100 cases in `memorygene_ask`).
4. **These counts are not frequencies.** The datasets were written to exercise exactly these phenomena; how often each one occurs in real conversations is unknown.

## Limitations

- Policy re-implementations only; no real Mem0 or Graphiti runs and no LLM in the loop.
- Small, fictional datasets labelled by the project authors; labels favour MemoryGene's stance on unmarked updates, which is why both conventions are reported.
- No external benchmark yet. The knowledge-update subset of LongMemEval is publicly available and is the natural next test; it requires an LLM to extract candidates from English chat sessions.

## Follow-up: unattended mode (added after these results)

Prompted by these results and the LongMemEval sample, MemoryGene gained an optional `update="latest"` mode (`memorygene-dsh remember --update latest`, or `"update_policy": "latest"` in the adapter configuration). In this mode a newer explicit assertion of a different value becomes current even without a stated change. The event is marked `policy: latest`, and the agent receives an `auto_updated` notice. Supplements, uncertain statements and older evidence are handled as in the default mode.

| Policy | Structured labels / latest | NL dev labels / latest | Held-out labels / latest |
| --- | --- | --- | --- |
| latest_explicit | 22 / 24 | 42 / 46 | 29 / 30 |
| memorygene (default, `confirm`) | 24 / 22 | 46 / 42 | 30 / 29 |
| memorygene_latest | 23 / 23 | 45 / 43 | 29 / 30 |

The new mode differs from the default only in the 5 unmarked-assertion cases. Unlike `latest_explicit`, it still keeps "X is also nice" from replacing a favourite. The earlier rows of this report were recomputed and are unchanged.
