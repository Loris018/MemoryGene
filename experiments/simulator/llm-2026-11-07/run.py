"""LLM paraphrase + independent LLM extraction on simulated timelines.

Design (fixed before any model call):
  * Sample: simulate.generate(120, seed=20261107), alternating zh/en. This seed
    was not used during development (7) or for the check run (20261106).
  * Step `paraphrase`: DeepSeek Harness headless (deepseek-flash) rewrites each
    utterance with paraphrase_prompt.md, 40 utterances per call. A rewrite is
    accepted only if it passes the CHECKS below; otherwise the template text
    is kept and the fallback is counted. The gold never changes.
  * Step `extract`: separate calls with extract_prompt.md, 10 timelines per
    call, once on the template text and once on the accepted paraphrases. The
    extractor sees the messages, dates and attribute, never the event types.
  * Step `score`: every policy in experiments/simulator/evaluate.py processes
    the extracted candidates; final current values are compared with the
    generator's `confirm` and `latest` gold. Label accuracy (decision, intent,
    certainty) is compared with the oracle labels.

Usage:
  python experiments/simulator/llm-2026-11-07/run.py paraphrase|extract|score
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path[:0] = [str(PROJECT / "src"), str(PROJECT / "experiments"), str(HERE.parent)]

import baselines_eval as b  # noqa: E402
import simulate  # noqa: E402

from memorygene import Candidate  # noqa: E402

RAW = HERE / "raw"
DSH = Path("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh")
PATCH = PROJECT / "tools" / "dsh" / "headless-account.patch.yml"
N, SEED = 120, 20261107
PARAPHRASE_BATCH, EXTRACT_BATCH = 40, 10
POLICIES = ("overwrite", "mem0_style", "graphiti_style", "latest_explicit",
            "memorygene", "memorygene_latest")
ATTRIBUTE_NAMES = {
    "preference.favorite_flower": "the user's favourite flower",
    "preference.favorite_drink": "the user's favourite drink",
    "preference.favorite_food": "the user's favourite food",
    "preference.favorite_color": "the user's favourite colour",
    "preference.favorite_sport": "the user's favourite sport",
    "profile.city": "the city the user lives in",
}
CHANGE_WORDS = re.compile(r"现在|如今|改|换|搬|最近|变|now|these days|chang|switch|mov|any ?more|lately|no longer", re.I)
HEDGE_WORDS = re.compile(r"可能|好像|也许|大概|说不定|不确定|不太确定|或许|maybe|might|perhaps|not sure|i think|probably|guess", re.I)
NEGATION_WORDS = re.compile(r"不再|不喜欢|没那么|不住|不爱|已经不|not|no longer|any ?more|n't", re.I)
THIRD_PARTY_WORDS = re.compile(r"妈|爸|朋友|室友|哥|姐|弟|妹|同事|mum|mom|dad|friend|brother|sister|roommate|colleague", re.I)


def check(event, text):
    """Return None if the rewrite keeps the event's meaning markers, else a reason."""
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if event["value"].lower() not in text.lower():
        return "value_missing"
    kind = event["type"]
    if kind == "change_unmarked" and CHANGE_WORDS.search(text):
        return "change_word_in_unmarked"
    if kind == "hesitate" and not HEDGE_WORDS.search(text):
        return "hedge_missing"
    if kind == "retract" and not NEGATION_WORDS.search(text):
        return "negation_missing"
    if kind == "third_party" and not THIRD_PARTY_WORDS.search(text):
        return "person_missing"
    return None


def timelines():
    return simulate.generate(N, SEED)


def call(prompt, out_path):
    if out_path.is_file():
        return json.loads(out_path.read_text("utf-8"))
    started = datetime.now(timezone.utc)
    result = subprocess.run([str(DSH), "--profile", "headless", "--patch", str(PATCH), "--json", prompt],
                            capture_output=True, text=True, timeout=600, cwd=str(HERE))
    final = ""
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "final":
            final = event.get("text", "")
    record = {"exit": result.returncode, "final": final,
              "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1)}
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out_path.name}: exit={record['exit']} {record['seconds']}s", flush=True)
    return record


def json_array(text):
    start, end = text.find("["), text.rfind("]")
    try:
        rows = json.loads(text[start:end + 1]) if 0 <= start < end else None
    except json.JSONDecodeError:
        rows = None
    return rows if isinstance(rows, list) else []


def paraphrase():
    RAW.mkdir(exist_ok=True)
    items = [{"id": f"{t['id']}#{i}", "language": t["lang"], "meaning": e["type"],
              "value": e["value"], "text": e["text"]}
             for t in timelines() for i, e in enumerate(t["events"])]
    template = (HERE / "paraphrase_prompt.md").read_text("utf-8")
    for k in range(0, len(items), PARAPHRASE_BATCH):
        batch = items[k:k + PARAPHRASE_BATCH]
        call(template.replace("{{ITEMS}}", json.dumps(batch, ensure_ascii=False, indent=1)),
             RAW / f"paraphrase-{k // PARAPHRASE_BATCH:02d}.json")


def paraphrased_timelines():
    rewrites = {}
    for path in sorted(RAW.glob("paraphrase-*.json")):
        for row in json_array(json.loads(path.read_text("utf-8"))["final"]):
            if isinstance(row, dict) and "id" in row:
                rewrites[row["id"]] = row.get("text")
    out, fallbacks = [], {}
    for t in timelines():
        t = json.loads(json.dumps(t))
        for i, e in enumerate(t["events"]):
            text = rewrites.get(f"{t['id']}#{i}")
            reason = check(e, text) if text is not None else "not_returned"
            if reason:
                fallbacks[reason] = fallbacks.get(reason, 0) + 1
            else:
                e["text"] = text.strip()
        out.append(t)
    return out, fallbacks


def conversations_block(batch):
    blocks = []
    for t in batch:
        lines = [f"Conversation {t['id']} (attribute: {ATTRIBUTE_NAMES[t['topic']]}):"]
        for i, e in enumerate(t["events"], 1):
            lines.append(f"  {i}. [{e['at'][:10]}] {e['text']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def extract():
    RAW.mkdir(exist_ok=True)
    template = (HERE / "extract_prompt.md").read_text("utf-8")
    para, _ = paraphrased_timelines()
    for label, data in (("template", timelines()), ("paraphrased", para)):
        for k in range(0, len(data), EXTRACT_BATCH):
            batch = data[k:k + EXTRACT_BATCH]
            call(template.replace("{{CONVERSATIONS}}", conversations_block(batch)),
                 RAW / f"extract-{label}-{k // EXTRACT_BATCH:02d}.json")


def extracted(label, data):
    rows = {}
    for path in sorted(RAW.glob(f"extract-{label}-*.json")):
        for row in json_array(json.loads(path.read_text("utf-8"))["final"]):
            try:
                rows[(row["conversation"], int(row["message"]))] = row
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def score_condition(label, data):
    rows = extracted(label, data)
    labels = {"messages": 0, "returned": 0, "decision": 0, "intent": 0, "certainty": 0,
              "value": 0, "invalid": 0}
    by_policy = {p: {"confirm": 0, "latest": 0} for p in POLICIES}
    intent_confusion = {}
    for t in data:
        cands = []
        for i, e in enumerate(t["events"]):
            labels["messages"] += 1
            row = rows.get((t["id"], i + 1))
            oracle = e["oracle"]
            if row is None:
                continue
            labels["returned"] += 1
            decision = row.get("decision")
            labels["decision"] += decision == oracle["decision"]
            if decision == "write" and oracle["decision"] == "write":
                labels["intent"] += row.get("intent") == oracle["intent"]
                labels["certainty"] += row.get("certainty") == oracle["certainty"]
                labels["value"] += str(row.get("value", "")).strip().lower() == e["value"].lower()
                key = f"{oracle['intent']}->{row.get('intent')}"
                intent_confusion[key] = intent_confusion.get(key, 0) + 1
            if decision != "write":
                continue
            try:
                c = Candidate("sim", "user", t["topic"], str(row["value"]).strip(),
                              str(row.get("source") or e["text"]).strip(), e["at"],
                              certainty=row.get("certainty"), intent=row.get("intent"))
                c.validate()
            except (KeyError, TypeError, ValueError):
                labels["invalid"] += 1
                continue
            cands.append(c)
        stream = {"dataset": "sim", "id": t["id"], "topic": t["topic"], "now": t["now"],
                  "candidates": cands}
        for p in POLICIES:
            r = b.run(p, stream)
            current = r["current"].lower() if isinstance(r["current"], str) else None
            for convention in ("confirm", "latest"):
                gold = t["gold"][convention]["current"]
                by_policy[p][convention] += current == (gold.lower() if gold else None)
    both_write = sum(v for k, v in intent_confusion.items())
    return {"timelines": len(data), "labels": labels, "both_write": both_write,
            "intent_confusion": dict(sorted(intent_confusion.items(), key=lambda kv: -kv[1])),
            "policies": by_policy}


def score():
    para, fallbacks = paraphrased_timelines()
    result = {
        "sample": {"n": N, "seed": SEED},
        "paraphrase": {"utterances": sum(len(t["events"]) for t in para),
                       "fallbacks": fallbacks},
        "template": score_condition("template", timelines()),
        "paraphrased": score_condition("paraphrased", para),
        "examples": [{"id": t["id"], "texts": [e["text"] for e in t["events"]]} for t in para[:6]],
    }
    (HERE / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "examples"}, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["paraphrase", "extract", "score"])
    {"paraphrase": paraphrase, "extract": extract, "score": score}[parser.parse_args().step]()


if __name__ == "__main__":
    main()
