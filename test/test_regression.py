"""Regression gates use real synthetic processes, recording and fresh inspect."""
from contextlib import redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.formats import load_json
from dsh_eval.regression import compare_baseline
from dsh_eval.runner import ROOT
from test_report import ReportFixture


def wrong_answer(events):
    final = next(event for event in reversed(events) if event["type"] == "assistant/message")
    final["data"]["message"]["content"] = [{"type": "text", "text": "WRONG_ANSWER"}]


class RegressionTests(ReportFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.manifest["configurations"] = self.manifest["configurations"][:1]
        self.manifest["repetitions"] = 1

    def old(self):
        self.experiment()
        return self.path

    def compare(self, old, **kwargs):
        return compare_baseline(old, self.path, **kwargs)

    def cli(self, old, *args):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["--compare-baseline", str(old), "--candidate", str(self.path), *args])
        return code, json.loads(stdout.getvalue())

    def test_fresh_no_regression_is_read_only_and_cli_returns_zero(self):
        old = self.old()
        self.experiment()
        before = self.digest(self.directory / "experiments")
        with patch("dsh_eval.runner.run_case", side_effect=AssertionError("must not run")):
            code, result = self.cli(old)
        self.assertEqual(code, 0)
        self.assertEqual(result["counts"]["unchanged_passed"], 1)
        self.assertEqual(result["comparability"]["status"], "comparable")
        self.assertFalse(result["modelCalled"])
        self.assertEqual(before, self.digest(self.directory / "experiments"))

    def test_regressions_and_improvements_do_not_cancel_each_other_or_trust_saved_success(self):
        self.manifest["repetitions"] = 2
        self.experiment()
        self.rerecord(1, wrong_answer)
        old = self.path
        self.experiment()
        self.rerecord(0, wrong_answer)
        # Persisted summaries still describe successful fixture executions.
        self.assertEqual(self.saved["samples"][0]["outcome"], "passed")
        code, result = self.cli(old)
        self.assertEqual(code, 1)
        self.assertEqual([row["change"] for row in result["samples"]], ["regression", "improvement"])
        self.assertTrue(result["hasRegressions"])
        self.assertEqual(result["samples"][0]["candidate"]["outcome"], "failed")
        self.assertEqual(result["samples"][0]["candidate"]["saved"]["outcome"], "passed")

    def test_improvement_and_unchanged_failure_are_not_regressions(self):
        self.manifest["repetitions"] = 2
        self.experiment()
        self.rerecord(0, wrong_answer)
        self.rerecord(1, wrong_answer)
        old = self.path
        self.experiment()
        self.rerecord(1, wrong_answer)
        result = self.compare(old)
        self.assertEqual(result["exitCode"], 0)
        self.assertEqual([row["change"] for row in result["samples"]], ["improvement", "unchanged_failed"])

    def test_configuration_changes_require_explicit_fields_and_selection(self):
        old = self.old()
        self.manifest["configurations"][0].update(configurationId="renamed")
        self.manifest["configurations"][0]["configRef"]["model"] = "second"
        self.experiment()
        rejected = self.compare(old)
        self.assertEqual(rejected["exitCode"], 2)
        self.assertEqual(rejected["samples"][0]["change"], "incompatible")
        self.assertEqual(self.compare(old, allow_config_changes=["profile"])["exitCode"], 2)
        code, allowed = self.cli(old, "--baseline-config", "first", "--candidate-config", "renamed", "--allow-config-change", "model")
        self.assertEqual(code, 0)
        self.assertEqual(allowed["configurationChanges"], [{"field": "model", "baseline": "first", "candidate": "second", "allowed": True}])
        with self.assertRaisesRegex(ValueError, "Unknown configuration"):
            self.compare(old, candidate_config="missing")
        with self.assertRaisesRegex(ValueError, "Unsupported allowed"):
            self.compare(old, allow_config_changes=["assertions"])
        self.manifest["configurations"][0]["configRef"]["provider"] = "another-synthetic"
        self.experiment()
        self.assertEqual(self.compare(old, allow_config_changes=["model"])["exitCode"], 2)
        self.assertEqual(self.compare(old, allow_config_changes=["model", "provider"])["exitCode"], 0)

    def test_multiple_configurations_require_selection_instead_of_positional_pairing(self):
        self.manifest["configurations"].append({"configurationId": "second", "configRef": {**self.case["configRef"], "model": "second"}})
        old = self.old()
        self.experiment()
        code, result = self.cli(old)
        self.assertEqual((code, result["status"]), (2, "error"))
        self.assertEqual(self.compare(old, baseline_config="first", candidate_config="second", allow_config_changes=["model"])["exitCode"], 0)

    def test_changed_task_fields_cannot_be_allowed_as_configuration_changes(self):
        old = self.old()
        original = copy.deepcopy(self.case)
        for change in ({"input": "Different prompt"}, {"environment": {**original["environment"], "files": {**original["environment"]["files"], "other.txt": "different"}}},
                       {"budget": {"timeoutSeconds": 90}}, {"recorder": {"maxEventBytes": 1000000}},
                       {"assertions": [*original["assertions"], {"id": "no-write", "type": "tool_forbidden", "tool": "write"}]},
                       {"caseId": "different-case"}):
            with self.subTest(change=change):
                self.case = {**copy.deepcopy(original), **change}
                self.save(self.directory / "case.json", self.case)
                self.experiment()
                result = self.compare(old, allow_config_changes=["provider", "model", "profile", "pluginVersion"])
                self.assertEqual(result["exitCode"], 2)
                self.assertIn("task_input_changed", result["samples"][0]["reasons"])
                self.assertEqual(result["samples"][0]["taskChanges"], list(change))
                self.assertEqual(result["counts"]["regression"], 0)

    def test_repetition_and_case_membership_missing_items_are_explicit(self):
        self.manifest["repetitions"] = 2
        self.manifest["cases"].append({"entryId": "old-only", "casePath": "case.json"})
        old = self.old()
        self.manifest["repetitions"] = 1
        self.manifest["cases"][1]["entryId"] = "new-only"
        self.experiment()
        result = self.compare(old)
        self.assertEqual(result["exitCode"], 2)
        self.assertEqual(result["counts"]["missing_in_candidate"], 3)
        self.assertEqual(result["counts"]["missing_in_baseline"], 1)
        self.assertEqual(result["counts"]["compared"], 1)

    def test_alignment_uses_case_entry_and_repeat_not_sample_id(self):
        self.manifest["cases"].append({"entryId": "second-case", "casePath": "case.json"})
        old = self.old()
        self.manifest["cases"].reverse()
        self.experiment()
        self.rerecord(0, wrong_answer)
        result = self.compare(old)
        self.assertEqual(result["exitCode"], 1)
        changed = next(row for row in result["samples"] if row["change"] == "regression")
        self.assertEqual(changed["caseEntryId"], "second-case")
        self.assertNotEqual(changed["baseline"]["sampleId"], changed["candidate"]["sampleId"])

    def test_missing_evidence_has_priority_but_retains_confirmed_regression(self):
        self.manifest["repetitions"] = 2
        old = self.old()
        self.experiment()
        self.rerecord(0, wrong_answer)
        (self.base / self.saved["samples"][1]["evidencePath"]).unlink()
        code, result = self.cli(old)
        self.assertEqual(code, 2)
        self.assertEqual((result["counts"]["regression"], result["counts"]["unavailable"]), (1, 1))
        self.assertTrue(result["hasRegressions"])

    def test_matrix_missing_items_take_priority_without_erasing_known_changes(self):
        self.manifest["repetitions"] = 2
        old = self.old()
        self.manifest["repetitions"] = 1
        self.experiment()
        self.rerecord(0, wrong_answer)
        code, result = self.cli(old)
        self.assertEqual(code, 2)
        self.assertEqual((result["counts"]["regression"], result["counts"]["missing_in_candidate"]), (1, 1))
        self.assertEqual((result["counts"]["compared"], result["counts"]["total"]), (1, 2))
        self.assertTrue(result["hasRegressions"])
        missing = next(row for row in result["samples"] if row["change"] == "missing_in_candidate")
        self.assertIsNone(missing["candidate"])
        reverse = compare_baseline(self.path, old)
        self.assertEqual(reverse["exitCode"], 2)
        self.assertEqual((reverse["counts"]["improvement"], reverse["counts"]["missing_in_baseline"]), (1, 1))
        self.assertFalse(reverse["hasRegressions"])

    def test_disjoint_case_matrices_never_pass_with_zero_comparisons(self):
        old = self.old()
        self.manifest["cases"][0]["entryId"] = "renamed-entry"
        self.experiment()
        code, result = self.cli(old, "--allow-config-change", "model")
        self.assertEqual(code, 2)
        self.assertEqual(result["comparability"]["status"], "incomplete")
        self.assertEqual((result["counts"]["compared"], result["counts"]["total"]), (0, 2))
        self.assertEqual({row["change"] for row in result["samples"]}, {"missing_in_baseline", "missing_in_candidate"})
        self.assertFalse(result["hasRegressions"])

    def test_corrupt_recording_and_unmatched_routes_never_turn_into_regressions(self):
        old = self.old()
        for mode in ("route", "trace", "assertion"):
            with self.subTest(mode=mode):
                self.experiment()
                if mode == "route":
                    def wrong_route(events):
                        next(event for event in events if event["type"] == "request/header")["data"]["header"]["config"]["model"] = "unexpected"
                    self.rerecord(0, wrong_route)
                elif mode == "assertion":
                    self.rerecord(0, lambda events: events.__setitem__(slice(None), [event for event in events
                        if event["type"] not in ("tool/call", "tool/result")]))
                else:
                    trace = next((self.base / self.saved["samples"][0]["runDir"]).glob("*.jsonl"))
                    trace.write_bytes(trace.read_bytes()[:-10])
                result = self.compare(old, allow_config_changes=["provider", "model", "profile", "pluginVersion"])
                self.assertEqual(result["exitCode"], 2)
                self.assertEqual(result["counts"]["unavailable"], 1)
                self.assertFalse(result["hasRegressions"])

    def test_skipped_candidates_remain_unavailable(self):
        self.manifest["repetitions"] = 2
        old = self.old()
        self.experiment(stop_after=1)
        result = self.compare(old)
        self.assertEqual(result["exitCode"], 2)
        self.assertEqual(result["counts"]["unavailable"], 1)
        self.assertEqual(result["counts"]["unchanged_passed"], 1)

    def test_provenance_and_missing_original_plan_block_comparison(self):
        old = self.old()
        self.experiment()
        self.source(0, "live")
        self.persist()
        result = self.compare(old)
        self.assertIn("source_mismatch", result["samples"][0]["reasons"])
        self.assertEqual(result["exitCode"], 2)
        self.source(0, "synthetic")
        del self.saved["planInputPath"]
        self.persist()
        result = self.compare(old)
        self.assertIn("candidate_plan_unverified", result["comparability"]["issues"])
        self.assertEqual(result["exitCode"], 2)

    def test_same_experiment_or_reused_execution_identity_cannot_pass(self):
        old = self.old()
        result = self.compare(old)
        self.assertEqual(result["exitCode"], 2)
        self.assertIn("same_experiment", result["comparability"]["issues"])
        identity = self.saved["samples"][0]["caseRunId"]
        self.experiment()
        self.saved["samples"][0]["caseRunId"] = self.batch["entries"][0]["caseRunId"] = identity
        evidence_path = self.base / self.saved["samples"][0]["evidencePath"]
        evidence = load_json(evidence_path)
        evidence["caseRunId"] = identity
        self.save(evidence_path, evidence)
        self.persist()
        result = self.compare(old)
        self.assertIn("shared_caseRunId", result["comparability"]["issues"])
        self.assertEqual(result["exitCode"], 2)

    def test_invalid_input_and_cli_options_fail_without_creating_output(self):
        old = self.old()
        self.experiment()
        output = self.directory / "gate.json"
        damaged = load_json(self.path)
        damaged["samples"] = []
        self.save(self.path, damaged)
        code, result = self.cli(old, "--output", str(output))
        self.assertEqual((code, result["status"]), (2, "error"))
        self.assertFalse(output.exists())
        for args in (["--compare-baseline", str(old)], ["--case", "case", "--evidence", "evidence", "--candidate", "candidate"],
                     ["--compare-baseline", str(old), "--candidate", str(old), "--run"],
                     ["--compare-baseline", str(old), "--candidate", str(old), "--plan"],
                     ["--compare-baseline", str(old), "--candidate", str(old), "--allow-config-change", "input"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)

    def test_non_object_result_roots_return_input_error_two_without_traceback_or_output(self):
        old = self.old()
        self.experiment()
        originals = {old: load_json(old), self.path: load_json(self.path)}
        output = self.directory / "invalid-root.json"
        for side in (old, self.path):
            for data in ([], ["experimentResumeResultFormatVersion"], "experimentResumeResultFormatVersion", None, 0):
                with self.subTest(side=side, data=data):
                    for path, value in originals.items():
                        self.save(path, value)
                    self.save(side, data)
                    code, result = self.cli(old, "--output", str(output))
                    self.assertEqual((code, result["exitCode"], result["status"]), (2, 2, "error"))
                    self.assertFalse(output.exists())
        self.save(old, originals[old])
        self.save(self.path, ["experimentResumeResultFormatVersion"])
        for args in (["--compare-baseline", str(old), "--candidate", str(self.path)], ["--report", str(self.path)]):
            process = subprocess.run([sys.executable, "-m", "dsh_eval", *args], cwd=ROOT,
                                     capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(process.returncode, 2, process.stderr)
            self.assertEqual(json.loads(process.stdout)["outcome"], "unevaluable")
            self.assertNotIn("Traceback", process.stderr)

    def test_cli_output_is_exclusive_and_real_process_returns_regression_code(self):
        old = self.old()
        self.experiment()
        self.rerecord(0, wrong_answer)
        output = self.directory / "gate.json"
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--compare-baseline", str(old), "--candidate", str(self.path),
                                  "--output", str(output)], cwd=ROOT, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 1, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result, load_json(output))
        before = output.read_bytes()
        code, _ = self.cli(old, "--output", str(output))
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), before)

    def test_plan_snapshot_tampering_is_an_input_error_not_an_outcome_change(self):
        old = self.old()
        self.experiment()
        path = self.base / self.saved["planInputPath"]
        plan = load_json(path)
        plan["cases"][0]["input"] = "Modified after execution"
        self.save(path, plan)
        code, result = self.cli(old)
        self.assertEqual((code, result["exitCode"], result["status"]), (2, 2, "error"))
        self.assertNotIn("samples", result)

    def test_explicit_continuation_chains_compare_without_executing_or_mutating(self):
        import test_experiment_resume as fixtures
        from dsh_eval.experiment import run_experiment
        from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
        fixture = fixtures.ExperimentResumeTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        baseline = run_experiment(fixture.path, fixture.directory / "baseline")
        candidate = run_experiment(fixture.path, fixture.directory / "candidate", stop_after=2)
        source = Path(candidate["experimentDirectory"]) / "experiment-result.json"
        original = source
        for stop in (2, None):
            plan = plan_experiment_resume(source)
            result = resume_experiment(source, fixture.directory / "continuations", stop_after=stop,
                                       expected_plan_sha256=plan["planFingerprint"]["sha256"])
            source = Path(result["resumeDirectory"]) / "experiment-resume-result.json"
        old = Path(baseline["experimentDirectory"]) / "experiment-result.json"
        before = self.digest(fixture.directory)
        with patch("dsh_eval.resume.run_batch", side_effect=AssertionError("must not resume")), \
                patch("dsh_eval.batch.run_case", side_effect=AssertionError("must not run")):
            compared = compare_baseline(old, source, baseline_config="baseline", candidate_config="baseline")
            same = compare_baseline(original, source, baseline_config="baseline", candidate_config="baseline")
        self.assertEqual(compared["exitCode"], 0)
        self.assertEqual(compared["counts"]["unchanged_passed"], 4)
        self.assertEqual({row["candidate"]["executionOrigin"] for row in compared["samples"]}, {"reused", "new"})
        self.assertEqual(same["exitCode"], 2)
        self.assertIn("same_experiment", same["comparability"]["issues"])
        self.assertEqual(before, self.digest(fixture.directory))


if __name__ == "__main__":
    unittest.main()
