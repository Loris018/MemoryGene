"""Behaviour of the re-implemented update policies used in experiments/BASELINES.md."""

import importlib.util
import unittest
from pathlib import Path

from memorygene import Candidate

SPEC = importlib.util.spec_from_file_location(
    "baselines_eval", Path(__file__).resolve().parents[1] / "experiments" / "baselines_eval.py")
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)

NOW = "2026-11-02T00:00:00Z"


def stream(*turns):
    cands = [Candidate("t", "u", "preference.favorite_music", v, s, at, **kw)
             for v, s, at, kw in turns]
    return {"dataset": "test", "id": "x", "topic": "preference.favorite_music",
            "now": NOW, "candidates": cands, "gold_current": None, "gold_history": []}


class PolicyTests(unittest.TestCase):
    def test_supplement_replaces_only_in_latest_explicit(self):
        s = stream(("爵士", "最喜欢爵士", "2026-10-01T00:00:00Z", {}),
                   ("古典", "古典也不错", "2026-10-02T00:00:00Z", {"intent": "supplement"}))
        self.assertEqual(b.run("latest_explicit", s)["current"], "古典")
        self.assertEqual(b.run("memorygene", s)["current"], "爵士")

    def test_certainty_filter(self):
        s = stream(("爵士", "最喜欢爵士", "2026-10-01T00:00:00Z", {}),
                   ("古典", "可能更喜欢古典", "2026-10-02T00:00:00Z", {"certainty": "uncertain"}))
        self.assertEqual(b.run("graphiti_style", s)["current"], "古典")
        self.assertEqual(b.run("latest_explicit", s)["current"], "爵士")

    def test_valid_time_beats_arrival_order(self):
        s = stream(("爵士", "最喜欢爵士", "2026-10-10T00:00:00Z", {}),
                   ("古典", "以前最喜欢古典", "2026-10-01T00:00:00Z", {}))
        self.assertEqual(b.run("mem0_style", s)["current"], "古典")
        self.assertEqual(b.run("graphiti_style", s)["current"], "爵士")

    def test_one_question_turns_an_unmarked_change_into_an_update(self):
        s = stream(("上海", "我住上海", "2026-10-01T00:00:00Z", {}),
                   ("北京", "我住北京", "2026-10-15T00:00:00Z", {}))
        self.assertEqual(b.run("memorygene", s)["current"], "上海")
        asked = b.run("memorygene_ask", s)
        self.assertEqual((asked["current"], asked["questions"]), ("北京", 1))


if __name__ == "__main__":
    unittest.main()
