# Memory stability under repeated consolidation: results (2026-11-07)

Pre-registration: [PREREGISTRATION.md](PREREGISTRATION.md), committed before any model call. Raw outputs: [raw/](raw/). Numbers: [results.json](results.json). All 40 model calls succeeded and every record and answer was parsed.

## Results

Errors among 50 memory records (A: summary only; B: proofread against the user's words):

| Round | Wrong current value | Hesitation or "also nice" promoted to current | Value not in user's words | Wrong certainty | History lost |
| --- | --- | --- | --- | --- | --- |
| A1 = B1 (first consolidation) | 6 | 6 | 0 | 1 | 2 |
| A2 | 6 | 6 | 0 | 1 | 2 |
| A3 | 6 | 6 | 0 | 1 | 2 |
| B2 | 6 | 6 | 0 | 1 | 2 |
| B3 | 6 | 6 | 0 | 1 | 2 |

Independent readers after round 3, out of 50:

| Reader input | Correct value | Correct value and sureness |
| --- | --- | --- |
| A's record | 44 | 43 |
| B's record | 44 | 43 |
| A's record plus the user's original messages | 44 | 43 |

## Predictions

1. *Errors in A do not decrease and may grow*: **held, but trivially.** They did not change at all.
2. *B has no more errors than A at round 3*: **held, but trivially.** Proofreading never had anything to revert.
3. *A reader with the original messages is at least as accurate*: **held, but trivially.** The extra messages did not change a single answer.

## What actually happened

- **No drift during rewriting.** In rounds 2 and 3 the model rephrased the free-text notes of 40 of the 50 records but never changed a current value, a certainty or a history entry. For structured records and two rewrites with this model, the hypothesis that memories drift when they are repeatedly reorganised was **not supported**. (Free-text rewriting is different: in [the paraphrase run](../simulator/llm-2026-11-07/REPORT.md) the same model dropped the hedge from 13 of 394 sentences.)
- **The damage happens at the first consolidation.** All six wrong records are the same error: the user stated a value and later only hesitated about another one ("豆浆好像更对我胃口，但我也拿不准"). The model made the hesitated value the current value, marked "uncertain", and pushed the stated value aside. This happened in 6 of the 15 timelines that contain a hesitation.
- **Keeping the original words did not help an LLM reader.** Given both the record and the user's messages, the reader still followed the record in all six cases. Evidence is only useful if something actually checks against it.

## Post-hoc comparison (not pre-registered)

The same 50 timelines were already labelled by an independent extractor in the earlier [LLM run](../simulator/llm-2026-11-07/REPORT.md). Feeding those labels through the update rules (no new model calls):

| Memory approach | Correct current value (50) | Timelines with a hesitation (15) |
| --- | --- | --- |
| LLM-written summary record (A3) | 44 | 9 |
| Graphiti-style update rule | 36 | 6 |
| **MemoryGene (default or `latest` mode)** | **48** | **15** |

MemoryGene keeps each statement as evidence and decides with explicit rules that a hesitation cannot replace a stated value. That is where its stability comes from in this experiment.

## Conclusions

1. On this data, a memory does not go wrong because it is rewritten. It goes wrong when it is first written, if a hesitation is allowed to overwrite a decision.
2. Storing the original words is not enough on its own. Rules have to use them: MemoryGene's state machine at write time and the pairing check. An LLM given the words as extra context does not reliably correct its own summary.
3. The proofreading rule was never triggered here. Its value remains untested and would need a setting where rewrites actually drift (free text, more rounds, or a weaker model).

## Limitations

- One model, one run, 50 short timelines, structured records and only two rewrite rounds.
- The post-hoc comparison reuses extraction outputs produced for a different experiment, and it was decided after seeing these results.
