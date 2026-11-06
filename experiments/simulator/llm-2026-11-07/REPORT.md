# LLM paraphrase and independent LLM extraction on simulated timelines (2026-11-07)

Reproduce the scoring from the cached outputs with `python experiments/simulator/llm-2026-11-07/run.py score`; the `paraphrase` and `extract` steps call the model and reuse [raw/](raw/) when present. Numbers: [results.json](results.json). The design, prompts ([paraphrase_prompt.md](paraphrase_prompt.md), [extract_prompt.md](extract_prompt.md)) and acceptance checks were committed before any model call.

## Setup

- **Sample:** 120 simulated timelines (seed 20261107, 60 Chinese and 60 English, 394 messages). This seed was not used during development or for the earlier check run.
- **Paraphrase:** DeepSeek Harness headless (`deepseek-flash`) rewrote every template message into casual speech, 40 per call (10 calls). A rewrite was accepted only if it kept the value verbatim and the event's meaning marker (no change words in an unmarked change, a hedge in a hesitation, a negation in a retraction, a person in a third-party remark). Otherwise the template text was kept.
- **Extraction:** separate calls labelled every message (write or skip, value, certainty, intent), 10 timelines per call, once on the template text and once on the paraphrased text (24 calls). The extractor saw the messages, dates and the attribute, but never the event types or the gold.
- **Scoring:** all policies processed the same extracted candidates; final current values were compared with the generator's gold.

## Results

Correct final current value out of 120 timelines. "Confirm" and "latest" are the two gold conventions for unmarked changes.

| Policy | Template, confirm | Template, latest | Paraphrased, confirm | Paraphrased, latest |
| --- | --- | --- | --- | --- |
| overwrite | 55 | 82 | 55 | 82 |
| mem0_style | 66 | 93 | 66 | 93 |
| graphiti_style | 66 | 93 | 66 | 93 |
| latest_explicit | 84 | 112 | 86 | 116 |
| memorygene | **110** | 99 | **104** | 97 |
| memorygene_latest | 90 | **119** | 87 | **118** |

For contrast, with the rule-based extractor on the 60 Chinese template timelines: MemoryGene 31/60 (confirm) and `memorygene_latest` 29/60 (latest).

Label accuracy of the LLM extractor (paraphrased text): write/skip decision 394/394; value 329/329 and intent 294/329 on messages that should be written; certainty 318/329.

## Findings

1. **With an LLM extractor, MemoryGene's `latest` mode was the most accurate policy**: 119/120 on template text and 118/120 on paraphrased text under the latest convention, against 112 and 116 for the strongest baseline. The baseline's remaining errors were mostly supplements ("X is also nice") replacing a favourite, as in the earlier comparisons.
2. **The LLM extractor turns many unmarked changes into marked ones.** Of 40 unmarked changes, it labelled 12 to 14 as `change` (and 2 as `correct` in the paraphrased run), presumably because it could see the earlier value in the same conversation. The default `confirm` mode therefore accepted those changes, which is wrong under the confirm convention. This accounts for most of its 10 to 16 errors. The conservative rule cannot hold if the extractor decides by itself that a statement is a change. This matches the instability of the intent label seen on LongMemEval.
3. **Paraphrasing barely affected the LLM extractor** (at most a few cases per policy), while the rule-based extractor gets only about half of the template timelines right. Extraction quality depends on the extractor, not on the template style.
4. **Third-party remarks and passing mentions were never written** (decision 394/394), so this part of selective memory was solved by the extractor on this data.
5. **The paraphraser tends to remove hedges.** 13 of the 15 rejected rewrites had dropped the uncertainty of a hesitation, for example by turning "maybe I like X more" into a plain preference. Without the acceptance check, hesitations would have become plain statements. An LLM that rewrites or summarises memories can erase exactly the information the certainty filter relies on.
6. In the paraphrased run, `memorygene_latest` made 2 errors on retractions.

## Limitations

- One sample, one model, one run per condition. Differences of a few timelines are within noise.
- The extractor was told which attribute each conversation concerns, so topic naming, the problem studied in [../../RECONSOLIDATION.md](../../RECONSOLIDATION.md), is not tested here.
- The timelines are short (2 to 5 messages) and still built from a fixed set of event types chosen by the project authors.
- The acceptance checks use fixed word lists and may accept a rewrite that subtly changes the meaning.
