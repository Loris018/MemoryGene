"""Task continuation guarantees, using synthetic data and isolated stores only."""

import concurrent.futures
import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, IntegrityError, MemoryStore, tasks
from memorygene.codec import checksum, packed_complement
from memorygene.core import canonical
from memorygene.recall import recall

NOW = "2026-10-29T10:00:00Z"
LATER = "2026-10-30T10:00:00Z"


def document(memory=None):
    sources = [
        {
            "id": "u1",
            "kind": "conversation",
            "locator": "fictional-turn-1",
            "role": "user",
        }
    ]
    result = {
        "sources": sources,
        "items": [
            {"kind": "goal", "text": "为虚构项目设计测试", "source_ids": ["u1"]},
            {"kind": "next_step", "text": "先确认尚未验证的部分", "source_ids": ["u1"]},
        ],
    }
    if memory:
        c = memory["candidate"]
        sources.append(
            {
                "id": "m1",
                "kind": "memory",
                "topic": c["topic"],
                "event_id": memory["id"],
                "scope": c["scope"],
            }
        )
        result["items"].append(
            {"kind": "constraint", "text": c["value"], "source_ids": ["m1"]}
        )
    return result


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.close)

    def memory(self, value="虚构偏好：桂花", event_id="memory-1", **kw):
        fields = dict(
            namespace="demo",
            subject="fiction",
            topic="preference.flower",
            value=value,
            source="虚构原话",
            at=NOW,
        )
        fields.update(kw)
        return self.store.ingest(Candidate(**fields), event_id, now=NOW)

    def save(self, doc=None, **kwargs):
        return tasks.save(
            self.store,
            "demo",
            "fiction",
            "test-task",
            "A",
            doc or document(),
            now=NOW,
            **kwargs,
        )

    def show(self, **kwargs):
        return tasks.show(
            self.store,
            "demo",
            "fiction",
            "test-task",
            "A",
            now=kwargs.pop("now", NOW),
            **kwargs,
        )

    def test_lazy_storage_and_read_only_missing(self):
        before = list(self.store.db.iterdump())
        self.assertEqual(self.show()["status"], "missing")
        self.assertEqual(
            tasks.forget(self.store, "demo", "fiction", "test-task", "A"), 0
        )
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertFalse(tasks.installed(self.store))

    def test_save_show_mark_unverified_sources_and_no_long_term_promotion(self):
        saved = self.save()
        self.assertFalse(saved["context_replaced"])
        before = list(self.store.db.iterdump())
        shown = self.show()
        self.assertEqual(shown["status"], "review_required")
        self.assertEqual(shown["checkpoint"]["document"], document())
        self.assertEqual(
            shown["source_checks"][0]["status"], "caller_reference_unverified"
        )
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(self.store.topics("demo", "fiction"), [])
        self.assertEqual(recall(self.store, "demo", "fiction", "虚构")["matches"], [])
        self.assertTrue(self.store.verify()["ok"])

    def test_memory_sources_current_then_changed_blocks_all_content(self):
        memory = self.memory()
        self.save(document(memory))
        self.assertEqual(self.show()["source_checks"][1]["status"], "current")
        self.memory("虚构偏好：玫瑰", "memory-2", intent="change")
        stale = self.show()
        self.assertEqual(stale["status"], "stale")
        self.assertIsNone(stale["checkpoint"])
        self.assertNotIn("桂花", canonical(stale))
        self.assertTrue(self.store.verify()["ok"], "stale is not corrupt")

    def test_pending_conflict_expired_or_other_identity_cannot_be_sources(self):
        cases = [
            {"certainty": "uncertain"},
            {"subject": "someone-else"},
            {"namespace": "other"},
            {"scope": "session", "session": "B"},
        ]
        for i, fields in enumerate(cases):
            source = self.memory(event_id=f"m{i}", **fields)
            before = list(self.store.db.iterdump())
            with self.assertRaises(ValueError):
                self.save(document(source))
            self.assertEqual(before, list(self.store.db.iterdump()))
        self.memory(event_id="confirmed")
        conflict = self.memory("different", "conflict")
        with self.assertRaises(ValueError):
            self.save(document(conflict))

    def test_expired_memory_invalidates_task_without_resurrecting_old_value(self):
        source = self.memory(expires_at=LATER)
        self.save(document(source))
        self.assertEqual(self.show(now=LATER)["status"], "stale")
        with self.assertRaises(ValueError):
            tasks.save(
                self.store,
                "demo",
                "fiction",
                "different",
                "A",
                document(source),
                now=LATER,
            )

    def test_source_content_digest_binds_even_same_event_id(self):
        memory = self.memory()
        self.save(document(memory))
        altered = copy.deepcopy(memory)
        altered["candidate"]["value"] = "tampered-current"
        raw = canonical(altered).encode()
        self.store.db.execute(
            "UPDATE events SET payload=?,digest=? WHERE id=?",
            (raw, checksum(raw), memory["id"]),
        )
        self.assertEqual(self.show()["status"], "stale")

    def test_update_requires_current_version_and_returns_latest(self):
        first = self.save()
        with self.assertRaises(ValueError):
            self.save()
        second_doc = document()
        second_doc["items"][1]["text"] = "先执行用户最新指定的核对步骤"
        second = self.save(second_doc, previous_id=first["checkpoint_id"])
        self.assertEqual(second["previous_id"], first["checkpoint_id"])
        with self.assertRaises(ValueError):
            self.save(previous_id=first["checkpoint_id"])
        self.assertEqual(self.show()["checkpoint"]["document"], second_doc)
        old = tasks.resume(
            self.store, "demo", "fiction", "A", first["checkpoint_id"], now=NOW
        )
        self.assertEqual(old, {"status": "superseded", "checkpoint": None})

    def test_failed_new_source_update_leaves_prior_checkpoint(self):
        source = self.memory()
        first = self.save()
        self.store.forget("demo", "fiction", "preference.flower")
        before = list(self.store.db.iterdump())
        with self.assertRaises(ValueError):
            self.save(document(source), previous_id=first["checkpoint_id"])
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(self.show()["checkpoint_id"], first["checkpoint_id"])

    def test_task_expiry_does_not_fall_back_to_old_version(self):
        first = self.save()
        self.save(previous_id=first["checkpoint_id"], expires_at=LATER)
        shown = self.show(now=LATER)
        self.assertEqual(shown["status"], "expired")
        self.assertIsNone(shown["checkpoint"])
        for expiry in (NOW, "2027-10-29T00:00:00Z"):
            with self.assertRaises(ValueError):
                self.save(previous_id=shown["checkpoint_id"], expires_at=expiry)

    def test_session_and_identity_isolation_and_explicit_transfer(self):
        saved = self.save()
        for namespace, subject, session in (
            ("other", "fiction", "A"),
            ("demo", "other", "A"),
            ("demo", "fiction", "B"),
        ):
            self.assertEqual(
                tasks.show(
                    self.store, namespace, subject, "test-task", session, now=NOW
                )["status"],
                "missing",
            )
        with self.assertRaises(ValueError):
            tasks.resume(
                self.store, "demo", "fiction", "B", saved["checkpoint_id"], now=NOW
            )
        allowed = tasks.resume(
            self.store,
            "demo",
            "fiction",
            "B",
            saved["checkpoint_id"],
            allow_cross_session=True,
            now=NOW,
        )
        self.assertEqual(allowed["status"], "review_required")
        other = tasks.resume(
            self.store,
            "demo",
            "other",
            "B",
            saved["checkpoint_id"],
            allow_cross_session=True,
            now=NOW,
        )
        self.assertEqual(other["status"], "missing")
        self.assertEqual(
            tasks.show(self.store, "demo", "fiction", "test-task", "B", now=NOW)[
                "status"
            ],
            "missing",
        )

    def test_session_memory_dependencies_cannot_transfer(self):
        saved = self.save(document(self.memory(scope="session", session="A")))
        with self.assertRaises(ValueError):
            tasks.resume(
                self.store,
                "demo",
                "fiction",
                "B",
                saved["checkpoint_id"],
                allow_cross_session=True,
                now=NOW,
            )

    def test_forget_source_purges_all_task_versions_and_backups(self):
        source = self.memory()
        first = self.save(document(source))
        self.save(
            previous_id=first["checkpoint_id"]
        )  # old version still contains the source
        tasks.save(self.store, "demo", "fiction", "unrelated", "A", document(), now=NOW)
        tasks.save(self.store, "demo", "other", "test-task", "A", document(), now=NOW)
        self.assertEqual(self.store.forget("demo", "fiction", "preference.flower"), 1)
        self.assertEqual(self.show()["status"], "missing")
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM task_checkpoints").fetchone()[
                0
            ],
            2,
        )
        self.assertTrue(self.store.verify()["ok"])
        with self.assertRaises(KeyError):
            tasks.repair(
                self.store, "demo", "fiction", "test-task", "A", first["checkpoint_id"]
            )

    def test_corrupt_checkpoint_blocks_forget_atomically_until_explicit_removal(self):
        saved = self.save(document(self.memory()))
        self.store.db.execute(
            "UPDATE task_checkpoints SET payload=? WHERE id=?",
            (b"bad", saved["checkpoint_id"]),
        )
        with self.assertRaises(IntegrityError):
            self.store.forget("demo", "fiction", "preference.flower")
        self.assertIsNotNone(
            self.store.current("demo", "fiction", "preference.flower", now=NOW)
        )
        self.assertEqual(
            tasks.forget(self.store, "demo", "fiction", "test-task", "A"), 1
        )
        self.assertEqual(self.store.forget("demo", "fiction", "preference.flower"), 1)

    def test_forget_transaction_rolls_back_task_deletion_on_memory_failure(self):
        self.save(document(self.memory()))
        self.store.db.execute(
            "CREATE TRIGGER fail_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
        before = list(self.store.db.iterdump())
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.forget("demo", "fiction", "preference.flower")
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_complement_repair_and_no_version_rollback(self):
        first = self.save()
        second = self.save(previous_id=first["checkpoint_id"])
        row = self.store.db.execute(
            "SELECT * FROM task_checkpoints WHERE id=?", (first["checkpoint_id"],)
        ).fetchone()
        self.assertEqual(row["backup"], packed_complement(row["payload"]))
        self.store.db.execute(
            "UPDATE task_checkpoints SET payload=? WHERE id=?",
            (b"bad", first["checkpoint_id"]),
        )
        self.assertFalse(self.store.verify()["ok"])
        tasks.repair(
            self.store, "demo", "fiction", "test-task", "A", first["checkpoint_id"]
        )
        self.assertTrue(self.store.verify()["ok"])
        self.assertEqual(self.show()["checkpoint_id"], second["checkpoint_id"])

    def test_repair_cannot_make_stale_source_current_or_guess_lost_bytes(self):
        saved = self.save(document(self.memory()))
        self.memory("new-value", "new-id", intent="change")
        self.store.db.execute("UPDATE task_checkpoints SET payload=?", (b"bad",))
        tasks.repair(
            self.store, "demo", "fiction", "test-task", "A", saved["checkpoint_id"]
        )
        self.assertEqual(self.show()["status"], "stale")
        self.store.db.execute(
            "UPDATE task_checkpoints SET payload=?,backup=?", (b"bad", b"bad")
        )
        with self.assertRaises(IntegrityError):
            tasks.repair(
                self.store, "demo", "fiction", "test-task", "A", saved["checkpoint_id"]
            )

    def test_visible_corruption_fails_closed_but_other_identity_not_decoded(self):
        saved = self.save()
        self.store.db.execute("UPDATE task_checkpoints SET payload=?", (b"bad",))
        with self.assertRaises(IntegrityError):
            self.show()
        self.assertEqual(
            tasks.resume(
                self.store, "demo", "other", "A", saved["checkpoint_id"], now=NOW
            )["status"],
            "missing",
        )

    def test_document_validation_and_missing_session_do_not_write(self):
        invalid = []
        doc = document()
        doc["extra"] = "unexpected"
        invalid.append(doc)
        doc = document()
        doc["items"][0]["source_ids"] = ["missing"]
        invalid.append(doc)
        doc = document()
        doc["items"][0]["kind"] = "guessed_fact"
        invalid.append(doc)
        doc = document()
        doc["items"][0]["text"] = "x" * 1001
        invalid.append(doc)
        doc = document()
        doc["sources"].append(copy.deepcopy(doc["sources"][0]))
        invalid.append(doc)
        doc = document()
        doc["items"].pop()
        invalid.append(doc)
        before = list(self.store.db.iterdump())
        for doc in invalid:
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                self.save(doc)
        with self.assertRaises(ValueError):
            tasks.save(self.store, "demo", "fiction", "task", "", document(), now=NOW)
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_reopen_and_competing_writers_only_one_revision_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "fixture.db")
            with MemoryStore(path) as store:
                first = tasks.save(
                    store, "demo", "fiction", "task", "A", document(), now=NOW
                )

            def update(_):
                with MemoryStore(path) as store:
                    try:
                        tasks.save(
                            store,
                            "demo",
                            "fiction",
                            "task",
                            "A",
                            document(),
                            previous_id=first["checkpoint_id"],
                            now=NOW,
                        )
                        return "saved"
                    except ValueError:
                        return "version_conflict"

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(update, range(2)))
            self.assertCountEqual(results, ["saved", "version_conflict"])
            with MemoryStore(path) as store:
                self.assertEqual(store.verify()["task_checkpoints"], 2)
                self.assertTrue(store.verify()["ok"])

    def test_cli_save_show_cross_session_and_forget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json"
            source.write_text(json.dumps(document(), ensure_ascii=False))
            env = {
                k: v for k, v in os.environ.items() if not k.startswith("MEMORYGENE_")
            }
            env["DSH_SESSION_ID"] = "A"
            base = [
                sys.executable,
                "-m",
                "memorygene.adapter",
                "--db",
                str(root / "fixture.db"),
                "--namespace",
                "demo",
                "--subject",
                "fiction",
                "--now",
                NOW,
            ]

            def invoke(*args, ok=True):
                result = subprocess.run(
                    base + list(args), env=env, cwd=root, capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 0 if ok else 2, result.stderr)
                return json.loads(result.stdout if ok else result.stderr)

            invoke("task-save", "--task", "demo", "--file", str(source), ok=False)
            self.assertFalse((root / "fixture.db").exists())
            saved = invoke(
                "--allow-create", "task-save", "--task", "demo", "--file", str(source)
            )["result"]
            self.assertEqual(
                invoke("task-show", "--task", "demo")["result"]["status"],
                "review_required",
            )
            env["DSH_SESSION_ID"] = "B"
            invoke("task-resume", "--checkpoint-id", saved["checkpoint_id"], ok=False)
            self.assertEqual(
                invoke(
                    "task-resume",
                    "--checkpoint-id",
                    saved["checkpoint_id"],
                    "--allow-cross-session",
                )["result"]["status"],
                "review_required",
            )
            env["DSH_SESSION_ID"] = "A"
            self.assertEqual(
                invoke("task-forget", "--task", "demo")["result"]["versions"], 1
            )
            self.assertEqual(
                invoke("task-show", "--task", "demo")["result"]["status"], "missing"
            )


if __name__ == "__main__":
    unittest.main()
