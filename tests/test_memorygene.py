import concurrent.futures
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, IntegrityError, MemoryStore
from memorygene.codec import (
    checksum,
    complement,
    decode,
    encode,
    packed_complement,
    recover,
)

NOW = "2026-10-24T10:00:00+00:00"


def candidate(value="玫瑰", **kwargs):
    fields = dict(
        namespace="demo",
        subject="fictional-user",
        topic="preference.favorite_flower",
        value=value,
        source="虚构用户明确陈述",
        at="2026-10-01T08:00:00+00:00",
    )
    fields.update(kwargs)
    return Candidate(**fields)


class CodecTests(unittest.TestCase):
    def test_known_example(self):
        self.assertEqual(encode(b"A"), "CAAC")
        self.assertEqual(complement("CAAC"), "GTTG")

    def test_all_bytes_and_unicode_roundtrip(self):
        for data in (bytes(range(256)), "栀子花🌸".encode(), b""):
            self.assertEqual(decode(encode(data)), data)
            self.assertEqual(complement(complement(encode(data))), encode(data))
            self.assertEqual(decode(complement(encode(data))), packed_complement(data))

    def test_invalid_sequences(self):
        for seq in ("A", "AAAAZAAA", "acgt"):
            with self.assertRaises(ValueError):
                decode(seq)
        with self.assertRaises(ValueError):
            complement("X")

    def test_equal_budget_and_no_guess(self):
        data = b"important record"
        for mode in ("copy", "complement"):
            backup = data if mode == "copy" else packed_complement(data)
            self.assertEqual(len(backup), len(data))
            self.assertEqual(recover(b"", backup, checksum(data), mode), data)
            with self.assertRaises(IntegrityError):
                recover(b"bad", b"bad", checksum(data), mode)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def tearDown(self):
        self.store.close()

    def put(self, c=None, event_id="1", **kwargs):
        return self.store.ingest(
            c or candidate(), event_id, now=kwargs.pop("now", NOW), **kwargs
        )

    def current(self, **kwargs):
        return self.store.current(
            "demo", "fictional-user", "preference.favorite_flower", now=NOW, **kwargs
        )

    def history(self, **kwargs):
        return self.store.history(
            "demo", "fictional-user", "preference.favorite_flower", now=NOW, **kwargs
        )

    def test_flower_lifecycle(self):
        self.put()
        hint = self.put(
            candidate("栀子花", certainty="uncertain", at="2026-10-10T00:00:00Z"), "2"
        )
        self.assertEqual(hint["status"], "pending")
        self.assertEqual(self.current()["candidate"]["value"], "玫瑰")
        changed = self.put(
            candidate("栀子花", intent="change", at="2026-10-20T00:00:00Z"), "3"
        )
        self.assertEqual(changed["previous_id"], "1")
        self.assertEqual(self.current()["candidate"]["value"], "栀子花")
        self.assertEqual(
            [e["status"] for e in self.history()], ["confirmed", "pending", "confirmed"]
        )

    def test_conflict_requires_explicit_change(self):
        self.put()
        self.assertEqual(self.put(candidate("百合"), "2")["status"], "conflict")
        self.assertEqual(self.current()["id"], "1")

    def test_correction_preserves_original(self):
        self.put()
        self.put(candidate("百合", intent="correct"), "2")
        self.assertEqual(self.current()["id"], "2")
        self.assertEqual(self.history()[0]["candidate"]["value"], "玫瑰")

    def test_explicit_resolution_links_pending_evidence(self):
        self.put(candidate(certainty="uncertain"))
        result = self.put(candidate(intent="change"), "2", resolves="1")
        self.assertEqual(result["resolves"], "1")
        self.assertEqual(self.current()["id"], "2")
        self.assertEqual(
            self.put(candidate(intent="change"), "2", resolves="1"), result
        )
        with self.assertRaises(ValueError):
            self.put(candidate(intent="change"), "3", resolves="1")

    def test_resolution_cannot_cross_subjects_or_confirm_uncertainty(self):
        self.put(candidate(certainty="uncertain"))
        for c in (
            candidate(subject="other", intent="change"),
            candidate(intent="change", certainty="uncertain"),
            candidate("百合", intent="change"),
        ):
            with self.assertRaises(ValueError):
                self.put(c, "2", resolves="1")
        self.assertIsNone(self.current())

    def test_bad_head_pointer_cannot_leak_other_subject(self):
        self.put()
        self.put(candidate(subject="other"), "2")
        self.store.db.execute("UPDATE heads SET event_id='2' WHERE event_id='1'")
        with self.assertRaises(IntegrityError):
            self.current()

    def test_inferred_never_confirmed(self):
        self.assertEqual(self.put(candidate(certainty="inferred"))["status"], "pending")
        self.assertIsNone(self.current())

    def test_uncertain_change_does_not_override(self):
        self.put()
        self.put(candidate("百合", intent="change", certainty="uncertain"), "2")
        self.assertEqual(self.current()["id"], "1")

    def test_supplement_does_not_replace_single_slot(self):
        self.put()
        self.assertEqual(
            self.put(candidate("百合", intent="supplement"), "2")["status"], "pending"
        )

    def test_low_value_and_sensitive_not_persisted(self):
        for c in (candidate(importance=0.1), candidate(sensitive=True)):
            self.assertIn(self.put(c)["status"], {"discarded", "rejected_sensitive"})
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 0
        )

    def test_sensitive_consent(self):
        self.assertEqual(
            self.put(candidate(sensitive=True, consent=True))["status"], "confirmed"
        )

    def test_idempotent_retry_and_mismatched_retry(self):
        original = self.put()
        self.assertEqual(self.put(), original)
        with self.assertRaises(ValueError):
            self.put(candidate("百合"))
        self.assertEqual(len(self.history()), 1)

    def test_duplicate_evidence_does_not_create_new_head(self):
        self.put()
        self.assertEqual(self.put(event_id="2")["status"], "duplicate")
        self.assertEqual(self.current()["id"], "1")

    def test_out_of_order_cannot_overwrite(self):
        self.put()
        self.assertEqual(
            self.put(
                candidate("百合", intent="change", at="2026-09-01T00:00:00Z"), "2"
            )["status"],
            "conflict",
        )

    def test_expiry_does_not_resurrect_superseded(self):
        self.put()
        self.put(
            candidate(
                "百合",
                intent="change",
                at="2026-10-10T00:00:00Z",
                expires_at="2026-10-20T00:00:00Z",
            ),
            "2",
            now="2026-10-15T00:00:00Z",
        )
        self.assertIsNone(self.current())

    def test_expired_input_not_stored(self):
        self.assertEqual(
            self.put(candidate(expires_at="2026-10-02T00:00:00Z"))["status"], "expired"
        )
        self.assertEqual(self.history(), [])

    def test_scope_and_subject_isolation(self):
        self.put()
        self.put(candidate("百合", subject="other"), "2")
        self.put(candidate("茶", scope="session", session="s1"), "3")
        self.assertEqual(self.current()["candidate"]["value"], "玫瑰")
        self.assertEqual(
            self.current(scope="session", session="s1")["candidate"]["value"], "茶"
        )
        self.assertIsNone(self.current(scope="session", session="s2"))
        self.assertIsNone(
            self.store.current("other", "fictional-user", "preference.favorite_flower")
        )

    def test_routing_is_unambiguous_and_normalized(self):
        self.assertNotEqual(
            self.store._route("a.b", "c", "d"), self.store._route("a", "b.c", "d")
        )
        self.assertEqual(
            self.store._route("é", "c", "d"), self.store._route("e\u0301", "c", "d")
        )

    def test_validation_no_nan_or_naive_time(self):
        for c in (
            candidate(importance=float("nan")),
            candidate(importance=2),
            candidate(importance=True),
            candidate(at="2026-01-01"),
            candidate(scope="session"),
            candidate(session="bad"),
            candidate(certainty="guess"),
            candidate(sensitive="false"),
            candidate(expires_at="2026-09-01T00:00:00Z"),
            candidate(topic=""),
            candidate(at="2030-01-01T00:00:00Z"),
        ):
            with self.subTest(c=c), self.assertRaises((ValueError, TypeError)):
                self.put(c)
        self.assertEqual(self.history(), [])

    def test_corrupt_primary_explicit_repair(self):
        self.put()
        self.store.db.execute("UPDATE events SET payload=x'00' WHERE id='1'")
        with self.assertRaises(IntegrityError):
            self.current()
        with self.assertRaises(IntegrityError):
            self.put(candidate("百合", intent="change"), "2")
        self.store.repair("1")
        self.assertEqual(self.current()["candidate"]["value"], "玫瑰")

    def test_repair_latest_never_rolls_back_change(self):
        self.put()
        self.put(candidate("百合", intent="change"), "2")
        self.store.db.execute("UPDATE events SET payload=x'00' WHERE id='2'")
        self.store.repair("2")
        self.assertEqual(self.current()["candidate"]["value"], "百合")

    def test_both_copies_lost_fail_closed(self):
        self.put()
        self.store.db.execute("UPDATE events SET payload=x'00',backup=x'00'")
        with self.assertRaises(IntegrityError):
            self.store.repair("1")

    def test_healthy_primary_repairs_bad_backup(self):
        self.put()
        self.store.db.execute("UPDATE events SET backup=x'00'")
        self.store.repair("1")
        self.store.db.execute("UPDATE events SET payload=x'00'")
        self.store.repair("1")
        self.assertEqual(self.current()["id"], "1")

    def test_forget_removes_all_copies_and_is_scoped(self):
        self.put()
        self.put(candidate("百合", intent="change"), "2")
        self.put(candidate(subject="other"), "3")
        self.assertEqual(
            self.store.forget("demo", "fictional-user", "preference.favorite_flower"), 2
        )
        self.assertIsNone(self.current())
        self.assertEqual(self.history(), [])
        with self.assertRaises(KeyError):
            self.store.repair("1")
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM events").fetchone()[0], 1
        )


class TopicsTests(unittest.TestCase):
    def test_topics_lists_current_expired_pending_and_scope(self):
        with MemoryStore() as s:
            s.ingest(candidate("玫瑰"), "1", now=NOW)
            s.ingest(
                candidate(
                    "栀子花",
                    certainty="uncertain",
                    intent="supplement",
                    at="2026-10-10T00:00:00Z",
                ),
                "2",
                now=NOW,
            )
            s.ingest(
                candidate(
                    "百合",
                    topic="preference.favorite_flower_2",
                    expires_at="2026-10-20T00:00:00Z",
                    at="2026-10-05T00:00:00Z",
                ),
                "3",
                now="2026-10-10T00:00:00Z",
            )
            s.ingest(
                candidate("茶", topic="preference.favorite_drink", scope="session", session="s1"),
                "4",
                now=NOW,
            )
            rows = s.topics("demo", "fictional-user", now=NOW)
            self.assertEqual(
                [(r["topic"], r["status"]) for r in rows],
                [
                    ("preference.favorite_drink", "current"),
                    ("preference.favorite_flower", "current"),
                    ("preference.favorite_flower_2", "expired"),
                ],
            )
            flower = rows[1]
            self.assertEqual(flower["current"]["value"], "玫瑰")
            self.assertEqual(flower["evidence"]["confirmed"], 1)
            self.assertEqual(flower["evidence"]["pending"], 1)
            self.assertEqual(rows[0]["scope"], "session")
            self.assertEqual(rows[0]["session"], "s1")
            self.assertIsNone(rows[2]["current"])
            self.assertEqual(s.topics("other", "fictional-user", now=NOW), [])
            self.assertEqual(
                s.topics("demo", "fictional-user", now="2026-10-21T00:00:00Z")[2][
                    "status"
                ],
                "expired",
            )

    def test_topics_works_with_plain_index_and_fails_closed_on_bad_route(self):
        with MemoryStore(index="plain") as s:
            s.ingest(candidate(), "1", now=NOW)
            self.assertEqual(s.topics("demo", "fictional-user", now=NOW)[0]["topic"],
                             "preference.favorite_flower")
            s.db.execute("UPDATE events SET route='not-a-route' WHERE id='1'")
            with self.assertRaises(IntegrityError):
                s.topics("demo", "fictional-user", now=NOW)

    def test_topics_does_not_resurrect_or_change_heads(self):
        with MemoryStore() as s:
            s.ingest(candidate("玫瑰"), "1", now=NOW)
            s.ingest(
                candidate("栀子花", intent="change", at="2026-10-20T00:00:00Z"),
                "2",
                now=NOW,
            )
            rows = s.topics("demo", "fictional-user", now=NOW)
            self.assertEqual(rows[0]["current"]["value"], "栀子花")
            self.assertEqual(s.current("demo", "fictional-user", candidate().topic,
                                       now=NOW)["id"], "2")


class VerifyAndEdgeCaseTests(unittest.TestCase):
    def test_verify_clean_database(self):
        with MemoryStore() as s:
            s.ingest(candidate(), "1", now=NOW)
            report = s.verify()
            self.assertTrue(report["ok"])
            self.assertEqual(report["events"], 1)
            self.assertEqual(report["heads"], 1)
            self.assertEqual(report["problems"], [])

    def test_verify_detects_corruption_and_route_tampering(self):
        with MemoryStore() as s:
            s.ingest(candidate(), "1", now=NOW)
            s.db.execute("UPDATE events SET payload=x'00' WHERE id='1'")
            report = s.verify()
            self.assertFalse(report["ok"])
            self.assertEqual(report["problems"][0]["event_id"], "1")
            s.db.execute("UPDATE events SET payload=(SELECT payload FROM events) WHERE 0")
        with MemoryStore() as s:
            s.ingest(candidate(), "1", now=NOW)
            s.db.execute("UPDATE events SET route='tampered' WHERE id='1'")
            report = s.verify()
            self.assertFalse(report["ok"])
            text = " ".join(p["problem"] for p in report["problems"])
            self.assertTrue(
                "mismatch" in text or "unreadable" in text, text
            )
        with MemoryStore() as s:
            s.ingest(candidate(), "1", now=NOW)
            route = s.db.execute("SELECT route FROM events").fetchone()[0]
            s.db.execute("UPDATE heads SET route='tampered-head'")
            report = s.verify()
            self.assertFalse(report["ok"])
            kinds = {p["kind"] for p in report["problems"]}
            self.assertIn("head", kinds)
            del route

    def test_verify_detects_head_rollback_and_missing_head(self):
        with MemoryStore() as s:
            s.ingest(candidate("玫瑰"), "1", now=NOW)
            s.ingest(
                candidate("栀子花", intent="change", at="2026-10-20T00:00:00Z"),
                "2",
                now=NOW,
            )
            self.assertTrue(s.verify()["ok"])
            # roll the head back to the older confirmed version
            s.db.execute("UPDATE heads SET event_id='1'")
            report = s.verify()
            self.assertFalse(report["ok"])
            self.assertTrue(
                any("latest confirmed" in p["problem"] for p in report["problems"]),
                report["problems"],
            )
            self.assertEqual(
                s.current("demo", "fictional-user", candidate().topic, now=NOW)["id"],
                "1",
            )
        with MemoryStore() as s:
            s.ingest(candidate(), "1", now=NOW)
            s.db.execute("DELETE FROM heads")
            report = s.verify()
            self.assertFalse(report["ok"])
            self.assertTrue(
                any("no head" in p["problem"] for p in report["problems"]),
                report["problems"],
            )
            self.assertIsNone(
                s.current("demo", "fictional-user", candidate().topic, now=NOW)
            )

    def test_verify_reports_head_to_unconfirmed_evidence(self):
        with MemoryStore() as s:
            s.ingest(candidate(certainty="uncertain"), "1", now=NOW)
            s.db.execute("INSERT INTO heads(route,event_id) VALUES(?,?)",
                         (s.db.execute("SELECT route FROM events").fetchone()[0], "1"))
            report = s.verify()
            self.assertFalse(report["ok"])
            self.assertTrue(any("unconfirmed" in p["problem"] for p in report["problems"]))

    def test_expired_head_older_same_value_restatement_is_confirmed(self):
        with MemoryStore() as s:
            s.ingest(
                candidate("玫瑰", expires_at="2026-10-10T00:00:00Z"),
                "1",
                now="2026-10-02T00:00:00Z",
            )
            old_evidence = candidate("玫瑰", at="2026-10-01T00:00:00Z")
            result = s.ingest(old_evidence, "2", now=NOW)
            self.assertEqual(result["status"], "confirmed")
            self.assertEqual(
                s.current("demo", "fictional-user", candidate().topic, now=NOW)["id"],
                "2",
            )

    def test_blank_session_id_is_rejected(self):
        with MemoryStore() as s:
            for session in ("", "   "):
                with self.subTest(session=session), self.assertRaises(ValueError):
                    s.ingest(
                        candidate(scope="session", session=session), "1", now=NOW
                    )


class IntegrationTests(unittest.TestCase):
    def test_cli_ingest_recall_and_forget(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.db"
            evidence = Path(d) / "candidate.json"
            from dataclasses import asdict

            evidence.write_text(
                json.dumps({"event_id": "cli-1", "candidate": asdict(candidate())}),
                encoding="utf-8",
            )
            base = [sys.executable, "-m", "memorygene.cli", "--db", str(path)]

            def run(*args):
                result = subprocess.run(
                    base + list(args), capture_output=True, text=True, check=True
                )
                return json.loads(result.stdout)

            self.assertEqual(run("ingest", str(evidence))["status"], "confirmed")
            query = [
                "--namespace",
                "demo",
                "--subject",
                "fictional-user",
                "--topic",
                candidate().topic,
            ]
            self.assertEqual(run("current", *query)["candidate"]["value"], "玫瑰")
            self.assertEqual(run("forget", *query), 1)
            self.assertIsNone(run("current", *query))

    def test_cli_invalid_timestamp_is_clean_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.db"
            evidence = Path(d) / "candidate.json"
            from dataclasses import asdict

            data = asdict(candidate())
            data["expires_at"] = 123
            evidence.write_text(
                json.dumps({"event_id": "cli-1", "candidate": data}), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "memorygene.cli",
                    "--db",
                    str(path),
                    "ingest",
                    str(evidence),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Timestamp", json.loads(result.stderr)["error"])

    def test_foreign_sqlite_file_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "foreign.db"
            import sqlite3 as _sqlite3

            with _sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE invoices(id INTEGER PRIMARY KEY, amount REAL)")
                conn.execute("INSERT INTO invoices(amount) VALUES(9.99)")
            with self.assertRaises(ValueError) as caught:
                MemoryStore(path)
            self.assertIn("Not a MemoryGene database", str(caught.exception))
            with _sqlite3.connect(path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertEqual(tables, {"invoices"})

    def test_foreign_sqlite_with_task_table_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "foreign-task.db"
            import sqlite3 as _sqlite3

            with _sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE task_checkpoints(seq INTEGER, thing TEXT)")
                conn.execute("INSERT INTO task_checkpoints VALUES(1, 'unrelated')")
            with self.assertRaises(ValueError) as caught:
                MemoryStore(path)
            self.assertIn("Not a MemoryGene database", str(caught.exception))
            with _sqlite3.connect(path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertEqual(tables, {"task_checkpoints"})

    def test_cli_read_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "missing.db"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "memorygene.cli",
                    "--db",
                    str(path),
                    "current",
                    "--namespace",
                    "demo",
                    "--subject",
                    "u",
                    "--topic",
                    "t",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to create", result.stderr)
            self.assertFalse(path.exists())

    def test_missing_config_is_not_silently_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.db"
            with MemoryStore(path) as s:
                s.ingest(candidate(), "1", now=NOW)
                s.db.execute("DELETE FROM config")
            with self.assertRaises(ValueError):
                MemoryStore(path)

    def test_all_protection_modes_at_store_level(self):
        for mode in ("none", "copy", "complement"):
            with self.subTest(mode=mode), MemoryStore(protection=mode) as s:
                s.ingest(candidate(), "1", now=NOW)
                s.db.execute("UPDATE events SET payload=x'00'")
                if mode == "none":
                    with self.assertRaises(IntegrityError):
                        s.repair("1")
                else:
                    s.repair("1")
                    self.assertEqual(
                        s.current("demo", "fictional-user", candidate().topic, now=NOW)[
                            "id"
                        ],
                        "1",
                    )

    def test_reopen_and_config_guard(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.db"
            with MemoryStore(path) as s:
                s.ingest(candidate(), "1", now=NOW)
            with MemoryStore(path) as s:
                self.assertEqual(
                    s.current(
                        "demo", "fictional-user", "preference.favorite_flower", now=NOW
                    )["id"],
                    "1",
                )
            with self.assertRaises(ValueError):
                MemoryStore(path, index="plain")

    def test_two_connections_serialize_conflicting_writes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "memory.db"
            with MemoryStore(path):
                pass

            def write(i):
                with MemoryStore(path) as s:
                    return s.ingest(candidate(str(i)), str(i), now=NOW)["status"]

            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                statuses = list(pool.map(write, [1, 2]))
            self.assertCountEqual(statuses, ["confirmed", "conflict"])

    def test_plain_and_complement_policy_equivalence(self):
        with MemoryStore(index="plain") as plain, MemoryStore() as dna:
            rng = random.Random(20261024)
            for i in range(100):
                c = candidate(
                    str(rng.randrange(4)),
                    intent=rng.choice(["assert", "change", "correct", "supplement"]),
                    certainty=rng.choice(["explicit", "uncertain", "inferred"]),
                )
                a = plain.ingest(c, str(i), now=NOW)
                b = dna.ingest(c, str(i), now=NOW)
                self.assertEqual(a, b)

    def test_synthetic_scenarios(self):
        cases = json.loads(
            (Path(__file__).parents[1] / "experiments/scenarios.json").read_text()
        )
        self.assertGreaterEqual(len(cases), 20)
        for case in cases:
            with self.subTest(case=case["id"]), MemoryStore() as s:
                for i, turn in enumerate(case["turns"]):
                    result = s.ingest(Candidate(**turn), str(i), now=NOW)
                    self.assertEqual(result["status"], case["expected_statuses"][i])
                events = s.history("fixture", "fictional", case["topic"], now=NOW)
                head = s.current("fixture", "fictional", case["topic"], now=NOW)
                self.assertEqual(
                    head["candidate"]["value"] if head else None,
                    case["expected_current"],
                )
                self.assertEqual(
                    [
                        e["candidate"]["value"]
                        for e in events
                        if e["status"] == "confirmed"
                    ],
                    case["expected_history"],
                )


if __name__ == "__main__":
    unittest.main()
