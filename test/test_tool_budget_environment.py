import copy
from pathlib import Path
import unittest

from dsh_eval.environment import StatefulEnvironment
from dsh_eval.formats import load_json, validate_case


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ["eval_read", "eval_list", "eval_write", "eval_delete", "eval_edit", "eval_rename"]


class ToolBudgetEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["environment"] = {
            "files": {"target.txt": "draft", "guard.txt": "keep"},
            "stateful": {"transientReadFailures": {}, "tools": TOOLS},
        }
        self.sequence = 0

    def environment(self, limit=1, delays=None, failures=None):
        self.case["budget"] = {"timeoutSeconds": 120, "toolTimeoutMs": 100}
        if limit is not None:
            self.case["budget"]["maxToolCalls"] = limit
        if delays is not None:
            self.case["environment"]["stateful"]["toolDelaysMs"] = delays
        if failures is not None:
            self.case["environment"]["stateful"]["transientReadFailures"] = failures
        validate_case(self.case)
        env = StatefulEnvironment(self.case["environment"], "case-run", self.case["budget"])
        env.bind("session")
        return env

    def request(self, operation="read", path="target.txt", request_id=None, **arguments):
        self.sequence += 1
        return {"type": "tool-request", "bridgeVersion": 1, "requestId": request_id or str(self.sequence),
                "caseRunId": "case-run", "sessionId": "session", "operation": operation,
                "arguments": {"path": path, **arguments}}

    def assert_state(self, env, limit, admitted, rejected, exhausted):
        self.assertEqual(env.budget_state(), {"toolCallBudgetFormatVersion": 1, "limit": limit,
                         "admitted": admitted, "rejected": rejected, "exhausted": exhausted})

    def assert_limit_error(self, response, path="target.txt"):
        self.assertTrue(response["isError"])
        self.assertEqual(response["errorCode"], "TOOL_CALL_LIMIT_EXCEEDED")
        self.assertEqual(response["text"], "TOOL_CALL_LIMIT_EXCEEDED: " + path)

    def test_zero_budget_rejects_every_operation_without_side_effects(self):
        operations = [("read", {}), ("list", {}), ("write", {"content": "changed"}),
                      ("delete", {}), ("edit", {"oldText": "draft", "newText": "changed"}),
                      ("rename", {"destination": "moved.txt"})]
        for operation, arguments in operations:
            with self.subTest(operation=operation):
                env = self.environment(0, failures={"target.txt": 1})
                before = copy.deepcopy((env.files, env.failures, env.attempts))
                self.assert_limit_error(env.submit(self.request(operation, **arguments), 0)[0])
                self.assertEqual((env.files, env.failures, env.attempts), before)
                self.assertEqual(env.pending, {})
                self.assert_state(env, 0, 0, 1, True)

    def test_inclusive_limit_and_mixed_entry_points_share_one_counter(self):
        env = self.environment(2)
        self.assertFalse(env.handle(self.request())["isError"])
        self.assertFalse(env.submit(self.request("write", content="ready"), 0)[0]["isError"])
        self.assert_state(env, 2, 2, 0, False)
        self.assertTrue(env.snapshot(self.case, "run", True)["complete"])
        self.assert_limit_error(env.handle(self.request("delete")))
        self.assertEqual(env.files["target.txt"], "ready")
        self.assert_state(env, 2, 2, 1, True)

    def test_poll_does_not_charge_admission_twice(self):
        env = self.environment(1, delays={"eval_write": [20]})
        request = self.request("write", content="ready")
        self.assertEqual(env.submit(request, 0), [])
        self.assert_state(env, 1, 1, 0, False)
        self.assertFalse(env.poll(.02)[0]["isError"])
        self.assertEqual(env.files["target.txt"], "ready")
        self.assert_state(env, 1, 1, 0, False)

    def test_cached_successes_do_not_charge_or_repeat_operations(self):
        env = self.environment(1)
        request = self.request("rename", destination="moved.txt")
        original = env.handle(request)
        self.assertFalse(original["isError"])
        self.assertEqual(env.submit(request, 1), [original])
        self.assertEqual(env.handle(request), original)
        self.assertEqual(env.files, {"moved.txt": "draft", "guard.txt": "keep"})
        self.assert_state(env, 1, 1, 0, False)

    def test_pending_duplicate_and_conflict_preserve_admission_and_schedule(self):
        env = self.environment(1, delays={"eval_read": [50]})
        request = self.request()
        self.assertEqual(env.submit(request, 0), [])
        pending = copy.deepcopy(env.pending)
        self.assertEqual(env.submit(request, .01), [])
        self.assertEqual(env.pending, pending)
        conflict = {**request, "arguments": {"path": "guard.txt"}}
        with self.assertRaisesRegex(ValueError, "Conflicting pending"):
            env.submit(conflict, .01)
        self.assertEqual(env.pending, pending)
        self.assertEqual(env.attempts, {"eval_read": 1})
        self.assert_state(env, 1, 1, 0, False)
        self.assertEqual(env.poll(.05)[0]["text"], "draft")

    def test_handle_cannot_bypass_pending_delay_or_timeout(self):
        env = self.environment(1, delays={"eval_write": [200]})
        request = self.request("write", content="changed")
        self.assertEqual(env.submit(request, 0), [])
        pending = copy.deepcopy(env.pending)
        with self.assertRaisesRegex(ValueError, "must complete through poll"):
            env.handle(request)
        self.assertEqual(env.pending, pending)
        self.assertEqual(env.files["target.txt"], "draft")
        self.assertEqual(env.poll(.1)[0]["text"], "TOOL_TIMEOUT: target.txt")
        self.assert_state(env, 1, 1, 0, False)

    def test_failed_operation_consumes_budget_without_refund(self):
        for operation, path, arguments, expected in (
            ("read", "missing.txt", {}, "NOT_FOUND"),
            ("read", "../target.txt", {}, "INVALID_PATH"),
            ("edit", "target.txt", {"oldText": "missing", "newText": "new"}, "TEXT_NOT_FOUND"),
        ):
            with self.subTest(expected=expected):
                env = self.environment(1)
                response = env.handle(self.request(operation, path, **arguments))
                self.assertEqual(response["text"], expected + ": " + path)
                self.assertNotIn("errorCode", response)
                self.assert_limit_error(env.submit(self.request(), 0)[0])
                self.assert_state(env, 1, 1, 1, True)

    def test_transient_failure_and_duplicate_consume_once(self):
        env = self.environment(1, failures={"target.txt": 2})
        request = self.request()
        response = env.submit(request, 0)[0]
        self.assertEqual(response["text"], "TEMPORARY_READ_FAILURE: target.txt")
        self.assertEqual(env.handle(request), response)
        self.assertEqual(env.failures, {"target.txt": 1})
        self.assert_limit_error(env.handle(self.request()))
        self.assertEqual(env.failures, {"target.txt": 1})
        self.assertEqual(env.attempts, {"eval_read": 1})
        self.assert_state(env, 1, 1, 1, True)

    def test_timeout_consumes_budget_and_replay_stays_timeout(self):
        env = self.environment(1, delays={"eval_write": [200, 0]})
        request = self.request("write", content="changed")
        self.assertEqual(env.submit(request, 0), [])
        response = env.poll(.1)[0]
        self.assertEqual(response["text"], "TOOL_TIMEOUT: target.txt")
        self.assertEqual(env.submit(request, 1), [response])
        self.assert_limit_error(env.submit(self.request("write", content="changed"), 1)[0])
        self.assertEqual(env.files["target.txt"], "draft")
        self.assertEqual(env.attempts, {"eval_write": 1})
        self.assert_state(env, 1, 1, 1, True)

    def test_cancellation_consumes_budget_and_cannot_revive_request(self):
        env = self.environment(1, delays={"eval_write": [50]})
        request = self.request("write", content="changed")
        env.submit(request, 0)
        env.cancel({key: request[key] for key in ("bridgeVersion", "requestId", "caseRunId", "sessionId")}
                   | {"type": "tool-cancel"})
        self.assertEqual(env.submit(request, 1)[0]["text"], "TOOL_CANCELLED: target.txt")
        self.assert_limit_error(env.handle(self.request()))
        self.assertEqual(env.poll(10), [])
        self.assertEqual(env.files["target.txt"], "draft")
        self.assert_state(env, 1, 1, 1, True)

    def test_exceeding_limit_cancels_all_pending_before_ready_work_can_commit(self):
        env = self.environment(2, delays={"eval_write": [50], "eval_delete": [50]})
        write = self.request("write", content="changed")
        delete = self.request("delete", "guard.txt")
        self.assertEqual(env.submit(write, 0), [])
        self.assertEqual(env.submit(delete, 0), [])
        self.assert_limit_error(env.submit(self.request(), .06)[0])
        self.assertEqual(env.pending, {})
        self.assertEqual(env.poll(10), [])
        self.assertEqual(env.files, self.case["environment"]["files"])
        for request in (write, delete):
            self.assertEqual(env.handle(request)["text"], "TOOL_CANCELLED: " + request["arguments"]["path"])
        self.assertEqual(env.attempts, {"eval_write": 1, "eval_delete": 1})
        self.assert_state(env, 2, 2, 1, True)

    def test_rejection_replays_are_cached_and_new_rejections_count_once(self):
        env = self.environment(0)
        request = self.request()
        response = env.handle(request)
        self.assert_limit_error(response)
        self.assertEqual(env.submit(request, 0), [response])
        response["text"] = "caller mutation"
        self.assert_limit_error(env.handle(request))
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            env.handle({**request, "arguments": {"path": "guard.txt"}})
        self.assert_state(env, 0, 0, 1, True)
        self.assert_limit_error(env.handle(self.request()))
        self.assert_state(env, 0, 0, 2, True)

    def test_invalid_protocol_identity_and_arguments_do_not_consume_budget(self):
        env = self.environment(0)
        request = self.request()
        variants = [{**request, **patch} for patch in (
            {"type": "tool-cancel"}, {"bridgeVersion": True}, {"bridgeVersion": 2},
            {"requestId": ""}, {"caseRunId": "other"}, {"sessionId": "other"},
            {"operation": "unknown"}, {"arguments": {"path": 1}},
            {"arguments": {"path": "target.txt", "unknown": True}}, {"arguments": {}},
        )]
        variants.extend([self.request("write", content=1), self.request("edit", oldText=1, newText="x"),
                         self.request("rename", destination=1)])
        for invalid in variants:
            with self.subTest(request=invalid), self.assertRaises(ValueError):
                env.submit(invalid, 0)
        self.assert_state(env, 0, 0, 0, False)
        self.assertEqual(env.responses, {})
        self.assertEqual(env.attempts, {})

    def test_snapshot_records_budget_and_cannot_claim_completion_after_rejection(self):
        env = self.environment(0)
        before = env.snapshot(self.case, "run", True)
        self.assertTrue(before["complete"])
        self.assertEqual(before["toolCallBudget"], env.budget_state())
        env.handle(self.request())
        after = env.snapshot(self.case, "run", True)
        self.assertFalse(after["complete"])
        self.assertEqual(after["toolCallBudget"], env.budget_state())
        after["toolCallBudget"]["rejected"] = 100
        self.assert_state(env, 0, 0, 1, True)
        self.assertEqual(before["toolCallBudget"]["rejected"], 0)

    def test_omitted_budget_keeps_legacy_snapshot_shape_and_unlimited_execution(self):
        env = self.environment(None)
        for _ in range(5):
            self.assertFalse(env.submit(self.request(), 0)[0]["isError"])
        self.assertIsNone(env.budget_state())
        self.assertFalse(env.budget_exhausted)
        snapshot = env.snapshot(self.case, "run", True)
        self.assertEqual(set(snapshot), {"environmentSnapshotFormatVersion", "caseRunId", "sessionId", "runId",
                                       "environmentSha256", "toolBudget", "complete", "files"})
        self.assertEqual(snapshot["toolBudget"], {"toolTimeoutMs": 100})
        self.assertTrue(snapshot["complete"])


if __name__ == "__main__":
    unittest.main()
