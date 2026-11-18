"""Tests for the cross-project global-instructions installer (temporary DSH home)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts" / "install_global_auto.py"


def parse(result):
    return json.loads(result.stdout or "{}")


class GlobalAutoInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "dsh-home"
        self.home.mkdir()
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MEMORYGENE_")
        }
        self.env["HOME"] = str(Path(self.tmp.name) / "home")
        Path(self.env["HOME"]).mkdir()
        self.db = Path(self.tmp.name) / "memory.db"
        self.db.write_bytes(b"")
        self.env["MEMORYGENE_DB"] = str(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--dsh-home", str(self.home), "--json", *args],
            capture_output=True,
            text=True,
            env=self.env,
            cwd=str(PROJECT),
        )

    def test_enable_check_and_uninstall(self):
        enabled = self.run_script()
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        body = parse(enabled)
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "created")
        agents = self.home / "AGENTS.md"
        self.assertTrue(agents.is_file())
        text = agents.read_text(encoding="utf-8")
        self.assertEqual(text.count("memorygene:global-auto:begin"), 1)
        self.assertIn("memorygene-dsh", text)
        self.assertTrue((self.home / ".memorygene-global-auto.json").is_file())
        checked = parse(self.run_script("--check"))
        self.assertTrue(checked["ok"])
        self.assertTrue(checked["section_present"])
        removed = parse(self.run_script("--uninstall"))
        self.assertTrue(removed["ok"])
        self.assertFalse(agents.exists())
        self.assertFalse((self.home / ".memorygene-global-auto.json").exists())
        # user-level skill is intentionally kept by uninstall
        self.assertTrue((self.home / "skills" / "memorygene" / "SKILL.md").is_file())

    def test_rerun_updates_section_in_place(self):
        self.run_script()
        text_before = (self.home / "AGENTS.md").read_text(encoding="utf-8")
        again = parse(self.run_script())
        self.assertEqual(again["mode"], "updated")
        text_after = (self.home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(text_after.count("memorygene:global-auto:begin"), 1)
        self.assertEqual(
            len(text_before.splitlines()), len(text_after.splitlines())
        )

    def test_existing_unrelated_agents_file_is_preserved(self):
        agents = self.home / "AGENTS.md"
        agents.write_text("# 我的全局规则\n\n不要删除我。\n", encoding="utf-8")
        refused = self.run_script()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Refusing to overwrite", refused.stdout + refused.stderr)
        self.assertEqual(agents.read_text(encoding="utf-8"), "# 我的全局规则\n\n不要删除我。\n")
        forced = self.run_script("--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        body = parse(forced)
        self.assertEqual(body["mode"], "appended")
        self.assertTrue(Path(body["backup"]).is_file())
        text = agents.read_text(encoding="utf-8")
        self.assertIn("不要删除我。", text)
        self.assertIn("memorygene:global-auto:begin", text)

    def test_check_reports_not_enabled_before_install(self):
        report = parse(self.run_script("--check"))
        self.assertFalse(report["ok"])
        self.assertFalse(report["global_instructions_present"])


if __name__ == "__main__":
    unittest.main()
