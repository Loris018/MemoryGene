"""Invariants of the scenario simulator in experiments/simulator."""

import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "experiments" / "simulator" / "simulate.py"
SPEC = importlib.util.spec_from_file_location("simulate", PATH)
sim = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sim)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.data = sim.generate(300, 11)

    def test_generation_is_deterministic(self):
        self.assertEqual(self.data, sim.generate(300, 11))
        self.assertNotEqual(self.data, sim.generate(300, 12))

    def test_every_utterance_contains_its_value(self):
        for t in self.data:
            for e in t["events"]:
                self.assertIn(e["value"].lower(), e["text"].lower(), (t["id"], e))

    def test_times_increase_and_now_is_after_the_last_event(self):
        for t in self.data:
            times = [e["at"] for e in t["events"]]
            self.assertEqual(times, sorted(times))
            self.assertGreater(t["now"], times[-1])

    def test_no_convention_dependent_event_after_an_unmarked_change(self):
        for t in self.data:
            seen_unmarked = False
            for e in t["events"]:
                if seen_unmarked and e["type"] in {"assert", "change_marked", "correct", "retract"}:
                    seen_unmarked = False
                if seen_unmarked:
                    self.assertNotIn(e["type"], {"repeat", "change_unmarked"}, t["id"])
                if e["type"] == "change_unmarked":
                    seen_unmarked = True

    def test_gold_semantics(self):
        state = (None, [])
        events = [{"type": "assert", "value": "a"}, {"type": "hesitate", "value": "b"},
                  {"type": "change_unmarked", "value": "c"}, {"type": "retract", "value": "a"}]
        confirm = latest = state
        for e in events[:3]:
            confirm = sim.gold_step(confirm, e, "confirm")
            latest = sim.gold_step(latest, e, "latest")
        self.assertEqual(confirm, ("a", ["a"]))
        self.assertEqual(latest, ("c", ["a", "c"]))
        self.assertEqual(sim.gold_step(confirm, events[3], "confirm"), (None, ["a"]))

    def test_conventions_differ_only_through_unmarked_changes(self):
        for t in self.data:
            if t["gold"]["confirm"] != t["gold"]["latest"]:
                self.assertIn("change_unmarked", [e["type"] for e in t["events"]])


if __name__ == "__main__":
    unittest.main()
