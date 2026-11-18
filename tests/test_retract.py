"""Retraction ("I don't like roses any more"). All data is fictional."""

import unittest

from memorygene import Candidate, MemoryStore
from memorygene.recall import recall
from memorygene.reconsolidate import review

NOW = "2026-11-02T00:00:00Z"
TOPIC = "preference.favorite_flower"


def cand(value, source, at, **kw):
    return Candidate("t", "u", TOPIC, value, source, at, **kw)


class RetractTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.close)
        self.n = 0
        self.put("玫瑰", "我最喜欢玫瑰", "2026-10-01T00:00:00Z")

    def put(self, value, source, at, **kw):
        self.n += 1
        return self.store.ingest(cand(value, source, at, **kw), f"e{self.n}", now=NOW)

    def current(self):
        head = self.store.current("t", "u", TOPIC, now=NOW)
        return head["candidate"]["value"] if head else None

    def test_retraction_clears_current_and_keeps_history(self):
        result = self.put("玫瑰", "我不再喜欢玫瑰了", "2026-10-10T00:00:00Z", intent="retract")
        self.assertEqual((result["status"], self.current()), ("retracted", None))
        statuses = [e["status"] for e in self.store.history("t", "u", TOPIC, now=NOW)]
        self.assertEqual(statuses, ["confirmed", "retracted"])
        topic = self.store.topics("t", "u", now=NOW)[0]
        self.assertEqual((topic["status"], topic["current"]), ("retracted", None))
        self.assertTrue(self.store.verify()["ok"])

    def test_new_statement_after_retraction_becomes_current(self):
        self.put("玫瑰", "我不再喜欢玫瑰了", "2026-10-10T00:00:00Z", intent="retract")
        self.assertEqual(self.put("百合", "我最喜欢百合", "2026-10-20T00:00:00Z")["status"],
                         "confirmed")
        self.assertEqual(self.current(), "百合")
        self.assertTrue(self.store.verify()["ok"])

    def test_restating_the_value_later_brings_it_back(self):
        self.put("玫瑰", "我不再喜欢玫瑰了", "2026-10-10T00:00:00Z", intent="retract")
        self.put("玫瑰", "其实还是最喜欢玫瑰", "2026-10-20T00:00:00Z")
        self.assertEqual(self.current(), "玫瑰")

    def test_older_evidence_does_not_undo_a_retraction(self):
        self.put("玫瑰", "我不再喜欢玫瑰了", "2026-10-10T00:00:00Z", intent="retract")
        late = self.put("玫瑰", "我最喜欢玫瑰", "2026-10-05T00:00:00Z")
        self.assertEqual((late["status"], self.current()), ("conflict", None))

    def test_retracting_something_that_is_not_current_does_nothing(self):
        result = self.put("百合", "我不再喜欢百合了", "2026-10-10T00:00:00Z", intent="retract")
        self.assertEqual((result["status"], self.current()), ("nothing_to_retract", "玫瑰"))
        self.assertEqual(len(self.store.history("t", "u", TOPIC, now=NOW)), 1)

    def test_uncertain_retraction_is_only_evidence(self):
        result = self.put("玫瑰", "好像没那么喜欢玫瑰了", "2026-10-10T00:00:00Z",
                          intent="retract", certainty="uncertain")
        self.assertEqual((result["status"], self.current()), ("pending", "玫瑰"))

    def test_retraction_cannot_resolve_evidence(self):
        with self.assertRaises(ValueError):
            self.store.ingest(cand("玫瑰", "不喜欢了", "2026-10-10T00:00:00Z", intent="retract"),
                              "x", now=NOW, resolves="e1")

    def test_recall_and_review_skip_retracted_slots(self):
        self.put("玫瑰", "我不再喜欢玫瑰了", "2026-10-10T00:00:00Z", intent="retract")
        self.assertEqual(recall(self.store, "t", "u", "玫瑰", now=NOW)["matches"], [])
        report = review(self.store, "t", "u", now=NOW)
        self.assertEqual((report["unresolved"], report["unpaired_current"]), ([], []))

    def test_verify_detects_a_head_rolled_back_past_a_retraction(self):
        self.put("玫瑰", "我不再喜欢玫瑰了", "2026-10-10T00:00:00Z", intent="retract")
        self.store.db.execute("UPDATE heads SET event_id='e1'")
        problems = self.store.verify()["problems"]
        self.assertTrue(any("latest" in p["problem"] for p in problems))


if __name__ == "__main__":
    unittest.main()
