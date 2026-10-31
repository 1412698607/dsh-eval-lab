"""Stop at real scheduler boundaries; synthetic tasks still write and recheck evidence."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_batch_resume as batch_fixtures
import test_experiment_resume as experiment_fixtures
from dsh_eval.__main__ import main
from dsh_eval.batch import _checkpoint, run_batch
from dsh_eval.browser import ArtifactBrowser
from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.resume import CLAIM_NAME, plan_batch_resume, resume_batch
from dsh_eval.runner import ROOT


class SchedulerStopTests(unittest.TestCase):
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

    def assert_unstarted(self, rows):
        for row in rows:
            self.assertEqual((row["status"], row["skipReason"]), ("skipped", "stop_after"))
            for key in ("caseRunId", "caseDirectory", "runId", "sessionId", "evaluationPath", "evidencePath",
                        "runtimeReport", "runDir", "outcome", "source", "metrics"):
                self.assertIsNone(row[key], key)

    def test_invalid_api_controls_reject_before_reading_or_allocating(self):
        for function in (run_batch, run_experiment, resume_batch, resume_experiment):
            for value in (True, False, 0, -1, 1.5, "2"):
                with self.subTest(function=function.__name__, value=value), \
                        self.assertRaisesRegex(ValueError, "stop_after must be a positive integer"):
                    function("does-not-exist.json", stop_after=value)

    def test_cli_rejects_nonpositive_and_nonexecution_combinations(self):
        commands = [[selector, "missing.json", "--plan", "--stop-after", "1"]
                    for selector in ("--experiment", "--resume-batch", "--resume-experiment")]
        commands += [[selector, "missing.json", "--run", "--stop-after", value]
                     for selector in ("--batch", "--experiment", "--resume-batch", "--resume-experiment")
                     for value in ("0", "-1", "1.5")]
        commands += [["--case", "missing.json", "--run", "--stop-after", "1"],
                     ["--report", "missing.json", "--stop-after", "1"],
                     ["--browse", "--stop-after", "1"]]
        for command in commands:
            with self.subTest(command=command), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(command)
            self.assertEqual(error.exception.code, 2)

    def test_live_candidate_is_a_read_only_six_task_preview(self):
        path = ROOT / "fixtures/evaluation/core/continuous-resume.experiment.json"
        with patch("dsh_eval.experiment.uuid4", side_effect=AssertionError("preview cannot allocate")), \
                patch("dsh_eval.batch.run_case", side_effect=AssertionError("preview cannot execute")):
            code, plan = self.cli("--experiment", path, "--plan", "--max-samples", 6)
        self.assertEqual(code, 0)
        self.assertFalse(plan["modelCalled"])
        self.assertEqual(plan["counts"], {"cases": 2, "configurations": 1, "samples": 6})
        self.assertEqual(plan["failurePolicy"], "stop")
        self.assertEqual([row["caseEntryId"] for row in plan["samples"]], ["direct-read", "retry-once"] * 3)
        self.assertEqual([row["repeatIndex"] for row in plan["samples"]], [1, 1, 2, 2, 3, 3])
        self.assertTrue(all(row["requestedConfiguration"]["model"] == "deepseek-flash" for row in plan["samples"]))

    def test_batch_cli_stops_and_resumes_only_new_tasks(self):
        fixture = self.fixture()
        code, original = self.cli("--batch", fixture.path, "--run", "--runs-root", fixture.directory / "original",
                                  "--stop-after", 1)
        self.assertEqual(code, 2)
        self.assertEqual((original["status"], original["stopReason"], original["stopAfter"]), ("stopped", "stop_after", 1))
        self.assertEqual(fixture.called, ["resume-one"])
        self.assert_unstarted(original["entries"][1:])
        source = Path(original["batchDirectory"]) / "batch-result.json"
        before = self.snapshot(source.parent)
        plan = plan_batch_resume(source, max_samples=2)
        self.assertTrue(plan["canResume"])
        code, continuation = self.cli("--resume-batch", source, "--run", "--runs-root", fixture.outputs,
                                     "--max-samples", 2, "--expected-plan-sha256", plan["planFingerprint"]["sha256"],
                                     "--stop-after", 1)
        self.assertEqual(code, 2)
        self.assertEqual((continuation["stopAfter"], continuation["stopReason"]), (1, "stop_after"))
        child_path = Path(continuation["resumeDirectory"]) / continuation["batchResultPath"]
        child = load_json(child_path)
        self.assert_unstarted(child["entries"][1:])
        self.assertEqual(fixture.called, ["resume-one", "resume-two"])
        self.unchanged(before)
        self.assertEqual(set(self.snapshot(source.parent)) - set(before), {str(source.parent / CLAIM_NAME)})
        self.assertFalse(plan_batch_resume(source)["canResume"])
        with self.assertRaisesRegex(ValueError, "cannot resume"):
            resume_batch(source, fixture.outputs, stop_after=1, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        next_plan = plan_batch_resume(child_path)
        final = resume_batch(child_path, fixture.outputs, stop_after=1,
                             expected_plan_sha256=next_plan["planFingerprint"]["sha256"])
        self.assertEqual((final["status"], final["outcome"], final["stopReason"]), ("completed", "passed", None))
        self.assertEqual(fixture.called, ["resume-one", "resume-two", "resume-three"])

    def test_six_task_experiment_cli_chain_reports_and_browses_all_evidence(self):
        fixture = self.fixture(experiment=True)
        fixture.manifest.update(repetitions=3, failurePolicy="stop")
        fixture.manifest["configurations"] = fixture.manifest["configurations"][:1]
        fixture.save(fixture.path, fixture.manifest)
        preview = plan_experiment(fixture.path, max_samples=6)
        checkpoints = []

        def checkpoint(directory, report):
            _checkpoint(directory, report)
            if report["entries"][1]["status"] == "finished" and report["status"] == "running":
                checkpoints.append(load_json(directory / "batch-result.json"))

        with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint):
            code, original = self.cli("--experiment", fixture.path, "--run", "--runs-root", fixture.directory / "original",
                                      "--max-samples", 6, "--expected-plan-sha256", preview["planFingerprint"]["sha256"],
                                      "--stop-after", 2)
        self.assertEqual(code, 2)
        self.assertEqual(original["planFingerprint"], preview["planFingerprint"])
        self.assertEqual((original["summary"]["planned"], original["summary"]["attempted"], original["summary"]["skipped"]),
                         (6, 2, 4))
        self.assertEqual(checkpoints[0]["entries"][2]["status"], "pending")
        self.assertIsNone(checkpoints[0]["entries"][2]["caseRunId"])
        self.assert_unstarted(original["samples"][2:])
        source = Path(original["experimentDirectory"]) / "experiment-result.json"
        original_files = self.snapshot(source.parent)
        for reused, remaining in ((2, 4), (4, 2)):
            plan = plan_experiment_resume(source, max_samples=remaining)
            self.assertEqual(plan["counts"], {"original": 6, "reused": reused, "newSamples": remaining, "blocked": 0})
            before = self.snapshot(fixture.directory)
            code, continuation = self.cli("--resume-experiment", source, "--run", "--runs-root", fixture.directory / "continued",
                                         "--max-samples", remaining, "--expected-plan-sha256", plan["planFingerprint"]["sha256"],
                                         "--stop-after", 2)
            self.assertEqual(code, 2 if remaining == 4 else 0)
            self.assertEqual(continuation["stopAfter"], 2)
            self.assertEqual(continuation["stopReason"], "stop_after" if remaining == 4 else None)
            self.assertEqual(len(fixture.called), reused + 2)
            self.unchanged(before)
            self.assertFalse(plan_experiment_resume(source)["eligibleForResume"])
            source = Path(continuation["resumeDirectory"]) / "experiment-resume-result.json"
        self.assertEqual(len(set(fixture.called)), 6)
        self.assertEqual((continuation["status"], continuation["outcome"]), ("completed", "passed"))
        self.unchanged(original_files)
        report = generate_report(source, fixture.directory / "reports")
        self.assertEqual(report["comparisonReportFormatVersion"], 3)
        self.assertEqual(report["verificationCounts"], {"verified": 6})
        self.assertEqual(report["summary"]["sourceCounts"], {"synthetic": 6})
        self.assertEqual((report["reusedSummary"]["planned"], report["newlyExecutedSummary"]["planned"]), (4, 2))
        self.assertEqual(len(report["batchIds"]), 3)
        browser = ArtifactBrowser(ROOT / "fixtures/evaluation", fixture.directory)
        pending = [browser.reference(Path(report["reportDirectory"]) / "report.json")]
        before = self.snapshot(fixture.directory)
        visited = set()
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("browse must not recheck")):
            while pending:
                identifier = pending.pop()
                if identifier not in visited:
                    visited.add(identifier)
                    pending.extend(link["id"] for link in browser.document(identifier)["links"] if link["id"])
        self.assertEqual(sum(path.endswith(".jsonl") for path in visited), 6)
        self.assertEqual(self.snapshot(fixture.directory), before)

    def test_limit_at_or_above_total_completes_normally(self):
        fixture = self.fixture()
        for stop_after in (3, 4):
            report = run_batch(fixture.path, fixture.outputs, stop_after=stop_after)
            self.assertEqual((report["status"], report["stopReason"], report["outcome"]), ("completed", None, "passed"))
            self.assertEqual(len(list((Path(report["batchDirectory"]) / "cases").iterdir())), 3)

    def test_failure_policy_precedes_limit_and_continue_counts_failed_tasks(self):
        fixture = self.fixture()
        case = fixture.cases["one"]
        next(item for item in case["assertions"] if item["type"] == "final_text")["equals"] = "wrong"
        fixture.save(fixture.directory / "one.json", case)
        for policy in ("stop", "continue"):
            fixture.manifest["failurePolicy"] = policy
            fixture.save(fixture.path, fixture.manifest)
            report = run_batch(fixture.path, fixture.outputs, stop_after=1)
            self.assertEqual((report["status"], report["outcome"]), ("stopped", "failed"))
            self.assertEqual(report["stopReason"], "failure_policy" if policy == "stop" else "stop_after")
            self.assertEqual(report["entries"][0]["status"], "finished")
            self.assertTrue(all(row["caseRunId"] is None for row in report["entries"][1:]))
            plan = plan_batch_resume(Path(report["batchDirectory"]) / "batch-result.json")
            self.assertEqual(plan["canResume"], policy == "continue")

    def test_unconfirmed_cleanup_precedes_limit_and_blocks_resume(self):
        fixture = self.fixture()

        def unconfirmed(*args, **kwargs):
            result = fixture.synthetic_case(*args, **kwargs)
            runtime_path = Path(result["association"]["evidencePath"]).parent / "runtime.json"
            runtime = load_json(runtime_path)
            runtime["supervisor"]["stdinWriterStopped"] = False
            fixture.save(runtime_path, runtime)
            return result

        with patch("dsh_eval.batch.run_case", side_effect=unconfirmed):
            report = run_batch(fixture.path, fixture.outputs, stop_after=1)
        self.assertEqual((report["status"], report["stopReason"]), ("error", "cleanup_unconfirmed"))
        self.assertEqual(len(fixture.called), 1)
        self.assertFalse(plan_batch_resume(Path(report["batchDirectory"]) / "batch-result.json")["canResume"])

    def test_user_interrupt_precedes_limit(self):
        fixture = self.fixture()
        with patch("dsh_eval.runner._prepare", side_effect=KeyboardInterrupt):
            report = run_batch(fixture.path, fixture.outputs, stop_after=1)
        self.assertEqual((report["status"], report["stopReason"]), ("interrupted", "user_interrupt"))
        self.assertTrue(all(row["caseRunId"] is None for row in report["entries"][1:]))

    def test_checkpoint_failure_never_starts_a_later_task(self):
        fixture = self.fixture()

        def checkpoint(directory, report):
            if report["entries"][0]["status"] == "finished":
                raise OSError("checkpoint unavailable")
            _checkpoint(directory, report)

        with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint), self.assertRaisesRegex(OSError, "checkpoint unavailable"):
            run_batch(fixture.path, fixture.outputs, stop_after=2)
        self.assertEqual(len(fixture.called), 1)
        source = next(fixture.outputs.glob("*/batch-result.json"))
        self.assertEqual(load_json(source)["entries"][1]["status"], "pending")
        self.assertTrue(plan_batch_resume(source)["canResume"])

    def test_stop_control_does_not_shrink_plans_or_bypass_task_cap(self):
        fixture = self.fixture(experiment=True)
        before = plan_experiment(fixture.path, max_samples=8)
        with self.assertRaisesRegex(ValueError, "exceeds max_samples"):
            run_experiment(fixture.path, fixture.directory / "original", max_samples=2, stop_after=1)
        self.assertEqual(fixture.called, [])
        self.assertFalse((fixture.directory / "original").exists())
        original = run_experiment(fixture.path, fixture.directory / "original", max_samples=8, stop_after=2)
        self.assertEqual(original["planFingerprint"], before["planFingerprint"])
        source = Path(original["experimentDirectory"]) / "experiment-result.json"
        plan = plan_experiment_resume(source)
        with self.assertRaisesRegex(ValueError, "exceeds max_samples"):
            resume_experiment(source, fixture.directory / "continued", max_samples=2, stop_after=1,
                              expected_plan_sha256=plan["planFingerprint"]["sha256"])
        batch_source = source.parent / original["batchResultPath"]
        self.assertFalse((batch_source.parent / CLAIM_NAME).exists())
        self.assertFalse((fixture.directory / "continued").exists())
