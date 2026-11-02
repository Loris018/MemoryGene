"""Policy-level comparison of MemoryGene with re-implemented update policies.

The baselines re-implement the *update policies* of common memory designs from
their public descriptions. They are not the products themselves: no LLM is
called, and every policy receives exactly the same candidate fields
(value, time, certainty, intent, importance, sensitivity, expiry).

Policies
  overwrite          last write wins, no filtering
  append_latest      keep every write, the latest one is current
  mem0_style         ADD / UPDATE / NONE in arrival order; importance,
                     consent and expiry filters; no certainty filter
  graphiti_style     bitemporal: the fact with the latest valid time is
                     current, history kept; same filters, no certainty filter
  latest_explicit    graphiti_style plus a certainty filter: the latest
                     explicit statement wins whatever its intent
  memorygene         the MemoryGene state machine
  memorygene_ask     MemoryGene, and whenever it returns confirm_change the
                     simulated user confirms once (counted as a question)

There is no policy-neutral ground truth. The datasets' own labels encode
MemoryGene's conservative stance on unmarked updates, while the
LongMemEval "knowledge update" convention treats the latest explicit
statement as true; that convention is exactly latest_explicit. Both are
reported, together with where policies disagree and why.

Deterministic, no network. Usage: python experiments/baselines_eval.py [--out DIR]
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from memorygene import Candidate, MemoryStore  # noqa: E402
from memorygene.core import instant  # noqa: E402
from memorygene.reconsolidate import advise  # noqa: E402

IMPORTANCE = {"low": 0.3, "mid": 0.7, "high": 0.95}
POLICIES = ("overwrite", "append_latest", "mem0_style", "graphiti_style",
            "latest_explicit", "memorygene", "memorygene_ask")


def structured_streams():
    out = []
    for case in json.loads((HERE / "scenarios.json").read_text("utf-8")):
        out.append({
            "dataset": "structured", "id": case["id"], "topic": case["topic"],
            "now": "2026-10-24T10:00:00Z",
            "candidates": [Candidate(**t) for t in case["turns"]],
            "gold_current": case["expected_current"],
            "gold_history": case["expected_history"],
        })
    return out


def nl_streams():
    out = []
    for case in json.loads((HERE / "nl_cases.json").read_text("utf-8")):
        if case.get("session"):
            continue  # session-scoped cases are not comparable across policies
        cands = []
        for turn in case["turns"]:
            label = turn["label"]
            if not label["should_write"]:
                continue
            cands.append(Candidate(
                namespace="nl", subject="fictional-user", topic=label["topic"],
                value=label["value"], source=label["source"],
                at=case.get("at", "2026-10-01T00:00:00+00:00"),
                certainty=label["certainty"], intent=label["intent"],
                importance=IMPORTANCE[label["importance"]],
                expires_at=label.get("expires_at"),
                sensitive=bool(label.get("sensitive", False)),
                consent=bool(label.get("consent", False)),
            ))
        out.append({
            "dataset": "nl_dev", "id": case["id"], "topic": case["topic"],
            "now": "2026-10-24T10:00:00+00:00", "candidates": cands,
            "gold_current": case["expected_current"],
            "gold_history": case["expected_history"],
        })
    return out


def heldout_streams():
    out = []
    path = HERE / "heldout-2026-10-29" / "cases.json"
    for case in json.loads(path.read_text("utf-8")):
        cands = []
        for turn in case["turns"]:
            g = turn["gold"]
            if g["decision"] != "write":
                continue
            cands.append(Candidate(
                namespace="heldout", subject="fictional-user", topic=g["topic"],
                value=g["value"], source=turn["text"], at=g["at"],
                certainty=g["certainty"], intent=g["intent"],
                importance=IMPORTANCE[g["importance_band"]],
                expires_at=g["expires_at"], sensitive=g["sensitive"], consent=g["consent"],
            ))
        topic = cands[0].topic if cands else None
        out.append({
            "dataset": "heldout", "id": case["id"], "topic": topic,
            "now": "2026-10-29T12:00:00Z", "candidates": cands,
            "gold_current": case["expected_current"],
            "gold_history": case["expected_history"],
        })
    return out


def _passes_filters(c, now):
    if c.sensitive and not c.consent:
        return False
    if c.scope == "persistent" and c.importance < 0.5:
        return False
    return not (c.expires_at and instant(c.expires_at) <= instant(now))


def _live(c, now):
    return not (c.expires_at and instant(c.expires_at) <= instant(now))


def run_simple(policy, stream):
    """Return per-step current values plus final current and confirmed history."""
    now, topic = stream["now"], stream["topic"]
    accepted, steps = [], []  # accepted: (valid_time, arrival, value, candidate)
    for arrival, c in enumerate(stream["candidates"]):
        if c.topic == topic:
            if policy in ("overwrite", "append_latest"):
                accepted.append((arrival, arrival, c.value, c))
            elif _passes_filters(c, now) and (
                    policy != "latest_explicit" or c.certainty == "explicit"):
                key = arrival if policy == "mem0_style" else (instant(c.at), arrival)
                accepted.append((key, arrival, c.value, c))
        steps.append(_current(policy, accepted, now))
    current = steps[-1] if steps else None
    if policy == "overwrite":
        history = [current] if current is not None else []
    elif policy == "append_latest":
        history = [a[2] for a in accepted]
    else:
        ordered = sorted(accepted, key=lambda a: (a[0], a[1]))
        history = []
        for a in ordered:
            if _live(a[3], now) and (not history or history[-1] != a[2]):
                history.append(a[2])
    return {"steps": steps, "current": current, "history": history, "questions": 0}


def _current(policy, accepted, now):
    if not accepted:
        return None
    if policy in ("overwrite", "append_latest"):
        return accepted[-1][2]
    live = [a for a in accepted if _live(a[3], now)]
    if not live:
        return None
    return max(live, key=lambda a: (a[0], a[1]))[2]


def run_memorygene(stream, ask=False):
    now, topic = stream["now"], stream["topic"]
    steps, questions = [], 0
    with MemoryStore() as store:
        for i, c in enumerate(stream["candidates"]):
            result = store.ingest(c, f"e{i}", now=now)
            if ask and any(a["kind"] == "confirm_change"
                           for a in advise(store, c, result, now=now)):
                questions += 1
                confirmed = Candidate(**{**c.__dict__, "intent": "change"})
                store.ingest(confirmed, f"e{i}-confirmed", now=now, resolves=result["id"])
            head = store.current(c.namespace, c.subject, topic, now=now) if topic else None
            steps.append(head["candidate"]["value"] if head else None)
        if topic and stream["candidates"]:
            c0 = stream["candidates"][0]
            head = store.current(c0.namespace, c0.subject, topic, now=now)
            history = [e["candidate"]["value"]
                       for e in store.history(c0.namespace, c0.subject, topic, now=now)
                       if e["status"] == "confirmed"]
        else:
            head, history = None, []
    return {"steps": steps, "current": head["candidate"]["value"] if head else None,
            "history": history, "questions": questions}


def run(policy, stream):
    if policy == "memorygene":
        return run_memorygene(stream)
    if policy == "memorygene_ask":
        return run_memorygene(stream, ask=True)
    return run_simple(policy, stream)


def divergence_reason(stream, ours, theirs, now):
    """Classify the first step at which two policies' current values differ."""
    for i, (a, b) in enumerate(zip(ours, theirs)):
        if a != b:
            c = stream["candidates"][i]
            if c.topic != stream["topic"]:
                continue
            if c.sensitive and not c.consent:
                return "sensitive_without_consent"
            if c.importance < 0.5:
                return "low_importance"
            if c.expires_at and instant(c.expires_at) <= instant(now):
                return "expired"
            if c.certainty != "explicit":
                return "uncertain_or_inferred"
            if c.intent == "supplement":
                return "supplement"
            earlier = [p for p in stream["candidates"][:i] if p.topic == c.topic]
            if any(instant(c.at) < instant(p.at) for p in earlier):
                return "older_evidence_arriving_late"
            if c.intent == "assert":
                return "unmarked_new_assertion"
            return "other"
    return "expiry_at_read" if ours[-1:] != theirs[-1:] else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args()
    streams = structured_streams() + nl_streams() + heldout_streams()
    results = {p: {s["dataset"] + ":" + s["id"]: run(p, s) for s in streams} for p in POLICIES}
    summary = {}
    for dataset in ("structured", "nl_dev", "heldout"):
        ds = [s for s in streams if s["dataset"] == dataset]
        summary[dataset] = {"cases": len(ds)}
        for p in POLICIES:
            rows = [(s, results[p][dataset + ":" + s["id"]]) for s in ds]
            latest = [results["latest_explicit"][dataset + ":" + s["id"]] for s in ds]
            summary[dataset][p] = {
                "labels_current": sum(r["current"] == s["gold_current"] for s, r in rows),
                "labels_history": sum(r["history"] == s["gold_history"] for s, r in rows),
                "latest_convention_current": sum(
                    r["current"] == lt["current"] for (s, r), lt in zip(rows, latest)),
                "questions_asked": sum(r["questions"] for _, r in rows),
                "uncertain_became_current": sum(
                    any(c.certainty != "explicit" and c.topic == s["topic"]
                        and r["steps"][i] == c.value and c.value != s["gold_current"]
                        for i, c in enumerate(s["candidates"])) for s, r in rows),
            }
    disagreements = {}
    for p in POLICIES:
        if p == "memorygene":
            continue
        counts = {}
        for s in streams:
            key = s["dataset"] + ":" + s["id"]
            reason = divergence_reason(s, results["memorygene"][key]["steps"],
                                       results[p][key]["steps"], s["now"])
            if reason:
                counts[reason] = counts.get(reason, 0) + 1
        disagreements[p] = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    out = {
        "summary": summary, "disagreements_with_memorygene": disagreements,
        "notes": [
            "Baselines re-implement update policies from public descriptions; they are not the products.",
            "Dataset labels encode MemoryGene's conservative stance; the latest-explicit convention "
            "(LongMemEval knowledge update) is identical to the latest_explicit policy by construction.",
            "memorygene_ask simulates a user who always confirms an explicit newer statement.",
            "Session-scoped NL cases are excluded; held-out cases use the first written topic.",
        ],
        "cases": [
            {"dataset": s["dataset"], "id": s["id"], "gold_current": s["gold_current"],
             **{p: results[p][s["dataset"] + ":" + s["id"]]["current"] for p in POLICIES}}
            for s in streams
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "baselines.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "disagreements_with_memorygene": disagreements},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
