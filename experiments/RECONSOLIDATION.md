# Reconsolidation support: slot recognition and advice (2026-11-02)

Reproduce: `python experiments/reconsolidation_eval.py` (no network, deterministic, under a second).
Raw rows: [results/reconsolidation.json](results/reconsolidation.json). Code: [src/memorygene/reconsolidate.py](../src/memorygene/reconsolidate.py).

## What was added

Before a statement is stored or a question answered, the agent can now see which existing memory it touches. This is the computational part we take from reconsolidation: a reactivated memory is the one that may be revised, so the system first has to find it.

- **`locate`** ranks existing slots that may hold the same attribute. Cues are topic-name tokens, Chinese bigrams / words of values and verbatim sources, weighted by how rare each term is among the user's own slots. A slot is **anchored** only when the attribute word of either topic (`flower` in `preference.liked_flower`) appears in the other, or the values share cues; sharing category words such as `preference` / `favorite` is not enough.
- **`open_evidence`** returns pending/conflict evidence that nothing later has settled (no `resolves` link, no later confirmed statement, not equal to the current value, not expired).
- **`advise`** returns at most a few suggestions after each write: `confirm_change`, `possible_same_slot`, `repeated_uncertain`. It never writes; the state machine stays the only path that changes memory.
- **`recall`** additionally lists matching unresolved evidence under `unresolved`, each marked `not_a_fact`.
- **`review`** lists unresolved evidence and possibly duplicated slots for an explicit "check my memory" request.

## A. Topic drift (exploratory)

The independent held-out extractor (deepseek-flash, run on 2026-10-29) often chose topic names different from the canonical ones. For each of its 27 write decisions we built a store with one slot per canonical topic taken from **other** dialogues (different value and wording, like an earlier session) and asked whether the model's topic attaches to the right slot.

| Method | Correct attach (of 23) | Wrong attach | Missed | New fact kept new (of 4) |
| --- | --- | --- | --- | --- |
| Exact topic string (previous behaviour) | 11 | 0 | 12 | 4 |
| Topic-name cues + anchoring | **20** | 0 | 3 | 4 |
| Topic + value + source cues + anchoring | **20** | 0 | 3 | 4 |

- All three remaining misses need world knowledge: `favorite_tea` / `favorite_coffee` should map to `favorite_drink`. Lexical cues cannot know that tea is a drink.
- **Value and source cues added nothing on this data** (same 20/23). They help only when the old slot holds the same or overlapping value (dev scenario "renamed drink topic via value" below). We report this as a neutral result.
- Caveat: the topic names in this set were visible while the anchoring rule was designed, and the set is small. This is not a held-out result; a fresh dialogue set is needed.

## B. Advice (development scenarios)

Fourteen hand-written fictional scenarios state when the agent should ask the user and when it should stay quiet.

| Measure | Result |
| --- | --- |
| Scenarios with the exact expected advice | 13 / 14 |
| Should advise, did | 5 / 5 |
| Should stay quiet, interrupted anyway | 1 / 9 |

The one unneeded interruption: "周五晚上去吃火锅" stored under `plan.dinner` was flagged as possibly the same slot as `preference.favorite_food = 火锅`, because the values are equal. Equal values are a strong lexical cue but not proof of the same attribute. The same authors wrote the rules and the scenarios, so this is a development check, not a benchmark.

## What this does and does not show

- It shows that a read-only recognition step can recover most cross-session topic drift without wrong merges on this small set, and can turn silent `conflict` / `pending` dead ends into one well-placed question.
- It does not show semantic understanding, does not prove the advice improves real conversations (no user study), and does not involve any DNA mechanism. Whether complementary "recognition strands" add anything beyond these lexical cues is the next, separate hypothesis (README roadmap item 2).
