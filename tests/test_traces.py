"""Anonymous traces of low-importance statements, and the one-time question."""

import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene.reconsolidate import advise

TOPIC = "preference.snack"


def small(value, source, day, **kw):
    return Candidate("t", "u", TOPIC, value, source, f"2026-10-{day:02d}T09:00:00Z",
                     importance=0.3, **kw)


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "m.db"
        self.store = MemoryStore(self.path)
        self.addCleanup(self.store.close)
        self.n = 0

    def put(self, c, now="2026-10-20T00:00:00Z"):
        self.n += 1
        return self.store.ingest(c, f"e{self.n}", now=now)

    def test_third_different_day_asks_once(self):
        results = [self.put(small("薯片", "在吃薯片", d)) for d in (1, 1, 3, 7, 9)]
        self.assertEqual([r["status"] for r in results], ["discarded"] * 5)
        self.assertEqual([r["trace_days"] for r in results], [1, 1, 2, 3, 4])
        self.assertEqual([r["ask_to_remember"] for r in results], [False, False, False, True, False])
        c = small("薯片", "又在吃薯片", 7)
        kinds = [a["kind"] for a in advise(self.store, c, results[3], now="2026-10-20T00:00:00Z")]
        self.assertEqual(kinds, ["recurring_low_importance"])
        self.assertEqual(self.store.topics("t", "u", now="2026-10-20T00:00:00Z"), [])

    def test_traces_hold_no_readable_words_or_values(self):
        self.put(small("薯片", "在吃薯片", 1))
        self.store.close()
        raw = self.path.read_bytes()
        self.assertNotIn("薯片".encode(), raw)
        self.store = MemoryStore(self.path)

    def test_traces_expire_after_30_days(self):
        for d in (1, 2):
            self.put(small("薯片", "在吃薯片", d))
        later = self.put(small("薯片", "在吃薯片", 31), now="2026-11-05T00:00:00Z")
        self.assertEqual(later["trace_days"], 1)

    def test_forget_removes_traces_of_the_topic(self):
        for d in (1, 2):
            self.put(small("薯片", "在吃薯片", d))
        self.store.forget("t", "u", TOPIC)
        self.assertEqual(self.put(small("薯片", "在吃薯片", 3))["trace_days"], 1)

    def test_store_with_traces_reopens_and_verifies(self):
        self.put(small("薯片", "在吃薯片", 1))
        self.store.close()
        self.store = MemoryStore(self.path)
        self.assertTrue(self.store.verify()["ok"])


if __name__ == "__main__":
    unittest.main()
