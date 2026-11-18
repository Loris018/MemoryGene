"""Behavioral guarantees for scoped, budgeted memory discovery."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene.codec import IntegrityError
from memorygene.core import canonical
from memorygene.recall import recall

NOW = "2026-10-28T12:00:00Z"
OLD = "2020-01-01T00:00:00Z"


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.close)

    def add(self, topic, value, **overrides):
        fields = dict(namespace="test", subject="fiction", topic=topic,
                      value=value, source=f"虚构用户：{value}", at=OLD)
        fields.update(overrides)
        event_id = f"event-{self.store.db.execute('select count(*) from events').fetchone()[0]}"
        return self.store.ingest(Candidate(**fields), event_id, now=NOW)

    def query(self, query, **kwargs):
        return recall(self.store, "test", "fiction", query, now=NOW, **kwargs)

    def test_old_rare_fact_survives_recent_distractors_and_is_read_only(self):
        saved = self.add("storage.family_album", "童年相册保存在老屋阁楼蓝色箱子里")
        for i in range(30):
            self.add(f"recent.item{i}", f"今天喝茶第{i}杯", at=NOW)
        before = list(self.store.db.iterdump())
        results = [self.query("童年相册在哪") for _ in range(3)]
        self.assertEqual([m["id"] for m in results[0]["matches"]], [saved["id"]])
        self.assertEqual(results[0], results[2])
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_current_only_no_old_pending_conflicting_or_expired_facts(self):
        self.add("flower.favorite", "玫瑰")
        current = self.add("flower.favorite", "桂花", intent="change", at=NOW)
        self.add("flower.favorite", "牡丹", at=NOW)
        self.add("flower.maybe", "玫瑰", certainty="uncertain")
        self.add("flower.expired", "玫瑰", expires_at="2026-01-01T00:00:00Z",
                 at=OLD)  # ingest rejects already expired input
        self.assertFalse(self.query("玫瑰 牡丹")["matches"])
        self.assertEqual(self.query("桂花")["matches"][0]["id"], current["id"])
        # Also check evidence that was live when stored and expires on reads.
        self.store.ingest(Candidate("test", "fiction", "flower.ttl", "玫瑰", "玫瑰", OLD,
                                    expires_at="2021-01-01T00:00:00Z"), "ttl", now=OLD)
        self.assertFalse(self.query("玫瑰")["matches"])

    def test_user_namespace_and_session_filter_before_payload_decode(self):
        shared = self.add("shared.flower", "桂花")
        a = self.add("task.flower", "桂花", scope="session", session="A")
        b = self.add("task.flower", "桂花", scope="session", session="B")
        foreign = self.add("other.flower", "桂花", subject="other")
        self.add("ns.flower", "桂花", namespace="other")
        self.store.db.execute("UPDATE events SET payload=? WHERE id IN (?,?)",
                              (b"corrupt-private", b["id"], foreign["id"]))
        self.assertEqual({m["id"] for m in self.query("桂花")["matches"]}, {shared["id"]})
        self.assertEqual({m["id"] for m in self.query("桂花", visible_session="A")["matches"]},
                         {shared["id"], a["id"]})
        with self.assertRaises(IntegrityError):
            self.query("桂花", visible_session="B")

    def test_hard_budget_unicode_escaping_limits_and_truncation(self):
        for i in range(12):
            self.add(f"flower.item{i}", '桂花"\\\n' * 100)
        for budget in (256, 500, 1000, 2000):
            result = self.query("桂花", budget_chars=budget, limit=3)
            self.assertLessEqual(len(canonical(result)) + 1, budget)
            self.assertLessEqual(len(result["matches"]), 3)
            self.assertEqual(result["matched"], 12)
            self.assertEqual(result["omitted"], 12 - len(result["matches"]))
            self.assertTrue(all(m["preview_truncated"] for m in result["matches"]))

    def test_lexical_english_normalization_source_cues_and_no_semantic_claim(self):
        self.add("project.runtime", "Python", source="虚构项目：使用 Python 编写月报")
        self.assertTrue(self.query("ＰＹＴＨＯＮ")["matches"])
        source_match = self.query("月报")["matches"][0]
        self.assertEqual(source_match["matched_fields"], ["source"])
        self.assertFalse(self.query("蟒蛇")["matches"])

    def test_forget_removes_recall_without_stale_index_or_cache(self):
        self.add("flower.favorite", "桂花")
        self.assertTrue(self.query("桂花")["matches"])
        self.store.forget("test", "fiction", "flower.favorite")
        self.assertFalse(self.query("桂花")["matches"])

    def test_invalid_queries_and_bounds(self):
        for query in ("", "   ", "...", "x" * 1001, None):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.query(query)
        for options in ({"limit": 0}, {"limit": True}, {"limit": 21},
                        {"budget_chars": 255}, {"budget_chars": 20001},
                        {"visible_session": None}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.query("花", **options)

    def test_corrupt_visible_record_fails_closed(self):
        saved = self.add("flower.favorite", "桂花")
        self.store.db.execute("UPDATE events SET payload=? WHERE id=?", (b"bad", saved["id"]))
        with self.assertRaises(IntegrityError):
            self.query("桂花")

    def test_cli_whole_stdout_budget_and_session_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "fixture.db"
            with MemoryStore(db) as store:
                for scope, session in (("persistent", ""), ("session", "A"), ("session", "B")):
                    store.ingest(Candidate("test", "fiction", "flower.favorite", "桂花", "桂花",
                                           OLD, scope=scope, session=session), scope + session, now=NOW)
            env = {k: v for k, v in os.environ.items() if not k.startswith("MEMORYGENE_")}
            env["DSH_SESSION_ID"] = "A"
            command = [sys.executable, "-m", "memorygene.adapter", "recall", "--db", str(db),
                       "--namespace", "test", "--subject", "fiction", "--query", "桂花",
                       "--budget-chars", "1000", "--now", NOW]
            result = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
            self.assertLessEqual(len(result.stdout), 1000)
            body = json.loads(result.stdout)
            self.assertEqual({m["id"] for m in body["matches"]}, {"persistent", "sessionA"})


if __name__ == "__main__":
    unittest.main()
