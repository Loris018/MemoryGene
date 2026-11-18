#!/usr/bin/env python3
"""Two real DSH sessions testing explicit task save/resume on a new synthetic DB.

Uses the existing account patch, never changes credentials/profile configuration.
Each run gets a new directory. Raw streams contain only this fictional test.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import e2e_harness as harness

from memorygene import MemoryStore, tasks


def returned_checkpoint(events, checkpoint_id):
    """Check actual completed tool output, not just model prose or a tool call."""
    calls = {
        event.get("callId")
        for event in events
        if event.get("type") == "tool_call"
        and event.get("tool") == "bash"
        and "task-resume" in event.get("input", {}).get("command", "")
        and checkpoint_id in event.get("input", {}).get("command", "")
    }
    for event in events:
        if (
            event.get("type") != "tool_result"
            or event.get("status") != "completed"
            or event.get("callId") not in calls
        ):
            continue
        try:
            raw = event.get("result", "").lstrip()
            body, end = json.JSONDecoder().raw_decode(raw)
            # DSH bash appends an exit marker after stdout JSON.
            if raw[end:].strip() not in {"", "---exit:0"}:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        if not isinstance(body, dict):
            continue
        result = body.get("result", {})
        if not isinstance(result, dict) or not isinstance(
            result.get("checkpoint"), dict
        ):
            continue
        if (
            body.get("ok") is True
            and body.get("command") == "task-resume"
            and result.get("status") == "review_required"
            and result.get("checkpoint_id") == checkpoint_id
            and result.get("checkpoint", {}).get("id") == checkpoint_id
        ):
            return True
    return False


def main():
    run = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")
    harness.OUT = harness.PROJECT / "evidence/08-tasks/harness" / run
    harness.DB = harness.OUT / "synthetic.db"
    harness.NAMESPACE = "task-harness-fixture"
    harness.SUBJECT = "fictional-user"
    harness.TIMEOUT = 240
    harness.OUT.mkdir(parents=True, exist_ok=False)
    with MemoryStore(harness.DB):
        pass
    sessions, checks = [], {}
    try:
        a = harness.run_session(
            "A-save",
            """这是隔离的虚构验收，请使用 memorygene skill，读取任务接续说明。
已有 MEMORYGENE_DB/NAMESPACE/SUBJECT 环境覆盖；doctor 显示的测试库是唯一允许使用的库，禁止使用生产库。
虚构任务：设计一个蓝色纸盒；约束：只做纸模型；尚未完成：测试承重；下一步：用虚构数据列承重测试计划。
请保存一份带来源的任务接续记录，任务名为 paper-box。来源使用本条用户消息的位置，标明未独立验证。
用 task-save 保存，再用 task-show 核对，并删除自己创建的临时输入文件。不能把未完成事项写成已完成。
只用宿主真实 DSH_SESSION_ID，不要捏造 session；缺失则报告错误。不要写长期 remember，不要声称上下文已经替换。
最终简短报告真实 checkpoint_id。""",
        )
        sessions.append(a)
        checks["save_session_completed"] = a["exit"] == 0 and bool(a["session_id"])
        checks["save_skill_and_adapter_completed"] = all(a["tool_evidence"].values())
        if not all(checks.values()):
            raise RuntimeError("Save session did not complete its real tool calls")
        with MemoryStore(harness.DB) as store:
            shown = tasks.show(
                store, harness.NAMESPACE, harness.SUBJECT, "paper-box", a["session_id"]
            )
            checks["saved_in_actual_session"] = shown["status"] == "review_required"
            if not checks["saved_in_actual_session"]:
                raise RuntimeError("No task checkpoint for actual Harness session")
            checkpoint_id = shown["checkpoint_id"]
            items = shown["checkpoint"]["document"]["items"]
            checks["goal_preserved"] = any(
                i["kind"] == "goal" and "纸盒" in i["text"] for i in items
            )
            checks["constraint_preserved"] = any(
                i["kind"] == "constraint" and "纸模型" in i["text"] for i in items
            )
            checks["pending_not_promoted"] = any(
                i["kind"] in {"todo", "open_question", "next_step"}
                and "承重" in i["text"]
                for i in items
            ) and not any(i["kind"] == "done" and "承重" in i["text"] for i in items)
            checks["no_long_term_fact_written"] = (
                store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
            )
            before = hashlib.sha256("\n".join(store.db.iterdump()).encode()).hexdigest()
        if not all(checks.values()):
            raise RuntimeError("Checkpoint content or isolation check failed")
        b = harness.run_session(
            "B-resume",
            f"""这是同一虚构测试的新会话，请使用 memorygene skill。
环境变量已指向隔离测试库，禁止使用生产库。用户明确授权：将 checkpoint_id 为 {checkpoint_id} 的任务记录读入当前会话。
按任务接续说明，用 task-resume 和 --allow-cross-session 读取，不要改写 session。
核对后报告目标、约束、未完成事项与下一步，并说明对话来源仍需核对。只读，不另存、不写长期事实，不执行任务，不声称自动压缩成功。""",
        )
        sessions.append(b)
        checks["resume_session_completed"] = (
            b["exit"] == 0
            and bool(b["session_id"])
            and b["session_id"] != a["session_id"]
        )
        checks["resume_skill_and_adapter_completed"] = all(b["tool_evidence"].values())
        raw_events = [
            json.loads(line)
            for line in Path(b["events_file"]).read_text().splitlines()
            if line.startswith("{")
        ]
        completed = {
            event.get("callId")
            for event in raw_events
            if event.get("type") == "tool_result" and event.get("status") == "completed"
        }
        checks["explicit_resume_tool_completed"] = any(
            call.get("callId") in completed
            and call.get("tool") == "bash"
            and "task-resume" in call.get("input", {}).get("command", "")
            and checkpoint_id in call.get("input", {}).get("command", "")
            and "--allow-cross-session" in call.get("input", {}).get("command", "")
            for call in b["tool_calls"]
        )
        checks["resume_returned_expected_record"] = returned_checkpoint(
            raw_events, checkpoint_id
        )
        checks["answer_contains_task_and_constraint"] = (
            "纸盒" in b["final_text"]
            and "纸模型" in b["final_text"]
            and "承重" in b["final_text"]
        )
        with MemoryStore(harness.DB) as store:
            after = hashlib.sha256("\n".join(store.db.iterdump()).encode()).hexdigest()
            checks["resume_did_not_write"] = before == after
    except Exception as exc:
        checks["exception"] = False
        error = f"{type(exc).__name__}: {exc}"
    else:
        error = None
    report = {
        "passed": bool(checks) and all(value is True for value in checks.values()),
        "checks": checks,
        "sessions": sessions,
        "error": error,
        "scope": "Explicit Skill + CLI, two fictional headless sessions. No GUI, automatic compaction or native context switching test.",
    }
    path = harness.OUT / "summary.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {"passed": report["passed"], "checks": checks, "summary": str(path)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
