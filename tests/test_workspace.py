import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from memorygene import project, turns, workspace


class TaskWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "memory.sqlite"
        project.init(self.path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        workspace.migrate(self.db)

    def write(self, item, value, version=0, **overrides):
        data = dict(
            task="widgets",
            item=item,
            value=value,
            quote=value,
            expected_version=version,
            kind="step",
            state="planned",
            speaker="user",
            certainty="explicit",
        )
        data.update(overrides)
        return project.invoke(self.path, "gpt", "task_record", data)

    def call(self, name, **kwargs):
        return project.invoke(self.path, "gpt", name, kwargs)

    def test_semantic_routing_preferences_and_ambiguity(self):
        self.write("goal", "开发库存导出代码", kind="goal", state="active")
        self.write(
            "goal", "讲解微积分课件", task="calculus", kind="goal", state="active"
        )
        self.write(
            "detail",
            "concise answers",
            task="defaults",
            kind="preference",
            state="active",
        )
        self.write(
            "detail",
            "include a worked example",
            task="calculus",
            kind="preference",
            state="active",
        )
        self.assertEqual(self.call("task_resume", query="库存导出")["mode"], "coding")
        lesson = self.call("task_resume", query="继续微积分课件")
        self.assertEqual((lesson["task"], lesson["mode"]), ("calculus", "study"))
        self.assertEqual(lesson["preferences"]["detail"]["scope"], "calculus")
        self.assertEqual(
            self.call("task_resume", query="继续昨天那个")["status"], "choose_task"
        )
        self.assertNotEqual(
            self.call("task_resume", query="开始名为 orchard 的项目任务")["status"],
            "ready",
        )

    def test_paged_recovery_and_transitive_impact(self):
        self.write("limit", "capacity")
        self.write("export", "prepare export", depends_on=["limit"])
        self.write("print", "deliver export", depends_on=["export"])
        self.write("limit", "new capacity", 1)
        self.assertIn(
            "limit", self.call("task_related", task="widgets", item="print")["changed"]
        )
        with self.assertRaises(ValueError):
            self.write("limit", "cycle", 2, depends_on=["print"])
        for i in range(12):
            self.write(f"memo{i}", "other step")
        pages = []
        cursor = ""
        while True:
            p = self.call(
                "task_check",
                task="widgets",
                seen={"export": 1, "print": 1, "limit": 1},
                after=cursor,
            )
            pages.extend(p["entries"])
            cursor = p["next_cursor"]
            if not cursor:
                break
        self.assertEqual(len(pages), 15)
        self.assertTrue(
            next(r for r in pages if r["item"] == "print")["review_required"]
        )

    def test_precapture_then_confirm_deletes_excerpts(self):
        self.write("goal", "widgets coding", kind="goal", state="active")

        def send(i, msg, role="user"):
            return turns.turn(self.db, "gpt", "session", str(i), role, msg)

        send(1, "widgets has two editions")
        send(2, "which one?", "assistant")
        pending = send(3, "change widgets to A2")["pending_clip"]
        send(4, "only the printed edition")
        samples = self.call("task_clip", task="widgets", clip=pending, action="read")[
            "samples"
        ]
        self.assertEqual(
            [s["role"] for s in samples], ["user", "assistant", "user", "user"]
        )
        with self.assertRaises(ValueError):
            self.write("paper", "unsupported quote", clip=pending)
        self.write(
            "paper", "A2 print only", clip=pending, quote="only the printed edition"
        )
        with self.assertRaises(ValueError):
            self.call("task_clip", task="widgets", clip=pending, action="read")
        self.assertEqual(
            self.db.execute("SELECT recent FROM capture_stream").fetchone()[0], "[]"
        )

    def test_retention_and_incremental_step(self):
        self.write("goal", "widgets code", kind="goal", state="active")
        now = int(time.time())

        def event(i, text, role="user"):
            return turns.turn(self.db, "gpt", "s", str(i), role, text, now + i)

        event(0, "resume widgets")
        step = event(1, "Next: count the widgets")["recorded_step"]
        event(2, "Done: count the widgets", "assistant")
        current = workspace.current(self.db, "widgets", step)
        self.assertEqual(
            (current["version"], current["speaker"], current["state"]),
            (2, "assistant", "done"),
        )
        event(3, "change widgets to blue")
        with self.db:
            turns.clean(self.db, now + 305)
        for table in ("capture_clip", "capture_stream"):
            self.assertEqual(
                self.db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0
            )

    def test_uncertain_and_conflicting_options(self):
        self.write("format", "plain")
        result = self.write("format", "JSON", 1, quote="Maybe JSON would work")
        self.assertEqual(result["status"], "pending")
        option = self.call(
            "task_propose",
            task="widgets",
            item="format",
            value="JSON",
            quote="I suggest JSON",
        )
        self.write(
            "format",
            "JSON",
            1,
            quote="We choose JSON",
            proposal=option["options"][0]["id"],
        )
        self.assertFalse(
            self.call("task_propose", task="widgets", item="format")["options"]
        )
        self.assertEqual(
            self.call("project_history", task="widgets", item="format")["versions"][1][
                "value"
            ],
            "plain",
        )

    def test_legacy_decisions_and_migration(self):
        with self.db:
            self.db.execute("DELETE FROM card_terms")
            self.db.execute("PRAGMA user_version=0")
            self.db.execute(
                "INSERT INTO versions VALUES('legacy','topic',1,'rareword','source','dsh')"
            )
            self.db.execute("INSERT INTO heads VALUES('legacy','topic',1)")
        packet = self.call("task_resume", query="rareword")
        self.assertEqual(packet["entries"][0]["writer_client"], "dsh")
        self.assertEqual(packet["entries"][0]["kind"], "decision")

    def test_closed_goal_and_context_repair(self):
        self.write("goal", "copper ledger", kind="goal", state="active")
        self.write("rule", "only for print")
        packet = self.call(
            "task_check",
            task="widgets",
            seen={"goal": 1, "rule": 1},
            remembered={"rule": "for all editions"},
        )
        self.assertEqual([r["item"] for r in packet["entries"]], ["rule"])
        self.write("goal", "finished copper ledger", 1, kind="goal", state="done")
        self.assertEqual(self.call("task_resume", task="widgets")["status"], "done")
        self.assertNotEqual(
            self.call("task_resume", query="copper ledger")["status"], "ready"
        )

    def test_bound_native_hooks_support_workspaces_with_spaces(self):
        import json
        import subprocess
        import sys

        folder = Path(self.tmp.name) / "working space & notes"
        binder = Path(__file__).resolve().parents[1] / "scripts" / "bind_project.py"
        cmd = [
            sys.executable,
            str(binder),
            "--workspace",
            str(folder),
            "--db",
            str(self.path),
            "--grok",
            "--turn-hooks",
        ]
        subprocess.run(cmd, check=True)
        subprocess.run(cmd, check=True)
        self.write("goal", "widgets coding", kind="goal", state="active")
        for conf in (
            folder / ".codex/hooks.json",
            folder / ".grok/hooks/mg_project.json",
        ):
            hooks = json.loads(conf.read_text())["hooks"]["UserPromptSubmit"]
            self.assertEqual(len(hooks), 1)
            proc = subprocess.run(
                hooks[0]["hooks"][0]["command"],
                shell=True,
                cwd=folder,
                input=json.dumps(
                    {
                        "session_id": "one",
                        "turn_id": "one",
                        "hook_event_name": "UserPromptSubmit",
                        "prompt": "resume widgets",
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(
                "widgets",
                json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"],
            )
        self.assertTrue((folder / ".memorygene/start-dsh-turns").is_file())

    def test_erasure_does_not_resurrect_a_stale_write(self):
        self.write("format", "red")
        self.write("export", "prepare file", depends_on=["format"])
        self.assertEqual(
            self.call("task_remove", task="widgets", item="format", expected_version=1)[
                "version"
            ],
            2,
        )
        self.assertEqual(self.write("format", "stale", 1)["status"], "conflict")
        self.assertEqual(
            self.call("project_history", task="widgets", item="format")["versions"], []
        )
        check = self.call("task_check", task="widgets", seen={"format": 1, "export": 1})
        self.assertEqual(check["removed"], ["format"])
        self.assertTrue(check["entries"][0]["review_required"])
        self.assertEqual(self.write("format", "fresh", 2)["version"], 3)

    def test_mode_scoped_preferences_and_similar_key_warning(self):
        self.write("goal", "开发库存导出代码", kind="goal", state="active")
        self.write(
            "coding.testing",
            "always run pytest before reporting done",
            task="defaults",
            kind="preference",
            state="active",
        )
        self.write(
            "study.depth",
            "explain intuition before formulas",
            task="defaults",
            kind="preference",
            state="active",
        )
        self.write("prod_log_days", "keep 30 days", kind="decision", state="active")
        dup = self.write("log_days_prod", "keep 30 days", kind="decision", state="active")
        self.assertIn("prod_log_days", dup.get("similar_items", []))
        coding_packet = self.call("task_resume", query="库存导出")
        self.assertIn("coding.testing", coding_packet["preferences"])
        self.assertNotIn("study.depth", coding_packet["preferences"])

    def test_query_relevant_entries_prioritized_in_turns(self):
        self.write("goal", "widgets coding", kind="goal", state="active")
        for i in range(10):
            self.write(f"alpha_{i:02d}", f"routine step {i}")
        self.write("zebra_cache", "redis cache ttl 60s", kind="decision", state="active")
        packet = turns.turn(
            self.db, "gpt", "s_rel", "ev1", "user", "widgets redis cache"
        )
        self.assertEqual(packet["entries"][0][0], "zebra_cache")
