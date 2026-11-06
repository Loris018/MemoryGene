"""Small-sample test on the LongMemEval knowledge-update questions.

Data: LongMemEval (Wu et al., 2024), MIT licence, file
`longmemeval_oracle.json` from https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
(sha256 821a2034d219ab45...). The dataset itself is not redistributed here.

Sample (fixed before running): the first 20 questions of type
"knowledge-update" in question_id order, oracle sessions only, user turns only.

Step 1, `extract`: one DeepSeek Harness headless call per question
(deepseek-flash) lists the user's statements relevant to the question, with
verbatim source, value, certainty and intent. The model does not answer.
Raw outputs are cached under raw/ and reused on later runs.

Step 2, `score`: every policy from experiments/baselines_eval.py processes the
same candidates. Scoring rules (fixed before running):
  * abstention questions (id ends with _abs): correct iff nothing is remembered;
  * history questions (initially / before / earlier / previous / first /
    used to / originally): correct iff the answer is in the confirmed history;
  * other questions: correct iff the final current value matches the answer.
A value matches when, after normalisation, one string contains the other, or
both contain numbers and the value's numbers all appear in the answer.

Usage:
  python experiments/longmemeval-ku-2026-11-02/run.py extract --data PATH
  python experiments/longmemeval-ku-2026-11-02/run.py score --data PATH
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "experiments"))

import baselines_eval as b  # noqa: E402

from memorygene import Candidate  # noqa: E402

RAW = HERE / "raw"
DSH = Path("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh")
PATCH = PROJECT / "tools" / "dsh" / "headless-account.patch.yml"
SAMPLE = 20
POLICIES = ("overwrite", "append_latest", "mem0_style", "graphiti_style",
            "latest_explicit", "memorygene", "memorygene_ask", "memorygene_latest")
HISTORY_WORDS = re.compile(
    r"\b(initially|before|earlier|previous|previously|first|used to|originally)\b", re.I)
NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}


def sample(data_path):
    data = json.loads(Path(data_path).read_text("utf-8"))
    ku = sorted((x for x in data if x["question_type"] == "knowledge-update"),
                key=lambda x: x["question_id"])
    return ku[:SAMPLE]


def iso(date_text):
    stamp = re.sub(r"\s*\(\w+\)\s*", " ", date_text).strip()
    return datetime.strptime(stamp, "%Y/%m/%d %H:%M").replace(tzinfo=timezone.utc).isoformat()


def user_messages(item):
    out = []
    for i, (date, session) in enumerate(zip(item["haystack_dates"], item["haystack_sessions"]), 1):
        out.append((i, date, [t["content"] for t in session if t["role"] == "user"]))
    return out


def prompt_for(item):
    blocks = []
    for i, date, msgs in user_messages(item):
        body = "\n".join(f"- {m}" for m in msgs)
        blocks.append(f"Session {i} ({date}):\n{body}")
    template = (HERE / "prompt.md").read_text("utf-8")
    return template.replace("{{QUESTION}}", item["question"]).replace(
        "{{SESSIONS}}", "\n\n".join(blocks))


def extract(items, raw=RAW):
    raw.mkdir(exist_ok=True)
    for n, item in enumerate(items, 1):
        out = raw / f"{item['question_id']}.json"
        if out.is_file():
            print(f"[{n}/{len(items)}] {item['question_id']} cached", flush=True)
            continue
        cmd = [str(DSH), "--profile", "headless", "--patch", str(PATCH), "--json", prompt_for(item)]
        started = datetime.now(timezone.utc)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=400, cwd=str(HERE))
        final = ""
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "final":
                final = event.get("text", "")
        seconds = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        out.write_text(json.dumps({"question_id": item["question_id"], "exit": result.returncode,
                                   "seconds": seconds, "final": final},
                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{n}/{len(items)}] {item['question_id']} exit={result.returncode} {seconds}s", flush=True)


def parse(final):
    start, end = final.find("["), final.rfind("]")
    if start < 0 or end < start:
        return None
    try:
        rows = json.loads(final[start:end + 1])
    except json.JSONDecodeError:
        return None
    return rows if isinstance(rows, list) else None


def normalise(text):
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return " ".join(NUMBER_WORDS.get(w, w) for w in words)


def matches(value, answer):
    v, a = normalise(value), normalise(answer)
    if not v or not a:
        return False
    if v in a or a in v:
        return True
    nv, na = set(re.findall(r"\d+", v)), set(re.findall(r"\d+", a))
    return bool(nv) and nv <= na


def candidates(item, rows):
    sessions = {i: (date, msgs) for i, date, msgs in user_messages(item)}
    out, dropped, verbatim = [], 0, 0
    for row in rows:
        try:
            date, msgs = sessions[int(row["session"])]
            c = Candidate("lme", "user", "lme.answer", str(row["value"]).strip(),
                          str(row["source"]).strip(), iso(date),
                          certainty=row["certainty"], intent=row["intent"])
            c.validate()
        except (KeyError, ValueError, TypeError):
            dropped += 1
            continue
        verbatim += any(c.source in m for m in msgs)
        out.append(c)
    return out, dropped, verbatim


def score(items, raw=RAW, out=HERE / "results.json"):
    rows_out, totals = [], {p: 0 for p in POLICIES}
    by_kind = {}
    stats = {"parsed": 0, "candidates": 0, "dropped": 0, "verbatim_source": 0, "questions": 0}
    for item in items:
        record = json.loads((raw / f"{item['question_id']}.json").read_text("utf-8"))
        rows = parse(record["final"])
        stats["parsed"] += rows is not None
        cands, dropped, verbatim = candidates(item, rows or [])
        stats["candidates"] += len(cands)
        stats["dropped"] += dropped
        stats["verbatim_source"] += verbatim
        qid = item["question_id"]
        kind = ("abstention" if qid.endswith("_abs")
                else "history" if HISTORY_WORDS.search(item["question"]) else "current")
        # One item (2133c1b5) has a session timestamped hours after its question;
        # the evaluation clock is the later of the two so no evidence is "future".
        clock = max(iso(item["question_date"]), *(iso(d) for d in item["haystack_dates"]))
        stream = {"dataset": "lme", "id": qid, "topic": "lme.answer",
                  "now": clock, "candidates": cands,
                  "gold_current": None, "gold_history": []}
        row = {"question_id": qid, "kind": kind, "question": item["question"],
               "answer": item["answer"], "extracted": [
                   {"value": c.value, "at": c.at, "certainty": c.certainty, "intent": c.intent}
                   for c in cands]}
        for p in POLICIES:
            r = b.run(p, stream)
            if kind == "abstention":
                ok = r["current"] is None and not r["history"]
            elif kind == "history":
                ok = any(matches(h, item["answer"]) for h in r["history"])
            else:
                ok = r["current"] is not None and matches(r["current"], item["answer"])
            row[p] = {"current": r["current"], "history": r["history"], "correct": ok,
                      "questions": r["questions"]}
            totals[p] += ok
            by_kind.setdefault(kind, {q: 0 for q in POLICIES})
            by_kind[kind][p] += ok
            if p == "memorygene_ask":
                stats["questions"] += r["questions"]
        rows_out.append(row)
    kinds = {k: sum(r["kind"] == k for r in rows_out) for k in by_kind}
    result = {"sample": len(items), "kinds": kinds, "correct": totals, "correct_by_kind": by_kind,
              "extraction": stats, "rows": rows_out}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["extract", "score"])
    parser.add_argument("--data", required=True)
    args = parser.parse_args()
    items = sample(args.data)
    extract(items) if args.step == "extract" else score(items)


if __name__ == "__main__":
    main()
