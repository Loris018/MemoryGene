"""Acceptance must inspect successful structured task-resume tool results."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class TaskHarnessGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        spec = importlib.util.spec_from_file_location(
            "task_harness_guards", scripts / "task_harness.py"
        )
        cls.module = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", [str(scripts), *sys.path]):
            spec.loader.exec_module(cls.module)

    def events(
        self, *, ok=True, status="review_required", event_id="task-good", exit_code=0
    ):
        body = {
            "ok": ok,
            "command": "task-resume",
            "result": {
                "status": status,
                "checkpoint_id": event_id,
                "checkpoint": {"id": event_id},
            },
        }
        return [
            {
                "type": "tool_call",
                "tool": "bash",
                "callId": "c1",
                "input": {
                    "command": "memorygene-dsh task-resume --checkpoint-id task-good --allow-cross-session"
                },
            },
            {
                "type": "tool_result",
                "status": "completed",
                "callId": "c1",
                "result": json.dumps(body) + f"\n---exit:{exit_code}\n",
            },
        ]

    def test_real_bash_footer_is_parsed(self):
        self.assertTrue(self.module.returned_checkpoint(self.events(), "task-good"))

    def test_truthy_wrong_status_id_and_failed_exit_are_rejected(self):
        for kw in (
            {"ok": "true"},
            {"status": "stale"},
            {"event_id": "other"},
            {"exit_code": 2},
        ):
            with self.subTest(kw=kw):
                self.assertFalse(
                    self.module.returned_checkpoint(self.events(**kw), "task-good")
                )

    def test_uncorrelated_tool_output_is_not_proof(self):
        events = self.events()
        events[1]["callId"] = "different"
        self.assertFalse(self.module.returned_checkpoint(events, "task-good"))
