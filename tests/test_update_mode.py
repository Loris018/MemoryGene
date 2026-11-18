"""The optional update="latest" mode for unattended use. All data is fictional."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene.reconsolidate import advise

NOW = "2026-11-02T00:00:00Z"
TOPIC = "profile.city"


def cand(value, source, at, **kw):
    return Candidate("t", "u", TOPIC, value, source, at, **kw)


class UpdateModeTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.close)
        self.store.ingest(cand("上海", "我住上海", "2026-10-01T00:00:00Z"), "e0", now=NOW)

    def current(self):
        return self.store.current("t", "u", TOPIC, now=NOW)["candidate"]["value"]

    def test_default_mode_holds_an_unmarked_change(self):
        result = self.store.ingest(cand("北京", "我住北京", "2026-10-15T00:00:00Z"), "e1", now=NOW)
        self.assertEqual((result["status"], self.current()), ("conflict", "上海"))
        self.assertNotIn("policy", result)

    def test_latest_mode_accepts_and_marks_an_unmarked_change(self):
        c = cand("北京", "我住北京", "2026-10-15T00:00:00Z")
        result = self.store.ingest(c, "e1", now=NOW, update="latest")
        self.assertEqual((result["status"], result["policy"], self.current()),
                         ("confirmed", "latest", "北京"))
        history = [e["candidate"]["value"] for e in self.store.history("t", "u", TOPIC, now=NOW)]
        self.assertEqual(history, ["上海", "北京"])
        self.assertEqual([a["kind"] for a in advise(self.store, c, result, now=NOW)],
                         ["auto_updated"])
        self.assertTrue(self.store.verify()["ok"])

    def test_latest_mode_keeps_the_other_safeguards(self):
        cases = [
            (cand("北京", "可能搬去北京", "2026-10-15T00:00:00Z", certainty="uncertain"), "pending"),
            (cand("北京", "北京也不错", "2026-10-15T00:00:00Z", intent="supplement"), "pending"),
            (cand("北京", "我住北京", "2026-09-01T00:00:00Z"), "conflict"),
        ]
        for i, (c, expected) in enumerate(cases):
            result = self.store.ingest(c, f"x{i}", now=NOW, update="latest")
            self.assertEqual(result["status"], expected, c.source)
            self.assertNotIn("policy", result)
        self.assertEqual(self.current(), "上海")

    def test_explicit_change_is_not_marked_as_policy(self):
        result = self.store.ingest(cand("北京", "我搬到北京了", "2026-10-15T00:00:00Z",
                                        intent="change"), "e1", now=NOW, update="latest")
        self.assertEqual(result["status"], "confirmed")
        self.assertNotIn("policy", result)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.ingest(cand("北京", "我住北京", "2026-10-15T00:00:00Z"), "e1",
                              now=NOW, update="auto")


class AdapterUpdateModeTests(unittest.TestCase):
    def cli(self, *args, config=None):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        for key in ("DSH_SESSION_ID", "MEMORYGENE_DB", "MEMORYGENE_CONFIG"):
            env.pop(key, None)
        extra = ["--config", config] if config else []
        out = subprocess.run(
            [sys.executable, "-m", "memorygene.adapter", *extra, "--db", self.db,
             "--now", NOW, *args], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def remember(self, value, source, at, *extra, config=None):
        return self.cli("remember", "--topic", TOPIC, "--value", value, "--source", source,
                        "--at", at, *extra, config=config)

    def test_flag_and_config_select_the_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.db = str(Path(tmp) / "m.db")
            self.cli("--allow-create", "remember", "--topic", TOPIC, "--value", "上海",
                     "--source", "我住上海", "--at", "2026-10-01T00:00:00Z")
            held = self.remember("北京", "我住北京", "2026-10-15T00:00:00Z")
            self.assertEqual(held["result"]["status"], "conflict")
            flagged = self.remember("广州", "我住广州", "2026-10-20T00:00:00Z", "--update", "latest")
            self.assertEqual(flagged["result"]["status"], "confirmed")
            self.assertEqual([a["kind"] for a in flagged["advice"]], ["auto_updated"])
            config = Path(tmp) / "dsh.json"
            config.write_text(json.dumps({"db": self.db, "update_policy": "latest"}))
            self.assertEqual(self.cli("doctor", config=str(config))["update_policy"], "latest")
            via_config = self.remember("深圳", "我住深圳", "2026-10-25T00:00:00Z",
                                       config=str(config))
            self.assertEqual(via_config["result"]["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
