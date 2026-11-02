"""P2 evaluation: two-strand pairing vs byte protection vs exact containment.

M0-M2 implement the pre-registered design in experiments/STRANDS.md exactly.
M3 is a post-hoc rule added after seeing those results; it is exploratory.
Deterministic, no network. Usage: python experiments/strand_eval.py [--out DIR]
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from memorygene import Candidate, MemoryStore  # noqa: E402
from memorygene.strands import contained, pairing  # noqa: E402

NOW = "2026-11-02T00:00:00Z"
MODIFIERS = ("蓝色", "进口", "小号", "野生")
OPERATORS = ("substitute", "embellish", "merge", "negation_loss", "truncate")


def gold_pairs():
    pairs = []
    for case in json.loads((HERE / "nl_cases.json").read_text("utf-8")):
        for i, turn in enumerate(case["turns"]):
            label = turn.get("label", {})
            if label.get("should_write"):
                pairs.append({"id": f"{case['id']}#{i}", "value": label["value"],
                              "source": label.get("source") or turn["text"]})
    heldout = HERE / "heldout-2026-10-29"
    for case in json.loads((heldout / "cases.json").read_text("utf-8")):
        for i, turn in enumerate(case["turns"]):
            if turn["gold"]["decision"] == "write":
                pairs.append({"id": f"{case['id']}#{i}", "value": turn["gold"]["value"],
                              "source": turn["text"]})
    return pairs


def llm_pairs():
    pairs = []
    for path in sorted((HERE / "heldout-2026-10-29" / "raw").glob("batch-??-final.txt")):
        text = path.read_text("utf-8")
        for item in json.loads(text[text.find("["):text.rfind("]") + 1]):
            for turn in item.get("turns", []):
                if (turn.get("decision") == "write" and isinstance(turn.get("value"), str)
                        and isinstance(turn.get("source"), str)):
                    pairs.append({"id": f"{item['case_id']}#{turn['turn']}",
                                  "value": turn["value"], "source": turn["source"]})
    return pairs


def damage(pairs):
    out = []
    n = len(pairs)
    for i, p in enumerate(pairs):
        others = [pairs[(i + k) % n]["value"] for k in range(1, n)]
        other = next((o for o in others if o not in p["source"] and o != p["value"]), None)
        if other:
            out.append({**p, "op": "substitute", "value": other})
            out.append({**p, "op": "merge", "value": f"{p['value']}、{other}"})
        out.append({**p, "op": "embellish", "value": MODIFIERS[i % len(MODIFIERS)] + p["value"]})
        out.append({**p, "op": "negation_loss", "source": f"我不再喜欢{p['value']}了"})
        if len(p["value"]) >= 3:
            out.append({**p, "op": "truncate", "value": p["value"][:-1]})
    return out


def byte_protection_detects(rows):
    """Write each damaged value through the legitimate path, then verify()."""
    detected = 0
    with MemoryStore(":memory:", index="complement", protection="complement") as store:
        for i, row in enumerate(rows):
            store.ingest(Candidate("eval", "fictional-user", f"t.case{i}", row["value"],
                                   row["source"], "2026-10-01T00:00:00Z"), f"d{i}", now=NOW)
        report = store.verify()
        flagged = {p["event_id"] for p in report["problems"] if "event_id" in p}
        detected = sum(f"d{i}" in flagged for i in range(len(rows)))
    return detected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args()
    gold, llm = gold_pairs(), llm_pairs()
    damaged = damage(gold)
    detection = {}
    for op in OPERATORS:
        rows = [r for r in damaged if r["op"] == op]
        detection[op] = {
            "n": len(rows),
            "M0_byte_protection": byte_protection_detects(rows),
            "M1_containment": sum(not contained(r["value"], r["source"]) for r in rows),
            "M2_strand_pairing": sum(
                not pairing(r["value"], r["source"], mode="preregistered")["paired"] for r in rows),
            "M3_posthoc_strict": sum(
                not pairing(r["value"], r["source"], mode="strict")["paired"] for r in rows),
        }
    false_alarms = {}
    for name, rows in (("gold", gold), ("heldout_llm", llm)):
        m1 = [r for r in rows if not contained(r["value"], r["source"])]
        m2 = [r for r in rows if not pairing(r["value"], r["source"], mode="preregistered")["paired"]]
        m3 = [r for r in rows if not pairing(r["value"], r["source"], mode="strict")["paired"]]
        false_alarms[name] = {
            "n": len(rows),
            "M1_containment": len(m1), "M2_strand_pairing": len(m2),
            "M3_posthoc_strict": len(m3),
            "M1_examples": [{k: r[k] for k in ("id", "value", "source")} for r in m1[:10]],
            "M2_examples": [{k: r[k] for k in ("id", "value", "source")}
                            | {"pairing": pairing(r["value"], r["source"], mode="preregistered")}
                            for r in m2[:10]],
            "M3_examples": [{k: r[k] for k in ("id", "value", "source")} for r in m3[:10]],
        }
    result = {
        "now": NOW, "preregistration": "experiments/STRANDS.md",
        "detection": detection, "false_alarms": false_alarms,
        "note": "M0-M2 are pre-registered. M3 (containment + clause-scoped negation) was "
                "added after seeing M0-M2 results and is exploratory.",
        "limitations": [
            "Damage is synthetic (deterministic operators), not observed rewrite errors.",
            "Legitimate pairs are small, fictional and written by the same team; one LLM run.",
            "Lexical pairing: no paraphrase, number or date normalisation.",
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "strands.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"detection": detection,
                      "false_alarms": {k: {kk: vv for kk, vv in v.items() if "examples" not in kk}
                                       for k, v in false_alarms.items()}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
