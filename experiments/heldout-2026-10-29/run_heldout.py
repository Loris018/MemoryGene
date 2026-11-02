#!/usr/bin/env python3
"""Independent held-out NL extraction benchmark (new 30 fictional cases).

Uses real DeepSeek Harness headless sessions (deepseek-flash) as an independent
extractor, then runs the extracted candidates and label-oracle candidates through
the *same* MemoryGene policy. All cases/labels are new, fictional, and never used
to tune the extractor or policy. Labels are not shown to the model.

No network API is called directly: the official dsh CLI is used with the user's
existing login, and raw outputs/session ids are saved under raw/.
"""

import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"
RAW = HERE / "raw"
DSH = Path("/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh")
PATCH = PROJECT / "tools" / "dsh" / "headless-account.patch.yml"
NOW = "2026-10-29T12:00:00Z"
NAMESPACE = "heldout"
SUBJECT = "fictional-user"
IMPORTANCE = {"low": 0.3, "mid": 0.7, "high": 0.95}
BATCH_SIZE = 5
MODEL = "deepseek-flash (deepseek-account via DSH headless)"
PROMPT_TEMPLATE = (HERE / "prompt.md").read_text(encoding="utf-8")


def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return [None, None]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def parse_json_array(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            obj, end = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            return obj, text[end:]
    return None, text


def run_batch(index, batch):
    RAW.mkdir(parents=True, exist_ok=True)
    final_path = RAW / f"batch-{index:02d}-final.txt"
    events_path = RAW / f"batch-{index:02d}-events.jsonl"
    if final_path.is_file() and events_path.is_file():
        final_text = final_path.read_text(encoding="utf-8")
        session_id = None
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "session":
                session_id = event.get("sessionId")
        parsed, _ = parse_json_array(final_text)
        print(f"  (reusing saved raw output; delete {final_path} to re-run)", flush=True)
        return {
            "batch": index,
            "case_ids": [c["id"] for c in batch],
            "exit": 0,
            "elapsed_seconds": None,
            "session_id": session_id,
            "parsed": parsed,
            "raw_final": final_text,
            "stderr_tail": "",
            "reused": True,
        }
    payload = [
        {"case_id": c["id"], "turns": [t["text"] for t in c["turns"]]} for c in batch
    ]
    prompt = PROMPT_TEMPLATE.replace(
        "{{CASES_JSON}}", json.dumps(payload, ensure_ascii=False, indent=2)
    )
    (RAW / f"batch-{index:02d}-prompt.txt").write_text(prompt, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMORYGENE_")}
    env["DSH_PERMISSION_MODE"] = "danger-full-access"
    cmd = [
        str(DSH), "--profile", "headless", "--patch", str(PATCH), "--json", prompt,
    ]
    started = datetime.now(timezone.utc)
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=str(PROJECT), timeout=360
    )
    elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    (RAW / f"batch-{index:02d}-events.jsonl").write_text(result.stdout, encoding="utf-8")
    (RAW / f"batch-{index:02d}-stderr.txt").write_text(result.stderr, encoding="utf-8")
    session_id, final_text = None, ""
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "session":
            session_id = event.get("sessionId")
        if event.get("type") == "final":
            final_text = event.get("text", "")
    (RAW / f"batch-{index:02d}-final.txt").write_text(final_text, encoding="utf-8")
    parsed, _ = parse_json_array(final_text)
    return {
        "batch": index,
        "case_ids": [c["id"] for c in batch],
        "exit": result.returncode,
        "elapsed_seconds": elapsed,
        "session_id": session_id,
        "parsed": parsed,
        "raw_final": final_text,
        "stderr_tail": result.stderr[-1000:],
    }


def gold_candidates(case):
    out = []
    for i, turn in enumerate(case["turns"]):
        gold = turn["gold"]
        if gold["decision"] != "write":
            continue
        out.append(
            {
                "turn": i,
                "topic": gold["topic"],
                "value": gold["value"],
                "certainty": gold["certainty"],
                "intent": gold["intent"],
                "importance": IMPORTANCE[gold["importance_band"]],
                "sensitive": gold["sensitive"],
                "consent": gold["consent"],
                "expires_at": gold["expires_at"],
                "source": turn["text"],
                "at": gold["at"],
            }
        )
    return out


def model_candidates(case, extracted):
    out = []
    if not isinstance(extracted, dict):
        return out
    turns = extracted.get("turns")
    if not isinstance(turns, list):
        return out
    by_turn = {}
    for item in turns:
        if isinstance(item, dict) and type(item.get("turn")) is int:
            by_turn[item["turn"]] = item
    for i, turn in enumerate(case["turns"]):
        item = by_turn.get(i)
        if not isinstance(item, dict) or item.get("decision") != "write":
            continue
        band = item.get("importance")
        out.append(
            {
                "turn": i,
                "topic": item.get("topic"),
                "value": item.get("value"),
                "certainty": item.get("certainty"),
                "intent": item.get("intent"),
                "importance": IMPORTANCE.get(band, 0.7),
                "sensitive": bool(item.get("sensitive")),
                "consent": bool(item.get("consent")),
                "expires_at": item.get("expires_at"),
                "source": item.get("source"),
                "at": turn["gold"]["at"],
            }
        )
    return out


def valid_candidate(c):
    return (
        isinstance(c.get("topic"), str)
        and isinstance(c.get("value"), str)
        and c["topic"].strip()
        and c["value"].strip()
        and c.get("certainty") in {"explicit", "uncertain", "inferred"}
        and c.get("intent") in {"assert", "change", "correct", "supplement"}
    )


def run_policy(case, candidates, tag):
    from memorygene import Candidate, MemoryStore

    store = MemoryStore()
    statuses = []
    for i, c in enumerate(candidates):
        candidate = Candidate(
            namespace=NAMESPACE,
            subject=SUBJECT,
            topic=c["topic"],
            value=c["value"],
            source=(c.get("source") or "heldout")[:4000],
            at=c["at"],
            certainty=c["certainty"],
            intent=c["intent"],
            importance=c["importance"],
            sensitive=c["sensitive"],
            consent=c["consent"],
            expires_at=c["expires_at"],
        )
        event = store.ingest(candidate, f"{tag}-{case['id']}-{c['turn']}", now=NOW)
        statuses.append(event["status"])
    topic = next(
        (t["gold"]["topic"] for t in case["turns"] if t["gold"]["decision"] == "write"),
        None,
    )
    current = store.current(NAMESPACE, SUBJECT, topic, now=NOW) if topic else None
    history = (
        [e["candidate"]["value"] for e in store.history(NAMESPACE, SUBJECT, topic, now=NOW) if e["status"] == "confirmed"]
        if topic
        else []
    )
    head_count = store.db.execute("SELECT COUNT(*) FROM heads").fetchone()[0]
    store.close()
    return (current["candidate"]["value"] if current else None), history, statuses, head_count


def main():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    RAW.mkdir(parents=True, exist_ok=True)
    batches = [cases[i : i + BATCH_SIZE] for i in range(0, len(cases), BATCH_SIZE)]
    results = {"model": MODEL, "fixed_now": NOW, "cases": len(cases),
               "turns": sum(len(c["turns"]) for c in cases), "batches": []}
    extracted = {}
    for i, batch in enumerate(batches, 1):
        print(f"batch {i}/{len(batches)}: {[c['id'] for c in batch]}", flush=True)
        info = run_batch(i, batch)
        results["batches"].append(
            {
                "batch": i,
                "exit": info["exit"],
                "elapsed_seconds": info["elapsed_seconds"],
                "session_id": info["session_id"],
                "case_ids": info["case_ids"],
                "parse_ok": info["parsed"] is not None,
                "stderr_tail": info["stderr_tail"],
            }
        )
        for item in info["parsed"] or []:
            if isinstance(item, dict) and isinstance(item.get("case_id"), str):
                extracted[item["case_id"]] = item
    # L1: extraction fields vs gold
    fields = ["topic", "value", "certainty", "intent", "importance_band"]
    l1 = {f: {"correct": 0, "total": 0} for f in fields}
    l1.update({"decision": {"correct": 0, "total": 0},
               "source_verbatim": {"correct": 0, "total": 0},
               "sensitive": {"correct": 0, "total": 0},
               "consent": {"correct": 0, "total": 0},
               "skip_reason": {"correct": 0, "total": 0}})
    failures = []
    for case in cases:
        ext = extracted.get(case["id"], {})
        turns = ext.get("turns") if isinstance(ext, dict) else None
        by_turn = {}
        if isinstance(turns, list):
            for item in turns:
                if isinstance(item, dict) and type(item.get("turn")) is int:
                    by_turn[item["turn"]] = item
        for i, turn in enumerate(case["turns"]):
            gold = turn["gold"]
            item = by_turn.get(i)
            model_write = isinstance(item, dict) and item.get("decision") == "write"
            gold_write = gold["decision"] == "write"
            l1["decision"]["total"] += 1
            if model_write == gold_write:
                l1["decision"]["correct"] += 1
            else:
                failures.append({"case": case["id"], "turn": i, "field": "decision",
                                 "expected": "write" if gold_write else "skip",
                                 "observed": "write" if model_write else "skip"})
            if not gold_write or not model_write:
                continue
            checks = {
                "topic": (item.get("topic"), gold["topic"]),
                "value": (item.get("value"), gold["value"]),
                "certainty": (item.get("certainty"), gold["certainty"]),
                "intent": (item.get("intent"), gold["intent"]),
                "importance_band": (item.get("importance"), gold["importance_band"]),
                "sensitive": (bool(item.get("sensitive")), gold["sensitive"]),
                "consent": (bool(item.get("consent")), gold["consent"]),
            }
            for field, (observed, expected) in checks.items():
                l1[field]["total"] += 1
                if observed == expected:
                    l1[field]["correct"] += 1
                else:
                    failures.append({"case": case["id"], "turn": i, "field": field,
                                     "expected": expected, "observed": observed})
            source = item.get("source")
            l1["source_verbatim"]["total"] += 1
            if isinstance(source, str) and source and source in turn["text"]:
                l1["source_verbatim"]["correct"] += 1
            else:
                failures.append({"case": case["id"], "turn": i, "field": "source",
                                 "expected": "verbatim substring", "observed": source})
        # skip reason diagnostic (only for gold skip turns where model skipped)
    for case in cases:
        ext = extracted.get(case["id"], {})
        turns = ext.get("turns") if isinstance(ext, dict) else None
        by_turn = {}
        if isinstance(turns, list):
            for item in turns:
                if isinstance(item, dict) and type(item.get("turn")) is int:
                    by_turn[item["turn"]] = item
        for i, turn in enumerate(case["turns"]):
            gold = turn["gold"]
            item = by_turn.get(i)
            if gold["decision"] == "skip" and isinstance(item, dict) and item.get("decision") == "skip":
                l1["skip_reason"]["total"] += 1
                if item.get("skip_reason") == gold["skip_reason"]:
                    l1["skip_reason"]["correct"] += 1
    metrics = {}
    for field, v in l1.items():
        metrics[field] = {
            "correct": v["correct"], "total": v["total"],
            "rate": round(v["correct"] / v["total"], 4) if v["total"] else None,
            "wilson95": wilson(v["correct"], v["total"]) if v["total"] else [None, None],
        }
    # L2: oracle vs extracted, against manually expected current/history
    l2 = {"oracle": {"current": 0, "history": 0, "total": 0},
          "extracted": {"current": 0, "history": 0, "total": 0},
          "classification": {"extraction_only": [], "storage_only": [], "both": [], "neither": []},
          "cases": []}
    for case in cases:
        oracle = gold_candidates(case)
        model = [c for c in model_candidates(case, extracted.get(case["id"], {})) if valid_candidate(c)]
        oc, oh, os_, o_heads = run_policy(case, oracle, "oracle")
        mc, mh, ms, m_heads = run_policy(case, model, "model")
        l2["oracle"]["total"] += 1
        l2["extracted"]["total"] += 1
        o_ok = oc == case["expected_current"] and oh == case["expected_history"]
        m_ok = (
            mc == case["expected_current"]
            and mh == case["expected_history"]
            and m_heads == o_heads
        )
        if o_ok:
            l2["oracle"]["current"] += 1
            l2["oracle"]["history"] += 1
        if m_ok:
            l2["extracted"]["current"] += 1
            l2["extracted"]["history"] += 1
        if o_ok and not m_ok:
            label = "extraction_only"
        elif not o_ok and not m_ok:
            label = "both"
        elif not o_ok and m_ok:
            label = "storage_only"
        else:
            label = "neither"
        l2["classification"][label].append(case["id"])
        l2["cases"].append({"case": case["id"], "oracle_current": oc, "oracle_history": oh,
                            "model_current": mc, "model_history": mh,
                            "expected_current": case["expected_current"],
                            "expected_history": case["expected_history"],
                            "oracle_statuses": os_, "model_statuses": ms,
                            "oracle_heads": o_heads, "model_heads": m_heads, "class": label})
    result = {
        "metadata": {
            "purpose": "independent held-out fictional NL extraction benchmark",
            "model": MODEL,
            "harness": "dsh --profile headless --patch tools/dsh/headless-account.patch.yml",
            "fixed_now": NOW,
            "cases": len(cases), "turns": results["turns"],
            "prompt_sha256": __import__("hashlib").sha256(PROMPT_TEMPLATE.encode()).hexdigest(),
            "not_used_for_tuning": True,
            "fictional_data": True,
        },
        "batches": results["batches"],
        "L1": metrics,
        "L1_failures": len(failures),
        "L1_failure_list": failures,
        "L2": {
            "oracle_current_accuracy": f'{l2["oracle"]["current"]}/{l2["oracle"]["total"]}',
            "oracle_history_accuracy": f'{l2["oracle"]["history"]}/{l2["oracle"]["total"]}',
            "extracted_current": f'{l2["extracted"]["current"]}/{l2["extracted"]["total"]}',
            "extracted_history": f'{l2["extracted"]["history"]}/{l2["extracted"]["total"]}',
            "extracted_current_rate": round(l2["extracted"]["current"] / l2["extracted"]["total"], 4),
            "extracted_history_rate": round(l2["extracted"]["history"] / l2["extracted"]["total"], 4),
            "classification": {k: {"count": len(v), "cases": v} for k, v in l2["classification"].items()},
            "cases": l2["cases"],
        },
        "raw_dir": str(RAW),
    }
    (HERE / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"L1": metrics, "L2": {k: result["L2"][k] for k in ("oracle_current_accuracy", "extracted_current", "classification")}, "batches": result["batches"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
