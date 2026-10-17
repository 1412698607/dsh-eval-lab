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

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "evaluation"


def fixture(name="read-project", kind="case"):
    return load_json(FIXTURES / f"{name}.{kind}.json")


def resequence(events):
    for index, event in enumerate(events):
        event["seq"] = index
    return events


class FormatTests(unittest.TestCase):
    def test_both_public_cases_load(self):
        for name in ("read-project", "missing-file"):
            self.assertEqual(validate_case(fixture(name))["caseId"], name)

    def test_unknown_versions_fields_assertions_and_duplicate_ids_rejected(self):
        mutations = [lambda case: case.update(caseFormatVersion=2),
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

    def record(self, events=None, seal=True, name="read-project"):
        self.case_path.write_text(json.dumps(fixture(name)), encoding="utf-8")
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
        result = evaluate(self.case_path, self.evidence_path)
        self.assertEqual(result["recording"]["inspection"]["outcome"], "complete")
        self.assertEqual(result["recording"]["outcome"], "unverified")
        self.assertEqual(result["outcome"], "unevaluable")

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
        for updates in ({"caseRunId": "not-uuid"}, {"caseRunId": original["runId"]}, {"caseId": "other"}, {"evidenceFormatVersion": 2},
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
