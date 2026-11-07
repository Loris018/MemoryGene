"""Stability of memory under repeated consolidation, with and without the evidence strand.

Pre-registered before any model call (see PREREGISTRATION.md).

Data: the LLM-paraphrased simulated timelines of experiments/simulator/llm-2026-11-07
(accepted rewrites only), keeping timelines whose `confirm` and `latest` gold agree,
first 50 in id order. The user's messages form the evidence strand.

Conditions:
  A  summary only   round 1 turns the messages into a memory record; rounds 2 and 3
                    rewrite the previous record without access to the messages.
  B  proofread      round 1 is A's round 1; after each later rewrite, the record is
                    checked against the messages and failing changes are reverted.
  Readers (after round 3): an independent call answers "current value, and is the
  user sure?" from (i) A's record, (ii) B's record, (iii) A's record plus the messages.

Usage: python experiments/stability-2026-11-07/run.py consolidate|read|score
"""

import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLM_RUN = HERE.parent / "simulator" / "llm-2026-11-07" / "run.py"
SPEC = importlib.util.spec_from_file_location("sim_llm_run", LLM_RUN)
llm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(llm)

from memorygene.strands import pairing  # noqa: E402

RAW = HERE / "raw"
N, BATCH, ROUNDS = 50, 10, 3
READERS = ("summary_A", "summary_B", "summary_A_plus_source")


def timelines():
    para, _ = llm.paraphrased_timelines()
    agree = [t for t in para if t["gold"]["confirm"] == t["gold"]["latest"]]
    return agree[:N]


def norm(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip().casefold()
    return None if text in ("", "none", "null", "n/a") else text


def same(value, gold):
    v, g = norm(value), norm(gold)
    if g is None or v is None:
        return v is None and g is None
    return g in v or v in g


def supported(value, messages, allow_hedged):
    """Is `value` stated (not negated) in some message, and not only in hedged ones?"""
    support = [m for m in messages if pairing(str(value), m)["paired"]]
    if not support:
        return False
    return allow_hedged or any(not llm.HEDGE_WORDS.search(m) for m in support)


def proofread(new, previous, messages):
    """Accept a rewritten record only where it still pairs with the evidence strand."""
    out = dict(new)
    if norm(new.get("current_value")) != norm(previous.get("current_value")):
        value = new.get("current_value")
        ok = value is None and previous.get("current_value") is None
        if value is not None:
            # A value the user only hesitated about may not replace a stated one.
            hedge_ok = (new.get("certainty") == "uncertain"
                        and previous.get("certainty") != "explicit")
            ok = supported(value, messages, hedge_ok)
        if not ok:
            out["current_value"] = previous.get("current_value")
            out["certainty"] = previous.get("certainty")
    if (previous.get("certainty") == "uncertain" and out.get("certainty") == "explicit"
            and out.get("current_value") is not None
            and not supported(out["current_value"], messages, allow_hedged=False)):
        out["certainty"] = "uncertain"
    kept = [v for v in previous.get("history") or [] if supported(v, messages, True)]
    for v in new.get("history") or []:
        if supported(v, messages, True) and not any(same(v, k) for k in kept):
            kept.append(v)
    out["history"] = kept
    return out


def messages_of(t):
    return [e["text"] for e in t["events"]]


def records(path):
    rows = llm.json_array(json.loads(path.read_text("utf-8"))["final"])
    return {r.get("conversation"): r for r in rows if isinstance(r, dict)}


def batches(data):
    return [data[k:k + BATCH] for k in range(0, len(data), BATCH)]


def round_records(chain, rnd):
    out = {}
    for path in sorted(RAW.glob(f"{chain}-r{rnd}-*.json")):
        out.update(records(path))
    return out


def consolidate():
    RAW.mkdir(exist_ok=True)
    data = timelines()
    first = (HERE / "consolidate_first_prompt.md").read_text("utf-8")
    nxt = (HERE / "consolidate_next_prompt.md").read_text("utf-8")
    for i, batch in enumerate(batches(data)):
        llm.call(first.replace("{{CONVERSATIONS}}", llm.conversations_block(batch)),
                 RAW / f"A-r1-{i}.json")
    for chain in ("A", "B"):
        for rnd in range(2, ROUNDS + 1):
            prev = chain_state(chain, rnd - 1, data)
            for i, batch in enumerate(batches(data)):
                items = [{**prev[t["id"]], "conversation": t["id"],
                          "attribute": llm.ATTRIBUTE_NAMES[t["topic"]]} for t in batch]
                llm.call(nxt.replace("{{RECORDS}}", json.dumps(items, ensure_ascii=False, indent=1)),
                         RAW / f"{chain}-r{rnd}-{i}.json")


def chain_state(chain, rnd, data):
    """Records of a chain after round `rnd` (B applies proofreading after round 1)."""
    empty = {"current_value": None, "certainty": None, "history": [], "notes": ""}
    base = round_records("A", 1)
    state = {t["id"]: base.get(t["id"], empty) for t in data}
    for r in range(2, rnd + 1):
        new = round_records(chain, r)
        for t in data:
            rewritten = new.get(t["id"], state[t["id"]])
            state[t["id"]] = (proofread(rewritten, state[t["id"]], messages_of(t))
                              if chain == "B" else rewritten)
    return state


def read():
    data = timelines()
    template = (HERE / "reader_prompt.md").read_text("utf-8")
    a, b = chain_state("A", ROUNDS, data), chain_state("B", ROUNDS, data)
    for reader in READERS:
        for i, batch in enumerate(batches(data)):
            items = []
            for t in batch:
                record = a[t["id"]] if reader != "summary_B" else b[t["id"]]
                item = {"conversation": t["id"], "attribute": llm.ATTRIBUTE_NAMES[t["topic"]],
                        "memory_record": {k: record.get(k) for k in
                                          ("current_value", "certainty", "history", "notes")}}
                if reader == "summary_A_plus_source":
                    item["user_messages"] = [f"[{e['at'][:10]}] {e['text']}" for e in t["events"]]
                items.append(item)
            llm.call(template.replace("{{ITEMS}}", json.dumps(items, ensure_ascii=False, indent=1)),
                     RAW / f"read-{reader}-{i}.json")


def errors(record, t):
    gold = t["gold"]["confirm"]["current"]
    traps = {e["value"] for e in t["events"] if e["type"] in ("hesitate", "supplement")} - {gold}
    value = record.get("current_value")
    msgs = messages_of(t)
    return {
        "value_wrong": not same(value, gold),
        "hedge_or_supplement_promoted": norm(value) is not None and any(same(value, x) for x in traps),
        "unsupported_value": norm(value) is not None and not supported(value, msgs, True),
        "certainty_wrong": same(value, gold) and gold is not None and record.get("certainty") != "explicit",
        "history_lost": any(not any(same(h, g) for h in (record.get("history") or []) + [value])
                            for g in t["gold"]["confirm"]["history"]),
    }


def score():
    data = timelines()
    rounds = {}
    for chain in ("A", "B"):
        for rnd in range(1, ROUNDS + 1):
            state = chain_state(chain, rnd, data)
            totals = {}
            for t in data:
                for k, v in errors(state[t["id"]], t).items():
                    totals[k] = totals.get(k, 0) + bool(v)
            rounds[f"{chain}{rnd}"] = totals
    readers = {}
    for reader in READERS:
        answers = {}
        for path in sorted(RAW.glob(f"read-{reader}-*.json")):
            answers.update(records(path))
        value_ok = sure_ok = 0
        for t in data:
            gold = t["gold"]["confirm"]["current"]
            ans = answers.get(t["id"], {})
            value_ok += same(ans.get("value"), gold)
            sure_ok += same(ans.get("value"), gold) and bool(ans.get("sure")) == (gold is not None)
        readers[reader] = {"value_correct": value_ok, "value_and_sureness_correct": sure_ok}
    result = {"timelines": len(data), "rounds": rounds, "readers": readers}
    (HERE / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["consolidate", "read", "score"])
    {"consolidate": consolidate, "read": read, "score": score}[parser.parse_args().step]()


if __name__ == "__main__":
    main()
