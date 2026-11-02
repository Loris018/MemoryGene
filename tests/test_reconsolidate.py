"""Reconsolidation support: locate related slots, open evidence, advice, review.

All data is fictional. The module is read-only; these tests also pin that
advice never changes the stored memory.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memorygene import Candidate, MemoryStore
from memorygene.recall import recall
from memorygene.reconsolidate import (
    advise,
    attribute,
    locate,
    open_evidence,
    review,
    slots,
)

NOW = "2026-11-02T00:00:00Z"
NS, SUBJ = "test", "fiction"


class ReconsolidationTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.close)
        self.n = 0

    def put(self, topic, value, source, at, **kw):
        self.n += 1
        c = Candidate(NS, SUBJ, topic, value, source, at, **kw)
        result = self.store.ingest(c, f"e{self.n}", now=NOW)
        return c, result

    def kinds(self, c, result, **kw):
        return [a["kind"] for a in advise(self.store, c, result, now=NOW, **kw)]

    def test_attribute_is_last_topic_token(self):
        self.assertEqual(attribute("preference.liked_flower"), "flower")
        self.assertEqual(attribute("personal.residence.city"), "city")

    def test_explicit_newer_assertion_in_conflict_asks_to_confirm_change(self):
        self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01T00:00:00Z")
        c, r = self.put("preference.favorite_flower", "百合", "我最喜欢百合", "2026-10-10T00:00:00Z")
        self.assertEqual(r["status"], "conflict")
        advice = advise(self.store, c, r, now=NOW)
        self.assertEqual([a["kind"] for a in advice], ["confirm_change"])
        self.assertEqual((advice[0]["current"], advice[0]["proposed"]), ("玫瑰", "百合"))
        # Following the advice with an explicit change settles the evidence.
        c2 = Candidate(NS, SUBJ, "preference.favorite_flower", "百合", "对，改成百合",
                       "2026-10-11T00:00:00Z", intent="change")
        self.assertEqual(self.store.ingest(c2, "e-fix", now=NOW, resolves=r["id"])["status"],
                         "confirmed")
        self.assertEqual(review(self.store, NS, SUBJ, now=NOW)["unresolved"], [])

    def test_out_of_order_conflict_does_not_ask_for_change(self):
        self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-10T00:00:00Z")
        c, r = self.put("preference.favorite_flower", "百合", "我最喜欢百合", "2026-10-01T00:00:00Z")
        self.assertEqual(r["status"], "conflict")
        self.assertEqual(self.kinds(c, r), [])

    def test_repeated_uncertain_value_is_flagged_once_heard_twice(self):
        self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01T00:00:00Z")
        c, r = self.put("preference.favorite_flower", "百合", "可能更喜欢百合",
                        "2026-10-05T00:00:00Z", certainty="uncertain")
        self.assertEqual(self.kinds(c, r), [])
        c, r = self.put("preference.favorite_flower", "百合", "好像更喜欢百合",
                        "2026-10-08T00:00:00Z", certainty="uncertain")
        self.assertEqual(self.kinds(c, r), ["repeated_uncertain"])
        self.assertEqual(self.store.current(NS, SUBJ, "preference.favorite_flower",
                                            now=NOW)["candidate"]["value"], "玫瑰")

    def test_renamed_topic_is_flagged_but_unrelated_favorite_is_not(self):
        self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01T00:00:00Z")
        self.put("preference.favorite_color", "蓝色", "我最喜欢蓝色", "2026-10-01T00:00:00Z")
        c, r = self.put("preference.liked_flower", "栀子花", "我喜欢的花是栀子花",
                        "2026-10-02T00:00:00Z")
        advice = advise(self.store, c, r, now=NOW)
        self.assertEqual([a["kind"] for a in advice], ["possible_same_slot"])
        self.assertEqual(advice[0]["existing_topic"], "preference.favorite_flower")
        c, r = self.put("preference.favorite_movie", "星际穿越", "我最喜欢的电影是星际穿越",
                        "2026-10-02T00:00:00Z")
        self.assertEqual(self.kinds(c, r), [])

    def test_value_cues_anchor_a_renamed_topic(self):
        self.put("preference.favorite_drink", "乌龙茶", "我最爱喝乌龙茶", "2026-10-01T00:00:00Z")
        top = locate(self.store, NS, SUBJ, "preference.favorite_tea", "乌龙", "我最爱喝乌龙",
                     now=NOW)[0]
        self.assertEqual((top["topic"], top["anchored"], top["relation"]),
                         ("preference.favorite_drink", True, "mismatch"))

    def test_locate_ablation_topic_only_ignores_values(self):
        self.put("preference.favorite_drink", "乌龙茶", "我最爱喝乌龙茶", "2026-10-01T00:00:00Z")
        self.put("preference.favorite_color", "蓝色", "我最喜欢蓝色", "2026-10-01T00:00:00Z")
        full = locate(self.store, NS, SUBJ, "preference.favorite_tea", "乌龙", "我最爱喝乌龙",
                      now=NOW)
        topic_only = locate(self.store, NS, SUBJ, "preference.favorite_tea", "乌龙",
                            "我最爱喝乌龙", now=NOW, use=("t",))
        self.assertEqual(full[0]["topic"], "preference.favorite_drink")
        self.assertFalse(any(r["anchored"] for r in topic_only))

    def test_rejected_and_duplicate_inputs_get_no_advice(self):
        self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01T00:00:00Z")
        c, r = self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-02T00:00:00Z")
        self.assertEqual((r["status"], self.kinds(c, r)), ("duplicate", []))
        c, r = self.put("chat.mood", "累", "今天好累", "2026-10-02T00:00:00Z", importance=0.2)
        self.assertEqual((r["status"], self.kinds(c, r)), ("discarded", []))

    def test_open_evidence_is_settled_by_later_confirmation_or_expiry(self):
        self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01T00:00:00Z")
        self.put("preference.favorite_flower", "百合", "可能喜欢百合", "2026-10-02T00:00:00Z",
                 certainty="uncertain")
        self.put("promo.code", "X1", "优惠码 X1", "2026-10-02T00:00:00Z",
                 certainty="uncertain", expires_at="2026-11-10T00:00:00Z")
        later = "2026-11-20T00:00:00Z"
        by_topic = {s["topic"]: s for s in slots(self.store, NS, SUBJ, now=later)}
        self.assertEqual(len(open_evidence(by_topic["preference.favorite_flower"], now=later)), 1)
        self.assertEqual(len(open_evidence(by_topic["promo.code"], now=NOW)), 1)
        self.assertEqual(open_evidence(by_topic["promo.code"], now=later), [])
        self.put("preference.favorite_flower", "郁金香", "现在最喜欢郁金香",
                 "2026-10-03T00:00:00Z", intent="change")
        self.assertEqual([u["topic"] for u in review(self.store, NS, SUBJ, now=NOW)["unresolved"]],
                         ["promo.code"])

    def test_recall_surfaces_unresolved_evidence_as_not_a_fact(self):
        self.put("preference.favorite_flower", "玫瑰", "我最喜欢玫瑰", "2026-10-01T00:00:00Z")
        self.put("preference.favorite_flower", "百合", "我最喜欢百合", "2026-10-10T00:00:00Z")
        result = recall(self.store, NS, SUBJ, "百合", now=NOW)
        self.assertEqual(result["matches"], [])
        self.assertEqual([u["preview"] for u in result["unresolved"]], ["百合"])
        self.assertTrue(result["unresolved"][0]["not_a_fact"])
        self.assertEqual(result["unresolved"][0]["current"], "玫瑰")

    def test_session_evidence_is_invisible_outside_its_session(self):
        self.put("task.style", "简洁", "这次回答简洁点", "2026-10-01T00:00:00Z",
                 scope="session", session="s1", certainty="uncertain")
        self.assertEqual(review(self.store, NS, SUBJ, now=NOW)["unresolved"], [])
        self.assertEqual(len(review(self.store, NS, SUBJ, now=NOW,
                                    visible_session="s1")["unresolved"]), 1)

    def test_review_reports_duplicate_slots_and_is_read_only(self):
        self.put("profile.city", "上海", "我住在上海", "2026-10-01T00:00:00Z")
        self.put("personal.residence.city", "杭州", "我现在住杭州", "2026-10-02T00:00:00Z")
        self.put("preference.favorite_color", "蓝色", "我最喜欢蓝色", "2026-10-01T00:00:00Z")
        before = list(self.store.db.iterdump())
        result = review(self.store, NS, SUBJ, now=NOW)
        self.assertEqual([d["topics"] for d in result["possible_duplicate_slots"]],
                         [["personal.residence.city", "profile.city"]])
        self.assertEqual(before, list(self.store.db.iterdump()))


class AdapterReconsolidationTests(unittest.TestCase):
    def run_cli(self, db, *args):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        env.pop("DSH_SESSION_ID", None)
        out = subprocess.run(
            [sys.executable, "-m", "memorygene.adapter", "--db", db,
             "--namespace", NS, "--subject", SUBJ, "--now", NOW, *args],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_remember_returns_advice_and_review_lists_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "m.db")
            self.run_cli(db, "--allow-create", "remember", "--topic", "preference.favorite_flower",
                         "--value", "玫瑰", "--source", "我最喜欢玫瑰",
                         "--at", "2026-10-01T00:00:00Z")
            out = self.run_cli(db, "remember", "--topic", "preference.favorite_flower",
                               "--value", "百合", "--source", "我最喜欢百合",
                               "--at", "2026-10-10T00:00:00Z")
            self.assertEqual(out["result"]["status"], "conflict")
            self.assertEqual([a["kind"] for a in out["advice"]], ["confirm_change"])
            listed = self.run_cli(db, "review")
            self.assertEqual([u["value"] for u in listed["unresolved"]], ["百合"])
            found = self.run_cli(db, "locate", "--topic", "preference.liked_flower",
                                 "--value", "百合", "--source", "我喜欢百合")
            self.assertEqual(found["related"][0]["topic"], "preference.favorite_flower")


if __name__ == "__main__":
    unittest.main()
