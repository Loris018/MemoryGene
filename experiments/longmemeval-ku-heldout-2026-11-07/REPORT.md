# LongMemEval knowledge-update: held-out results (2026-11-07)

Pre-registration: [PREREGISTRATION.md](PREREGISTRATION.md), committed before any model call. Method and scoring are unchanged from [../longmemeval-ku-2026-11-02](../longmemeval-ku-2026-11-02/REPORT.md). Raw outputs: [raw/](raw/). Numbers: [results.json](results.json).

## Results

58 questions not used before: 47 current-value, 8 history and 3 abstention questions. All 58 model outputs parsed; 151 candidates were extracted and all of them quote the user verbatim.

| Policy | Current (47) | History (8) | Abstention (3) | Total (58) | Questions asked |
| --- | --- | --- | --- | --- | --- |
| overwrite | 44 | 3 | 2 | 49 | 0 |
| append_latest | 44 | 7 | 2 | 53 | 0 |
| mem0_style | 44 | 7 | 2 | **53** | 0 |
| graphiti_style | 44 | 7 | 2 | **53** | 0 |
| latest_explicit | 42 | 7 | 2 | 51 | 0 |
| memorygene (default) | 27 | 7 | 2 | 36 | 0 |
| memorygene_ask | 42 | 7 | 2 | 51 | 19 |
| memorygene_latest | 42 | 7 | 2 | 51 | 0 |

## Predictions

1. **`memorygene_latest` ≥ `latest_explicit`: held** (51 = 51).
2. **`memorygene` ≤ `memorygene_latest`: held** (36 vs 51). Without confirmation, the default mode lost 15 questions. Recovering them took 19 confirmation questions over 58 conversations.
3. **Shared errors come from extraction or scoring, not from the update policy: held.** Five questions were missed by every policy:
   - three yes/no questions ("Did I finish reading …?") whose stored values ("finished recently") are correct but cannot match "Yes" under the pre-registered string rule;
   - one borderline match ("above my bed" vs the reference "in my bedroom");
   - one abstention question where the extractor took "tennis" for "table tennis".

   These are scored as failures, as specified. Because they affect all policies equally, they do not change the ranking.

## Not predicted: the certainty filter cost two questions

The best policies on this set were the ones **without** a certainty filter (`mem0_style`, `graphiti_style`, `append_latest`: 53/58), two questions ahead of `memorygene_latest` and `latest_explicit` (51/58). In both differing questions, the user did update the value, but the extractor labelled the update as hedged or inferred: "close to 1300 followers" was labelled `uncertain`, and a new coin count was labelled `inferred`. The filter then kept the old value.

On the simulated timelines the same filter was the largest single source of advantage, because hesitations there are frequent and rarely true updates. LongMemEval's knowledge-update questions are built around real updates, and approximate wording there usually still means an update. **The value of the certainty filter therefore depends on the data:** it pays off when hedged statements are mostly not updates, and costs accuracy when they mostly are. No single policy was best on every dataset in this project.

## Conclusions

- On unseen real-style conversations, the `latest` mode matched the strongest baseline with a certainty filter (51/58) without asking the user anything, which confirms the earlier 20-question result.
- The default `confirm` mode is a poor fit for unattended use on update-heavy conversations: 36/58 without asking, or 51/58 at the cost of 19 questions.
- Policies without a certainty filter did slightly better here (53/58) but much worse on the simulated timelines with many hesitations. Which policy to deploy depends on how often users hedge without meaning a change.

## Limitations

- One extraction run with one model; question-conditioned extraction, as before.
- Automatic string matching cannot score yes/no answers; this affects all policies equally.
- 58 questions; a difference of two questions is small.
