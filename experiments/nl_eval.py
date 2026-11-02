"""Independent fictional natural-language evaluation for the extractor prototype.

Two layers are scored separately:

L1 extraction
    topic / value / certainty / intent / importance band / persistence decision
    / source verbatim+minimality, plus two auxiliary field checks (sensitive,
    consent) and skip-reason classification.

L2 storage
    The same core rules receive (a) oracle candidates built from the human
    labels and (b) candidates produced by ``memorygene.extract``. Final current
    value, confirmed history and per-turn statuses are compared with the human
    expectations. Every failing case is classified as extraction-only,
    storage-only, both, or neither.

Fairness
    The extractor -> Candidate -> MemoryStore pipeline is re-run with
    index=plain/complement and protection=none/copy/complement. Copy and
    complement redundancy have exactly one payload-length copy (equal bytes);
    semantic outcomes must be identical in every configuration. Routing-key
    bytes and database size are measured, not assumed.

Caveat: the rule table and these cases were developed together by the
same author. This is a regression/quality check of a rule-based prototype, NOT a
held-out benchmark and NOT an NLU capability claim. All cases are fictional.
"""

import hashlib
import json
import sys
import tempfile
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene.extract import extract

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "nl_cases.json"
OUT_DIR = HERE / "results"
NOW = "2026-10-24T10:00:00+00:00"
AT = "2026-10-01T00:00:00+00:00"
NAMESPACE = "nl-fixture"
SUBJECT = "fictional-user"
IMPORTANCE = {"low": 0.3, "mid": 0.7, "high": 0.95}
VALID_CERTAINTY = {"explicit", "uncertain", "inferred"}
VALID_INTENT = {"assert", "change", "correct", "supplement"}
VALID_IMPORTANCE = set(IMPORTANCE)
SKIP_REASONS = {
    "third_party",
    "negation",
    "consent_refused",
    "low_importance",
    "unmapped_topic",
    "no_value",
}
FAIRNESS_CONFIGS = (
    ("plain", "none"),
    ("plain", "copy"),
    ("plain", "complement"),
    ("complement", "none"),
    ("complement", "copy"),
    ("complement", "complement"),
)
LIMITATIONS = [
    "人工标签与规则由同一作者同期开发，本评估是回归/质量检查，不是独立留出基准。",
    "案例全部为虚构中文对话；不包含真实聊天记录或个人数据。",
    "固定现在时间 2026-10-24T10:00:00Z、固定 namespace/subject；每组对话独立建库。",
    "每轮只评估首个提取结果；同一轮多记忆陈述的切分不在本评估范围。",
    "主题映射是固定表，未映射主题只能弃权；不能据此推断通用语义理解能力。",
    "值匹配为字符串精确匹配，同义值、数字格式差异均计为错误。",
    "未做标注者一致性、置信区间、模型多次采样或主动召回评估。",
    "plain/complement 与 copy/complement 只比较编码/副本表示；不声称压缩、加密、语义或纠错优势。",
]


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def norm(text):
    return unicodedata.normalize("NFKC", text).strip()


def band(value):
    if value < 0.5:
        return "low"
    if value >= 0.9:
        return "high"
    return "mid"


def scope_of(case):
    session = case.get("session", "")
    return ("session", session) if session else ("persistent", "")


def load_cases(path=CASES_PATH):
    cases = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(cases, list) and len(cases) >= 30, "at least 30 cases")
    seen = set()
    turns_total = 0
    for case in cases:
        cid = case["id"]
        _require(cid not in seen, f"duplicate case id {cid}")
        seen.add(cid)
        _require(case.get("fictional") is True, f"{cid} must be marked fictional")
        turns = case["turns"]
        _require(len(turns) >= 1, f"{cid} needs turns")
        _require(
            len(case["expected_statuses"]) == len(turns),
            f"{cid} expected_statuses length",
        )
        _require(isinstance(case["topic"], str) and case["topic"], f"{cid} topic")
        for turn in turns:
            _require(isinstance(turn["text"], str) and turn["text"], f"{cid} text")
            label = turn["label"]
            _require(isinstance(label.get("should_write"), bool), f"{cid} should_write")
            if label["should_write"]:
                for field in ("topic", "value", "source"):
                    _require(
                        isinstance(label.get(field), str) and label[field],
                        f"{cid} missing {field}",
                    )
                _require(
                    label["source"] in turn["text"],
                    f"{cid} label source is not a verbatim substring",
                )
                _require(label["certainty"] in VALID_CERTAINTY, f"{cid} certainty")
                _require(label["intent"] in VALID_INTENT, f"{cid} intent")
                _require(label["importance"] in VALID_IMPORTANCE, f"{cid} importance")
            else:
                _require(
                    label.get("skip_reason") in SKIP_REASONS,
                    f"{cid} skip_reason",
                )
            turns_total += 1
    return cases, turns_total


def _require(condition, message):
    if not condition:
        raise ValueError(f"invalid evaluation fixture: {message}")


def candidate_from_label(label, case):
    scope, session = scope_of(case)
    return Candidate(
        namespace=NAMESPACE,
        subject=SUBJECT,
        topic=label["topic"],
        value=label["value"],
        source=label["source"],
        at=case.get("at", AT),
        certainty=label["certainty"],
        intent=label["intent"],
        importance=IMPORTANCE[label["importance"]],
        scope=scope,
        session=session,
        expires_at=label.get("expires_at"),
        sensitive=bool(label.get("sensitive", False)),
        consent=bool(label.get("consent", False)),
    )


def query_state(store, case):
    topic = case["topic"]
    scope, session = scope_of(case)
    current = store.current(
        NAMESPACE, SUBJECT, topic, scope=scope, session=session, now=NOW
    )
    history = store.history(
        NAMESPACE, SUBJECT, topic, scope=scope, session=session, now=NOW
    )
    return {
        "current": current["candidate"]["value"] if current else None,
        "history": [
            event["candidate"]["value"]
            for event in history
            if event["status"] == "confirmed"
        ],
    }


def collect_extractions(cases):
    """Run the extractor once; extraction is independent of the store config."""
    results = {}
    for case in cases:
        session = case.get("session", "")
        per_turn = []
        for turn in case["turns"]:
            found = extract(
                turn["text"],
                namespace=NAMESPACE,
                subject=SUBJECT,
                at=case.get("at", AT),
                session=session,
            )
            per_turn.append(found)
        results[case["id"]] = per_turn
    return results


def run_oracle(cases):
    outcomes = {}
    for case in cases:
        with MemoryStore(":memory:", index="plain", protection="copy") as store:
            statuses = []
            for index, turn in enumerate(case["turns"]):
                label = turn["label"]
                if label["should_write"]:
                    event = store.ingest(
                        candidate_from_label(label, case),
                        f"oracle-{case['id']}-{index}",
                        now=NOW,
                    )
                    statuses.append(event["status"])
                else:
                    statuses.append("skipped")
            outcomes[case["id"]] = {"statuses": statuses, **query_state(store, case)}
    return outcomes


def run_extractor(cases, extractions):
    outcomes = {}
    for case in cases:
        with MemoryStore(":memory:", index="plain", protection="copy") as store:
            statuses = []
            for index, found in enumerate(extractions[case["id"]]):
                primary = found[0] if found else None
                if primary is not None and primary.decision == "write":
                    event = store.ingest(
                        primary.candidate(),
                        f"extractor-{case['id']}-{index}",
                        now=NOW,
                    )
                    statuses.append(event["status"])
                else:
                    statuses.append("skipped")
            outcomes[case["id"]] = {"statuses": statuses, **query_state(store, case)}
    return outcomes


def _ratio(correct, total):
    return {"correct": correct, "total": total, "rate": correct / total if total else None}


def evaluate_l1(cases, extractions):
    counters = {
        "decision": [0, 0],
        "topic": [0, 0],
        "value": [0, 0],
        "certainty": [0, 0],
        "intent": [0, 0],
        "importance_band": [0, 0],
        "source_verbatim": [0, 0],
        "source_not_bloated": [0, 0],
        "source_exact": [0, 0],
        "sensitive": [0, 0],
        "consent": [0, 0],
        "skip_reason": [0, 0],
    }
    failures = []
    turn_scores = {}
    for case in cases:
        cid = case["id"]
        turn_scores[cid] = []
        for index, turn in enumerate(case["turns"]):
            label = turn["label"]
            text = turn["text"]
            found = extractions[cid][index]
            primary = found[0] if found else None
            should_write = label["should_write"]
            observed_write = primary is not None and primary.decision == "write"
            mismatches = []
            counters["decision"][1] += 1
            if should_write == observed_write:
                counters["decision"][0] += 1
            else:
                mismatches.append(
                    {
                        "field": "decision",
                        "expected": "write" if should_write else "skip",
                        "observed": "skip"
                        if should_write
                        else "write",
                    }
                )
            if should_write:
                fields = ("topic", "value", "certainty", "intent")
                observed = {
                    "topic": primary.topic if observed_write else None,
                    "value": primary.value if observed_write else None,
                    "certainty": primary.certainty if observed_write else None,
                    "intent": primary.intent if observed_write else None,
                    "importance_band": band(primary.importance)
                    if observed_write
                    else None,
                    "sensitive": primary.sensitive if observed_write else None,
                    "consent": primary.consent if observed_write else None,
                }
                expected = {
                    "topic": label["topic"],
                    "value": label["value"],
                    "certainty": label["certainty"],
                    "intent": label["intent"],
                    "importance_band": label["importance"],
                    "sensitive": bool(label.get("sensitive", False)),
                    "consent": bool(label.get("consent", False)),
                }
                for field in fields:
                    counters[field][1] += 1
                    if observed[field] == expected[field]:
                        counters[field][0] += 1
                    else:
                        mismatches.append(
                            {
                                "field": field,
                                "expected": expected[field],
                                "observed": observed[field],
                            }
                        )
                for field in ("importance_band", "sensitive", "consent"):
                    counters[field][1] += 1
                    if observed[field] == expected[field]:
                        counters[field][0] += 1
                    else:
                        mismatches.append(
                            {
                                "field": field,
                                "expected": expected[field],
                                "observed": observed[field],
                            }
                        )
                source = primary.source if observed_write else None
                verbatim = bool(source) and source in text
                not_bloated = (
                    verbatim
                    and len(norm(source)) <= len(norm(label["source"]))
                )
                identical = verbatim and norm(source) == norm(label["source"])
                for field, value in (
                    ("source_verbatim", verbatim),
                    ("source_not_bloated", not_bloated),
                    ("source_exact", identical),
                ):
                    counters[field][1] += 1
                    if value:
                        counters[field][0] += 1
                    else:
                        mismatches.append(
                            {
                                "field": field,
                                "expected": label["source"],
                                "observed": source if observed_write else "<no extraction>",
                            }
                        )
            else:
                counters["skip_reason"][1] += 1
                expected_reason = label["skip_reason"]
                observed_reason = (
                    primary.skip_reason if primary is not None else "<none>"
                )
                if observed_write or observed_reason != expected_reason:
                    mismatches.append(
                        {
                            "field": "skip_reason",
                            "expected": expected_reason,
                            "observed": (
                                "write:" + str(primary.intent)
                                if observed_write
                                else observed_reason
                            ),
                        }
                    )
                else:
                    counters["skip_reason"][0] += 1
            turn_scores[cid].append(
                {
                    "decision_correct": should_write == observed_write,
                    "mismatches": mismatches,
                }
            )
            failures.extend(
                {"case": cid, "turn": index, "text": text, **item}
                for item in mismatches
            )
    metrics = {name: _ratio(*counts) for name, counts in counters.items()}
    return metrics, failures, turn_scores


def _outcomes_equal(left, right):
    return (
        left["statuses"] == right["statuses"]
        and left["current"] == right["current"]
        and left["history"] == right["history"]
    )


def evaluate_l2(cases, oracle_outcomes, extractor_outcomes, turn_scores):
    classification = {"extraction_only": [], "storage_only": [], "both": [], "neither": []}
    cases_out = []
    status_confusion = {"oracle": {}, "extractor": {}}
    oracle_current = oracle_history = oracle_statuses = 0
    ext_current = ext_history = ext_statuses = 0
    different_outcomes = 0
    for case in cases:
        cid = case["id"]
        expected = {
            "statuses": case["expected_statuses"],
            "current": case["expected_current"],
            "history": case["expected_history"],
        }
        oracle = oracle_outcomes[cid]
        extracted = extractor_outcomes[cid]
        oracle_ok = _outcomes_equal(oracle, expected)
        extractor_ok = _outcomes_equal(extracted, expected)
        extraction_failed = any(
            item["mismatches"] for item in turn_scores[cid]
        )
        different_outcomes += not _outcomes_equal(oracle, extracted)
        for want, oracle_status, extractor_status in zip(
            expected["statuses"],
            oracle["statuses"],
            extracted["statuses"],
            strict=True,
        ):
            oracle_statuses += want == oracle_status
            ext_statuses += want == extractor_status
            if want != oracle_status:
                key = f"{want}->{oracle_status}"
                status_confusion["oracle"][key] = (
                    status_confusion["oracle"].get(key, 0) + 1
                )
            if want != extractor_status:
                key = f"{want}->{extractor_status}"
                status_confusion["extractor"][key] = (
                    status_confusion["extractor"].get(key, 0) + 1
                )
        oracle_current += oracle["current"] == expected["current"]
        oracle_history += oracle["history"] == expected["history"]
        ext_current += extracted["current"] == expected["current"]
        ext_history += extracted["history"] == expected["history"]
        if oracle_ok and extractor_ok and not extraction_failed:
            verdict = "pass"
        elif extraction_failed and not oracle_ok:
            verdict = "both"
            classification["both"].append(cid)
        elif extraction_failed:
            verdict = "extraction_only"
            classification["extraction_only"].append(cid)
        elif not oracle_ok:
            verdict = "storage_only"
            classification["storage_only"].append(cid)
        else:
            verdict = "neither"
            classification["neither"].append(cid)
        cases_out.append(
            {
                "case": cid,
                "verdict": verdict,
                "expected": expected,
                "oracle": oracle,
                "extractor": extracted,
                "extraction_failures": [
                    item for item in turn_scores[cid] if item["mismatches"]
                ],
            }
        )
    total_cases = len(cases)
    total_turns = sum(len(case["turns"]) for case in cases)
    summary = {
        "cases": total_cases,
        "turns": total_turns,
        "oracle": {
            "current_correct": _ratio(oracle_current, total_cases),
            "history_correct": _ratio(oracle_history, total_cases),
            "statuses_correct": _ratio(oracle_statuses, total_turns),
        },
        "extractor": {
            "current_correct": _ratio(ext_current, total_cases),
            "history_correct": _ratio(ext_history, total_cases),
            "statuses_correct": _ratio(ext_statuses, total_turns),
        },
        "oracle_vs_extractor_outcomes_different": different_outcomes,
        "classification": {
            name: {"count": len(ids), "cases": ids}
            for name, ids in classification.items()
        },
        "status_confusion": status_confusion,
        "failing_cases": [item for item in cases_out if item["verdict"] != "pass"],
    }
    return summary, cases_out


def _byte_stats(store):
    row = store.db.execute(
        "SELECT count(*), COALESCE(sum(length(payload)),0), "
        "COALESCE(sum(length(backup)),0), "
        "COALESCE(sum(length(cast(route as blob))),0) FROM events"
    ).fetchone()
    return {
        "events": row[0],
        "payload_bytes": row[1],
        "backup_bytes": row[2],
        "route_key_bytes": row[3],
    }


def fairness(cases, extractions, main_extractor_outcomes):
    configs = []
    semantic_runs = {}
    main_digest = digest(main_extractor_outcomes)
    for index_mode, protection in FAIRNESS_CONFIGS:
        totals = {
            "events": 0,
            "payload_bytes": 0,
            "backup_bytes": 0,
            "route_key_bytes": 0,
        }
        outcomes = {}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            with MemoryStore(path, index=index_mode, protection=protection) as store:
                for case in cases:
                    statuses = []
                    for turn_index, found in enumerate(extractions[case["id"]]):
                        primary = found[0] if found else None
                        if primary is not None and primary.decision == "write":
                            event = store.ingest(
                                primary.candidate(),
                                f"fair-{case['id']}-{turn_index}",
                                now=NOW,
                            )
                            statuses.append(event["status"])
                        else:
                            statuses.append("skipped")
                    outcomes[case["id"]] = {
                        "statuses": statuses,
                        **query_state(store, case),
                    }
                    stats = _byte_stats(store)
                    for key in totals:
                        totals[key] += stats[key]
                    scope, session = scope_of(case)
                    store.forget(
                        NAMESPACE,
                        SUBJECT,
                        case["topic"],
                        scope=scope,
                        session=session,
                    )
            database_bytes = path.stat().st_size
        semantic_digest = digest(outcomes)
        semantic_runs[f"{index_mode}/{protection}"] = semantic_digest
        configs.append(
            {
                "index": index_mode,
                "protection": protection,
                **totals,
                "database_bytes": database_bytes,
                "semantic_digest": semantic_digest,
            }
        )
    digests = {item["semantic_digest"] for item in configs}
    _require(len(digests) == 1, "semantic outcomes differ across fairness configs")
    by_config = {(item["index"], item["protection"]): item for item in configs}
    redundancy_equal = True
    for index_mode in ("plain", "complement"):
        copy_bytes = by_config[(index_mode, "copy")]["backup_bytes"]
        complement_bytes = by_config[(index_mode, "complement")]["backup_bytes"]
        payload_bytes = by_config[(index_mode, "copy")]["payload_bytes"]
        redundancy_equal = redundancy_equal and (
            copy_bytes == complement_bytes == payload_bytes
        )
    none_bytes = by_config[("plain", "none")]["database_bytes"]
    none_logical = (
        by_config[("plain", "none")]["payload_bytes"]
        + by_config[("plain", "none")]["backup_bytes"]
        + by_config[("plain", "none")]["route_key_bytes"]
    )
    for item in configs:
        item["redundancy_bytes"] = item["backup_bytes"]
        item["logical_bytes"] = (
            item["payload_bytes"]
            + item["backup_bytes"]
            + item["route_key_bytes"]
        )
        item["logical_overhead_vs_no_protection"] = (
            (item["logical_bytes"] - none_logical) / none_logical
            if none_logical
            else None
        )
        item["database_overhead_vs_no_protection"] = (
            (item["database_bytes"] - none_bytes) / none_bytes if none_bytes else None
        )
    route_ratio = None
    if by_config[("plain", "copy")]["route_key_bytes"]:
        route_ratio = (
            by_config[("complement", "copy")]["route_key_bytes"]
            / by_config[("plain", "copy")]["route_key_bytes"]
        )
    summary = {
        "configs": configs,
        "semantic_identical": True,
        "main_l2_extractor_digest_matches_fairness": digests == {main_digest},
        "main_l2_extractor_digest": main_digest,
        "semantic_digests": semantic_runs,
        "equal_redundancy_bytes": redundancy_equal,
        "redundancy_bytes_per_config": {
            f"{index_mode}/{protection}": by_config[
                (index_mode, protection)
            ]["backup_bytes"]
            for index_mode, protection in FAIRNESS_CONFIGS
        },
        "index_route_key_byte_ratio_complement_over_plain": route_ratio,
        "logical_bytes_note": (
            "logical_bytes = payload 表字节 + backup 副本字节 + route 键字节的实测合计；"
            "与 SQLite 页对齐后的 database_bytes 分开报告。"
        ),
        "database_size_note": (
            "database_bytes 是相同案例序列写入后、按案例 forget 隔离、关闭连接后的实测文件大小；"
            "含 SQLite 页分配与 freelist，不做压缩或纠错推断。"
        ),
    }
    _require(redundancy_equal, "copy/complement redundancy bytes differ")
    _require(
        summary["main_l2_extractor_digest_matches_fairness"],
        "fairness semantic outcomes differ from the main L2 extractor run",
    )
    return summary


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases, turns_total = load_cases()
    extractions = collect_extractions(cases)
    oracle_outcomes = run_oracle(cases)
    extractor_outcomes = run_extractor(cases, extractions)
    l1_metrics, l1_failures, turn_scores = evaluate_l1(cases, extractions)
    l2_summary, _l2_cases = evaluate_l2(
        cases, oracle_outcomes, extractor_outcomes, turn_scores
    )
    fairness_summary = fairness(cases, extractions, extractor_outcomes)
    result = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fictional_data": True,
            "purpose": "rule-based extractor prototype regression/quality check",
            "not_a_benchmark": True,
            "now": NOW,
            "evidence_at": AT,
            "namespace": NAMESPACE,
            "subject": SUBJECT,
            "cases": len(cases),
            "turns": turns_total,
            "python": sys.version,
            "command": "PYTHONPATH=src .venv/bin/python experiments/nl_eval.py",
            "label_definition_should_write": (
                "extractor should emit a Candidate for the storage layer; "
                "rejected/discarded/expired candidates can still be should_write"
            ),
            "importance_band_rule": "low < 0.5 <= mid < 0.9 <= high",
            "oracle_importance_representative": IMPORTANCE,
        },
        "L1": {
            "metrics": l1_metrics,
            "failure_count": len(l1_failures),
            "failures": l1_failures,
        },
        "L2": l2_summary,
        "fairness": fairness_summary,
        "limitations": LIMITATIONS,
    }
    (OUT_DIR / "nl_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    trace = {
        "metadata": result["metadata"],
        "cases": [
            {
                "id": case["id"],
                "note": case["note"],
                "topic": case["topic"],
                "session": case.get("session", ""),
                "expected": {
                    "statuses": case["expected_statuses"],
                    "current": case["expected_current"],
                    "history": case["expected_history"],
                },
                "oracle": oracle_outcomes[case["id"]],
                "extractor": extractor_outcomes[case["id"]],
                "turns": [
                    {
                        "index": index,
                        "text": turn["text"],
                        "label": turn["label"],
                        "extractions": [
                            asdict(item) for item in extractions[case["id"]][index]
                        ],
                        "l1": turn_scores[case["id"]][index],
                    }
                    for index, turn in enumerate(case["turns"])
                ],
            }
            for case in cases
        ],
    }
    (OUT_DIR / "nl_trace.json").write_text(
        json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "cases": len(cases),
        "turns": turns_total,
        "L1": l1_metrics,
        "L1_failure_count": len(l1_failures),
        "L2": {
            "oracle": l2_summary["oracle"],
            "extractor": l2_summary["extractor"],
            "classification": l2_summary["classification"],
            "oracle_vs_extractor_outcomes_different": l2_summary[
                "oracle_vs_extractor_outcomes_different"
            ],
        },
        "fairness": {
            "semantic_identical": fairness_summary["semantic_identical"],
            "equal_redundancy_bytes": fairness_summary["equal_redundancy_bytes"],
            "main_l2_extractor_digest_matches_fairness": fairness_summary[
                "main_l2_extractor_digest_matches_fairness"
            ],
            "index_route_key_byte_ratio": fairness_summary[
                "index_route_key_byte_ratio_complement_over_plain"
            ],
            "configs": [
                {
                    "index": item["index"],
                    "protection": item["protection"],
                    "events": item["events"],
                    "payload_bytes": item["payload_bytes"],
                    "backup_bytes": item["backup_bytes"],
                    "route_key_bytes": item["route_key_bytes"],
                    "logical_bytes": item["logical_bytes"],
                    "database_bytes": item["database_bytes"],
                }
                for item in fairness_summary["configs"]
            ],
        },
        "outputs": [
            str(OUT_DIR / "nl_results.json"),
            str(OUT_DIR / "nl_trace.json"),
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
