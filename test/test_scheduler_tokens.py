"""Observed token controls through real synthetic processes, recording and rechecks."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_batch_resume as batch_fixtures
import test_experiment_resume as experiment_fixtures
from dsh_eval.__main__ import main
from dsh_eval.batch import _checkpoint, _token_usage, run_batch
from dsh_eval.browser import ArtifactBrowser
from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.resume import CLAIM_NAME, plan_batch_resume, resume_batch
from dsh_eval.runner import ROOT


class SchedulerTokenTests(unittest.TestCase):
    def setUp(self):
        usage = patch.dict(os.environ, {"DSH_TEST_USAGE": json.dumps({"inputTokens": 2, "outputTokens": 3, "totalTokens": 5})})
        usage.start()
        self.addCleanup(usage.stop)

    def fixture(self, experiment=False):
        fixture = experiment_fixtures.ExperimentResumeTests() if experiment else batch_fixtures.BatchResumeTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.save(fixture.path, fixture.manifest)
        return fixture

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(map(str, args)))
        self.assertEqual(stderr.getvalue(), "")
        return code, json.loads(stdout.getvalue())

    def snapshot(self, directory):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.rglob("*") if path.is_file()}

    def unchanged(self, before):
        self.assertTrue(all(Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                            for path, digest in before.items()))

    def test_invalid_controls_reject_before_reading_or_allocating(self):
        for function in (run_batch, run_experiment, resume_batch, resume_experiment):
            for value in (True, False, 0, -1, 1.5, "2"):
                with self.subTest(function=function.__name__, value=value), \
                        self.assertRaisesRegex(ValueError, "stop_after_tokens must be a positive integer"):
                    function("does-not-exist.json", stop_after_tokens=value)

    def test_cli_rejects_nonpositive_and_nonexecution_combinations(self):
        commands = [[selector, "missing.json", "--plan", "--stop-after-tokens", "1"]
                    for selector in ("--experiment", "--resume-batch", "--resume-experiment")]
        commands += [[selector, "missing.json", "--run", "--stop-after-tokens", value]
                     for selector in ("--batch", "--experiment", "--resume-batch", "--resume-experiment")
                     for value in ("0", "-1", "1.5")]
        commands += [["--case", "missing.json", "--run", "--stop-after-tokens", "1"],
                     ["--report", "missing.json", "--stop-after-tokens", "1"],
                     ["--browse", "--stop-after-tokens", "1"]]
        for command in commands:
            with self.subTest(command=command), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(command)
            self.assertEqual(error.exception.code, 2)

    def test_cumulative_threshold_and_overshoot_preserve_checkpoint_and_unstarted_identity(self):
        fixture = self.fixture()
        for threshold in (8, 10):
            checkpoints = []

            def checkpoint(directory, report):
                _checkpoint(directory, report)
                if report["entries"][1]["status"] == "finished" and report["status"] == "running":
                    checkpoints.append(load_json(directory / "batch-result.json"))

            with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint):
                result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=threshold, stop_after=2)
            self.assertEqual((result["status"], result["stopReason"]), ("stopped", "stop_after_tokens"))
            self.assertEqual(result["tokenUsage"], {"observedSamples": 2, "missingSamples": 0, "observedTotal": 10})
            self.assertEqual(result["stopAfterTokens"], threshold)
            self.assertEqual(checkpoints[0]["tokenUsage"], result["tokenUsage"])
            self.assertEqual(checkpoints[0]["entries"][2]["status"], "pending")
            unstarted = result["entries"][2]
            self.assertEqual((unstarted["status"], unstarted["skipReason"]), ("skipped", "stop_after_tokens"))
            for key in ("caseRunId", "caseDirectory", "runId", "sessionId", "outcome", "source", "metrics"):
                self.assertIsNone(unstarted[key], key)
            self.assertEqual(len(list((Path(result["batchDirectory"]) / "cases").iterdir())), 2)

    def test_zero_usage_and_threshold_at_final_task_complete_normally(self):
        fixture = self.fixture()
        for tokens, threshold in ((5, 15), (5, 20), (0, 1)):
            with self.subTest(tokens=tokens, threshold=threshold), \
                    patch.dict(os.environ, {"DSH_TEST_USAGE": json.dumps({"totalTokens": tokens})}):
                result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=threshold)
            self.assertEqual((result["status"], result["stopReason"], result["outcome"]), ("completed", None, "passed"))
            self.assertEqual(result["tokenUsage"], {"observedSamples": 3, "missingSamples": 0, "observedTotal": 3 * tokens})
        result = run_batch(fixture.path, fixture.outputs, stop_after=1, stop_after_tokens=100)
        self.assertEqual(result["stopReason"], "stop_after")
        fixture.manifest["cases"] = fixture.manifest["cases"][:1]
        fixture.save(fixture.path, fixture.manifest)
        with patch.dict(os.environ, {"DSH_TEST_USAGE": "null"}):
            result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=1)
        self.assertEqual((result["status"], result["stopReason"]), ("completed", None))
        self.assertEqual(result["tokenUsage"]["missingSamples"], 1)

    def test_missing_or_invalid_reported_usage_stops_without_inventing_zero(self):
        fixture = self.fixture()
        for usage in (None, {}, {"totalTokens": True}, {"totalTokens": -1}, {"totalTokens": 1.5}, {"totalTokens": "5"}):
            with self.subTest(usage=usage), patch.dict(os.environ, {"DSH_TEST_USAGE": json.dumps(usage)}):
                result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=100)
            self.assertEqual((result["status"], result["stopReason"]), ("stopped", "token_usage_unavailable"))
            self.assertEqual(result["tokenUsage"], {"observedSamples": 0, "missingSamples": 1, "observedTotal": None})
            self.assertEqual(result["entries"][0]["outcome"], "passed")
            self.assertTrue(all(row["caseRunId"] is None for row in result["entries"][1:]))
        source = Path(result["batchDirectory"]) / "batch-result.json"
        plan = plan_batch_resume(source)
        self.assertTrue(plan["canResume"])
        resumed = resume_batch(source, fixture.outputs, stop_after_tokens=1,
                               expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(resumed["tokenUsage"], {"observedSamples": 1, "missingSamples": 0, "observedTotal": 5})
        with patch.dict(os.environ, {"DSH_TEST_USAGE": "null"}):
            result = run_batch(fixture.path, fixture.outputs)
        self.assertEqual(result["outcome"], "passed")
        self.assertIsNone(result["stopAfterTokens"])
        self.assertIsNone(result["tokenUsage"])

    def test_partial_usage_retains_observed_total_and_aggregate_overflow_is_unavailable(self):
        fixture = self.fixture()
        usages = iter(({"totalTokens": 7}, None))

        def reported_usage(*args, **kwargs):
            with patch.dict(os.environ, {"DSH_TEST_USAGE": json.dumps(next(usages))}):
                return fixture.synthetic_case(*args, **kwargs)

        with patch("dsh_eval.batch.run_case", side_effect=reported_usage):
            result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=100)
        self.assertEqual(result["stopReason"], "token_usage_unavailable")
        self.assertEqual(result["tokenUsage"], {"observedSamples": 1, "missingSamples": 1, "observedTotal": 7})
        self.assertIsNone(result["entries"][2]["caseRunId"])

        def row(value):
            return {"status": "finished", "metrics": {"totalTokens": value}}

        usage = _token_usage([row(7), row(None), row(True), row(1.5), {"status": "pending"}])
        self.assertEqual(usage, {"observedSamples": 1, "missingSamples": 3, "observedTotal": 7})
        usage = _token_usage([row(10 ** 308), row(10 ** 308)])
        self.assertEqual(usage, {"observedSamples": 2, "missingSamples": 0, "observedTotal": None})
        json.dumps(usage, allow_nan=False)

    def test_batch_cli_continuations_reset_usage_and_require_explicit_controls(self):
        fixture = self.fixture()
        code, original = self.cli("--batch", fixture.path, "--run", "--runs-root", fixture.directory / "original",
                                  "--stop-after-tokens", 5)
        self.assertEqual(code, 2)
        source = Path(original["batchDirectory"]) / "batch-result.json"
        before = self.snapshot(source.parent)
        plan = plan_batch_resume(source)
        code, continued = self.cli("--resume-batch", source, "--run", "--runs-root", fixture.outputs,
                                   "--expected-plan-sha256", plan["planFingerprint"]["sha256"], "--stop-after-tokens", 5)
        self.assertEqual(code, 2)
        self.assertEqual(continued["tokenUsage"], {"observedSamples": 1, "missingSamples": 0, "observedTotal": 5})
        self.assertEqual(continued["stopReason"], "stop_after_tokens")
        self.assertEqual(continued["stopAfterTokens"], 5)
        self.unchanged(before)
        self.assertEqual(set(self.snapshot(source.parent)) - set(before), {str(source.parent / CLAIM_NAME)})
        self.assertFalse(plan_batch_resume(source)["canResume"])
        source = Path(continued["resumeDirectory"]) / continued["batchResultPath"]
        plan = plan_batch_resume(source)
        final = resume_batch(source, fixture.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(final["outcome"], "passed")
        self.assertIsNone(final["stopAfterTokens"])
        self.assertIsNone(final["tokenUsage"])
        self.assertEqual(fixture.called, ["resume-one", "resume-two", "resume-three"])

    def test_experiment_chain_rechecks_all_samples_and_preserves_historical_usage(self):
        fixture = self.fixture(experiment=True)
        fixture.manifest.update(repetitions=3, failurePolicy="stop")
        fixture.manifest["configurations"] = fixture.manifest["configurations"][:1]
        fixture.save(fixture.path, fixture.manifest)
        preview = plan_experiment(fixture.path, max_samples=6)
        code, original = self.cli("--experiment", fixture.path, "--run", "--runs-root", fixture.directory / "original",
                                  "--max-samples", 6, "--expected-plan-sha256", preview["planFingerprint"]["sha256"],
                                  "--stop-after-tokens", 8)
        self.assertEqual(code, 2)
        self.assertEqual(original["planFingerprint"], preview["planFingerprint"])
        self.assertEqual(original["tokenUsage"]["observedTotal"], 10)
        source = Path(original["experimentDirectory"]) / "experiment-result.json"
        for remaining in (4, 2):
            plan = plan_experiment_resume(source, max_samples=remaining)
            before = self.snapshot(fixture.directory)
            code, continued = self.cli("--resume-experiment", source, "--run", "--runs-root", fixture.directory / "continued",
                                       "--max-samples", remaining, "--expected-plan-sha256", plan["planFingerprint"]["sha256"],
                                       "--stop-after-tokens", 8)
            self.assertEqual(code, 2 if remaining == 4 else 0)
            self.assertEqual(continued["tokenUsage"], {"observedSamples": 2, "missingSamples": 0, "observedTotal": 10})
            self.assertEqual(continued["stopAfterTokens"], 8)
            self.assertEqual(continued["stopReason"], "stop_after_tokens" if remaining == 4 else None)
            self.unchanged(before)
            source = Path(continued["resumeDirectory"]) / "experiment-resume-result.json"
        self.assertEqual(len(set(fixture.called)), 6)
        report = generate_report(source, fixture.directory / "reports")
        self.assertEqual(report["comparisonReportFormatVersion"], 3)
        self.assertEqual(report["verificationCounts"], {"verified": 6})
        self.assertEqual(report["reusedSummary"]["metrics"]["totalTokens"]["observedTotal"], 20)
        self.assertEqual(report["newlyExecutedSummary"]["metrics"]["totalTokens"]["observedTotal"], 10)
        browser = ArtifactBrowser(ROOT / "fixtures/evaluation", fixture.directory)
        before = self.snapshot(fixture.directory)
        document = browser.document(browser.reference(source))
        self.assertEqual(document["data"]["tokenUsage"], continued["tokenUsage"])
        self.assertEqual(document["data"]["stopAfterTokens"], 8)
        self.unchanged(before)

    def test_failure_cleanup_and_interruption_precede_usage_controls(self):
        fixture = self.fixture()
        case = fixture.cases["one"]
        assertion = next(item for item in case["assertions"] if item["type"] == "final_text")
        assertion["equals"] = "wrong"
        fixture.save(fixture.directory / "one.json", case)
        for policy in ("stop", "continue"):
            fixture.manifest["failurePolicy"] = policy
            fixture.save(fixture.path, fixture.manifest)
            result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=1)
            self.assertEqual(result["stopReason"], "failure_policy" if policy == "stop" else "stop_after_tokens")

        def unconfirmed(*args, **kwargs):
            result = fixture.synthetic_case(*args, **kwargs)
            runtime_path = Path(result["association"]["evidencePath"]).parent / "runtime.json"
            runtime = load_json(runtime_path)
            runtime["supervisor"]["stdinWriterStopped"] = False
            fixture.save(runtime_path, runtime)
            return result

        with patch("dsh_eval.batch.run_case", side_effect=unconfirmed):
            result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=1)
        self.assertEqual((result["status"], result["stopReason"]), ("error", "cleanup_unconfirmed"))
        with patch("dsh_eval.runner._prepare", side_effect=KeyboardInterrupt):
            result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=1)
        self.assertEqual((result["status"], result["stopReason"]), ("interrupted", "user_interrupt"))
        with patch("dsh_eval.batch.run_case", side_effect=ValueError("runner failed")):
            result = run_batch(fixture.path, fixture.outputs, stop_after_tokens=1)
        self.assertEqual((result["status"], result["stopReason"]), ("error", "runner_error"))
        self.assertEqual(result["tokenUsage"]["missingSamples"], 1)

    def test_checkpoint_failure_never_starts_a_later_task(self):
        fixture = self.fixture()

        def checkpoint(directory, report):
            if report["entries"][0]["status"] == "finished":
                raise OSError("checkpoint unavailable")
            _checkpoint(directory, report)

        with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint), self.assertRaisesRegex(OSError, "checkpoint unavailable"):
            run_batch(fixture.path, fixture.outputs, stop_after_tokens=1)
        self.assertEqual(len(fixture.called), 1)
        source = next(fixture.outputs.glob("*/batch-result.json"))
        self.assertIsNone(load_json(source)["entries"][1]["caseRunId"])

    def test_token_control_does_not_bypass_plan_or_continuation_sample_cap(self):
        fixture = self.fixture(experiment=True)
        with self.assertRaisesRegex(ValueError, "exceeds max_samples"):
            run_experiment(fixture.path, fixture.directory / "original", max_samples=2, stop_after_tokens=1)
        self.assertFalse((fixture.directory / "original").exists())
        original = run_experiment(fixture.path, fixture.directory / "original", stop_after_tokens=1)
        source = Path(original["experimentDirectory"]) / "experiment-result.json"
        plan = plan_experiment_resume(source)
        with self.assertRaisesRegex(ValueError, "exceeds max_samples"):
            resume_experiment(source, fixture.directory / "continued", max_samples=2, stop_after_tokens=1,
                              expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertFalse((source.parent / original["batchResultPath"]).parent.joinpath(CLAIM_NAME).exists())
        self.assertFalse((fixture.directory / "continued").exists())
