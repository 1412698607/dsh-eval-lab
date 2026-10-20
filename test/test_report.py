import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.experiment import run_experiment
from dsh_eval.formats import load_json, parse_json
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-report-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.outputs = self.directory / "reports"
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["configRef"].update(provider="synthetic", model="first")
        self.save(self.directory / "case.json", self.case)
        self.manifest = {"experimentFormatVersion": 1, "experimentName": "comparison", "repetitions": 2,
                         "failurePolicy": "continue", "cases": [{"entryId": "retry", "casePath": "case.json"}],
                         "configurations": [{"configurationId": name, "configRef": {**self.case["configRef"], "model": name}}
                                            for name in ("first", "second")]}
        for target, options in (("dsh_eval.runner._prepare", {}),
                                ("dsh_eval.runner.ADAPTER", {"new": ROOT / "scripts/fixtures/batch-adapter.js"})):
            mocked = patch(target, **options)
            mocked.start()
            self.addCleanup(mocked.stop)

    def save(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def experiment(self, **options):
        path = self.directory / "experiment.json"
        self.save(path, self.manifest)
        self.saved = run_experiment(path, self.directory / "experiments", **options)
        self.base = Path(self.saved["experimentDirectory"])
        self.path = self.base / "experiment-result.json"
        self.batch = load_json(self.base / self.saved["batchResultPath"])
        # The test adapter uses real processes and the recorder but never calls a model.
        for sample, row in zip(self.saved["samples"], self.batch["entries"]):
            if sample["evidencePath"]:
                evidence_path = self.base / sample["evidencePath"]
                evidence = load_json(evidence_path)
                evidence["source"] = "synthetic"
                self.save(evidence_path, evidence)
                sample["source"] = row["source"] = "synthetic"
        self.persist()

    def persist(self):
        self.save(self.path, self.saved)
        self.save(self.base / self.saved["batchResultPath"], self.batch)

    def report(self):
        return generate_report(self.path, self.outputs)

    def runtime(self, sample, **changes):
        path = self.base / sample["runtimeReport"]
        data = load_json(path)
        data.update(changes)
        self.save(path, data)

    def source(self, index, value):
        sample = self.saved["samples"][index]
        path = self.base / sample["evidencePath"]
        evidence = load_json(path)
        evidence["source"] = value
        self.save(path, evidence)
        sample["source"] = self.batch["entries"][index]["source"] = value

    def digest(self, directory):
        return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.rglob("*") if path.is_file()}

    def rerecord(self, index, transform):
        sample = self.saved["samples"][index]
        trace = next((self.base / sample["runDir"]).glob("*.jsonl"))
        events = [parse_json(line)["event"] for line in trace.read_text(encoding="utf-8").splitlines()]
        transform(events)
        for seq, event in enumerate(events):
            event["seq"] = seq
        case_directory = self.base / sample["caseDirectory"]
        code = """
import { recordExample } from './scripts/demo-eval.js';
let text = ''; for await (const chunk of process.stdin) text += chunk;
const data = JSON.parse(text);
console.log(JSON.stringify(await recordExample(data.casePath, data.events, data.outputDir)));
"""
        process = subprocess.run(["node", "--input-type=module", "-e", code], cwd=ROOT,
                                 input=json.dumps({"casePath": str(case_directory / "case.json"), "events": events,
                                                   "outputDir": str(case_directory / "replacement")}),
                                 capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
        recorded = json.loads(process.stdout)
        evidence_path = self.base / sample["evidencePath"]
        evidence = load_json(evidence_path)
        run_directory = Path(recorded["evidencePath"]).parent
        for key in ("runId", "sessionId"):
            evidence[key] = sample[key] = self.batch["entries"][index][key] = recorded[key]
        evidence["runDir"] = str(run_directory.relative_to(case_directory))
        sample["runDir"] = run_directory.relative_to(self.base).as_posix()
        self.batch["entries"][index]["runDir"] = run_directory.relative_to(self.base / Path(self.saved["batchResultPath"]).parent).as_posix()
        self.save(evidence_path, evidence)
        self.persist()

    def test_fresh_paired_report_is_separate_and_never_overwrites_sources(self):
        self.experiment()
        for index, sample in enumerate(self.saved["samples"]):
            self.runtime(sample, elapsedSeconds=(1, 2, 3, 6)[index])
        before = self.digest(self.base)
        result = self.report()
        self.assertEqual(result["verificationCounts"], {"verified": 4})
        self.assertEqual(result["summary"]["outcomes"]["passed"], 4)
        comparison = result["comparisons"][0]
        self.assertEqual((comparison["source"], comparison["pairedSamples"], comparison["excludedPairs"]), ("synthetic", 2, 0))
        self.assertEqual(comparison["rateDifferences"]["attemptedPassRate"], 0)
        metric = comparison["metrics"]["elapsedSeconds"]
        self.assertEqual((metric["left"]["observedMean"], metric["right"]["observedMean"], metric["meanDifference"]), (2, 4, 2))
        self.assertEqual((metric["minDifference"], metric["maxDifference"]), (1, 3))
        self.assertIsNone(comparison["metrics"]["cost"]["meanDifference"])
        self.assertEqual(comparison["metrics"]["totalTokens"]["missingPairs"], 2)
        directory = Path(result["reportDirectory"])
        self.assertEqual(load_json(directory / "report.json"), result)
        self.assertEqual(len(list((directory / "evaluations").glob("*.json"))), 4)
        markdown = (directory / "report.md").read_text(encoding="utf-8")
        self.assertIn("置信区间", markdown)
        self.assertIn("观测 2 / 缺失 0", markdown)
        self.assertIn("均值 缺失；范围 缺失 .. 缺失", markdown)
        self.assertIn("+08:00（Asia/Shanghai）", markdown)
        self.assertEqual(self.digest(self.base), before)
        old_report = self.digest(directory)
        repeated = self.report()
        self.assertNotEqual(repeated["reportId"], result["reportId"])
        self.assertEqual(self.digest(directory), old_report)
        self.assertEqual(self.digest(self.base), before)

    def test_saved_summary_is_not_reused_and_changes_are_visible(self):
        self.experiment()
        self.saved["summary"]["outcomes"]["passed"] = 999
        self.saved["samples"][0].update(outcome="failed", metrics=None)
        self.persist()
        result = self.report()
        self.assertEqual(result["summary"]["outcomes"]["passed"], 4)
        self.assertEqual(result["savedSummary"]["outcomes"]["passed"], 999)
        self.assertIn("outcome", result["samples"][0]["changedFields"])
        self.assertIn("metrics", result["samples"][0]["changedFields"])

    def test_damaged_recording_cannot_keep_old_success_or_join_a_pair(self):
        self.experiment()
        trace = next((self.base / self.saved["samples"][0]["runDir"]).glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-1])
        result = self.report()
        row = result["samples"][0]
        self.assertEqual((row["outcome"], row["recordingOutcome"], row["configurationMatch"]), ("unevaluable", "invalid", "unknown"))
        self.assertIn("outcome", row["changedFields"])
        self.assertIsNone(row["metrics"]["modelCalls"])
        self.assertEqual(result["comparisons"][0]["repeatIndices"], [2])
        self.assertEqual(result["comparisons"][0]["excludedPairs"], 1)
        self.assertEqual(result["groups"][0]["summary"]["attemptedPassRate"]["denominator"], 2)

    def test_task_changes_reject_sample_without_changing_the_plan_denominator(self):
        self.experiment()
        for key, value in (("input", "another task"), ("environment", {"files": {"another.md": "changed"}}),
                           ("budget", {"timeoutSeconds": 1}), ("assertions", [{"id": "other", "type": "final_text", "equals": "other"}])):
            with self.subTest(key=key):
                sample = self.saved["samples"][0]
                path = self.base / sample["casePath"]
                original = load_json(path)
                self.save(path, {**original, key: value})
                result = self.report()
                self.assertEqual(result["samples"][0]["verification"], "rejected")
                self.assertIn("task/environment/budget/assertions", result["samples"][0]["reasons"][0])
                self.assertEqual(result["summary"]["planned"], 4)
                self.assertEqual(result["summary"]["outcomes"]["unevaluable"], 1)
                self.save(path, original)
        executed = self.base / sample["caseDirectory"] / "case.json"
        self.save(executed, {**self.case, "input": "altered executed snapshot"})
        self.assertEqual(self.report()["samples"][0]["verification"], "rejected")

    def test_evidence_identity_and_source_mismatches_are_not_attributed(self):
        self.experiment()
        sample = self.saved["samples"][0]
        path = self.base / sample["evidencePath"]
        original = load_json(path)
        for key, value in (("caseRunId", self.saved["samples"][1]["caseRunId"]), ("batchId", "other"),
                           ("source", "live"), ("runId", "other"), ("sessionId", "other")):
            with self.subTest(key=key):
                self.save(path, {**original, key: value})
                result = self.report()
                self.assertEqual(result["samples"][0]["verification"], "rejected")
                self.assertIsNone(result["samples"][0]["source"])
                self.assertEqual(result["comparisons"][0]["pairedSamples"], 1)
        self.save(path, original)

    def test_actual_configuration_and_recorded_headers_must_both_match(self):
        self.experiment()
        sample = self.saved["samples"][0]
        path = self.base / sample["evidencePath"]
        evidence = load_json(path)
        wrong = {**evidence["configuration"], "model": "unexpected"}
        evidence["configuration"] = sample["configuration"] = self.batch["entries"][0]["configuration"] = wrong
        self.save(path, evidence)
        self.persist()
        result = self.report()
        self.assertEqual(result["samples"][0]["configurationMatch"], "mismatched")
        self.assertEqual(result["groups"][0]["matchedSummary"]["planned"], 1)
        # Restore the declaration, then create a valid sealed trace with a different actual request route.
        evidence["configuration"] = sample["configuration"] = self.batch["entries"][0]["configuration"] = sample["requestedConfiguration"]
        self.save(path, evidence)
        self.rerecord(0, lambda events: next(e["data"]["header"]["config"] for e in events if e["type"] == "request/header").update(model="wrong-route"))
        result = self.report()
        self.assertEqual(result["samples"][0]["recordingOutcome"], "complete")
        self.assertEqual(result["samples"][0]["configurationMatch"], "mismatched")
        self.assertEqual(result["comparisons"][0]["pairedSamples"], 1)

    def test_missing_request_header_is_unknown_even_with_a_configuration_label(self):
        self.experiment()
        self.rerecord(0, lambda events: events.__setitem__(slice(None), [e for e in events if e["type"] != "request/header"]))
        result = self.report()
        self.assertEqual(result["samples"][0]["configurationMatch"], "unknown")
        self.assertEqual(result["comparisons"][0]["pairedSamples"], 1)

    def test_live_and_synthetic_are_never_paired_together(self):
        self.experiment()
        self.source(0, "live")
        self.source(3, "live")
        self.persist()
        result = self.report()
        self.assertEqual(result["summary"]["sourceCounts"], {"live": 2, "synthetic": 2})
        self.assertEqual({item["source"] for item in result["comparisons"]}, {"live", "synthetic"})
        self.assertTrue(all(item["pairedSamples"] == 0 for item in result["comparisons"]))
        self.assertTrue(all(item["rateDifferences"]["attemptedPassRate"] is None for item in result["comparisons"]))

    def test_same_config_aliases_do_not_become_different_models(self):
        self.manifest["configurations"][1]["configRef"] = copy.deepcopy(self.manifest["configurations"][0]["configRef"])
        self.experiment()
        comparison = self.report()["comparisons"][0]
        self.assertEqual((comparison["status"], comparison["pairedSamples"]), ("unavailable", 0))
        self.assertIn("same configRef", comparison["reason"])

    def test_single_configuration_is_a_valid_report_without_a_comparison(self):
        self.manifest["configurations"].pop()
        self.experiment()
        result = self.report()
        self.assertEqual(result["comparisons"], [])
        self.assertEqual(result["summary"]["planned"], 2)
        self.assertIn("只有一个配置", (Path(result["reportDirectory"]) / "report.md").read_text(encoding="utf-8"))

    def test_different_cases_are_compared_separately_and_keep_task_fingerprints(self):
        other = {**self.case, "input": "Recover the project name for this second task."}
        self.save(self.directory / "other.case.json", other)
        self.manifest["cases"].append({"entryId": "other", "casePath": "other.case.json"})
        self.manifest["repetitions"] = 1
        self.experiment()
        for index, value in enumerate((1, 2, 100, 50)):
            self.runtime(self.saved["samples"][index], elapsedSeconds=value)
        result = self.report()
        self.assertEqual([item["caseEntryId"] for item in result["comparisons"]], ["retry", "other"])
        self.assertEqual([item["metrics"]["elapsedSeconds"]["meanDifference"] for item in result["comparisons"]], [1, -50])
        self.assertNotEqual(result["cases"][0]["taskFingerprint"], result["cases"][1]["taskFingerprint"])

    def test_copied_experiment_uses_paths_beside_the_result_instead_of_old_absolute_paths(self):
        self.experiment()
        copied = self.directory / "relocated"
        shutil.copytree(self.base, copied)
        original = self.digest(copied)
        result = generate_report(copied / "experiment-result.json", self.outputs)
        self.assertEqual(result["verificationCounts"], {"verified": 4})
        self.assertTrue(all(Path(row["sourceEvidencePath"]).is_relative_to(copied) for row in result["samples"]))
        self.assertEqual(self.digest(copied), original)

    def test_failures_skips_cancellation_and_startup_errors_keep_denominators(self):
        next(item for item in self.case["assertions"] if item["type"] == "final_text")["equals"] = "wrong"
        self.save(self.directory / "case.json", self.case)
        self.manifest["failurePolicy"] = "stop"
        self.experiment()
        result = self.report()
        self.assertEqual((result["summary"]["attempted"], result["summary"]["skipped"]), (1, 3))
        self.assertEqual(result["summary"]["outcomes"], {"passed": 0, "failed": 1, "unevaluable": 0})
        self.assertEqual(result["groups"][1]["summary"]["attemptedPassRate"]["value"], None)
        self.case["input"] = "WAIT_FOR_CANCEL"
        self.save(self.directory / "case.json", self.case)
        self.manifest["failurePolicy"] = "continue"
        self.experiment(cancel_after_stream=True)
        result = self.report()
        self.assertEqual(result["summary"]["executionStatusCounts"], {"cancelled": 4})
        self.assertIsNone(result["summary"]["evaluablePassRate"]["value"])
        self.assertEqual(result["summary"]["attemptedPassRate"]["denominator"], 4)
        with patch("dsh_eval.runner._prepare", side_effect=ValueError("no host")):
            self.experiment()
        result = self.report()
        self.assertEqual(result["summary"]["executionStatusCounts"], {"runtime_error": 4})
        self.assertEqual(result["summary"]["configurationMatchCounts"], {"unknown": 4})
        self.assertEqual(result["comparisons"][0]["status"], "unavailable")

    def test_metric_pairs_use_the_same_observed_subset_and_preserve_overflow(self):
        self.experiment()
        for index, value in enumerate((1, 2, 3, 10 ** 400)):
            self.runtime(self.saved["samples"][index], elapsedSeconds=value)
        comparison = self.report()["comparisons"][0]["metrics"]["elapsedSeconds"]
        self.assertEqual((comparison["pairedSamples"], comparison["missingPairs"]), (1, 1))
        self.assertEqual((comparison["left"]["observedMean"], comparison["right"]["observedMean"], comparison["meanDifference"]), (1, 2, 1))
        for sample in self.saved["samples"]:
            self.runtime(sample, elapsedSeconds=1e308)
        result = self.report()
        metric = result["groups"][0]["summary"]["metrics"]["elapsedSeconds"]
        self.assertEqual((metric["observedSamples"], metric["missingSamples"]), (2, 0))
        self.assertIsNone(metric["observedMean"])
        self.assertIn("reason", metric)
        self.assertIsNone(result["comparisons"][0]["metrics"]["elapsedSeconds"]["meanDifference"])
        self.assertEqual(result["summary"]["outcomes"]["passed"], 4)
        parse_json((Path(result["reportDirectory"]) / "report.json").read_text(encoding="utf-8"))
        self.assertIn("finite numeric range", (Path(result["reportDirectory"]) / "report.md").read_text(encoding="utf-8"))

    def test_plan_and_batch_corruption_fail_before_creating_output(self):
        self.experiment()
        original = copy.deepcopy(self.saved)
        changes = [lambda r: r.update(experimentResultFormatVersion=True), lambda r: r.update(status="running"),
                   lambda r: r["samples"].pop(), lambda r: r["samples"][0].update(repeatIndex=True),
                   lambda r: r["samples"][0].update(configurationId="wrong"),
                   lambda r: r["samples"][0].update(casePath="../outside.json"),
                   lambda r: r["samples"][0].update(runId=r["samples"][1]["runId"]),
                   lambda r: r.update(configurations=[])]
        for mutate in changes:
            self.saved = copy.deepcopy(original)
            mutate(self.saved)
            self.save(self.path, self.saved)
            with self.assertRaises(ValueError):
                self.report()
            self.assertFalse(self.outputs.exists())

    def test_missing_evidence_is_reported_without_trusting_saved_success(self):
        self.experiment()
        (self.base / self.saved["samples"][0]["evidencePath"]).unlink()
        result = self.report()
        self.assertEqual(result["samples"][0]["verification"], "rejected")
        self.assertEqual(result["summary"]["outcomes"]["passed"], 3)
        self.assertEqual(result["summary"]["outcomes"]["unevaluable"], 1)
        self.assertEqual(result["comparisons"][0]["pairedSamples"], 1)

    def test_cli_is_offline_and_separates_report_success_from_task_results(self):
        self.experiment()
        trace = next((self.base / self.saved["samples"][0]["runDir"]).glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-1])
        with patch("dsh_eval.runner.run_case") as run, redirect_stdout(io.StringIO()) as output:
            code = main(["--report", str(self.path), "--reports-root", str(self.outputs)])
        run.assert_not_called()
        result = parse_json(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["summary"]["outcomes"]["unevaluable"], 1)
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--report", str(self.path),
                                  "--reports-root", str(self.outputs)], cwd=ROOT,
                                 env={**os.environ, "PYTHONIOENCODING": "cp936"},
                                 capture_output=True, timeout=30, check=True)
        self.assertEqual(parse_json(process.stdout.decode("utf-8"))["status"], "generated")
        for controls in (["--run"], ["--evidence", "x"], ["--output", "x"], ["--runs-root", "x"],
                         ["--host-modules", "x"], ["--cancel-after-stream"]):
            with self.subTest(controls=controls), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["--report", str(self.path), *controls])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--case", "x", "--evidence", "y", "--reports-root", "z"])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--report", str(self.directory / "missing.json")]), 2)
        self.assertEqual(parse_json(output.getvalue())["comparisonReportFormatVersion"], 1)


if __name__ == "__main__":
    unittest.main()
