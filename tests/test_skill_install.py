"""Installer rollback must preserve pre-existing files and later user edits."""

import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        spec = importlib.util.spec_from_file_location(
            "installer", PROJECT / "scripts/install_dsh_skill.py"
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.PROJECT = self.root
        self.module.TEMPLATE = PROJECT / "skills/memorygene/SKILL.md"
        self.config = self.root / ".memorygene/dsh.json"
        self.skill = self.root / ".dsh/skills/memorygene/SKILL.md"
        self.args = Namespace(
            target="project",
            config=None,
            dsh_home=None,
            db=str(self.root / "test.db"),
            adapter=str(Path(__file__)),
            python=str(Path(__file__)),
            namespace="test",
            subject="fictional",
            purge_db=False,
        )

    def existing(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(b'{"db":"original.db","subject":"original"}\n')
        self.config.chmod(0o640)
        self.skill.parent.mkdir(parents=True)
        self.skill.write_bytes(b"original instructions\n")
        self.skill.chmod(0o600)
        return self.config.read_bytes(), self.skill.read_bytes()

    def test_repeated_install_then_uninstall_restores_first_backup_and_modes(self):
        config, skill = self.existing()
        self.module.install(self.args)
        self.module.install(self.args)
        self.assertTrue(self.module.uninstall(self.args)["ok"])
        self.assertEqual(self.config.read_bytes(), config)
        self.assertEqual(self.skill.read_bytes(), skill)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.skill.stat().st_mode & 0o777, 0o600)

    def test_new_install_uninstall_keeps_database_and_unmanaged_nested_files(self):
        Path(self.args.db).write_bytes(b"keep this data")
        self.module.install(self.args)
        extra = self.skill.parent / "references/custom.md"
        extra.parent.mkdir()
        extra.write_text("user file")
        self.assertTrue(self.module.uninstall(self.args)["ok"])
        self.assertFalse(self.skill.exists())
        self.assertFalse(self.config.exists())
        self.assertEqual(extra.read_text(), "user file")
        self.assertEqual(Path(self.args.db).read_bytes(), b"keep this data")

    def test_edited_config_blocks_uninstall_without_partial_deletion(self):
        self.module.install(self.args)
        before = self.skill.read_bytes()
        self.config.write_text('{"db":"user-changed.db"}')
        with self.assertRaises(ValueError):
            self.module.uninstall(self.args)
        self.assertEqual(self.skill.read_bytes(), before)
        self.assertEqual(self.config.read_text(), '{"db":"user-changed.db"}')

    def test_edited_skill_blocks_reinstall(self):
        self.module.install(self.args)
        self.skill.write_text("user edits")
        before = self.config.read_bytes()
        with self.assertRaises(ValueError):
            self.module.install(self.args)
        self.assertEqual(self.skill.read_text(), "user edits")
        self.assertEqual(self.config.read_bytes(), before)

    def test_legacy_manifest_is_retained_as_pre_upgrade_state(self):
        config, skill = self.existing()
        manifest = self.skill.parent / self.module.MANIFEST_NAME
        old = json.dumps({"config": str(self.config), "db": self.args.db})
        manifest.write_text(old)
        self.module.install(self.args)
        self.module.uninstall(self.args)
        self.assertEqual(manifest.read_text(), old)
        self.assertEqual(self.config.read_bytes(), config)
        self.assertEqual(self.skill.read_bytes(), skill)

    def test_legacy_uninstall_without_backup_refuses(self):
        self.existing()
        (self.skill.parent / self.module.MANIFEST_NAME).write_text("{}")
        with self.assertRaises(ValueError):
            self.module.uninstall(self.args)
        self.assertTrue(self.skill.exists())
        self.assertTrue(self.config.exists())

    def test_uninstall_io_failure_restores_installed_state(self):
        self.existing()
        self.module.install(self.args)
        before = self.config.read_bytes(), self.skill.read_bytes()
        original = self.module.restore
        failed = False

        def fail_once(path, state):
            nonlocal failed
            if path == self.config and not failed:
                failed = True
                raise OSError("synthetic I/O failure")
            return original(path, state)

        with (
            patch.object(self.module, "restore", side_effect=fail_once),
            self.assertRaises(OSError),
        ):
            self.module.uninstall(self.args)
        self.assertEqual((self.config.read_bytes(), self.skill.read_bytes()), before)
        self.assertTrue(self.module.uninstall(self.args)["ok"])

    def test_symlink_file_is_not_overwritten(self):
        original, _ = self.existing()
        target = self.root / "real-config.json"
        self.config.rename(target)
        self.config.symlink_to(target)
        with self.assertRaises(ValueError):
            self.module.install(self.args)
        self.assertEqual(target.read_bytes(), original)
