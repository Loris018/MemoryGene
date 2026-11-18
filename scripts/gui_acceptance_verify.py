#!/usr/bin/env python3
"""Verify the prepared GUI acceptance workspace at each phase.

The human still has to send the messages in the DeepSeek Harness GUI; this
script records machine-checkable evidence from the isolated test database and
never touches the production memory database.

Phases:
  preflight  workspace/config/db/skill ready and DB empty
  after-a    session A: current favorite flower == 玫瑰
  after-b    session B: current == 栀子花, confirmed history == 玫瑰 → 栀子花
  after-c    session C: current is null and the topic is gone
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = PROJECT.parent / "MemoryGene-GUI-test-2026-10-27"
ADAPTER = PROJECT / ".venv" / "bin" / "memorygene-dsh"
TOPIC = "preference.favorite_flower"


def adapter(config, *args):
    result = subprocess.run(
        [str(ADAPTER), "--config", str(config), *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT),
    )
    raw = result.stdout.strip() or result.stderr.strip()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {"_raw": raw}
    return result.returncode, body


def db_count(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def check(name, passed, expected, actual):
    if type(passed) is not bool:
        raise TypeError("predicate must be bool")
    return {"name": name, "passed": passed, "expected": expected, "actual": actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True,
                        choices=["preflight", "after-a", "after-b", "after-c"])
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE))
    parser.add_argument("--out", default=str(PROJECT / "evidence/10-gui-acceptance"))
    args = parser.parse_args()
    workspace = Path(args.workspace).expanduser()
    config = workspace / ".memorygene" / "dsh.json"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    if not config.is_file():
        print(f"Missing workspace config: {config}")
        return 2
    db = json.loads(config.read_text(encoding="utf-8")).get("db")
    code, doctor = adapter(config, "doctor")
    checks.append(check("adapter doctor exit", code == 0, 0, code))
    checks.append(check("database configured", bool(db), True, db))
    checks.append(check("isolated namespace", doctor.get("namespace") == "gui-acceptance", "gui-acceptance",
                        doctor.get("namespace")))
    checks.append(check("isolated subject", doctor.get("subject") == "fictional-user", "fictional-user",
                        doctor.get("subject")))
    checks.append(check("production DB not used", str(db).endswith("gui-test.db"), True, db))
    skill_project = workspace / ".dsh" / "skills" / "memorygene" / "SKILL.md"
    skill_user = Path.home() / ".dsh" / "skills" / "memorygene" / "SKILL.md"
    checks.append(check("project skill present", skill_project.is_file(), True, str(skill_project)))
    checks.append(check("user skill present", skill_user.is_file(), True, str(skill_user)))
    if args.phase == "preflight":
        checks.append(check("test DB exists", Path(db).is_file(), True, db))
        checks.append(check("test DB empty", db_count(db) == 0, 0, db_count(db)))
    elif args.phase == "after-a":
        _, body = adapter(config, "current", "--topic", TOPIC)
        current = body.get("current")
        value = current["candidate"]["value"] if current else None
        checks.append(check("current after session A", value == "玫瑰", "玫瑰", value))
    elif args.phase == "after-b":
        _, cur = adapter(config, "current", "--topic", TOPIC)
        _, hist = adapter(config, "history", "--topic", TOPIC)
        current = cur.get("current")
        value = current["candidate"]["value"] if current else None
        confirmed = [e["candidate"]["value"] for e in hist.get("history", []) if e["status"] == "confirmed"]
        checks.append(check("current after session B", value == "栀子花", "栀子花", value))
        checks.append(check("confirmed history after session B", confirmed == ["玫瑰", "栀子花"],
                            ["玫瑰", "栀子花"], confirmed))
    else:
        _, cur = adapter(config, "current", "--topic", TOPIC)
        _, topics = adapter(config, "topics")
        names = [t["topic"] for t in topics.get("topics", [])]
        checks.append(check("current after forget", cur.get("current") is None, None, cur.get("current")))
        checks.append(check("topic gone after forget", TOPIC not in names, True, names))
    passed = all(c["passed"] for c in checks)
    report = {
        "phase": args.phase,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "database": db,
        "passed": passed,
        "checks": checks,
        "note": "Human GUI messages are still required; this only checks the isolated DB state.",
    }
    path = out / f"{args.phase}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": args.phase, "passed": passed, "evidence": str(path),
                      "failed": [c["name"] for c in checks if not c["passed"]]}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
