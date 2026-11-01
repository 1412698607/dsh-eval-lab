import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.evaluate import check_assertion, evaluate, inspect_recording, task_view
from dsh_eval.formats import load_json, parse_json, validate_case, validate_evidence
from dsh_eval.environment import StatefulEnvironment

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "evaluation"


def fixture(name="read-project", kind="case"):
    return load_json(FIXTURES / f"{name}.{kind}.json")


def resequence(events):
    for index, event in enumerate(events):
        event["seq"] = index
    return events


class FormatTests(unittest.TestCase):
    def test_behavior_assertions_accept_explicit_selectors_and_inclusive_bounds(self):
        for version in (1, 2):
            for assertion in (
                {"id": "guard", "type": "tool_forbidden", "tool": "read"},
                {"id": "guard", "type": "tool_forbidden", "tool": "read", "arguments": {}},
                {"id": "guard", "type": "tool_call_count", "tool": "read", "min": 0},
                {"id": "guard", "type": "tool_call_count", "tool": "read", "max": 0},
                {"id": "guard", "type": "tool_call_count", "tool": "read", "arguments": {"path": "README.md"}, "min": 1, "max": 1},
                {"id": "guard", "type": "tool_call_count", "tool": "read", "max": 9007199254740991},
            ):
                with self.subTest(version=version, assertion=assertion):
                    case = fixture()
                    case.update(caseFormatVersion=version)
                    case["assertions"].append(assertion)
                    original = copy.deepcopy(case)
                    self.assertEqual(validate_case(case), original)

    def test_behavior_assertions_reject_invalid_selectors_bounds_and_dependencies(self):
        base = {"id": "guard", "type": "tool_call_count", "tool": "read", "max": 1}
        variants = [{key: value for key, value in base.items() if key != "max"},
                    {**base, "min": 2}, {**base, "after": "read-evidence"}, {**base, "result": {}},
                    {**base, "tool": ""}, {key: value for key, value in base.items() if key != "tool"}]
        for value in (None, True, False, -1, 1.5, "1", 9007199254740992):
            variants.extend([{**base, "max": value}, {**base, "min": value}])
        variants.extend({**base, "arguments": value} for value in (None, [], "README.md", 1))
        variants.extend({"id": "guard", "type": "tool_forbidden", "tool": "read", **extra}
                        for extra in ({"min": 0}, {"max": 0}, {"after": "read-evidence"}, {"arguments": []}))
        for assertion in variants:
            with self.subTest(assertion=assertion), self.assertRaises(ValueError):
                case = fixture()
                case["assertions"].append(assertion)
                validate_case(case)
        case = fixture()
        case["assertions"].insert(0, {"id": "guard", "type": "tool_forbidden", "tool": "write"})
        case["assertions"][2]["after"] = "guard"
        with self.assertRaises(ValueError):
            validate_case(case)

    def test_only_version_two_allows_tool_result_without_argument_constraints(self):
        case = fixture()
        case["assertions"][1]["arguments"] = {}
        with self.assertRaises(ValueError):
            validate_case(case)
        case["caseFormatVersion"] = 2
        self.assertEqual(validate_case(case)["assertions"][1]["arguments"], {})

    def test_both_public_cases_load(self):
        for name in ("read-project", "missing-file"):
            self.assertEqual(validate_case(fixture(name))["caseId"], name)

    def test_unknown_versions_fields_assertions_and_duplicate_ids_rejected(self):
        mutations = [lambda case: case.update(caseFormatVersion=3),
                     lambda case: case.update(caseFormatVersion=True),
                     lambda case: case.update(typo="unsupported"),
                     lambda case: case.update(assertions=[]),
                     lambda case: case["assertions"][0].update(type="guess"),
                     lambda case: case["assertions"][1].update(id="answer"),
                     lambda case: case["budget"].update(timeoutSeconds=True),
                     lambda case: case["budget"].update(tokens=10),
                     lambda case: case["assertions"][1]["result"].update(isError=0)]
        for index, mutate in enumerate(mutations):
            case = fixture()
            mutate(case)
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_case(case)

    def test_unsafe_or_colliding_fixture_paths_rejected(self):
        for files in ({"../secret": "x"}, {"/absolute": "x"}, {"C:/file": "x"}, {"a\\b": "x"},
                      {"a/./b": "x"}, {"a//b": "x"}, {"a": "x", "a/b/c": "y"}):
            case = fixture()
            case["environment"]["files"] = files
            with self.subTest(files=files), self.assertRaises(ValueError):
                validate_case(case)

    def test_duplicate_keys_and_nonfinite_numbers_rejected(self):
        for text in ('{"caseId":"a","caseId":"b"}', '{"value":NaN}', '{"value":Infinity}', '{"value":1e999}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_json(text)


class AssertionTests(unittest.TestCase):
    def test_behavior_assertions_count_calls_with_no_result_or_error_after_final_answer(self):
        for with_result in (False, True):
            events = fixture(kind="events")
            call = {"type": "tool/call", "data": {"callId": "extra", "name": "read", "arguments": '{"path":"restricted.md"}'}}
            events.insert(-1, call)
            if with_result:
                events.insert(-1, {"type": "tool/result", "data": {"message": {"toolCallId": "extra", "isError": True, "content": []}}})
            view = task_view(resequence(events), fixture()["input"])
            for kind, bounds in (("tool_forbidden", {}), ("tool_call_count", {"max": 0})):
                assertion = {"id": "guard", "type": kind, "tool": "read", "arguments": {"path": "restricted.md"}, **bounds}
                result = check_assertion(assertion, view)
                self.assertEqual((result["outcome"], result["actual"]), ("failed", 1))
                self.assertEqual(result["evidence"][0]["callSeq"], call["seq"])
                self.assertGreater(result["evidence"][0]["callSeq"], view["final"]["seq"])
                self.assertEqual("resultSeq" in result["evidence"][0], with_result)

    def test_behavior_selectors_match_typed_arguments_without_path_normalization(self):
        events = fixture(kind="events")
        events[2]["data"]["arguments"] = json.dumps({"path": "README.md", "options": {"enabled": True}, "extra": 3})
        view = task_view(events, fixture()["input"])
        for arguments, count in (({}, 1), ({"path": "README.md"}, 1), ({"options": {"enabled": True}}, 1),
                                 ({"options": {"enabled": 1}}, 0), ({"missing": None}, 0),
                                 ({"path": "./README.md"}, 0), ({"path": "readme.md"}, 0)):
            assertion = {"id": "guard", "type": "tool_forbidden", "tool": "read", "arguments": arguments}
            result = check_assertion(assertion, view)
            self.assertEqual(result["actual"], count)
            self.assertEqual(result["outcome"], "failed" if count else "passed")
        self.assertEqual(check_assertion({"id": "guard", "type": "tool_forbidden", "tool": "READ"}, view)["actual"], 0)

    def test_behavior_count_bounds_include_zero_exact_minimum_and_maximum(self):
        view = task_view(fixture(kind="events"), fixture()["input"])
        for tool, bounds, outcome, actual in (
            ("read", {"min": 1, "max": 1}, "passed", 1), ("read", {"max": 0}, "failed", 1),
            ("read", {"min": 2}, "failed", 1), ("read", {"min": 0}, "passed", 1),
            ("write", {"max": 0}, "passed", 0), ("write", {"min": 1}, "failed", 0),
        ):
            with self.subTest(tool=tool, bounds=bounds):
                result = check_assertion({"id": "guard", "type": "tool_call_count", "tool": tool, **bounds}, view)
                self.assertEqual((result["outcome"], result["actual"]), (outcome, actual))
                self.assertEqual(len(result["evidence"]), actual)
        events = fixture(kind="events")
        extra = copy.deepcopy(events[2])
        extra["data"]["callId"] = "second-attempt"
        events.insert(4, extra)
        view = task_view(resequence(events), fixture()["input"])
        result = check_assertion({"id": "guard", "type": "tool_call_count", "tool": "read", "min": 2, "max": 2}, view)
        self.assertEqual((result["outcome"], result["actual"]), ("passed", 2))
        self.assertEqual([row["callId"] for row in result["evidence"]], ["read-1", "second-attempt"])

    def test_result_based_discovery_still_requires_tool_and_linked_success_content(self):
        assertion = next(item for item in fixture("stale-path")["assertions"] if item["id"] == "tool-2")
        events = fixture(kind="events")
        events[2]["data"].update(name="eval_list", arguments='{"path":"."}')
        events[3]["data"]["message"]["content"][0]["text"] = "README.md\ndocs/current.md"
        view = task_view(events, fixture()["input"])
        self.assertEqual(check_assertion(assertion, view)["outcome"], "passed")
        for mutation, expected in (
                (lambda rows: rows[2]["data"].update(name="other_tool"), "insufficient_evidence"),
                (lambda rows: rows[3]["data"]["message"].update(content=[{"type": "text", "text": "unrelated.md"}]), "failed"),
                (lambda rows: rows[3]["data"]["message"].update(isError=True), "failed"),
                (lambda rows: rows.pop(3), "insufficient_evidence")):
            variant = copy.deepcopy(events)
            mutation(variant)
            self.assertEqual(check_assertion(assertion, task_view(resequence(variant), fixture()["input"]))["outcome"], expected)

    def test_valid_evidence_includes_sequence_and_call_identity(self):
        view = task_view(fixture(kind="events"), fixture()["input"])
        result = check_assertion(fixture()["assertions"][1], view)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(result["evidence"], {"callId": "read-1", "callSeq": 2, "resultSeq": 3, "answerSeq": 4})

    def test_missing_result_and_late_result_cannot_pass(self):
        events = fixture(kind="events")
        missing = resequence([event for event in copy.deepcopy(events) if event["type"] != "tool/result"])
        late = copy.deepcopy(events)
        late[3], late[4] = late[4], late[3]
        for variant in (missing, resequence(late)):
            view = task_view(variant, fixture()["input"])
            self.assertEqual(check_assertion(fixture()["assertions"][1], view)["outcome"], "insufficient_evidence")

    def test_wrong_call_id_reversed_and_duplicate_results_rejected(self):
        wrong = fixture(kind="events")
        wrong[3]["data"]["message"]["toolCallId"] = "other"
        reversed_events = fixture(kind="events")
        reversed_events[2], reversed_events[3] = reversed_events[3], reversed_events[2]
        duplicate = fixture(kind="events")
        duplicate.insert(4, copy.deepcopy(duplicate[3]))
        duplicate_call = fixture(kind="events")
        duplicate_call.insert(3, copy.deepcopy(duplicate_call[2]))
        for variant in (wrong, resequence(reversed_events), resequence(duplicate), resequence(duplicate_call)):
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                task_view(variant, fixture()["input"])

    def test_wrong_answer_and_result_are_explicit_failures(self):
        events = fixture(kind="events")
        events[4]["data"]["message"]["content"][0]["text"] = "wrong"
        events[3]["data"]["message"]["isError"] = True
        view = task_view(events, fixture()["input"])
        for assertion in fixture()["assertions"][:2]:
            self.assertEqual(check_assertion(assertion, view)["outcome"], "failed")

    def test_tool_arguments_and_name_are_case_defined(self):
        events = fixture(kind="events")
        events[2]["data"].update(name="host-read", arguments='{"file_path":"README.md","limit":10}')
        assertion = fixture()["assertions"][1]
        assertion.update(tool="host-read", arguments={"file_path": "README.md"})
        view = task_view(events, fixture()["input"])
        self.assertEqual(check_assertion(assertion, view)["outcome"], "passed")
        assertion["arguments"] = {"limit": True}
        self.assertEqual(check_assertion(assertion, view)["outcome"], "insufficient_evidence")
        assertion.update(tool="wrong-tool", arguments={"file_path": "README.md"})
        self.assertEqual(check_assertion(assertion, view)["outcome"], "insufficient_evidence")

    def test_malformed_known_events_and_arguments_rejected(self):
        for mutate in (lambda events: events[2]["data"].update(arguments="invalid"),
                       lambda events: events[2]["data"].update(arguments='{"path":"README.md","path":"other"}'),
                       lambda events: events[3]["data"]["message"].pop("isError"),
                       lambda events: events[4]["data"].update(message={"content": "bad"})):
            events = fixture(kind="events")
            mutate(events)
            with self.assertRaises(ValueError):
                task_view(events, fixture()["input"])

    def test_input_boundaries_multi_turn_gaps_and_unknown_events(self):
        wrong_input = fixture(kind="events")
        wrong_input[1]["data"]["content"][0]["text"] = "different task"
        second_user = fixture(kind="events")
        second_user.insert(4, copy.deepcopy(second_user[1]))
        gap = fixture(kind="events")
        for event in gap[3:]:
            event["seq"] += 1
        after_end = fixture(kind="events")
        after_end.append(copy.deepcopy(after_end[4]))
        before_input = fixture(kind="events")
        before_input.insert(0, copy.deepcopy(before_input[4]))
        for variant in (wrong_input, resequence(second_user), gap, resequence(after_end), resequence(before_input)):
            with self.assertRaises(ValueError):
                task_view(variant, fixture()["input"])
        unknown = fixture(kind="events")
        unknown.insert(3, {"type": "future/opaque", "data": {"anything": True}})
        view = task_view(resequence(unknown), fixture()["input"])
        self.assertEqual(check_assertion(fixture()["assertions"][1], view)["outcome"], "passed")


class OfflineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-eval-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.case_path = self.directory / "case.json"
        self.case_path.write_text(json.dumps(fixture()), encoding="utf-8")

    def record(self, events=None, seal=True, name="read-project", case=None):
        self.case_path.write_text(json.dumps(fixture(name) if case is None else case), encoding="utf-8")
        code = """
import { recordExample } from './scripts/demo-eval.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
console.log(JSON.stringify(await recordExample(data.casePath, data.events, data.outputDir, { seal: data.seal })));
"""
        process = subprocess.run(["node", "--input-type=module", "-e", code], cwd=ROOT,
                                 input=json.dumps({"casePath": str(self.case_path), "events": events if events is not None else fixture(name, "events"),
                                                   "outputDir": str(self.directory), "seal": seal}),
                                 capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
        self.evidence_path = Path(json.loads(process.stdout)["evidencePath"])
        return load_json(self.evidence_path)

    def edit_evidence(self, **updates):
        evidence = load_json(self.evidence_path)
        evidence.update(updates)
        self.evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    def test_correct_answer_with_forbidden_or_excess_calls_fails_after_real_recording(self):
        for kind, path, bounds in (("tool_forbidden", "restricted.md", {}), ("tool_call_count", "README.md", {"max": 1})):
            for after_answer in (False, True):
                with self.subTest(kind=kind, after_answer=after_answer):
                    case, events = fixture(), fixture(kind="events")
                    case["assertions"].append({"id": "behavior", "type": kind, "tool": "read", "arguments": {"path": path}, **bounds})
                    call, response = copy.deepcopy(events[2:4])
                    call["data"].update(callId="extra", arguments=json.dumps({"path": path}))
                    response["data"]["message"].update(toolCallId="extra", isError=True)
                    position = len(events) - 1 if after_answer else 4
                    events[position:position] = [call, response]
                    self.record(resequence(events), case=case)
                    before = {p: p.read_bytes() for p in self.evidence_path.parent.iterdir() if p.is_file()}
                    result = evaluate(self.case_path, self.evidence_path)
                    self.assertEqual((result["execution"]["status"], result["recording"]["outcome"], result["outcome"]),
                                     ("completed", "complete", "failed"))
                    self.assertTrue(all(row["outcome"] == "passed" for row in result["assertions"]["results"][:-1]))
                    guard = result["assertions"]["results"][-1]
                    self.assertEqual((guard["outcome"], guard["actual"]), ("failed", 1 if kind == "tool_forbidden" else 2))
                    self.assertEqual(guard["evidence"][-1]["callSeq"], call["seq"])
                    self.assertEqual({p: p.read_bytes() for p in before}, before)
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(main(["--case", str(self.case_path), "--evidence", str(self.evidence_path)]), 1)

    def test_behavior_compliance_passes_and_minimum_shortfall_fails(self):
        case = fixture()
        case["assertions"].extend([
            {"id": "forbidden", "type": "tool_forbidden", "tool": "read", "arguments": {"path": "restricted.md"}},
            {"id": "count", "type": "tool_call_count", "tool": "read", "min": 1, "max": 1},
        ])
        self.record(case=case)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual([row["actual"] for row in result["assertions"]["results"][-2:]], [0, 1])
        case["assertions"][-1].update(min=2, max=2)
        self.record(case=case)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["assertions"]["results"][0]["outcome"], "passed")

    def test_behavior_missing_tool_result_is_still_a_counted_violation(self):
        case, events = fixture(), fixture(kind="events")
        case["assertions"] = [item for item in case["assertions"] if item["type"] != "tool_result"]
        case["assertions"].extend([
            {"id": "forbidden", "type": "tool_forbidden", "tool": "read"},
            {"id": "count", "type": "tool_call_count", "tool": "read", "max": 0},
        ])
        self.record(resequence([event for event in events if event["type"] != "tool/result"]), case=case)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual((result["recording"]["outcome"], result["outcome"]), ("complete", "failed"))
        self.assertEqual(result["assertions"]["results"][0]["outcome"], "passed")
        for row in result["assertions"]["results"][-2:]:
            self.assertEqual((row["outcome"], row["actual"]), ("failed", 1))
            self.assertEqual(row["evidence"], [{"callId": "read-1", "callSeq": 2}])

    def test_behavior_absence_is_not_inferred_from_incomplete_or_malformed_evidence(self):
        case = fixture()
        case["assertions"] = [{"id": "guard", "type": "tool_forbidden", "tool": "write"},
                              {"id": "count", "type": "tool_call_count", "tool": "write", "max": 0}]
        self.record(case=case, seal=False)
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["assertions"]["outcome"], "not_run")
        for corruption in ("arguments", "duplicate-id", "gap"):
            events = fixture(kind="events")
            if corruption == "arguments":
                events[2]["data"]["arguments"] = "not-json"
            elif corruption == "duplicate-id":
                events.insert(4, copy.deepcopy(events[2]))
                resequence(events)
            else:
                for event in events[3:]:
                    event["seq"] += 1
            self.record(events, case=case)
            result = evaluate(self.case_path, self.evidence_path)
            self.assertEqual(result["outcome"], "unevaluable")
            self.assertTrue(all(row["outcome"] != "passed" for row in result["assertions"]["results"]))
        self.record(case=case)
        self.edit_evidence(execution={"status": "runtime_error", "exitCode": 1})
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["assertions"]["outcome"], "not_run")

    def test_behavior_failure_keeps_missing_required_result_unevaluable(self):
        case, events = fixture(), fixture(kind="events")
        case["assertions"].extend([
            {"id": "forbidden", "type": "tool_forbidden", "tool": "read"},
            {"id": "count", "type": "tool_call_count", "tool": "read", "max": 0},
        ])
        self.record(resequence([event for event in events if event["type"] != "tool/result"]), case=case)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual((result["execution"]["status"], result["recording"]["outcome"], result["outcome"]),
                         ("completed", "complete", "unevaluable"))
        rows = {row["id"]: row for row in result["assertions"]["results"]}
        self.assertEqual(rows["answer"]["outcome"], "passed")
        self.assertEqual(rows["read-evidence"]["outcome"], "insufficient_evidence")
        for name in ("forbidden", "count"):
            self.assertEqual((rows[name]["outcome"], rows[name]["actual"]), ("failed", 1))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--case", str(self.case_path), "--evidence", str(self.evidence_path)]), 2)

    def test_behavior_calls_outside_task_boundaries_cannot_be_ignored_as_zero(self):
        for position in (1, 6):
            with self.subTest(position=position):
                case, events = fixture(), fixture(kind="events")
                case["assertions"] = [
                    {"id": "forbidden", "type": "tool_forbidden", "tool": "write"},
                    {"id": "count", "type": "tool_call_count", "tool": "write", "max": 0},
                ]
                events.insert(position, {"type": "tool/call", "data": {"callId": "outside", "name": "write", "arguments": "{}"}})
                self.record(resequence(events), case=case)
                result = evaluate(self.case_path, self.evidence_path)
                self.assertEqual(result["recording"]["outcome"], "complete")
                self.assertEqual(result["outcome"], "unevaluable")
                self.assertIn("outside the single task boundaries", result["assertions"]["reason"])
                for row in result["assertions"]["results"]:
                    self.assertEqual(row["outcome"], "insufficient_evidence")
                    self.assertNotIn("actual", row)

    def test_oversized_event_invalidates_recording_before_task_assertions(self):
        evidence = self.record()
        code = """
import { createRecorder } from './src/recorder.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
const recorder = createRecorder({ outputDir: data.outputDir });
// First persist all the valid task evidence, then reject an oversized event.
for (const event of data.events) recorder.record(data.sessionId, event);
await recorder.flush();
const accepted = recorder.record(data.sessionId, { seq: data.events.length, data: 'x'.repeat(1024 * 1024) });
let closeRejected = false;
try { await recorder.close(); } catch (error) {
  if (!(error instanceof AggregateError)) throw error;
  closeRejected = true;
}
console.log(JSON.stringify({ runId: recorder.runId, runDir: recorder.runDir, accepted, closeRejected }));
"""
        process = subprocess.run(["node", "--input-type=module", "-e", code], cwd=ROOT,
                                 input=json.dumps({"outputDir": str(self.directory), "sessionId": evidence["sessionId"],
                                                   "events": fixture(kind="events")}),
                                 capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
        run = json.loads(process.stdout)
        self.assertFalse(run["accepted"])
        self.assertTrue(run["closeRejected"])
        self.edit_evidence(runId=run["runId"], runDir=run["runDir"])
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["execution"]["status"], "completed")
        self.assertEqual(result["recording"]["outcome"], "invalid")
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["assertions"]["outcome"], "not_run")
        status = load_json(next(Path(run["runDir"]).glob("*.status.json")))
        self.assertEqual(status["error"]["code"], "EVENT_BYTES_LIMIT")

    def test_metrics_use_fresh_linked_recordings_and_reported_usage(self):
        events = fixture(kind="events")
        events[4]["data"]["usage"] = {"inputTokens": 9, "outputTokens": 3, "totalTokens": 12}
        events.insert(2, {"type": "assistant/message", "data": {"message": {"content": []},
                         "usage": {"inputTokens": 2, "outputTokens": 0, "totalTokens": 2}}})
        self.record(resequence(events))
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual({key: result["metrics"][key] for key in ("modelCalls", "toolCalls", "inputTokens", "outputTokens", "totalTokens")},
                         {"modelCalls": 2, "toolCalls": 1, "inputTokens": 11, "outputTokens": 3, "totalTokens": 14})
        self.assertIsNone(result["metrics"]["elapsedSeconds"])
        self.assertIsNone(result["metrics"]["cost"])
        trace = next(self.evidence_path.parent.glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-1])
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["recording"]["outcome"], "invalid")
        self.assertIsNone(result["metrics"]["modelCalls"])
        self.assertIsNone(result["metrics"]["totalTokens"])

    def test_cancelled_task_can_retain_observed_metrics_without_becoming_evaluable(self):
        events = fixture(kind="events")
        events[-1]["data"]["reason"] = {"kind": "aborted", "reason": {"kind": "user"}}
        self.record(events)
        self.edit_evidence(execution={"status": "cancelled", "exitCode": 1})
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["assertions"]["outcome"], "not_run")
        self.assertEqual(result["metrics"]["modelCalls"], 1)
        self.assertIsNone(result["metrics"]["inputTokens"])

    def test_elapsed_measurement_requires_matching_runtime_identity(self):
        original = self.record()
        runtime_path = self.evidence_path.parent / "runtime.json"
        self.edit_evidence(evidenceFormatVersion=2, runtimeReport="runtime.json")
        for identity, elapsed, expected in (("wrong", 4.25, None), (original["caseRunId"], -1, None),
                                            (original["caseRunId"], True, None), (original["caseRunId"], 4.25, 4.25)):
            with self.subTest(identity=identity, elapsed=elapsed):
                runtime_path.write_text(json.dumps({"runtimeFormatVersion": 1, "caseRunId": identity, "elapsedSeconds": elapsed}), encoding="utf-8")
                result = evaluate(self.case_path, self.evidence_path)
                self.assertEqual(result["metrics"]["elapsedSeconds"], expected)
                self.assertEqual(result["outcome"], "passed")

    def test_oversized_elapsed_metric_preserves_evaluation_and_cli_result(self):
        original = self.record()
        baseline = evaluate(self.case_path, self.evidence_path)
        self.edit_evidence(evidenceFormatVersion=2, runtimeReport="runtime.json")
        runtime_path = self.evidence_path.parent / "runtime.json"
        for elapsed in (10 ** 400, -(10 ** 400)):
            with self.subTest(elapsed=elapsed):
                runtime_path.write_text(json.dumps({"runtimeFormatVersion": 1, "caseRunId": original["caseRunId"],
                                                    "elapsedSeconds": elapsed}), encoding="utf-8")
                result = evaluate(self.case_path, self.evidence_path)
                self.assertEqual(result["outcome"], "passed")
                self.assertEqual(result["execution"], baseline["execution"])
                self.assertEqual(result["recording"]["outcome"], "complete")
                self.assertEqual(result["assertions"], baseline["assertions"])
                self.assertEqual(result["metrics"]["modelCalls"], baseline["metrics"]["modelCalls"])
                self.assertIsNone(result["metrics"]["elapsedSeconds"])
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(["--case", str(self.case_path), "--evidence", str(self.evidence_path)]), 0)
                self.assertEqual(parse_json(output.getvalue())["outcome"], "passed")

    def test_stale_path_recovery_accepts_root_and_docs_discovery(self):
        case = fixture("stale-path")
        for directory in (".", "docs"):
            with self.subTest(directory=directory):
                environment = StatefulEnvironment(case["environment"], "synthetic-case")
                environment.bind("synthetic-session")
                events = [{"type": "turn/start", "data": {}},
                          {"type": "user/message", "data": {"source": {"kind": "user"},
                           "content": [{"type": "text", "text": case["input"]}]}}]
                for index, (operation, path) in enumerate((("read", "README.md"), ("read", "docs/old.md"),
                                                           ("list", directory), ("read", "docs/current.md"))):
                    call_id = f"recovery-{index}"
                    response = environment.handle({"type": "tool-request", "bridgeVersion": 1, "requestId": call_id,
                        "caseRunId": "synthetic-case", "sessionId": "synthetic-session", "operation": operation,
                        "arguments": {"path": path}})
                    events.extend([
                        {"type": "tool/call", "data": {"callId": call_id, "name": f"eval_{operation}",
                         "arguments": json.dumps({"path": path})}},
                        {"type": "tool/result", "data": {"message": {"toolCallId": call_id, "isError": response["isError"],
                         "content": [{"type": "text", "text": response["text"]}]}}}])
                events.extend([
                    {"type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "dsh-stateful-path"}]}}},
                    {"type": "turn/end", "data": {"reason": {"kind": "completed"}}}])
                self.record(resequence(events), case=case)
                result = evaluate(self.case_path, self.evidence_path)
                self.assertEqual(result["recording"]["outcome"], "complete")
                self.assertEqual(result["assertions"]["outcome"], "passed")
                self.assertEqual(result["outcome"], "passed")

    def test_two_synthetic_cases_pass_with_independent_associations(self):
        ids = []
        for name in ("read-project", "missing-file"):
            evidence = self.record(name=name)
            result = evaluate(self.case_path, self.evidence_path)
            self.assertEqual(result["outcome"], "passed")
            self.assertEqual(result["recording"]["outcome"], "complete")
            self.assertEqual(result["execution"]["status"], "completed")
            self.assertFalse(result["budgetEnforcement"]["timeoutSeconds"])
            self.assertNotEqual(result["caseRunId"], evidence["runId"])
            ids.append(result["caseRunId"])
        self.assertEqual(len(set(ids)), 2)

    def test_fresh_inspect_rejects_truncation_even_after_old_success(self):
        self.record()
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["outcome"], "passed")
        trace = next(self.evidence_path.parent.glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-1])
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["recording"]["outcome"], "invalid")
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_open_and_missing_recordings_do_not_run_assertions(self):
        self.record(seal=False)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["recording"]["outcome"], "unverified")
        self.assertEqual(result["assertions"]["outcome"], "not_run")
        self.edit_evidence(runDir="does-not-exist")
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["outcome"], "unevaluable")

    def test_missing_inventory_pair_cannot_inherit_a_previous_passed_result(self):
        import hashlib
        self.record()
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["outcome"], "passed")
        path = self.evidence_path.parent / "run.json"
        manifest = load_json(path)
        filename = hashlib.sha256(b"missing-session").hexdigest()
        manifest["sessions"].append({"sessionId": "missing-session", "traceFile": f"{filename}.jsonl",
                                     "statusFile": f"{filename}.status.json"})
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["recording"]["outcome"], "invalid")
        self.assertEqual(result["recording"]["inspection"]["runManifest"]["outcome"], "invalid")
        self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_open_inventory_does_not_inherit_a_sealed_sessions_success(self):
        self.record()
        path = self.evidence_path.parent / "run.json"
        manifest = load_json(path)
        manifest["state"] = "recording"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertEqual(result["recording"]["outcome"], "unverified")
        self.assertEqual(result["recording"]["inspection"]["sessions"][0]["outcome"], "complete")
        self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_legacy_recording_keeps_its_pass_with_explicitly_unknown_run_coverage(self):
        self.record()
        path = self.evidence_path.parent / "run.json"
        manifest = load_json(path)
        for key in ("runManifestFormatVersion", "state", "sessions"):
            manifest.pop(key)
        manifest["formatVersion"] = 1
        path.write_text(json.dumps(manifest), encoding="utf-8")
        before = path.read_bytes()
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(result["recording"]["outcome"], "complete")
        self.assertEqual(result["recording"]["inspection"]["runManifest"]["outcome"], "unverified")
        self.assertEqual(path.read_bytes(), before)

    def test_valid_recording_wrong_answer_is_task_failed(self):
        events = fixture(kind="events")
        events[4]["data"]["message"]["content"][0]["text"] = "wrong"
        self.record(events)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["recording"]["outcome"], "complete")
        self.assertEqual(result["assertions"]["results"][0]["outcome"], "failed")

    def test_sealed_missing_tool_result_and_bad_call_id_are_unevaluable(self):
        events = fixture(kind="events")
        missing = resequence([event for event in copy.deepcopy(events) if event["type"] != "tool/result"])
        events[3]["data"]["message"]["toolCallId"] = "wrong"
        for variant in (missing, events):
            self.record(variant)
            result = evaluate(self.case_path, self.evidence_path)
            self.assertEqual(result["recording"]["outcome"], "complete")
            self.assertEqual(result["assertions"]["outcome"], "insufficient_evidence")
            self.assertEqual(result["outcome"], "unevaluable")

    def test_cancel_timeout_runtime_error_are_not_task_failures(self):
        events = fixture(kind="events")[:2]
        events.append({"seq": 2, "type": "turn/end", "data": {"reason": {"kind": "aborted", "reason": {"kind": "user"}}}})
        self.record(events)
        for status in ("cancelled", "timed_out", "runtime_error", "unknown"):
            self.edit_evidence(execution={"status": status, "reason": "adapter fact", "exitCode": 1})
            result = evaluate(self.case_path, self.evidence_path)
            self.assertEqual(result["execution"]["status"], status)
            self.assertEqual(result["outcome"], "unevaluable")
            self.assertEqual(result["assertions"]["outcome"], "not_run")

    def test_completed_claim_conflicts_with_cancel_end_and_exit(self):
        events = fixture(kind="events")
        events[-1]["data"]["reason"] = {"kind": "aborted", "reason": {"kind": "user"}}
        self.record(events)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["execution"]["status"], "unknown")
        self.assertEqual(result["outcome"], "unevaluable")
        self.record()
        self.edit_evidence(execution={"status": "completed", "exitCode": 1})
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["execution"]["status"], "unknown")

    def test_missing_end_and_malformed_event_never_pass(self):
        self.record(fixture(kind="events")[:-1])
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["execution"]["status"], "unknown")
        self.assertEqual(result["outcome"], "unevaluable")
        events = fixture(kind="events")
        events[3]["data"] = None
        self.record(events)
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["recording"]["outcome"], "complete")
        self.assertEqual(result["assertions"]["outcome"], "insufficient_evidence")

    def test_extra_session_cannot_be_silently_ignored(self):
        self.record()
        run_dir = self.evidence_path.parent
        # A second independently valid session in the same run exceeds the single-task adapter scope.
        original_trace = next(run_dir.glob("*.jsonl"))
        original_status = next(run_dir.glob("*.status.json"))
        import hashlib
        second_id = "additional-session"
        filename = hashlib.sha256(second_id.encode()).hexdigest()
        rows = [json.loads(line) for line in original_trace.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            row["sessionId"] = second_id
        raw = ("".join(json.dumps(row) + "\n" for row in rows)).encode()
        status = load_json(original_status)
        status.update(sessionId=second_id, traceFile=f"{filename}.jsonl", writtenBytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        (run_dir / f"{filename}.jsonl").write_bytes(raw)
        (run_dir / f"{filename}.status.json").write_text(json.dumps(status), encoding="utf-8")
        manifest = load_json(run_dir / "run.json")
        manifest["sessions"].append({"sessionId": second_id, "traceFile": f"{filename}.jsonl", "statusFile": f"{filename}.status.json"})
        (run_dir / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["recording"]["inspection"]["outcome"], "complete")
        self.assertEqual(result["recording"]["outcome"], "unverified")
        self.assertEqual(result["outcome"], "unevaluable")

    def test_version_two_live_routes_are_checked_against_fresh_events(self):
        # Synthetic events exercise route validation without invoking a model.
        events = fixture(kind="events")
        events.insert(2, {"type": "request/header", "data": {"header": {"config": {"provider": "synthetic", "model": "none"}}}})
        original = self.record(resequence(events))
        self.edit_evidence(evidenceFormatVersion=2, source="live")
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["outcome"], "passed")
        case = load_json(self.case_path)
        case["configRef"]["model"] = "tampered"
        self.case_path.write_text(json.dumps(case), encoding="utf-8")
        self.edit_evidence(configuration={**original["configuration"], "model": "tampered"})
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["recording"]["outcome"], "complete")
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertIn("request routes", result["assertions"]["reason"])

    def test_wrong_run_session_plugin_and_config_cannot_pass(self):
        original = self.record()
        for key in ("runId", "sessionId", "configuration"):
            altered = copy.deepcopy(original)
            altered[key] = "wrong" if key != "configuration" else {**altered[key], "pluginVersion": "wrong"}
            self.evidence_path.write_text(json.dumps(altered), encoding="utf-8")
            result = evaluate(self.case_path, self.evidence_path)
            self.assertEqual(result["recording"]["outcome"], "unverified")
            self.assertEqual(result["outcome"], "unevaluable")
        original["configuration"]["model"] = "different"
        self.evidence_path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(evaluate(self.case_path, self.evidence_path)["outcome"], "unevaluable")

    def test_bad_evidence_identity_and_versions_rejected(self):
        original = self.record()
        for updates in ({"caseRunId": "not-uuid"}, {"caseRunId": original["runId"]}, {"caseId": "other"}, {"evidenceFormatVersion": 3},
                        {"budgetEnforcement": {"tokens": True}}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_evidence({**original, **updates}, fixture())

    def test_cli_exit_codes_output_file_and_no_overwrite(self):
        self.record()
        output = self.directory / "result.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--case", str(self.case_path), "--evidence", str(self.evidence_path), "--output", str(output)]), 0)
            old = output.read_bytes()
            self.assertEqual(main(["--case", str(self.case_path), "--evidence", str(self.evidence_path), "--output", str(output)]), 2)
            self.assertEqual(output.read_bytes(), old)
            case = load_json(self.case_path)
            case["assertions"][0]["equals"] = "wrong"
            self.case_path.write_text(json.dumps(case), encoding="utf-8")
            self.assertEqual(main(["--case", str(self.case_path), "--evidence", str(self.evidence_path)]), 1)
            self.edit_evidence(runDir="missing")
            self.assertEqual(main(["--case", str(self.case_path), "--evidence", str(self.evidence_path)]), 2)

    def test_inspect_process_errors_remain_unverified(self):
        # Only the unavailable-process path is simulated; positive/negative recordings above use real Node.
        for error in (FileNotFoundError("node"), subprocess.TimeoutExpired("node", 30)):
            with patch("dsh_eval.evaluate.subprocess.run", side_effect=error):
                self.assertEqual(inspect_recording(self.directory)["outcome"], "unverified")


if __name__ == "__main__":
    unittest.main()
