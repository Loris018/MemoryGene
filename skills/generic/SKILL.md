---
name: memorygene
description: Long-term memory for the user across conversations and projects. Use it to recall what the user told you before, and to store the user's own preferences, facts, changes and hesitations with their original words.
memorygene-installed: true
---

# MemoryGene

Memory is stored outside the model, in a local database. Every command prints JSON. `MG` below is:

```sh
"{{MG_ADAPTER}}"
```

Run `"$MG" doctor` once per session to check which database and identity are in use. Never pass `--allow-create` unless the user asks for a new memory store.

## Reading

- Before answering a question about the user, search: `"$MG" recall --query "<keywords>"`. Each match carries the user's original words in `source`; repeat their nuance (a "maybe" stays a "maybe"). Items under `unresolved` are not facts.
- For one topic: `"$MG" current --topic <topic>`. `current: null` means there is no current value; do not substitute an old one. `evidence.paired: false` means answer from `evidence.source`.
- Only mention memories when they are relevant.

## Writing

Store only the user's own, lasting information (preferences, profile facts, ongoing projects, recent situation):

```sh
"$MG" remember --topic preference.favorite_flower --value "rose" --source "I like roses best." \
  --certainty explicit --intent assert --importance 0.8
```

- `--source`: the user's exact words. `--value`: nothing the words do not say.
- `--certainty uncertain` for hedged statements; `inferred` for your own inference.
- `--intent change` only when the user says something changed; `correct` for a correction; `supplement` for "X is also nice"; `retract` (with the withdrawn value) for "I don't like X any more".
- Before inventing a new topic, run `"$MG" locate --topic <topic> --value <value> --source <words>` and reuse an existing topic for the same attribute.
- Do not store small talk, other people's preferences, or sensitive data without the user's explicit consent (`--sensitive --consent --consent-evidence "<their words>"`).

Low-importance remarks (importance below 0.5) are not stored; only an anonymous trace is kept for 30 days. If the same thing comes up on three different days, `advice` contains `recurring_low_importance`: ask the user once whether to remember it.

Read `result.status` before telling the user anything was saved: only `confirmed` changed the current value. Follow `advice` when present (for example `confirm_change`: ask once whether this is a change, then write again with `--intent change --resolves <evidence_id>`).

## Profile

Prefix topics by category: `profile.*` basic facts, `preference.*` likes, `recent.*` the user's recent situation (worries, mood, what they are busy with; expires after 30 days unless mentioned again), `life.*` personal experiences, `project.*` their projects. `"$MG" profile` lists the current profile with the user's words.

## Your impressions of the user

You may record a short impression (personality, habits, lasting interests) with `"$MG" impression-save --text "..." --cite <event_id>`, citing the current memories it rests on and nothing more. When the user asks what you think of them, show `"$MG" impressions` with the evidence; delete with `impression-forget` when asked. Do not use impressions marked `stale`.

## Forgetting and checking

- `"$MG" forget --topic <topic>` only when the user asks to forget it.
- `"$MG" review` when the user asks you to check their memory.
