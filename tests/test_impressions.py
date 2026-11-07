"""Evidence-backed impressions of the user. All data is fictional."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene import impressions as imp
from memorygene.profile import profile

NOW = "2026-11-07T00:00:00Z"


class ImpressionTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.close)
        self.ids = {}
        for key, topic, value, source in (
            ("sport", "preference.favorite_sport", "攀岩", "我最喜欢攀岩"),
            ("trip", "life.trip_mountain", "去爬了黄山", "上个月去爬了黄山"),
        ):
            self.ids[key] = self.store.ingest(
                Candidate("t", "u", topic, value, source, "2026-10-01T00:00:00Z"),
                f"e-{key}", now=NOW)["id"]

    def test_save_requires_current_citations(self):
        with self.assertRaises(ValueError):
            imp.save(self.store, "t", "u", "喜欢户外运动", [], now=NOW)
        with self.assertRaises(ValueError):
            imp.save(self.store, "t", "u", "喜欢户外运动", ["no-such-event"], now=NOW)
        with self.assertRaises(ValueError):  # another user's memory
            imp.save(self.store, "t", "someone-else", "喜欢户外运动", [self.ids["sport"]], now=NOW)
        result = imp.save(self.store, "t", "u", "喜欢攀岩、爬山这类户外运动",
                          [self.ids["sport"], self.ids["trip"]], now=NOW)
        self.assertEqual((result["status"], result["citations"]), ("current", 2))
        self.assertNotIn("warning", result)

    def test_unrelated_text_gets_a_warning(self):
        result = imp.save(self.store, "t", "u", "性格内向", [self.ids["sport"]], now=NOW)
        self.assertIn("warning", result)

    def test_impression_goes_stale_when_evidence_changes(self):
        saved = imp.save(self.store, "t", "u", "喜欢攀岩", [self.ids["sport"]], now=NOW)
        self.store.ingest(Candidate("t", "u", "preference.favorite_sport", "游泳", "现在最喜欢游泳",
                                    "2026-10-20T00:00:00Z", intent="change"), "e-change", now=NOW)
        listed = imp.listing(self.store, "t", "u", now=NOW)
        self.assertEqual([(i["id"], i["status"]) for i in listed], [(saved["id"], "stale")])
        self.assertEqual(imp.listing(self.store, "t", "u", now=NOW, include_stale=False), [])
        self.assertEqual(profile(self.store, "t", "u", now=NOW)["impressions"], [])

    def test_forgetting_a_memory_deletes_impressions_citing_it(self):
        imp.save(self.store, "t", "u", "喜欢攀岩", [self.ids["sport"]], now=NOW)
        kept = imp.save(self.store, "t", "u", "去过黄山", [self.ids["trip"]], now=NOW)
        self.store.forget("t", "u", "preference.favorite_sport")
        self.assertEqual([i["id"] for i in imp.listing(self.store, "t", "u", now=NOW)], [kept["id"]])

    def test_listing_shows_evidence_and_user_can_delete(self):
        saved = imp.save(self.store, "t", "u", "喜欢攀岩", [self.ids["sport"]], now=NOW)
        listed = imp.listing(self.store, "t", "u", now=NOW)
        self.assertEqual(listed[0]["evidence"][0]["source"], "我最喜欢攀岩")
        self.assertEqual(profile(self.store, "t", "u", now=NOW)["impressions"][0]["id"], saved["id"])
        self.assertEqual(imp.forget(self.store, "t", "u", saved["id"]), 1)
        self.assertEqual(imp.listing(self.store, "t", "u", now=NOW), [])
        self.assertTrue(self.store.verify()["ok"])


class AdapterImpressionTests(unittest.TestCase):
    def test_cli_round_trip(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        env.pop("DSH_SESSION_ID", None)
        with tempfile.TemporaryDirectory() as tmp:
            base = [sys.executable, "-m", "memorygene.adapter", "--db", str(Path(tmp) / "m.db"),
                    "--namespace", "t", "--subject", "u", "--now", NOW]

            def run(*args, code=0):
                out = subprocess.run([*base, *args], capture_output=True, text=True, env=env)
                self.assertEqual(out.returncode, code, out.stderr)
                return json.loads(out.stdout) if code == 0 else out.stderr

            event = run("--allow-create", "remember", "--topic", "preference.favorite_sport",
                        "--value", "攀岩", "--source", "我最喜欢攀岩",
                        "--at", "2026-10-01T00:00:00Z")["event_id"]
            saved = run("impression-save", "--text", "喜欢攀岩", "--cite", event)["result"]
            self.assertEqual(run("impressions")["impressions"][0]["id"], saved["id"])
            run("impression-forget", code=2)
            self.assertEqual(run("impression-forget", "--all")["forgotten"], 1)


if __name__ == "__main__":
    unittest.main()
