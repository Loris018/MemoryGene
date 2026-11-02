"""Evaluate reconsolidation support: slot recognition under topic drift, and advice.

Part A (topic drift) reuses the recorded outputs of the independent held-out
extractor (deepseek-flash, 2026-10-29). For every statement the model chose to
write, the store holds one slot per gold topic taken from *other* dialogues
(different values and wording, like an earlier session), and we ask whether
the statement's model-chosen topic can be attached to the right existing slot.
This is exploratory: the topic names in that set were seen while the anchoring
rule was designed, so it is not a clean held-out test.

Part B (advice) runs hand-written fictional scenarios that say when the agent
should ask the user and when it should stay quiet. Same authors wrote rules
and scenarios: a development check, not a benchmark.

No network, no randomness. Usage: python experiments/reconsolidation_eval.py [--out DIR]
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from memorygene import Candidate, MemoryStore  # noqa: E402
from memorygene.reconsolidate import advise, locate  # noqa: E402

HELDOUT = HERE / "heldout-2026-10-29"
NOW = "2026-11-02T00:00:00Z"
NS, SUBJ = "eval", "fictional-user"
METHODS = {
    "exact_topic": None,
    "topic_cues": ("t",),
    "topic_value_source_cues": ("t", "v", "s"),
}


def parse_json_array(text):
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end + 1])


def heldout_pairs():
    cases = {c["id"]: c for c in json.loads((HELDOUT / "cases.json").read_text("utf-8"))}
    model = {}
    for path in sorted((HELDOUT / "raw").glob("batch-??-final.txt")):
        for item in parse_json_array(path.read_text("utf-8")):
            model[item["case_id"]] = {t["turn"]: t for t in item.get("turns", [])}
    pairs = []
    for case_id, case in cases.items():
        for i, turn in enumerate(case["turns"]):
            gold, out = turn["gold"], model.get(case_id, {}).get(i)
            if gold["decision"] != "write" or not out or out.get("decision") != "write":
                continue
            if not all(isinstance(out.get(k), str) and out[k].strip()
                       for k in ("topic", "value", "source")):
                continue
            pairs.append({"case": case_id, "turn": i, "gold": gold, "text": turn["text"],
                          "model": out})
    return pairs


def drift_eval(pairs):
    # One representative slot per gold topic, from the first dialogue using it.
    reps = {}
    for p in pairs:
        reps.setdefault(p["gold"]["topic"], []).append(p)
    rows = []
    for p in pairs:
        store = MemoryStore()
        n = 0
        for topic, uses in sorted(reps.items()):
            other = next((u for u in uses if u["case"] != p["case"]), None)
            if other is None:
                continue
            n += 1
            store.ingest(Candidate(NS, SUBJ, topic, other["gold"]["value"], other["text"],
                                   "2026-09-01T00:00:00Z"), f"slot{n}", now=NOW)
        existing = {s["topic"] for s in store.topics(NS, SUBJ, now=NOW)}
        expected = p["gold"]["topic"] if p["gold"]["topic"] in existing else None
        m = p["model"]
        row = {"case": p["case"], "turn": p["turn"], "model_topic": m["topic"],
               "expected": expected, "slots": len(existing)}
        for name, use in METHODS.items():
            if use is None:
                predicted = m["topic"] if m["topic"] in existing else None
            else:
                ranked = locate(store, NS, SUBJ, m["topic"], m["value"], m["source"],
                                now=NOW, use=use)
                top = next((r for r in ranked if r["same_topic"] or r["anchored"]), None)
                predicted = top["topic"] if top else None
            row[name] = predicted
        rows.append(row)
        store.close()
    summary = {}
    for name in METHODS:
        s = {"attach_correct": 0, "attach_wrong": 0, "missed": 0,
             "new_correct": 0, "new_but_attached": 0}
        for r in rows:
            got = r[name]
            if r["expected"] is None:
                s["new_correct" if got is None else "new_but_attached"] += 1
            elif got == r["expected"]:
                s["attach_correct"] += 1
            elif got is None:
                s["missed"] += 1
            else:
                s["attach_wrong"] += 1
        s["should_attach"] = sum(1 for r in rows if r["expected"])
        s["should_be_new"] = sum(1 for r in rows if not r["expected"])
        summary[name] = s
    return {"rows": rows, "summary": summary}


# Each scenario: prior statements, then one probe; `expect` lists advice kinds.
SCENARIOS = [
    ("explicit change without change marker", [
        ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01", {}),
    ], ("preference.favorite_flower", "百合", "我最喜欢百合", "2026-10-10", {}), ["confirm_change"]),
    ("stated change is applied silently", [
        ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01", {}),
    ], ("preference.favorite_flower", "百合", "现在最喜欢百合了", "2026-10-10",
        {"intent": "change"}), []),
    ("older evidence arriving late", [
        ("profile.city", "上海", "我住在上海", "2026-10-10", {}),
    ], ("profile.city", "北京", "我住在北京", "2026-10-01", {}), []),
    ("single hesitation stays quiet", [
        ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01", {}),
    ], ("preference.favorite_flower", "百合", "可能也喜欢百合", "2026-10-05",
        {"certainty": "uncertain"}), []),
    ("repeated hesitation", [
        ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01", {}),
        ("preference.favorite_flower", "百合", "可能更喜欢百合", "2026-10-05",
         {"certainty": "uncertain"}),
    ], ("preference.favorite_flower", "百合", "好像真的更喜欢百合", "2026-10-09",
        {"certainty": "uncertain"}), ["repeated_uncertain"]),
    ("repeat of same value", [
        ("preference.favorite_drink", "乌龙茶", "我最爱乌龙茶", "2026-10-01", {}),
    ], ("preference.favorite_drink", "乌龙茶", "还是乌龙茶最好", "2026-10-09", {}), []),
    ("renamed flower topic", [
        ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01", {}),
        ("preference.favorite_color", "蓝色", "我最喜欢蓝色", "2026-10-01", {}),
    ], ("preference.liked_flower", "栀子花", "我喜欢的花是栀子花", "2026-10-09", {}),
        ["possible_same_slot"]),
    ("renamed city topic", [
        ("profile.city", "上海", "我住在上海", "2026-10-01", {}),
        ("profile.job", "老师", "我是老师", "2026-10-01", {}),
    ], ("personal.residence.city", "杭州", "我搬到杭州了", "2026-10-09", {}),
        ["possible_same_slot"]),
    ("renamed drink topic via value", [
        ("preference.favorite_drink", "乌龙茶", "我最爱喝乌龙茶", "2026-10-01", {}),
    ], ("preference.favorite_tea", "乌龙", "我最爱喝乌龙", "2026-10-09", {}),
        ["possible_same_slot"]),
    ("new favorite of a different kind", [
        ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01", {}),
        ("preference.favorite_color", "蓝色", "我最喜欢蓝色", "2026-10-01", {}),
    ], ("preference.favorite_movie", "星际穿越", "我最喜欢的电影是星际穿越", "2026-10-09", {}), []),
    ("unrelated new profile fact", [
        ("profile.birthday", "3月5日", "我生日是3月5日", "2026-10-01", {}),
    ], ("profile.job", "工程师", "我是工程师", "2026-10-09", {}), []),
    ("first ever statement", [], (
        "preference.favorite_food", "火锅", "我最喜欢吃火锅", "2026-10-09", {}), []),
    ("low importance chatter", [
        ("preference.favorite_food", "火锅", "我最喜欢吃火锅", "2026-10-01", {}),
    ], ("chat.lunch", "火锅", "今天中午吃了火锅", "2026-10-09", {"importance": 0.2}), []),
    ("same value under a plan topic", [
        ("preference.favorite_food", "火锅", "我最喜欢吃火锅", "2026-10-01", {}),
    ], ("plan.dinner", "火锅", "周五晚上去吃火锅", "2026-10-09", {}), []),
]


def advice_eval():
    rows = []
    for name, prior, probe, expect in SCENARIOS:
        store = MemoryStore()
        for i, (t, v, s, d, kw) in enumerate(prior):
            store.ingest(Candidate(NS, SUBJ, t, v, s, f"{d}T00:00:00Z", **kw), f"p{i}", now=NOW)
        t, v, s, d, kw = probe
        c = Candidate(NS, SUBJ, t, v, s, f"{d}T00:00:00Z", **kw)
        result = store.ingest(c, "probe", now=NOW)
        got = [a["kind"] for a in advise(store, c, result, now=NOW)]
        rows.append({"scenario": name, "status": result["status"], "expected": expect,
                     "advice": got, "ok": got == expect})
        store.close()
    should = [r for r in rows if r["expected"]]
    quiet = [r for r in rows if not r["expected"]]
    return {
        "rows": rows,
        "summary": {
            "scenarios": len(rows),
            "exact_match": sum(r["ok"] for r in rows),
            "should_advise": len(should),
            "advised_correctly": sum(r["ok"] for r in should),
            "should_stay_quiet": len(quiet),
            "unneeded_interruptions": sum(bool(r["advice"]) for r in quiet),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result = {
        "now": NOW,
        "drift": drift_eval(heldout_pairs()),
        "advice": advice_eval(),
        "limitations": [
            "Part A topic names were seen while designing the anchoring rule; exploratory only.",
            "Part B scenarios were written by the same authors as the rules; development check.",
            "Lexical cues only: no synonyms, no embeddings; one extractor run.",
        ],
    }
    (args.out / "reconsolidation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"drift": result["drift"]["summary"],
                      "advice": result["advice"]["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
