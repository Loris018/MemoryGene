# Scenario simulator: generated timelines with gold by construction (2026-11-06)

Reproduce: `python experiments/simulator/evaluate.py` (development seed 7) and `python experiments/simulator/evaluate.py --seed 20261106` (check seed). Raw numbers: [../results/simulator.json](../results/simulator.json) and [../results/simulator_check_seed20261106.json](../results/simulator_check_seed20261106.json). Generator: [simulate.py](simulate.py).

## Why a simulator

Hand-written dialogue sets are small, slow to build, and labelled by the people who write the rules. The simulator samples a fictional user's timeline instead: a first statement followed by one to four events such as a marked change, an unmarked change, a correction, a hesitation, a supplement ("X is nice too"), a repetition, someone else's preference, a passing mention or a retraction. The correct memory state after every event follows from the event's meaning alone. MemoryGene's code is never used to compute the gold.

Each event is rendered from Chinese or English template banks. Values deliberately include items outside the rule-based extractor's vocabulary. Two gold conventions are kept for unmarked changes (`confirm` and `latest`); every other event type has a single gold outcome, and a retraction leaves no current value.

The development set has 400 timelines (seed 7) with 1,413 events. In 133 of them the two conventions differ.

## What the simulator exposed

The first run, with perfect labels, revealed two gaps that the hand-written sets had never exercised:

1. **Retraction could not be expressed.** MemoryGene had no way to record "I don't like roses any more"; all 32 of its errors on the development set came from retractions. A `retract` intent was added: an explicit retraction of the current value leaves the slot empty while keeping the history, and older evidence cannot undo it.
2. **A supplement could fill an empty slot.** After a retraction, "cycling is nice too" became the favourite sport. Supplements are now always kept as pending evidence. This costs one case in the hand-written NL set, where the rule-based extractor mislabels a first statement as a supplement; see [../NL_RESULTS.md](../NL_RESULTS.md).

| MemoryGene, perfect labels, development seed | `confirm` gold | `latest` gold |
| --- | --- | --- |
| before the fixes, default mode | 368 / 400 | — |
| before the fixes, `latest` mode | — | 378 / 400 |
| after the fixes, default mode | 400 / 400 | — |
| after the fixes, `latest` mode | — | 400 / 400 |

## Results on the check seed (20261106, generated after the fixes)

Correct final current value out of 400 timelines (perfect labels) or 200 Chinese timelines (rule-based extractor).

| Policy | Perfect labels, `confirm` | Perfect labels, `latest` | Rule extractor, `confirm` | Rule extractor, `latest` |
| --- | --- | --- | --- | --- |
| overwrite | 190 | 259 | 62 | 78 |
| mem0_style | 215 | 284 | 62 | 78 |
| graphiti_style | 215 | 284 | 62 | 78 |
| latest_explicit | 278 | 357 | 75 | 92 |
| memorygene | **400** | 308 | **97** | 84 |
| memorygene_latest | 308 | **400** | 78 | **99** |

Causes of error with perfect labels: the baselines fail on hesitations (about 77 cases for those without a certainty filter), on supplements (about 31) and on retractions (`overwrite` only). The other differences come from unmarked changes, which are counted against the `confirm` gold.

## How to read these numbers

- **The perfect-label rows are a consistency check, not a measure of intelligence.** After the two fixes, MemoryGene's rules agree with the generator's semantics on every event type the generator covers, so 400/400 is expected on any seed. The check seed confirms that the fixes generalise to new combinations of events, not that the semantics are right.
- **Extraction is the hard part.** The rule-based extractor gets roughly half of the Chinese timelines right whatever the policy. Most of its failures are first statements it cannot parse, because of unfamiliar values or phrasings. Its 57/57 topic accuracy on the hand-written set came from cases written alongside its rules.
- **Templates are easier than real speech.** Every utterance comes from a small template bank, so these results are an upper bound for template-like input. The natural next step is to have an LLM paraphrase each event, keeping the gold, and to measure an LLM extractor on the result.
- The event mix and the gold semantics were chosen by the project authors. The simulator removes the need to hand-label each case, but it does not remove the authors' choices.
