# LongMemEval knowledge-update: small-sample test (2026-11-02)

First test of MemoryGene on an external benchmark. The sample is small (20 questions), so the results indicate behaviour rather than establish performance.

## Setup

- **Data:** LongMemEval (Wu et al., *LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory*, ICLR 2025), MIT licence, `longmemeval_oracle.json` from the `longmemeval-cleaned` release (sha256 `821a2034d219ab45…`, identical to the original oracle file). The dataset is not redistributed here.
- **Sample:** the first 20 questions of type `knowledge-update` in `question_id` order, oracle sessions only, user turns only. The sample was fixed before any model call.
- **Extraction:** one DeepSeek Harness headless call per question (`deepseek-flash`, CLI 0.2.1-rc.5) with [prompt.md](prompt.md). The model lists the user's statements relevant to the question (verbatim source, value, certainty, intent) and does not answer. Raw outputs are in [raw/](raw/).
- **Policies:** the seven update policies from [../BASELINES.md](../BASELINES.md), all applied to the same extracted candidates.
- **Scoring** (committed before any model call; see the docstring of [run.py](run.py)):
  - current-value questions: the final current value must match the answer;
  - history questions ("initially", "first", …): the answer must appear in the confirmed history;
  - abstention questions (`_abs`): nothing may be remembered.

  A match means one normalised string contains the other, or the value's numbers all appear in the answer.
- **One harness fix after the first scoring attempt:** item `2133c1b5` has a session timestamped five hours after its question, which MemoryGene rejects as future evidence. The evaluation clock was changed to the later of the question time and the last session time, for all policies. This fix was committed separately; scoring rules were not changed.

## Results

| Policy | Current (13) | History (4) | Abstention (3) | Total (20) | Questions asked |
| --- | --- | --- | --- | --- | --- |
| overwrite | 11 | 2 | 1 | 14 | 0 |
| append_latest | 11 | 4 | 1 | 16 | 0 |
| mem0_style | 11 | 4 | 1 | 16 | 0 |
| graphiti_style | 11 | 4 | 1 | 16 | 0 |
| latest_explicit | 11 | 4 | 1 | 16 | 0 |
| memorygene | 9 | 4 | 1 | **14** | 0 |
| memorygene_ask | 11 | 4 | 1 | **16** | 2 |

Extraction: all 20 outputs parsed; 44 candidates were kept and 2 were dropped as invalid; all 44 sources are verbatim substrings of the user's messages.

## Item-level review

- **MemoryGene without confirmation lost 2 questions** (`2133c1b5`, `22d2cb42`). In both, the user did update the information, but the extractor labelled the new statement as a plain assertion rather than a change. MemoryGene held the new value as `conflict` and kept the old one; after one confirmation question it answered both correctly.
- **The intent label is unstable.** The same two Harajuku statements were labelled `assert` in `2133c1b5` and `change` in its abstention variant. MemoryGene's conservative update rule depends on exactly this label.
- **Keeping history matters.** `overwrite` failed two of the four history questions because the earlier value was gone; every policy that keeps history answered all four.
- **Four failures are shared by every policy and come from extraction:** in two abstention questions the extractor matched a similar but different fact (a different job title, a different neighbourhood); in two current-value questions it missed the later update.
- **One borderline item:** in `22d2cb42`, "Rhythm Central on Main St" may be the same shop as the reference answer "the music shop on Main St". It is scored by the pre-specified automatic rule (no match).

## Conclusions

1. On real conversational data, MemoryGene's conservative rule has a **measurable cost when no one is asked**: 14/20 against 16/20 for the latest-explicit and Graphiti-style policies.
2. With a single confirmation per detected change (`confirm_change`), MemoryGene **matches the best baselines** (16/20) at a cost of 2 questions in 20 conversations.
3. In unattended settings where no user can confirm, the latest-explicit policy is the better default. MemoryGene's rule only pays off when the agent actually asks. This should guide how the system is deployed.
4. Most remaining errors come from extraction (missed updates, matching the wrong entity), not from the update policy.

## Limitations

- 20 questions, one extraction run, one model; differences of one or two questions are within noise.
- Question-conditioned extraction: the extractor sees the question, which is easier than real use and weakens the abstention test.
- Automatic string matching; one borderline item noted above.
- Policies are re-implementations of update rules, not the Mem0 or Graphiti products.

## Reproduce

```sh
python experiments/longmemeval-ku-2026-11-02/run.py extract --data /path/to/longmemeval_oracle.json   # calls the model; cached in raw/
python experiments/longmemeval-ku-2026-11-02/run.py score --data /path/to/longmemeval_oracle.json
```
