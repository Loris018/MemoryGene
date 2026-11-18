#!/usr/bin/env python3
"""Real-DSH cross-session acceptance for the MemoryGene skill.

This script launches four independent ``dsh --profile headless`` sessions (four
separate Harness processes with their own session ids) against one MemoryGene
database:

  A  write "我最喜欢玫瑰"          -> confirmed
  B  recall across sessions, then uncertain "栀子花也好看" -> current unchanged
  C  explicit change "现在最喜欢栀子花" -> current updated, history kept
  D  forget the topic             -> deleted

Ground truth is always re-read from the SQLite database with the adapter, not
taken from the model's answer. Raw Harness event streams, persisted session
files and per-command transcripts are saved under evidence/01-e2e/.

It reuses the user's existing DeepSeek account login through
tools/dsh/headless-account.patch.yml (no credentials are stored here). All
people and values are fictional. Stop immediately on repeated failures.

Run:
    .venv/bin/python scripts/e2e_harness.py
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ADAPTER = PROJECT / ".venv" / "bin" / "memorygene-dsh"
PATCH = PROJECT / "tools" / "dsh" / "headless-account.patch.yml"
OUT = PROJECT / "evidence" / "01-e2e"
DSH = Path(
    "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
)
DB = OUT / "harness.db"
NAMESPACE = "dsh-harness"
SUBJECT = "harness-test-user"
DSH_HOME = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
TIMEOUT = 420

RESULTS = []
LOG = []


def record(kind, text):
    line = f"[{kind}] {text}"
    LOG.append(line)
    print(line)


def adapter(*args, expect=0):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("MEMORYGENE_") and key != "DSH_SESSION_ID"
    }
    cmd = [
        str(ADAPTER),
        "--db",
        str(DB),
        "--namespace",
        NAMESPACE,
        "--subject",
        SUBJECT,
        *args,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=str(PROJECT)
    )
    body = None
    raw = result.stdout.strip() or result.stderr.strip()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {"_raw": raw}
    if expect is not None and result.returncode != expect:
        record("adapter-error", f"exit {result.returncode}: {raw[:500]}")
    return result.returncode, body


def current_value(topic="preference.favorite_flower"):
    _, body = adapter("current", "--topic", topic)
    event = body.get("current")
    return event["candidate"]["value"] if event else None


def history_values(topic="preference.favorite_flower"):
    _, body = adapter("history", "--topic", topic)
    return [
        (event["status"], event["candidate"]["value"]) for event in body.get("history", [])
    ]


def topic_names():
    _, body = adapter("topics")
    return [item["topic"] for item in body.get("topics", [])]


def completed_memory_tools(events):
    completed = {
        event.get("callId") for event in events
        if event.get("type") == "tool_result" and event.get("status") == "completed"
        and event.get("callId")
    }
    calls = [event for event in events if event.get("type") == "tool_call"
             and event.get("callId") in completed]
    return {
        "skill": any(event.get("tool") == "skill" and event.get("input", {}).get("name") == "memorygene" for event in calls),
        "adapter": any(event.get("tool") == "bash" and "memorygene-dsh" in event.get("input", {}).get("command", "") for event in calls),
    }


def harness_checks(session):
    return [
        check("session ID present", bool(session["session_id"]), True, session["session_id"]),
        check("skill tool completed", session["tool_evidence"]["skill"], True, session["tool_evidence"]["skill"]),
        check("adapter tool completed", session["tool_evidence"]["adapter"], True, session["tool_evidence"]["adapter"]),
    ]


def run_session(name, prompt):
    OUT.mkdir(parents=True, exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("MEMORYGENE_") and key != "DSH_SESSION_ID"
    }
    env["MEMORYGENE_DB"] = str(DB)
    env["MEMORYGENE_NAMESPACE"] = NAMESPACE
    env["MEMORYGENE_SUBJECT"] = SUBJECT
    cmd = [
        str(DSH),
        "--profile",
        "headless",
        "--patch",
        str(PATCH),
        "--json",
        prompt,
    ]
    record("dsh", f"session {name}: {' '.join(cmd[1:])}")
    started = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT),
        timeout=TIMEOUT,
    )
    elapsed = round(time.time() - started, 1)
    (OUT / f"{name}-events.jsonl").write_text(result.stdout, encoding="utf-8")
    (OUT / f"{name}-stderr.txt").write_text(result.stderr, encoding="utf-8")
    events, session_id, final_text, tool_calls = [], None, "", []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        if event.get("type") == "session":
            session_id = event.get("sessionId")
        if event.get("type") == "final":
            final_text = event.get("text", "")
        if event.get("type") == "tool_call":
            tool_calls.append(event)
    record(
        "result",
        f"{name}: exit={result.returncode} elapsed={elapsed}s session={session_id} "
        f"final={final_text[-500:]!r}",
    )
    persisted = None
    if session_id:
        matches = list(DSH_HOME.glob(f"sessions/*/{session_id}"))
        if matches:
            persisted = matches[0]
            target = OUT / f"{name}-session"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(persisted, target)
    return {
        "name": name,
        "exit": result.returncode,
        "elapsed_seconds": elapsed,
        "session_id": session_id,
        "persisted_session": str(persisted) if persisted else None,
        "event_count": len(events),
        "final_text": final_text,
        "tool_calls": tool_calls,
        "tool_evidence": completed_memory_tools(events),
        "stderr_tail": result.stderr[-2000:],
        "events_file": str(OUT / f"{name}-events.jsonl"),
    }


def add_result(name, passed, checks, session=None):
    RESULTS.append(
        {
            "name": name,
            "passed": passed is True and bool(checks) and all(c["passed"] is True for c in checks),
            "checks": checks,
            "session": session,
        }
    )
    for item in checks:
        record(
            "check",
            f"{'PASS' if item['passed'] else 'FAIL'} {item['name']}: "
            f"expected={item['expected']!r} actual={item['actual']!r}",
        )


def check(name, passed, expected, actual):
    if type(passed) is not bool:
        raise TypeError("Check predicate must be bool; compare actual with expected explicitly")
    return {"name": name, "passed": passed, "expected": expected, "actual": actual}


def main():
    if not DSH.is_file():
        raise SystemExit(f"DSH CLI not found: {DSH}")
    if not ADAPTER.is_file():
        raise SystemExit(f"Adapter not found: {ADAPTER}")
    if not (PROJECT / ".dsh" / "skills" / "memorygene" / "SKILL.md").is_file():
        raise SystemExit(
            "Installed project skill missing; run scripts/install_dsh_skill.py first."
        )
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in (DB, DB.with_name(DB.name + "-wal"), DB.with_name(DB.name + "-shm")):
        if stale.exists():
            stale.unlink()
    # Explicit test-fixture setup: create the empty acceptance database. The model
    # itself is never told to pass --allow-create, so the skill's "never create a
    # new database implicitly" rule is still exercised by every session.
    code, body = adapter("--allow-create", "topics", expect=0)
    if code != 0 or not DB.is_file():
        raise SystemExit(f"Failed to initialize the test database: {body}")
    record("setup", f"explicitly created empty test database via --allow-create: {DB}")
    sessions = []

    # A: write
    prompt_a = (
        "请按 memorygene skill 的流程操作（先运行 doctor，再使用适配器）。"
        "用户这句是长期偏好，请写入：我最喜欢玫瑰。"
        "topic 用 preference.favorite_flower，source 用用户原话「我最喜欢玫瑰。」，"
        "certainty=explicit，intent=assert，importance=0.8。"
        "写入后用 current 验证，最后一行只输出 RESULT_A=<status>|<current value>。"
    )
    session_a = run_session("A-write", prompt_a)
    sessions.append(session_a)
    value = current_value()
    topic_names_a = topic_names()
    add_result(
        "A-write",
        value == "玫瑰" and "preference.favorite_flower" in topic_names_a,
        [
            check("harness session completed", session_a["exit"] == 0, 0, session_a["exit"]),
            *harness_checks(session_a),
            check("skill invoked (adapter command in tool events)",
                  any("memorygene" in json.dumps(e, ensure_ascii=False)
                      for e in session_a["tool_calls"]), True,
                  len(session_a["tool_calls"])),
            check("DB current after session A", (value) == ("玫瑰"), "玫瑰", value),
            check("topic listed", "preference.favorite_flower" in topic_names_a, True,
                  topic_names_a),
        ],
        session_a["session_id"],
    )

    # B: recall across sessions + uncertain supplement
    prompt_b = (
        "请按 memorygene skill 操作。先用 current 查询主题 preference.favorite_flower，"
        "告诉我用户现在最喜欢什么花。然后用户补充说：「栀子花也好看。」"
        "这只是一个不确定的补充，不是新的最爱；按 skill 规则写入（certainty=uncertain，"
        "intent=supplement）。最后再次 current 确认当前最爱没有被改变，"
        "最后一行只输出 RESULT_B=<current value>|<是否改变>。"
    )
    session_b = run_session("B-recall-and-supplement", prompt_b)
    sessions.append(session_b)
    value_b = current_value()
    history_b = history_values()
    pending = [item for item in history_b if item[0] == "pending"]
    add_result(
        "B-recall-and-supplement",
        value_b == "玫瑰" and len(pending) >= 1,
        [
            check("harness session completed", session_b["exit"] == 0, 0, session_b["exit"]),
            *harness_checks(session_b),
            check("new independent session", session_b["session_id"] != session_a["session_id"],
                  True, session_b["session_id"]),
            check("cross-session recall kept current", (value_b) == ("玫瑰"), "玫瑰", value_b),
            check("supplement stored as pending", len(pending) >= 1, ">=1", history_b),
        ],
        session_b["session_id"],
    )

    # C: explicit change + history
    prompt_c = (
        "请按 memorygene skill 操作。用户现在明确说：「现在最喜欢栀子花了。」"
        "请按明确修订写入（certainty=explicit，intent=change，topic 用 "
        "preference.favorite_flower，source 用原话）。然后查 current 和 history，"
        "说明当前值和历史确认过的值，最后一行只输出 RESULT_C=<current value>|<历史确认值列表>。"
    )
    session_c = run_session("C-explicit-change", prompt_c)
    sessions.append(session_c)
    value_c = current_value()
    confirmed_c = [value for status, value in history_values() if status == "confirmed"]
    add_result(
        "C-explicit-change",
        value_c == "栀子花" and confirmed_c == ["玫瑰", "栀子花"],
        [
            check("harness session completed", session_c["exit"] == 0, 0, session_c["exit"]),
            *harness_checks(session_c),
            check("new independent session", session_c["session_id"] != session_b["session_id"],
                  True, session_c["session_id"]),
            check("current updated", (value_c) == ("栀子花"), "栀子花", value_c),
            check("history kept both confirmed values", (confirmed_c) == (["玫瑰", "栀子花"]), ["玫瑰", "栀子花"],
                  confirmed_c),
        ],
        session_c["session_id"],
    )

    # D: forget
    prompt_d = (
        "请按 memorygene skill 操作。用户要求忘掉主题 preference.favorite_flower。"
        "请执行遗忘，然后验证 current 为空、topics 中不再有该主题。"
        "最后一行只输出 RESULT_D=<current是否为空>|<主题是否消失>。"
    )
    session_d = run_session("D-forget", prompt_d)
    sessions.append(session_d)
    value_d = current_value()
    topics_d = topic_names()
    add_result(
        "D-forget",
        value_d is None and "preference.favorite_flower" not in topics_d,
        [
            check("harness session completed", session_d["exit"] == 0, 0, session_d["exit"]),
            *harness_checks(session_d),
            check("new independent session", session_d["session_id"] != session_c["session_id"],
                  True, session_d["session_id"]),
            check("current is null after forget", value_d is None, None, value_d),
            check("topic gone", "preference.favorite_flower" not in topics_d, True,
                  topics_d),
        ],
        session_d["session_id"],
    )

    session_ids = [s["session_id"] for s in sessions]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dsh_cli": str(DSH),
        "dsh_patch": str(PATCH),
        "project_cwd": str(PROJECT),
        "database": str(DB),
        "namespace": NAMESPACE,
        "subject": SUBJECT,
        "sessions": sessions,
        "session_ids_distinct": all(session_ids) and len(set(session_ids)) == len(session_ids),
        "results": RESULTS,
        "passed": sum(1 for r in RESULTS if r["passed"]),
        "failed": [r["name"] for r in RESULTS if not r["passed"]],
        "evidence_level": (
            "Four separate DSH headless processes with different persisted session ids, "
            "same SQLite database; the skill was discovered from "
            "<project>/.dsh/skills. This is real Harness execution, not a simulation. "
            "It is not a GUI conversation; the GUI uses the desktop profile."
        ),
    }
    (OUT / "harness-results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "harness-log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "sessions": len(sessions),
                "distinct_session_ids": summary["session_ids_distinct"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "evidence": str(OUT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not summary["failed"] and summary["session_ids_distinct"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
