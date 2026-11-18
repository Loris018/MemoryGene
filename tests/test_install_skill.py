"""The host-neutral skill installer only manages its own files."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts" / "install_skill.py"
SPEC = importlib.util.spec_from_file_location("install_skill", PATH)
inst = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inst)


class InstallSkillTests(unittest.TestCase):
    def test_install_render_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(inst.main(["--host", "codex", "--dest", tmp, "--adapter", "/x/mg"]), 0)
            text = (Path(tmp) / "memorygene" / "SKILL.md").read_text("utf-8")
            self.assertIn('"/x/mg"', text)
            self.assertNotIn("{{", text)
            self.assertEqual(inst.main(["--host", "codex", "--dest", tmp, "--uninstall"]), 0)
            self.assertFalse((Path(tmp) / "memorygene").exists())

    def test_foreign_file_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            foreign = Path(tmp) / "memorygene" / "SKILL.md"
            foreign.parent.mkdir()
            foreign.write_text("someone else's skill", "utf-8")
            self.assertEqual(inst.main(["--host", "claude-code", "--dest", tmp]), 2)
            self.assertEqual(inst.main(["--host", "claude-code", "--dest", tmp, "--uninstall"]), 2)
            self.assertEqual(foreign.read_text("utf-8"), "someone else's skill")


if __name__ == "__main__":
    unittest.main()
