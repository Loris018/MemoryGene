"""Reads return the original words together with the stored value."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene.recall import recall

NOW = "2026-11-07T00:00:00Z"


class ReadEvidenceTests(unittest.TestCase):
    def test_recall_matches_carry_the_source(self):
        with MemoryStore() as store:
            store.ingest(Candidate("t", "u", "preference.favorite_flower", "玫瑰",
                                   "我可能最喜欢玫瑰，不过最近膝盖不好", "2026-10-01T00:00:00Z"),
                         "e1", now=NOW)
            match = recall(store, "t", "u", "玫瑰", now=NOW)["matches"][0]
        self.assertEqual(match["source"], "我可能最喜欢玫瑰，不过最近膝盖不好")
        self.assertFalse(match["source_truncated"])

    def test_current_reports_evidence_and_flags_unsupported_values(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        env.pop("DSH_SESSION_ID", None)
        with tempfile.TemporaryDirectory() as tmp:
            base = [sys.executable, "-m", "memorygene.adapter", "--db", str(Path(tmp) / "m.db"),
                    "--namespace", "t", "--subject", "u", "--now", NOW]

            def run(*args):
                out = subprocess.run([*base, *args], capture_output=True, text=True, env=env)
                self.assertEqual(out.returncode, 0, out.stderr)
                return json.loads(out.stdout)

            run("--allow-create", "remember", "--topic", "hardware.laptop",
                "--value", "虚构笔记本，32GB 内存", "--source", "我的电脑是虚构笔记本",
                "--at", "2026-10-01T00:00:00Z")
            body = run("current", "--topic", "hardware.laptop")
            self.assertEqual(body["evidence"]["source"], "我的电脑是虚构笔记本")
            self.assertFalse(body["evidence"]["paired"])
            self.assertIn("source", body["evidence"]["note"])
            self.assertIsNone(run("current", "--topic", "profile.city")["evidence"])


if __name__ == "__main__":
    unittest.main()
