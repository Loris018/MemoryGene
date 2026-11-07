# Pre-registration: memory stability under repeated consolidation (2026-11-07)

Written and committed before any model call for this experiment. Results will be reported in a separate REPORT.md without changing this file.

## Question

Many AI memory systems store only a condensed version of what the user said and periodically rewrite it. Does such rewriting make memories drift or lose information? Does keeping the user's original words (MemoryGene's evidence strand) prevent this, both when memories are rewritten and when they are read?

## Data

The LLM-paraphrased simulated timelines from [../simulator/llm-2026-11-07](../simulator/llm-2026-11-07) (accepted rewrites only). Timelines whose two gold conventions agree are kept, and the first 50 in id order are used. Each timeline concerns one attribute of the user. Its messages are the evidence strand, and the generator's gold gives the correct current value and history.

## Conditions (all calls: DeepSeek Harness headless, `deepseek-flash`, 10 timelines per call)

- **A, summary only:** round 1 turns the messages into a memory record (current value, certainty, history, notes). Rounds 2 and 3 rewrite the previous record without access to the messages.
- **B, proofread:** round 1 is shared with A. After rounds 2 and 3, each rewritten record is checked against the messages by fixed rules in [run.py](run.py) (`proofread`); changes that fail are reverted to the previous version. The rules are: a changed value must appear, not negated, in the user's words; a value the user only hesitated about cannot replace a stated value or be marked as certain; history values must appear in the user's words, and earlier history values are kept.
- **Readers, after round 3:** an independent call answers "what is the user's current value, and is the user sure?" from (i) A's record, (ii) B's record, (iii) A's record plus the original messages.

## Measures

For each record after each round: wrong current value; a hesitated or "also nice" value promoted to the current value; a current value not supported by the user's words; wrong certainty; earlier values lost from history. For readers: correct value, and correct value with correct sureness.

## Predictions

1. In A, errors do not decrease from round 1 to round 3 and may grow.
2. At round 3, B has no more errors than A on every measure.
3. The reader with the original messages is at least as accurate as the reader with A's record alone.

Results will be reported whether or not the predictions hold. With 50 timelines, differences of one or two are not meaningful.
