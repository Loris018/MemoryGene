"""User profile categories and the 30-day recent state. All data is fictional."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene.profile import category, profile

SRC = str(Path(__file__).resolve().parents[1] / "src")


class ProfileTests(unittest.TestCase):
    def test_category_from_topic_prefix(self):
        self.assertEqual([category(t) for t in ("profile.city", "preference.food", "recent.worry",
                                                "life.trip_qingdao", "project.memorygene", "x.y")],
                         ["basic", "preferences", "recent", "life", "projects", "other"])

    def test_restating_a_time_limited_value_renews_it(self):
        with MemoryStore() as store:
            def put(at, expires, eid):
                return store.ingest(Candidate("t", "u", "recent.worry", "考试", "最近在担心考试", at,
                                              expires_at=expires), eid, now="2026-10-25T00:00:00Z")
            put("2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z", "e1")
            again = put("2026-10-20T00:00:00Z", "2026-11-19T00:00:00Z", "e2")
            self.assertEqual((again["status"], again["renewal"]), ("confirmed", True))
            same = put("2026-10-21T00:00:00Z", "2026-11-10T00:00:00Z", "e3")
            self.assertEqual(same["status"], "duplicate")
            self.assertTrue(store.verify()["ok"])

    def test_profile_groups_current_items_and_lists_past_situations(self):
        with MemoryStore() as store:
            rows = [("profile.city", "上海", "我住在上海", None),
                    ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", None),
                    ("recent.worry", "考试", "最近在担心考试", "2026-10-15T00:00:00Z"),
                    ("recent.busy_with", "搬家", "这周在忙搬家", "2026-11-30T00:00:00Z"),
                    ("project.poster", "RLLS 海报", "我们在做 RLLS 海报", None)]
            for i, (topic, value, source, expires) in enumerate(rows):
                store.ingest(Candidate("t", "u", topic, value, source, "2026-10-01T00:00:00Z",
                                       expires_at=expires), f"e{i}", now="2026-10-02T00:00:00Z")
            result = profile(store, "t", "u", now="2026-11-07T00:00:00Z")
        groups = result["profile"]
        self.assertEqual([i["value"] for i in groups["basic"]], ["上海"])
        self.assertEqual([i["value"] for i in groups["recent"]], ["搬家"])
        self.assertEqual(groups["recent"][0]["days_left"], 23)
        self.assertEqual(groups["projects"][0]["source"], "我们在做 RLLS 海报")
        self.assertEqual([p["value"] for p in result["past_situations"]], ["考试"])


class AdapterRecentStateTests(unittest.TestCase):
    def test_recent_topics_get_a_default_expiry_and_profile_command(self):
        env = dict(os.environ, PYTHONPATH=SRC)
        env.pop("DSH_SESSION_ID", None)
        with tempfile.TemporaryDirectory() as tmp:
            base = [sys.executable, "-m", "memorygene.adapter", "--db", str(Path(tmp) / "m.db"),
                    "--namespace", "t", "--subject", "u", "--now", "2026-11-07T00:00:00Z"]

            def run(*args):
                out = subprocess.run([*base, *args], capture_output=True, text=True, env=env)
                self.assertEqual(out.returncode, 0, out.stderr)
                return json.loads(out.stdout)

            body = run("--allow-create", "remember", "--topic", "recent.worry", "--value", "考试",
                       "--source", "最近在担心考试", "--at", "2026-11-01T00:00:00Z")
            self.assertTrue(body["result"]["candidate"]["expires_at"].startswith("2026-12-01"))
            renewed = run("remember", "--topic", "recent.worry", "--value", "考试",
                          "--source", "还是在担心考试", "--at", "2026-11-06T00:00:00Z")
            self.assertTrue(renewed["result"]["renewal"])
            listed = run("profile")
            self.assertEqual(listed["profile"]["recent"][0]["days_left"], 29)


if __name__ == "__main__":
    unittest.main()
