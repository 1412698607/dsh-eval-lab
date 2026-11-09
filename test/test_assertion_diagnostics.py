"""Scorer diagnostics describe causes without changing the legacy assertion result contract."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from dsh_eval.evaluate import check_assertion, check_assertions, evaluate, task_view
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT, run_synthetic_case


def tool_rule(identity, path, after=None):
    return {"id": identity, "type": "tool_result", "tool": "eval_read", "arguments": {"path": path},
            "result": {"isError": False, "textEquals": "ok"}, **({"after": after} if after else {})}


def view_for(schedule):
    events = [{"type": "user/message", "data": {"source": {"kind": "user"},
               "content": [{"type": "text", "text": "task"}]}}]
    for kind, call_id, value in schedule:
        if kind == "call":
            events.append({"type": "tool/call", "data": {"callId": call_id, "name": "eval_read",
                           "arguments": json.dumps({"path": value})}})
        else:
            events.append({"type": "tool/result", "data": {"message": {"toolCallId": call_id,
                           "isError": False, "content": [{"type": "text", "text": value}]}}})
    events.extend([{"type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "done"}]}}},
                   {"type": "turn/end", "data": {"reason": {"kind": "completed"}}}])
    for seq, event in enumerate(events):
        event["seq"] = seq
    return task_view(events, "task")


class AssertionDiagnosticBranchTests(unittest.TestCase):
    def score(self, assertions, view):
        before = deepcopy(view)
        diagnostics = []
        legacy = check_assertions(assertions, view)
        actual = check_assertions(assertions, view, diagnostics=diagnostics)
        self.assertEqual(actual, legacy)
        self.assertEqual(view, before)
        self.assertEqual([(row["id"], row["type"], row["outcome"]) for row in diagnostics],
                         [(row["id"], row["type"], row["outcome"]) for row in legacy])
        self.assertTrue(all("reasonCode" not in row and "blockedBy" not in row for row in actual))
        return actual, {row["id"]: row for row in diagnostics}

    def test_complete_positive_preserves_declared_dependency_chain(self):
        rules = [tool_rule("a", "a.txt"), tool_rule("b", "b.txt", "a"), tool_rule("c", "c.txt", "b")]
        schedule = [row for name in "abc" for row in (("call", name, name + ".txt"), ("result", name, "ok"))]
        rows, diagnostics = self.score(rules, view_for(schedule))
        self.assertEqual([row["outcome"] for row in rows], ["passed"] * 3)
        self.assertEqual([diagnostics[name]["reasonCode"] for name in "abc"], ["matched"] * 3)
        self.assertNotIn("after", diagnostics["a"])
        self.assertEqual((diagnostics["b"]["after"], diagnostics["c"]["after"]), ("a", "b"))
        self.assertFalse(any("blockedBy" in row for row in diagnostics.values()))

    def test_missing_predecessor_preserves_legacy_row_and_lists_matching_observed_events(self):
        rules = [tool_rule("a", "a.txt"), tool_rule("b", "b.txt", "a")]
        rows, diagnostics = self.score(rules, view_for([("call", "b", "b.txt"), ("result", "b", "ok")]))
        self.assertEqual(rows[0], {"id": "a", "type": "tool_result", "outcome": "insufficient_evidence",
                                   "reason": "No matching call/result before final answer"})
        self.assertEqual(rows[1], {"id": "b", "type": "tool_result", "outcome": "insufficient_evidence",
                                   "reason": "Required earlier tool result assertion a did not pass"})
        self.assertEqual(diagnostics["a"]["reasonCode"], "tool_evidence_missing")
        self.assertEqual(diagnostics["b"], {"id": "b", "type": "tool_result", "outcome": "insufficient_evidence",
                                           "reasonCode": "dependency_not_passed", "after": "a", "blockedBy": ["a"],
                                           "observedMatches": [{"callId": "b", "callSeq": 1, "resultSeq": 2, "answerSeq": 3}]})

    def test_failed_predecessor_keeps_failed_successor_even_with_matching_result(self):
        rules = [tool_rule("a", "a.txt"), tool_rule("b", "b.txt", "a")]
        rows, diagnostics = self.score(rules, view_for([("call", "a", "a.txt"), ("result", "a", "wrong"),
                                                       ("call", "b", "b.txt"), ("result", "b", "ok")]))
        self.assertEqual([row["outcome"] for row in rows], ["failed", "failed"])
        self.assertEqual(diagnostics["a"]["reasonCode"], "tool_result_mismatch")
        self.assertEqual(diagnostics["b"]["reasonCode"], "dependency_not_passed")
        self.assertEqual(diagnostics["b"]["observedMatches"][0]["callId"], "b")

    def test_multiple_independent_missing_sources_have_separate_direct_dependencies(self):
        rules = [tool_rule("a", "a.txt"), tool_rule("b", "b.txt", "a"),
                 tool_rule("x", "x.txt"), tool_rule("y", "y.txt", "x")]
        _rows, diagnostics = self.score(rules, view_for([]))
        self.assertEqual([key for key, row in diagnostics.items() if row["reasonCode"] == "tool_evidence_missing"], ["a", "x"])
        self.assertEqual((diagnostics["b"]["blockedBy"], diagnostics["y"]["blockedBy"]), (["a"], ["x"]))

    def test_result_and_order_failures_are_distinguished_by_the_scoring_branch(self):
        rules = [tool_rule("a", "a.txt"), tool_rule("b", "b.txt", "a")]
        for schedule, code in (
                ([("call", "a", "a.txt"), ("result", "a", "ok"),
                  ("call", "b", "b.txt"), ("result", "b", "wrong")], "tool_result_mismatch"),
                ([("call", "a", "a.txt"), ("call", "b", "b.txt"),
                  ("result", "a", "ok"), ("result", "b", "ok")], "tool_order_mismatch"),
                ([("call", "a", "a.txt"), ("call", "b", "b.txt"),
                  ("result", "a", "ok"), ("result", "b", "wrong")], "tool_result_and_order_mismatch")):
            with self.subTest(code=code):
                rows, diagnostics = self.score(rules, view_for(schedule))
                self.assertEqual(rows[1]["outcome"], "failed")
                self.assertEqual(diagnostics["b"]["reasonCode"], code)

    def test_observed_matches_ignore_order_but_require_tool_arguments_and_result_before_answer(self):
        rule = tool_rule("b", "b.txt", "a")
        view = view_for([("call", "wrong-path", "x.txt"), ("result", "wrong-path", "ok"),
                         ("call", "wrong-result", "b.txt"), ("result", "wrong-result", "bad"),
                         ("call", "match", "b.txt"), ("result", "match", "ok"),
                         ("call", "late", "b.txt"), ("result", "late", "ok")])
        view["results"]["late"]["seq"] = view["final"]["seq"] + 1
        diagnostics = []
        legacy = check_assertion(rule, view)
        self.assertEqual(check_assertion(rule, view, diagnostics=diagnostics), legacy)
        self.assertEqual([row["callId"] for row in diagnostics[0]["observedMatches"]], ["match"])

    def test_missing_result_is_original_missing_evidence_rather_than_dependency_block(self):
        rows, diagnostics = self.score([tool_rule("a", "a.txt")], view_for([("call", "a", "a.txt")]))
        self.assertEqual(rows[0]["outcome"], "insufficient_evidence")
        self.assertEqual(diagnostics["a"]["reasonCode"], "tool_evidence_missing")
        self.assertNotIn("blockedBy", diagnostics["a"])

    def test_non_tool_assertion_reasons_and_passes_match_actual_branch(self):
        view = view_for([("call", "a", "a.txt"), ("result", "a", "ok")])
        rules = [{"id": "state", "type": "environment_files", "equals": {}},
                 {"id": "answer", "type": "final_text", "equals": "wrong"},
                 {"id": "end", "type": "turn_end", "reason": {"kind": "aborted"}},
                 {"id": "forbidden", "type": "tool_forbidden", "tool": "eval_read"},
                 {"id": "count", "type": "tool_call_count", "tool": "eval_read", "min": 2}]
        _rows, diagnostics = self.score(rules, view)
        self.assertEqual([row["reasonCode"] for row in diagnostics.values()],
                         ["environment_snapshot_missing", "final_text_mismatch", "turn_end_mismatch",
                          "forbidden_tool_observed", "tool_call_count_out_of_bounds"])
        view["environmentSnapshot"] = {"files": {"a.txt": "ok"}}
        _rows, diagnostics = self.score(rules[:1], view)
        self.assertEqual(diagnostics["state"]["reasonCode"], "environment_files_mismatch")
        for row in rules:
            if row["id"] == "state":
                row["equals"] = {"a.txt": "ok"}
            elif row["id"] == "answer":
                row["equals"] = "done"
            elif row["id"] == "end":
                row["reason"] = {"kind": "completed"}
            else:
                row["tool"] = "eval_write"
                row.pop("min", None)
        _rows, diagnostics = self.score(rules, view)
        self.assertEqual([row["reasonCode"] for row in diagnostics.values()], ["matched"] * len(rules))


class AssertionDiagnosticRecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="dsh-causal-diagnostics-")
        cls.directory = Path(cls.temporary.name)
        path = ROOT / "fixtures/evaluation/rename-timeout-retry.case.json"
        cls.positive = run_synthetic_case(path, cls.directory / "runs", final_text="done")
        cls.negative = run_synthetic_case(path, cls.directory / "runs", final_text="done",
                                          scenario="rename-timeout-skip-readbacks")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_real_skipped_trace_keeps_six_passes_four_missing_and_links_unqualified_retry(self):
        result = self.negative
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["assertionDiagnostics"]["assertionDiagnosticsFormatVersion"], 1)
        diagnostics = {row["id"]: row for row in result["assertionDiagnostics"]["results"]}
        rows = {row["id"]: row for row in result["assertions"]["results"]}
        self.assertEqual(sum(row["outcome"] == "passed" for row in rows.values()), 6)
        self.assertEqual([key for key, row in rows.items() if row["outcome"] == "insufficient_evidence"],
                         ["source-still-present", "target-still-missing", "retry", "verify"])
        self.assertEqual(diagnostics["source-still-present"]["reasonCode"], "tool_evidence_missing")
        self.assertEqual(diagnostics["source-still-present"]["after"], "timeout")
        for key, predecessor in (("target-still-missing", "source-still-present"),
                                 ("retry", "target-still-missing"), ("verify", "retry")):
            self.assertEqual(diagnostics[key]["reasonCode"], "dependency_not_passed")
            self.assertEqual(diagnostics[key]["blockedBy"], [predecessor])
        self.assertEqual(diagnostics["target-still-missing"]["observedMatches"], [])
        self.assertEqual(diagnostics["retry"]["observedMatches"],
                         [{"callId": "call-1", "callSeq": 4, "resultSeq": 5, "answerSeq": 8}])
        self.assertEqual(diagnostics["verify"]["observedMatches"],
                         [{"callId": "call-2", "callSeq": 6, "resultSeq": 7, "answerSeq": 8}])
        self.assertNotIn("evidence", rows["retry"])
        self.assertNotIn("evidence", rows["verify"])
        association = result["association"]
        fresh = evaluate(association["casePath"], association["evidencePath"])
        self.assertEqual(fresh["assertions"], result["assertions"])
        self.assertEqual(fresh["assertionDiagnostics"], result["assertionDiagnostics"])

    def test_real_positive_has_all_passed_steps_and_full_declared_chain(self):
        result = self.positive
        self.assertEqual(result["outcome"], "passed")
        self.assertTrue(all(row["reasonCode"] == "matched" for row in result["assertionDiagnostics"]["results"]))
        self.assertEqual([(row["id"], row["after"]) for row in result["assertionDiagnostics"]["results"] if "after" in row],
                         [("source-still-present", "timeout"), ("target-still-missing", "source-still-present"),
                          ("retry", "target-still-missing"), ("verify", "retry")])

    def test_recording_execution_and_invalid_evidence_gates_keep_original_outcomes(self):
        original = load_json(self.positive["association"]["evidencePath"])
        path = Path(self.positive["association"]["evidencePath"]).with_name("gate-evidence.json")
        for updates, outcome, code in (({"runDir": None}, "not_run", "recording_not_complete"),
                                       ({"execution": {"status": "runtime_error"}}, "not_run", "execution_not_completed"),
                                       ({"configuration": {**original["configuration"], "model": "different"}},
                                        "insufficient_evidence", "evaluation_evidence_invalid")):
            with self.subTest(code=code):
                path.write_text(json.dumps({**original, **updates}), encoding="utf-8")
                fresh = evaluate(self.positive["association"]["casePath"], path)
                self.assertEqual(fresh["outcome"], "unevaluable")
                self.assertTrue(all(row["outcome"] == outcome for row in fresh["assertions"]["results"]))
                self.assertTrue(all(row["reasonCode"] == code for row in fresh["assertionDiagnostics"]["results"]))
                declared = next(row for row in fresh["assertionDiagnostics"]["results"] if row["id"] == "retry")
                self.assertEqual(declared["after"], "target-still-missing")
                self.assertNotIn("blockedBy", declared)


if __name__ == "__main__":
    unittest.main()
