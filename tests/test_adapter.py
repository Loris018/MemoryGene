"""Adapter tests: identity/database rules and the chat-facing CLI contract."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def parse(result):
    if result.stdout.strip():
        return json.loads(result.stdout)
    return json.loads(result.stderr)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.db = self.root / "memory.db"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MEMORYGENE_")
        }
        self.env.update(
            {
                "HOME": str(self.home),
                "DSH_SESSION_ID": "session-test",
            }
        )

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args, cwd=None, env=None):
        merged = dict(self.env)
        if env:
            merged.update(env)
        return subprocess.run(
            [sys.executable, "-m", "memorygene.adapter", *args],
            capture_output=True,
            text=True,
            cwd=str(cwd or self.root),
            env=merged,
        )

    def remember(self, *args, env=None):
        return self.invoke(
            "--db",
            str(self.db),
            "--allow-create",
            "--namespace",
            "demo",
            "--subject",
            "u1",
            "remember",
            *args,
            env=env,
        )

    def test_topics_only_recall_persistent_and_current_session(self):
        for scope, session, topic in (
            ("persistent", "", "shared.preference"),
            ("session", "session-A", "task.private_a"),
            ("session", "session-B", "task.private_b"),
        ):
            result = self.remember(
                "--topic", topic, "--value", topic, "--source", topic,
                "--scope", scope, env={"DSH_SESSION_ID": session},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        for session, expected in (
            ("session-A", {"shared.preference", "task.private_a"}),
            ("session-B", {"shared.preference", "task.private_b"}),
            ("", {"shared.preference"}),
        ):
            with self.subTest(session=session):
                result = self.invoke(
                    "--db", str(self.db), "--namespace", "demo", "--subject", "u1",
                    "topics", env={"DSH_SESSION_ID": session},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual({t["topic"] for t in parse(result)["topics"]}, expected)

    def test_doctor_never_creates_a_database(self):
        result = self.invoke("--db", str(self.db), "doctor")
        self.assertEqual(result.returncode, 0)
        body = parse(result)
        self.assertTrue(body["ok"])
        self.assertFalse(body["db_exists"])
        self.assertFalse(body["ready"])
        self.assertFalse(self.db.exists())

    def test_missing_database_is_not_created_implicitly(self):
        result = self.invoke(
            "--db",
            str(self.db),
            "--namespace",
            "demo",
            "--subject",
            "u1",
            "current",
            "--topic",
            "preference.favorite_flower",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing to create", parse(result)["error"])
        self.assertFalse(self.db.exists())

    def test_remember_current_history_topics_and_flags_after_subcommand(self):
        saved = self.remember(
            "--topic",
            "preference.favorite_flower",
            "--value",
            "玫瑰",
            "--source",
            "我最喜欢玫瑰。",
            "--importance",
            "0.8",
            "--at",
            "2026-10-01T00:00:00Z",
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        event = parse(saved)
        self.assertEqual(event["result"]["status"], "confirmed")
        event_id = event["event_id"]

        statuses = []
        for value, certainty, intent, at in (
            ("栀子花", "uncertain", "supplement", "2026-10-10T00:00:00Z"),
            ("栀子花", "explicit", "change", "2026-10-20T00:00:00Z"),
        ):
            result = self.invoke(
                "remember",
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "--topic",
                "preference.favorite_flower",
                "--value",
                value,
                "--source",
                "虚构用户：%s。" % value,
                "--certainty",
                certainty,
                "--intent",
                intent,
                "--at",
                at,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            statuses.append(parse(result)["result"]["status"])
        self.assertEqual(statuses, ["pending", "confirmed"])

        current = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "current",
                "--topic",
                "preference.favorite_flower",
            )
        )
        self.assertEqual(current["current"]["candidate"]["value"], "栀子花")
        history = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "history",
                "--topic",
                "preference.favorite_flower",
            )
        )["history"]
        self.assertEqual(
            [(e["status"], e["candidate"]["value"]) for e in history],
            [("confirmed", "玫瑰"), ("pending", "栀子花"), ("confirmed", "栀子花")],
        )
        topics = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "topics",
            )
        )["topics"]
        self.assertEqual(topics[0]["topic"], "preference.favorite_flower")
        self.assertEqual(topics[0]["current"]["value"], "栀子花")
        self.assertEqual(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "repair",
                "--event-id",
                event_id,
            ).returncode,
            0,
        )

    def test_forget_removes_topic_and_verifies(self):
        self.remember(
            "--topic",
            "preference.favorite_flower",
            "--value",
            "玫瑰",
            "--source",
            "我最喜欢玫瑰。",
        )
        self.remember(
            "--topic",
            "preference.favorite_flower",
            "--value",
            "百合",
            "--source",
            "现在喜欢百合。",
            "--intent",
            "change",
        )
        forgotten = parse(
            self.invoke(
                "--now", "2030-01-01T00:00:00Z",
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "forget",
                "--topic",
                "preference.favorite_flower",
            )
        )
        self.assertEqual(forgotten["forgotten"], 2)
        current = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "current",
                "--topic",
                "preference.favorite_flower",
            )
        )["current"]
        self.assertIsNone(current)
        topics = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "topics",
            )
        )["topics"]
        self.assertEqual(topics, [])

    def test_sensitive_consent_is_enforced(self):
        no_consent = self.remember(
            "--topic",
            "profile.address",
            "--value",
            "虚构路1号",
            "--source",
            "我住在虚构路1号。",
            "--sensitive",
        )
        self.assertEqual(parse(no_consent)["result"]["status"], "rejected_sensitive")
        bare_boolean = self.remember(
            "--topic",
            "profile.address",
            "--value",
            "虚构路1号",
            "--source",
            "我住在虚构路1号。",
            "--sensitive",
            "--consent",
        )
        self.assertEqual(bare_boolean.returncode, 2)
        self.assertIn("consent-evidence", parse(bare_boolean)["error"])
        with_quote = self.remember(
            "--topic",
            "profile.address",
            "--value",
            "虚构路1号",
            "--source",
            "我住在虚构路1号。",
            "--sensitive",
            "--consent",
            "--consent-evidence",
            "可以记住这个地址",
        )
        self.assertEqual(parse(with_quote)["result"]["status"], "confirmed")
        stored = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "current",
                "--topic",
                "profile.address",
            )
        )["current"]
        self.assertIn("可以记住这个地址", stored["candidate"]["source"])

    def test_session_scope_uses_host_session_id(self):
        result = self.remember(
            "--topic",
            "task.context",
            "--value",
            "只在本会话",
            "--source",
            "本会话先这样。",
            "--scope",
            "session",
        )
        self.assertEqual(parse(result)["result"]["status"], "confirmed")
        persistent = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "current",
                "--topic",
                "task.context",
            )
        )["current"]
        self.assertIsNone(persistent)
        session = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "current",
                "--topic",
                "task.context",
                "--scope",
                "session",
            )
        )["current"]
        self.assertEqual(session["candidate"]["session"], "session-test")

    def test_subject_isolation_and_unknown_subject(self):
        self.remember(
            "--topic",
            "preference.favorite_flower",
            "--value",
            "玫瑰",
            "--source",
            "我最喜欢玫瑰。",
        )
        other = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u2",
                "current",
                "--topic",
                "preference.favorite_flower",
            )
        )["current"]
        self.assertIsNone(other)
        topics = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u2",
                "topics",
            )
        )["topics"]
        self.assertEqual(topics, [])

    def test_topic_name_and_missing_configuration_are_validated(self):
        bad_topic = self.remember(
            "--topic", "最喜欢的花", "--value", "玫瑰", "--source", "我喜欢玫瑰。"
        )
        self.assertEqual(bad_topic.returncode, 2)
        self.assertIn("topic must be", parse(bad_topic)["error"])
        no_config = self.invoke("current", "--topic", "preference.favorite_flower")
        self.assertEqual(no_config.returncode, 2)
        self.assertIn("No MemoryGene database configured", parse(no_config)["error"])

    def test_config_file_is_discovered_from_cwd(self):
        (self.root / ".memorygene").mkdir()
        (self.root / ".memorygene" / "dsh.json").write_text(
            json.dumps(
                {
                    "db": str(self.db),
                    "namespace": "demo",
                    "subject": "u1",
                }
            ),
            encoding="utf-8",
        )
        created = self.invoke(
            "remember",
            "--allow-create",
            "--topic",
            "preference.favorite_flower",
            "--value",
            "玫瑰",
            "--source",
            "我最喜欢玫瑰。",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(parse(created)["db"], str(self.db))
        doctor = parse(self.invoke("doctor"))
        self.assertTrue(doctor["ready"])
        self.assertEqual(doctor["namespace"], "demo")
        self.assertEqual(doctor["subject"], "u1")

    def test_corruption_fails_closed_and_repair_restores_latest(self):
        first = parse(
            self.remember(
                "--topic",
                "preference.favorite_flower",
                "--value",
                "玫瑰",
                "--source",
                "我最喜欢玫瑰。",
            )
        )
        second = parse(
            self.remember(
                "--topic",
                "preference.favorite_flower",
                "--value",
                "栀子花",
                "--source",
                "现在最喜欢栀子花。",
                "--intent",
                "change",
            )
        )
        self.assertEqual(second["result"]["status"], "confirmed")
        latest_id = second["event_id"]
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE events SET payload=x'00' WHERE id=?", (latest_id,))
        corrupt = self.invoke(
            "--db",
            str(self.db),
            "--namespace",
            "demo",
            "--subject",
            "u1",
            "current",
            "--topic",
            "preference.favorite_flower",
        )
        self.assertEqual(corrupt.returncode, 2)
        repaired = self.invoke(
            "--db",
            str(self.db),
            "--namespace",
            "demo",
            "--subject",
            "u1",
            "repair",
            "--event-id",
            latest_id,
        )
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        current = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "current",
                "--topic",
                "preference.favorite_flower",
            )
        )["current"]
        self.assertEqual(current["candidate"]["value"], "栀子花")
        self.assertNotEqual(first["event_id"], latest_id)

    def test_verify_command_reports_health_and_route_tampering(self):
        clean = parse(self.invoke("--db", str(self.db), "--allow-create", "verify"))
        self.assertTrue(clean["integrity"]["ok"])
        self.remember(
            "--topic",
            "preference.favorite_flower",
            "--value",
            "玫瑰",
            "--source",
            "我最喜欢玫瑰。",
        )
        healthy = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "verify",
            )
        )
        self.assertTrue(healthy["integrity"]["ok"])
        self.assertEqual(healthy["integrity"]["events"], 1)
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE events SET route='tampered'")
        broken = parse(
            self.invoke(
                "--db",
                str(self.db),
                "--namespace",
                "demo",
                "--subject",
                "u1",
                "verify",
            )
        )
        self.assertFalse(broken["integrity"]["ok"])
        self.assertTrue(broken["integrity"]["problems"])

    def test_unrecoverable_corruption_reports_error_without_guessing(self):
        saved = parse(
            self.remember(
                "--topic",
                "preference.favorite_flower",
                "--value",
                "玫瑰",
                "--source",
                "我最喜欢玫瑰。",
            )
        )
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE events SET payload=x'00', backup=x'00'")
        repaired = self.invoke(
            "--db",
            str(self.db),
            "--namespace",
            "demo",
            "--subject",
            "u1",
            "repair",
            "--event-id",
            saved["event_id"],
        )
        self.assertEqual(repaired.returncode, 2)
        self.assertIn("refusing to guess", parse(repaired)["error"].lower())


if __name__ == "__main__":
    unittest.main()
