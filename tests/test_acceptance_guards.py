"""The evidence scripts must fail when otherwise plausible outputs are wrong."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AcceptanceGuards(unittest.TestCase):
    def test_non_boolean_predicates_are_rejected(self):
        for name in ("acceptance", "e2e_harness"):
            module = load(name)
            for value in (0, 2, "confirmed", ["wrong"]):
                with (
                    self.subTest(script=name, value=value),
                    self.assertRaises(TypeError),
                ):
                    module.check("invalid predicate", value, 0, value)

    def test_wrong_truthy_current_does_not_pass(self):
        module = load("acceptance")
        with (
            patch.object(
                module,
                "remember",
                return_value=(0, {"result": {"status": "confirmed"}}),
            ),
            patch.object(
                module,
                "current",
                return_value=(0, {"current": {"candidate": {"value": "WRONG"}}}),
            ),
            patch.object(module, "sql", return_value=[(1,)]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            module.s01_important_information_saved()
        self.assertFalse(module.RESULTS[-1]["passed"])
        self.assertIn("current value", module.RESULTS[-1]["failures"])

    def test_sensitive_wrong_status_fails_entire_runner(self):
        module = load("acceptance")
        original = module.call

        def wrong_status(*args, **kwargs):
            code, body = original(*args, **kwargs)
            if "--sensitive" in args:
                body["result"]["status"] = "confirmed"
            return code, body

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(module, "call", side_effect=wrong_status),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            module.OUT = Path(directory)
            module.DB = module.OUT / "synthetic.db"
            self.assertEqual(module.main(), 1)
        failed = [r["id"] for r in module.RESULTS if not r["passed"]]
        self.assertEqual(failed, ["S12"])

    def test_harness_child_check_failure_fails_scenario(self):
        module = load("e2e_harness")
        with contextlib.redirect_stdout(io.StringIO()):
            module.add_result(
                "fake-success", True, [module.check("process failed", False, 0, 1)]
            )
        self.assertFalse(module.RESULTS[-1]["passed"])

    def test_model_claims_and_unfinished_calls_are_not_tool_evidence(self):
        module = load("e2e_harness")
        events = [
            {"type": "final", "text": "memorygene-dsh ran successfully"},
            {
                "type": "tool_call",
                "callId": "a",
                "tool": "bash",
                "input": {"command": "memorygene-dsh topics"},
            },
        ]
        self.assertEqual(
            module.completed_memory_tools(events), {"skill": False, "adapter": False}
        )
        events.append({"type": "tool_result", "callId": "a", "status": "completed"})
        self.assertEqual(
            module.completed_memory_tools(events), {"skill": False, "adapter": True}
        )
