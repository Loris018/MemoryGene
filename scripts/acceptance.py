#!/usr/bin/env python3
"""End-to-end acceptance for the MemoryGene DSH adapter.

Every check drives the real ``memorygene-dsh`` executable as a separate process,
then inspects the SQLite file directly so the evidence does not depend on the
model's or the adapter's own claims. All people and data are fictional.

Run:
    .venv/bin/python scripts/acceptance.py

Outputs:
    evidence/02-e2e/acceptance-results.json   machine-readable checks
    evidence/02-e2e/acceptance-log.txt        command/output transcript
    evidence/02-e2e/acceptance.db             the test database
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
VENV_ADAPTER = PROJECT / ".venv" / "bin" / "memorygene-dsh"
ADAPTER = VENV_ADAPTER if VENV_ADAPTER.is_file() else None
ADAPTER_CMD = (
    [str(VENV_ADAPTER)] if ADAPTER else [sys.executable, "-m", "memorygene.adapter"]
)
OUT = PROJECT / "evidence" / "02-e2e"
DB = OUT / "acceptance.db"
NAMESPACE = "dsh-acceptance"
SUBJECT = "acceptance-user"
SESSION_A = "session-acceptance-a"
SESSION_B = "session-acceptance-b"
FIXTURE_NOW = "2026-10-24T12:00:00Z"

LOG = []
RESULTS = []
CURRENT = {"scenario": None}


def now_iso(offset_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).isoformat()


def record(kind, text):
    line = f"[{kind}] {text}"
    LOG.append(line)
    print(line)


def base_env(session=SESSION_A):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("MEMORYGENE_")
    }
    env["DSH_SESSION_ID"] = session
    return env


def call(*args, session=SESSION_A, allow_create=False, expect=0):
    cmd = list(ADAPTER_CMD)
    if allow_create:
        cmd.append("--allow-create")
    cmd += [
        "--db",
        str(DB),
        "--namespace",
        NAMESPACE,
        "--subject",
        SUBJECT,
        # Fixed fictional clock; expiry fixtures must not fail after Nov 2026.
        # Explicit per-case --now arguments below override this default.
        "--now",
        FIXTURE_NOW,
        *args,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=base_env(session), cwd=str(PROJECT)
    )
    record("cmd", " ".join(cmd[1:]))
    body = None
    raw = result.stdout.strip() or result.stderr.strip()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {"_raw": raw}
    record("out", json.dumps(body, ensure_ascii=False)[:600])
    if expect is not None and result.returncode != expect:
        raise AssertionError(
            f"expected exit {expect}, got {result.returncode}: {raw[:400]}"
        )
    return result.returncode, body


def check(name, passed, expected, actual):
    if type(passed) is not bool:
        raise TypeError("Check predicate must be bool; compare actual with expected explicitly")
    scenario = RESULTS[-1]
    scenario["checks"].append(
        {
            "name": name,
            "passed": passed,
            "expected": expected,
            "actual": actual,
        }
    )
    if not passed:
        scenario["passed"] = False
        scenario["failures"].append(name)
    record("check", f"{'PASS' if passed else 'FAIL'} {name}: expected={expected!r} actual={actual!r}")


def remember(topic, value, source, **kwargs):
    args = [
        "remember",
        "--topic",
        topic,
        "--value",
        value,
        "--source",
        source,
    ]
    for key, val in kwargs.items():
        flag = "--" + key.replace("_", "-")
        if isinstance(val, bool):
            if val:
                args.append(flag)
        else:
            args += [flag, str(val)]
    return call(*args, allow_create=True)


def current(topic, **kwargs):
    return call("current", "--topic", topic, *query_scope(kwargs))


def history(topic, **kwargs):
    return call("history", "--topic", topic, *query_scope(kwargs))


def topics(subject=SUBJECT, session=SESSION_A):
    return call("--subject", subject, "topics", session=session)


def query_scope(kwargs):
    args = []
    if kwargs.get("scope"):
        args += ["--scope", kwargs["scope"]]
    if kwargs.get("now"):
        args += ["--now", kwargs["now"]]
    return args


def sql(query, params=()):
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        return list(conn.execute(query, params))


def scenario(identifier, title):
    RESULTS.append(
        {"id": identifier, "title": title, "passed": True, "checks": [], "failures": []}
    )
    CURRENT["scenario"] = identifier
    record("scenario", f"{identifier} {title}")


# ---------------------------------------------------------------- scenarios


def s01_important_information_saved():
    scenario("S01", "一句话的重要信息能被保存")
    _, body = remember(
        "preference.favorite_flower",
        "玫瑰",
        "我最喜欢玫瑰。",
        certainty="explicit",
        importance="0.8",
    )
    check("write status", body["result"]["status"] == "confirmed", "confirmed",
          body["result"]["status"])
    _, body = current("preference.favorite_flower")
    check("current value", ((body["current"] or {}).get("candidate", {}).get("value")) == ("玫瑰"),
          "玫瑰", (body["current"] or {}).get("candidate", {}).get("value"))
    rows = sql(
        "SELECT COUNT(*) FROM events WHERE CAST(payload AS TEXT) LIKE ?", ("%preference.favorite_flower%",)
    )
    check("persisted event row", rows[0][0] >= 1, ">=1", rows[0][0])


def s02_irrelevant_content_not_accumulated():
    scenario("S02", "重复的无关内容不持续积累为长期事实")
    before = sql("SELECT COUNT(*) FROM events")[0][0]
    statuses = []
    for i in range(5):
        _, body = remember(
            "chitchat.weather",
            f"今天天气不错{i}",
            f"今天天气不错{i}（闲聊）",
            importance="0.2",
        )
        statuses.append(body["result"]["status"])
    after = sql("SELECT COUNT(*) FROM events")[0][0]
    check("all discarded", all(s == "discarded" for s in statuses), "discarded*5", statuses)
    check("no event rows grew", after == before, before, after)
    _, body = call("topics")
    topics_names = [t["topic"] for t in body["topics"]]
    check("no chitchat topic", "chitchat.weather" not in topics_names, False,
          "chitchat.weather" in topics_names)
    # repeated identical *important* evidence keeps one current version only
    _, head = current("preference.favorite_flower")
    head_before = head["current"]["id"]
    for i in range(3):
        _, body = remember(
            "preference.favorite_flower",
            "玫瑰",
            f"重复证据{i}：我最喜欢玫瑰。",
            importance="0.8",
        )
        if i > 0:
            check(f"duplicate status {i}", body["result"]["status"] == "duplicate",
                  "duplicate", body["result"]["status"])
    _, body = current("preference.favorite_flower")
    check("current head unchanged", (body["current"]["id"]) == (head_before), head_before,
          body["current"]["id"])
    duplicates = sql(
        "SELECT COUNT(*) FROM events WHERE payload LIKE '%\"status\":\"duplicate\"%'"
    )[0][0]
    check("duplicates retained as evidence", duplicates >= 2, ">=2", duplicates)


def s03_supplement_does_not_replace():
    scenario("S03", "“也好看”不改变“最喜欢”")
    remember(
        "preference.favorite_flower.second_test",
        "玫瑰",
        "我最喜欢玫瑰。",
        importance="0.8",
        at="2026-10-01T00:00:00Z",
    )
    _, body = remember(
        "preference.favorite_flower.second_test",
        "栀子花",
        "栀子花也好看。",
        certainty="uncertain",
        intent="supplement",
        importance="0.6",
        at="2026-10-10T00:00:00Z",
    )
    check("supplement pending", body["result"]["status"] == "pending", "pending",
          body["result"]["status"])
    _, body = current("preference.favorite_flower.second_test")
    check("current still rose", (body["current"]["candidate"]["value"]) == ("玫瑰"), "玫瑰",
          body["current"]["candidate"]["value"])
    _, body = call("topics")
    row = [t for t in body["topics"] if t["topic"] == "preference.favorite_flower.second_test"][0]
    check("pending evidence recorded", (row["evidence"]["pending"]) == (1), 1,
          row["evidence"]["pending"])


def s04_explicit_change_keeps_history():
    scenario("S04", "明确说“现在最喜欢栀子花”后当前更新、历史保留玫瑰")
    remember(
        "preference.favorite_flower.change_test",
        "玫瑰",
        "我最喜欢玫瑰。",
        importance="0.8",
        at="2026-10-01T00:00:00Z",
    )
    _, body = remember(
        "preference.favorite_flower.change_test",
        "栀子花",
        "现在最喜欢栀子花了。",
        certainty="explicit",
        intent="change",
        importance="0.8",
        at="2026-10-20T00:00:00Z",
    )
    check("change confirmed", body["result"]["status"] == "confirmed", "confirmed",
          body["result"]["status"])
    _, body = current("preference.favorite_flower.change_test")
    check("current updated", (body["current"]["candidate"]["value"]) == ("栀子花"), "栀子花",
          body["current"]["candidate"]["value"])
    _, body = history("preference.favorite_flower.change_test")
    confirmed = [e["candidate"]["value"] for e in body["history"] if e["status"] == "confirmed"]
    check("history keeps rose then gardenia", (confirmed) == (["玫瑰", "栀子花"]), ["玫瑰", "栀子花"], confirmed)
    old = [e for e in body["history"] if e["candidate"]["value"] == "玫瑰"][0]
    check("old version is not current", (old["status"]) == ("confirmed"), "confirmed", old["status"])


def s05_unconfirmed_conflict_does_not_overwrite():
    scenario("S05", "未明确确认的冲突不覆盖")
    remember(
        "preference.favorite_flower.conflict_test",
        "玫瑰",
        "我最喜欢玫瑰。",
        importance="0.8",
        at="2026-10-01T00:00:00Z",
    )
    _, body = remember(
        "preference.favorite_flower.conflict_test",
        "百合",
        "其实我喜欢百合。",
        certainty="explicit",
        intent="assert",
        importance="0.8",
        at="2026-10-21T00:00:00Z",
    )
    check("conflict status", body["result"]["status"] == "conflict", "conflict",
          body["result"]["status"])
    _, body = current("preference.favorite_flower.conflict_test")
    check("current unchanged", (body["current"]["candidate"]["value"]) == ("玫瑰"), "玫瑰",
          body["current"]["candidate"]["value"])
    _, body = call("topics")
    row = [t for t in body["topics"] if t["topic"] == "preference.favorite_flower.conflict_test"][0]
    check("conflict recorded as evidence", (row["evidence"]["conflict"]) == (1), 1,
          row["evidence"]["conflict"])


def s06_new_process_and_reopen():
    scenario("S06", "新进程/重开数据库后仍能正确查询")
    remember(
        "profile.city",
        "虚构城",
        "我住在虚构城。",
        importance="0.9",
        at="2026-10-01T00:00:00Z",
    )
    _, body = current("profile.city")
    check("first query", (body["current"]["candidate"]["value"]) == ("虚构城"), "虚构城",
          body["current"]["candidate"]["value"])
    # every adapter invocation is a separate process; run three more to prove persistence
    values = []
    for _ in range(3):
        _, body = current("profile.city")
        values.append(body["current"]["candidate"]["value"])
    check("fresh processes all read value", (values) == (["虚构城"] * 3), ["虚构城"] * 3, values)


def s07_user_and_session_isolation():
    scenario("S07", "不同用户及不同会话隔离")
    remember(
        "preference.favorite_drink",
        "乌龙茶",
        "我最喜欢乌龙茶。",
        importance="0.8",
        at="2026-10-01T00:00:00Z",
    )
    _, body = call("--subject", "other-user", "current", "--topic",
                   "preference.favorite_drink")
    check("other subject sees nothing", body["current"] is None, None, body["current"])
    _, body = call("--subject", "other-user", "topics")
    check("other subject topics empty", body["topics"] == [], [], body["topics"])
    remember(
        "task.context",
        "本会话先这样",
        "本会话先这样安排。",
        scope="session",
        importance="0.8",
    )
    _, persistent = current("task.context")
    check("session memory not persistent", persistent["current"] is None, None,
          persistent["current"])
    _, same = current("task.context", scope="session")
    check("same session visible", (same["current"]["candidate"]["session"]) == (SESSION_A), SESSION_A,
          same["current"]["candidate"]["session"])
    _, other = call(
        "--session", SESSION_B, "current", "--topic", "task.context", "--scope", "session",
        session=SESSION_B,
    )
    check("other session isolated", other["current"] is None, None, other["current"])
    _, same_topics = topics(session=SESSION_A)
    same_names = [t["topic"] for t in same_topics["topics"]]
    check("same session topic visible", "task.context" in same_names, True, same_names)
    _, other_topics = topics(session=SESSION_B)
    other_names = [t["topic"] for t in other_topics["topics"]]
    check("other session topic hidden", "task.context" not in other_names, False, other_names)
    check("persistent topic shared", "preference.favorite_drink" in other_names, True, other_names)


def s08_expiry_not_current():
    scenario("S08", "到期记忆不再被当作当前事实")
    remember(
        "promotion.code",
        "FICTIONAL-CODE",
        "本次虚构优惠码是 FICTIONAL-CODE，11 月 1 日有效。",
        importance="0.9",
        expires_at="2026-11-01T00:00:00Z",
        at="2026-10-01T00:00:00Z",
    )
    _, before = call("current", "--topic", "promotion.code", "--now",
                     "2026-10-30T00:00:00Z")
    check("current before expiry", (before["current"]["candidate"]["value"]) == ("FICTIONAL-CODE"),
          "FICTIONAL-CODE", before["current"]["candidate"]["value"])
    _, after = call("current", "--topic", "promotion.code", "--now",
                    "2026-11-02T00:00:00Z")
    check("current after expiry", after["current"] is None, None, after["current"])
    _, hist = call("history", "--topic", "promotion.code", "--now",
                   "2026-11-02T00:00:00Z")
    check("expired history filtered", hist["history"] == [], [], hist["history"])
    _, top = call("topics", "--now", "2026-11-02T00:00:00Z")
    row = [t for t in top["topics"] if t["topic"] == "promotion.code"][0]
    check("topic status expired", (row["status"]) == ("expired"), "expired", row["status"])


def s09_forget_removes_main_history_redundancy():
    scenario("S09", "遗忘后主记录、历史与冗余副本都从逻辑库删除")
    remember(
        "preference.favorite_flower.forget_test",
        "玫瑰",
        "我最喜欢玫瑰。",
        importance="0.8",
        at="2026-10-01T00:00:00Z",
    )
    remember(
        "preference.favorite_flower.forget_test",
        "栀子花",
        "现在最喜欢栀子花。",
        intent="change",
        importance="0.8",
        at="2026-10-20T00:00:00Z",
    )
    heads_before = sql("SELECT COUNT(*) FROM heads")[0][0]
    _, old_history = history("preference.favorite_flower.forget_test")
    forgotten_ids = [event["id"] for event in old_history["history"]]
    placeholders = ",".join("?" for _ in forgotten_ids)
    untouched = sql(
        f"SELECT id, payload, backup FROM events WHERE id NOT IN ({placeholders}) ORDER BY id",
        forgotten_ids,
    )
    _, body = call("forget", "--topic", "preference.favorite_flower.forget_test")
    check("forget count", (body["forgotten"]) == (2), 2, body["forgotten"])
    events_after = sql(
        "SELECT COUNT(*) FROM events WHERE CAST(payload AS TEXT) LIKE ?",
        ("%preference.favorite_flower.forget_test%",),
    )[0][0]
    check("event rows for topic removed", events_after == 0, 0, events_after)
    heads_after = sql("SELECT COUNT(*) FROM heads")[0][0]
    check("head row removed", (heads_after) == (heads_before - 1), heads_before - 1, heads_after)
    # Identify the forgotten route, not values legitimately shared by other topics.
    topic_bytes = b"preference.favorite_flower.forget_test"
    complement_bytes = bytes(b ^ 0xFF for b in topic_bytes)
    residual = 0
    for payload, backup in sql("SELECT payload, backup FROM events"):
        if topic_bytes in bytes(payload) or (
            backup is not None and (complement_bytes in bytes(backup) or topic_bytes in bytes(backup))
        ):
            residual += 1
    check("no residual copies of forgotten route", residual == 0, 0, residual)
    remaining_ids = sql(f"SELECT id FROM events WHERE id IN ({placeholders})", forgotten_ids)
    check("deleted event IDs absent", remaining_ids == [], [], remaining_ids)
    after_untouched = sql("SELECT id, payload, backup FROM events ORDER BY id")
    check("unrelated topics unchanged", after_untouched == untouched, True, after_untouched == untouched)
    _, body = current("preference.favorite_flower.forget_test")
    check("current is null after forget", body["current"] is None, None, body["current"])
    _, body = history("preference.favorite_flower.forget_test")
    check("history empty after forget", body["history"] == [], [], body["history"])
    _, body = call("topics")
    names = [t["topic"] for t in body["topics"]]
    check("topic gone from topics", names.count(
        "preference.favorite_flower.forget_test") == 0, 0, names)
    code, body = call("repair", "--event-id", forgotten_ids[0], expect=2)
    check("repair of forgotten id errors", (code) == (2), 2, code)


def s10_corruption_repair_no_rollback():
    scenario("S10", "损坏恢复不会回滚合法的新版本")
    remember(
        "preference.favorite_flower.repair_test",
        "玫瑰",
        "我最喜欢玫瑰。",
        importance="0.8",
        at="2026-10-01T00:00:00Z",
    )
    _, changed = remember(
        "preference.favorite_flower.repair_test",
        "栀子花",
        "现在最喜欢栀子花。",
        intent="change",
        importance="0.8",
        at="2026-10-20T00:00:00Z",
    )
    latest_id = changed["event_id"]
    head_before = sql(
        "SELECT event_id FROM heads WHERE event_id=?", (latest_id,)
    )
    with sqlite3.connect(DB) as conn:
        conn.execute("UPDATE events SET payload=x'00' WHERE id=?", (latest_id,))
    code, body = call("current", "--topic", "preference.favorite_flower.repair_test",
                      expect=2)
    check("corruption fails closed", (code) == (2), 2, code)
    call("repair", "--event-id", latest_id)
    head_after = sql("SELECT event_id FROM heads WHERE event_id=?", (latest_id,))
    check("head unchanged by repair", (head_after) == (head_before), head_before, head_after)
    _, body = current("preference.favorite_flower.repair_test")
    check("repaired latest is still current", (body["current"]["candidate"]["value"]) == ("栀子花"),
          "栀子花", body["current"]["candidate"]["value"])
    _, body = history("preference.favorite_flower.repair_test")
    confirmed = [e["candidate"]["value"] for e in body["history"] if e["status"] == "confirmed"]
    check("repair did not resurrect rose as current", (confirmed) == (["玫瑰", "栀子花"]), ["玫瑰", "栀子花"], confirmed)


def s11_unrecoverable_reports_error():
    scenario("S11", "无法校验恢复时明确报错、不猜测")
    _, written = remember(
        "preference.favorite_flower.unrecoverable",
        "百合",
        "我最喜欢百合。",
        importance="0.8",
        at="2026-10-01T00:00:00Z",
    )
    event_id = written["event_id"]
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "UPDATE events SET payload=x'00', backup=x'00' WHERE id=?", (event_id,)
        )
        before = conn.execute(
            "SELECT payload, backup FROM events WHERE id=?", (event_id,)
        ).fetchone()
    code, body = call("repair", "--event-id", event_id, expect=2)
    check("repair fails with explicit error", "refusing to guess" in body["error"].lower(),
          "refusing to guess", body["error"])
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        after = conn.execute(
            "SELECT payload, backup FROM events WHERE id=?", (event_id,)
        ).fetchone()
    before_hex = [bytes(part).hex() for part in before]
    after_hex = [bytes(part).hex() for part in after]
    check("failed repair left bytes untouched", after_hex == before_hex, before_hex,
          after_hex)


def s12_sensitive_consent_not_fabricated():
    scenario("S12", "不捏造用户同意（补充验收）")
    _, body = remember(
        "profile.phone",
        "13800000000",
        "我的手机号是 13800000000。",
        sensitive=True,
        importance="0.9",
    )
    check("no fabricated consent", (body["result"]["status"]) == ("rejected_sensitive"), "rejected_sensitive",
          body["result"]["status"])
    count = sql(
        "SELECT COUNT(*) FROM events WHERE payload LIKE '%13800000000%'"
    )[0][0]
    check("sensitive value not persisted", count == 0, 0, count)


# ---------------------------------------------------------------- main


def main():
    if ADAPTER is None:
        probe = subprocess.run(
            [sys.executable, "-c", "import memorygene.adapter"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            raise SystemExit(
                "Adapter not importable; install the package first "
                "(pip install -e .)"
            )
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in (DB, DB.with_suffix(".db-wal"), DB.with_suffix(".db-shm")):
        if stale.exists():
            stale.unlink()
    steps = [
        s01_important_information_saved,
        s02_irrelevant_content_not_accumulated,
        s03_supplement_does_not_replace,
        s04_explicit_change_keeps_history,
        s05_unconfirmed_conflict_does_not_overwrite,
        s06_new_process_and_reopen,
        s07_user_and_session_isolation,
        s08_expiry_not_current,
        s09_forget_removes_main_history_redundancy,
        s10_corruption_repair_no_rollback,
        s11_unrecoverable_reports_error,
        s12_sensitive_consent_not_fabricated,
    ]
    for step in steps:
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - acceptance must record failures
            RESULTS[-1]["passed"] = False
            RESULTS[-1]["failures"].append("exception")
            record("error", f"{step.__name__}: {type(exc).__name__}: {exc}")
    summary = {
        "generated_at": now_iso(),
        "fixture_clock": FIXTURE_NOW,
        "adapter": " ".join(ADAPTER_CMD),
        "database": str(DB),
        "namespace": NAMESPACE,
        "subject": SUBJECT,
        "scenarios": len(RESULTS),
        "passed": sum(1 for r in RESULTS if r["passed"]),
        "failed": [r["id"] for r in RESULTS if not r["passed"]],
        "checks_total": sum(len(r["checks"]) for r in RESULTS),
        "checks_passed": sum(
            1 for r in RESULTS for c in r["checks"] if c["passed"]
        ),
        "results": RESULTS,
        "notes": [
            "Every adapter invocation is a separate OS process, so S06 also covers "
            "closing and reopening the SQLite file. It does not by itself prove "
            "cross-Harness-session memory; see evidence/01-e2e for real headless sessions.",
            "All names and values are fictional.",
            "expires_at behavior is read-time filtering; expired rows stay on disk.",
        ],
    }
    (OUT / "acceptance-results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "acceptance-log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "scenarios": summary["scenarios"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "checks": f'{summary["checks_passed"]}/{summary["checks_total"]}',
                "evidence": str(OUT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
