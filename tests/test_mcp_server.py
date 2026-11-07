"""The MCP server speaks JSON-RPC over stdio and reuses the adapter's checks."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "m.db")
        env = dict(os.environ, PYTHONPATH=SRC)
        env.pop("DSH_SESSION_ID", None)
        from memorygene import MemoryStore
        MemoryStore(self.db).close()  # create an empty store explicitly
        self.env = env

    def session(self, *messages):
        lines = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
        out = subprocess.run([sys.executable, "-m", "memorygene.mcp_server", "--db", self.db,
                              "--namespace", "t", "--subject", "u"],
                             input=lines, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return [json.loads(line) for line in out.stdout.splitlines()]

    def call(self, mid, name, arguments):
        return {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}}

    def test_handshake_listing_and_round_trip(self):
        replies = self.session(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            self.call(3, "memory_remember", {"topic": "preference.favorite_flower", "value": "玫瑰",
                                             "source": "我最喜欢玫瑰"}),
            self.call(4, "memory_remember", {"topic": "preference.favorite_flower", "value": "百合",
                                             "source": "可能更喜欢百合", "certainty": "uncertain"}),
            self.call(5, "memory_current", {"topic": "preference.favorite_flower"}),
            self.call(6, "memory_recall", {"query": "百合"}),
        )
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4, 5, 6])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "memorygene")
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertIn("memory_remember", names)
        body = lambda r: json.loads(r["result"]["content"][0]["text"])  # noqa: E731
        self.assertEqual(body(replies[2])["result"]["status"], "confirmed")
        self.assertEqual(body(replies[3])["result"]["status"], "pending")
        current = body(replies[4])
        self.assertEqual((current["current"]["candidate"]["value"], current["evidence"]["source"]),
                         ("玫瑰", "我最喜欢玫瑰"))
        self.assertEqual([u["preview"] for u in body(replies[5])["unresolved"]], ["百合"])

    def test_impression_with_a_list_of_citations(self):
        body = lambda r: json.loads(r["result"]["content"][0]["text"])  # noqa: E731
        first = self.session(self.call(1, "memory_remember", {
            "topic": "preference.favorite_sport", "value": "攀岩", "source": "我最喜欢攀岩"}))
        event = body(first[0])["event_id"]
        replies = self.session(
            self.call(2, "memory_impression_save", {"text": "喜欢攀岩", "cite": [event]}),
            self.call(3, "memory_impressions", {"current_only": True}),
            self.call(4, "memory_impression_forget", {"all": True}),
        )
        self.assertEqual(body(replies[0])["result"]["status"], "current")
        self.assertEqual(len(body(replies[1])["impressions"]), 1)
        self.assertEqual(body(replies[2])["forgotten"], 1)

    def test_errors_are_reported_not_fatal(self):
        replies = self.session(
            self.call(1, "memory_remember", {"topic": "Bad Topic", "value": "x", "source": "x"}),
            self.call(2, "memory_remember", {"topic": "a.b", "value": "x", "source": "x",
                                             "certainty": "sure"}),
            self.call(3, "no_such_tool", {}),
            {"jsonrpc": "2.0", "id": 4, "method": "no/such"},
        )
        self.assertTrue(all(r["result"]["isError"] for r in replies[:3]))
        self.assertEqual(replies[3]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
