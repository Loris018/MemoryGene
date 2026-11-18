import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from memorygene.project import init, invoke, project_rpc


class SharedProjectTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.db = Path(self.scratch.name) / "store.sqlite"
        init(self.db)
        self.item = {"task": "poster", "item": "paper_size"}

    def write(self, client, args, current, value):
        return invoke(
            self.db,
            client,
            "project_update",
            {
                **args,
                "expected_version": current,
                "value": value,
                "quote": "Use " + value,
            },
        )

    def test_competing_edits_and_unrelated_decisions(self):
        self.write("dsh", self.item, 0, "A0")
        barrier = threading.Barrier(2)

        def compete(client):
            barrier.wait(timeout=3)
            return self.write(client, self.item, 1, client)

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(compete, ["claude", "kimi"]))
        self.assertEqual(sorted(r["status"] for r in results), ["conflict", "saved"])
        self.write("gpt", {**self.item, "item": "edition"}, 0, "print")
        history = invoke(self.db, "dsh", "project_history", self.item)["versions"]
        self.assertEqual([r["version"] for r in history], [2, 1])
        self.assertEqual(history[1]["quote"], "Use A0")
        self.assertIn(history[0]["client"], {"claude", "kimi"})

    def test_project_isolation_and_refusal_to_create_on_read(self):
        fresh = self.db.with_name("other.sqlite")
        self.write("dsh", self.item, 0, "A0")
        with self.assertRaises(sqlite3.Error):
            invoke(fresh, "kimi", "project_read", self.item)
        self.assertFalse(fresh.exists())
        init(fresh)
        self.assertEqual(
            invoke(fresh, "kimi", "project_read", self.item)["records"], []
        )
        with self.assertRaises(FileExistsError):
            init(self.db)

    def test_tool_error_does_not_change_decision(self):
        self.write("dsh", self.item, 0, "A0")
        args = {**self.item, "expected_version": 0, "value": "A1", "quote": "Use A1"}
        msg = {
            "id": 1,
            "method": "tools/call",
            "params": {"name": "project_update", "arguments": args},
        }
        self.assertTrue(project_rpc(msg, (self.db, "gpt"))["isError"])
        args["db"] = "/wrong-file"
        self.assertTrue(project_rpc(msg, (self.db, "gpt"))["isError"])
        self.assertEqual(
            invoke(self.db, "kimi", "project_read", self.item)["records"][0]["version"],
            1,
        )
