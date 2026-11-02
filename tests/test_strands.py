"""Two-strand pairing of value and verbatim source. All data is fictional."""

import unittest

from memorygene import Candidate, MemoryStore
from memorygene.reconsolidate import advise, review
from memorygene.strands import contained, pairing

NOW = "2026-11-02T00:00:00Z"


class PairingTests(unittest.TestCase):
    def test_contained_value_pairs(self):
        self.assertTrue(pairing("玫瑰", "我最喜欢玫瑰。")["paired"])
        self.assertTrue(pairing("Rose", "I like ROSES best")["paired"])

    def test_substituted_embellished_and_merged_values_do_not_pair(self):
        for value in ("百合", "蓝色玫瑰", "玫瑰、百合"):
            self.assertFalse(pairing(value, "我最喜欢玫瑰。")["paired"], value)

    def test_negated_evidence_does_not_pair(self):
        result = pairing("玫瑰", "我不再喜欢玫瑰了")
        self.assertEqual((result["paired"], result["negated"]), (False, True))

    def test_strict_negation_is_clause_scoped(self):
        # "不是" belongs to the corrected old value, not to the new one.
        self.assertTrue(pairing("百合", "我说错了，其实不是玫瑰，是百合")["paired"])
        self.assertFalse(pairing("百合", "我说错了，其实不是玫瑰，是百合",
                                 mode="preregistered")["paired"])

    def test_preregistered_rule_tolerates_partial_cues(self):
        self.assertTrue(pairing("蓝色玫瑰", "我最喜欢玫瑰和蓝色", mode="preregistered")["paired"])
        self.assertFalse(pairing("蓝色玫瑰", "我最喜欢玫瑰和蓝色")["paired"])

    def test_truncation_is_a_known_blind_spot(self):
        self.assertTrue(pairing("乌龙", "我最爱喝乌龙茶")["paired"])

    def test_unknown_mode_and_empty_input(self):
        with self.assertRaises(ValueError):
            pairing("a", "a", mode="loose")
        self.assertFalse(pairing("", "x")["paired"])
        self.assertFalse(contained("", "x"))


class StrandIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.close)

    def test_byte_protection_accepts_damage_written_through_the_legal_path(self):
        c = Candidate("t", "u", "preference.favorite_flower", "蓝色玫瑰", "我最喜欢玫瑰",
                      "2026-10-01T00:00:00Z")
        result = self.store.ingest(c, "e1", now=NOW)
        self.assertTrue(self.store.verify()["ok"])
        kinds = [a["kind"] for a in advise(self.store, c, result, now=NOW)]
        self.assertEqual(kinds, ["unpaired_value"])

    def test_review_lists_unpaired_current_values(self):
        for i, (topic, value, source) in enumerate((
            ("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰"),
            ("hardware.laptop", "虚构笔记本，32GB 内存，带宽约 100GB/s", "我的电脑是虚构笔记本"),
        )):
            self.store.ingest(Candidate("t", "u", topic, value, source,
                                        "2026-10-01T00:00:00Z"), f"e{i}", now=NOW)
        unpaired = review(self.store, "t", "u", now=NOW)["unpaired_current"]
        self.assertEqual([u["topic"] for u in unpaired], ["hardware.laptop"])


if __name__ == "__main__":
    unittest.main()
