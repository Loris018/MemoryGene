"""Score update policies on simulated timelines against the generator's gold.

Two input conditions:
  oracle      the labels a perfect extractor would give (from the generator);
  rule        the rule-based Chinese extractor (src/memorygene/extract.py),
              Chinese timelines only.

Each policy is scored against the `confirm` and the `latest` gold. Errors
are attributed to the event type at which the policy's current value first
departs from the gold.

Deterministic, no network. Usage:
  python experiments/simulator/evaluate.py [--n 400] [--seed 7] [--out DIR]
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import baselines_eval as b  # noqa: E402
import simulate  # noqa: E402

from memorygene import Candidate  # noqa: E402
from memorygene.core import Candidate as _C  # noqa: E402,F401
from memorygene.extract import extract  # noqa: E402

POLICIES = ("overwrite", "mem0_style", "graphiti_style", "latest_explicit",
            "memorygene", "memorygene_latest")
SUPPORTED_INTENTS = {"assert", "change", "correct", "supplement", "retract"}


def memorygene_supports_retract():
    try:
        Candidate("t", "u", "x", "v", "s", "2026-01-01T00:00:00Z", intent="retract").validate()
        return True
    except ValueError:
        return False


def oracle_candidates(timeline, mg_retract):
    out = []
    for e in timeline["events"]:
        o = e["oracle"]
        if o["decision"] != "write":
            out.append(None)
            continue
        if o["intent"] == "retract" and not mg_retract:
            out.append("retract-unsupported")
            continue
        out.append(Candidate("sim", "user", o["topic"], o["value"], e["text"], e["at"],
                             certainty=o["certainty"], intent=o["intent"]))
    return out


def rule_candidates(timeline):
    out = []
    for e in timeline["events"]:
        found = [x for x in extract(e["text"], namespace="sim", subject="user", at=e["at"])
                 if x.decision == "write"]
        out.append([x.candidate() for x in found] or None)
    return out


def stream_for(timeline, per_event, policy):
    """Flatten per-event candidates into a policy input stream."""
    cands, owners = [], []
    for i, item in enumerate(per_event):
        items = item if isinstance(item, list) else [item]
        for c in items:
            if c == "retract-unsupported":
                if policy in ("memorygene", "memorygene_latest"):
                    continue  # MemoryGene cannot express a retraction yet
                o = timeline["events"][i]["oracle"]
                c = Candidate("sim", "user", o["topic"], o["value"], timeline["events"][i]["text"],
                              timeline["events"][i]["at"], intent="retract")
            if c is not None:
                cands.append(c)
                owners.append(i)
    return {"dataset": "sim", "id": timeline["id"], "topic": timeline["topic"],
            "now": timeline["now"], "candidates": cands}, owners


def gold_steps(timeline, convention):
    state, steps = (None, []), []
    for e in timeline["events"]:
        state = simulate.gold_step(state, e, convention)
        steps.append(state[0])
    return steps


def score(timelines, per_event_fn, mg_retract):
    summary, causes = {}, {}
    for policy in POLICIES:
        s = {"timelines": len(timelines)}
        for convention in ("confirm", "latest"):
            s[f"{convention}_current"] = 0
            s[f"{convention}_history"] = 0
        cause = {}
        for t in timelines:
            stream, owners = stream_for(t, per_event_fn(t), policy)
            r = b.run(policy, stream)
            for convention in ("confirm", "latest"):
                g = t["gold"][convention]
                s[f"{convention}_current"] += r["current"] == g["current"]
                s[f"{convention}_history"] += r["history"] == g["history"]
            g = t["gold"]["confirm"]
            if r["current"] != g["current"]:
                # Replay to find the event at which the policy departs from gold.
                per_event_current = [None] * len(t["events"])
                last = None
                step_iter = iter(r["steps"])
                for i in range(len(t["events"])):
                    for _ in range(owners.count(i)):
                        last = next(step_iter)
                    per_event_current[i] = last
                gold = gold_steps(t, "confirm")
                first = next((i for i in range(len(gold)) if gold[i] != per_event_current[i]),
                             len(gold) - 1)
                kind = t["events"][first]["type"]
                cause[kind] = cause.get(kind, 0) + 1
        summary[policy] = s
        causes[policy] = dict(sorted(cause.items(), key=lambda kv: -kv[1]))
    return summary, causes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=400)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=HERE.parent / "results")
    args = parser.parse_args()
    timelines = simulate.generate(args.n, args.seed)
    mg_retract = memorygene_supports_retract()
    zh = [t for t in timelines if t["lang"] == "zh"]
    oracle = score(timelines, lambda t: oracle_candidates(t, mg_retract), mg_retract)
    rule = score(zh, rule_candidates, mg_retract)
    result = {
        "generator": {"n": args.n, "seed": args.seed, "memorygene_supports_retract": mg_retract},
        "oracle": {"summary": oracle[0], "error_causes_vs_confirm_gold": oracle[1]},
        "rule_extractor_zh": {"summary": rule[0], "error_causes_vs_confirm_gold": rule[1]},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "simulator.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
