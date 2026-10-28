"""No-model re-preflight of a terminal experiment continuation."""
from contextlib import ExitStack, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_experiment_resume as fixtures
from dsh_eval.__main__ import main
from dsh_eval.batch import _checkpoint
from dsh_eval.batch_lock import batch_lock
from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
from dsh_eval.formats import load_json
from dsh_eval.resume import CLAIM_NAME
from dsh_eval.resume import plan_batch_resume
from dsh_eval.report import generate_report
from dsh_eval.browser import ArtifactBrowser
from dsh_eval.runner import ROOT


class ExperimentResumeChainTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentResumeTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.crash()
        def stop(directory, report):
            _checkpoint(directory, report)
            if report["status"] == "running" and report["entries"][1]["status"] == "finished":
                raise KeyboardInterrupt
        with patch("dsh_eval.batch._checkpoint", side_effect=stop):
            result = self.fixture.execute()
        self.source = Path(result["resumeDirectory"]) / "experiment-resume-result.json"
        self.child_path = self.source.parent / result["batchResumeResultPath"]
        self.child = load_json(self.child_path)
        self.batch_path = self.child_path.parent / self.child["batchResultPath"]
        self.batch = load_json(self.batch_path)
        self.fixture.called.clear()

    def snapshot(self):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.fixture.directory.rglob("*") if path.is_file()}

    def plan(self, **kwargs):
        return plan_experiment_resume(self.source, **kwargs)

    def test_terminal_continuation_maps_all_original_samples_and_does_not_allocate_or_write(self):
        before = self.snapshot()
        with ExitStack() as stack:
            for target in ("dsh_eval.experiment_resume.uuid4", "dsh_eval.resume.uuid4", "dsh_eval.batch.run_case",
                           "dsh_eval.resume.run_batch", "dsh_eval.runner._prepare"):
                stack.enter_context(patch(target, side_effect=AssertionError("preflight must not execute or allocate")))
            plan = self.plan(max_samples=4)
        self.assertEqual(plan["experimentResumePlanFormatVersion"], 2)
        self.assertTrue(plan["executionSupported"])
        self.assertFalse(plan["modelCalled"])
        self.assertTrue(plan["eligibleForResume"])
        self.assertEqual(plan["counts"], {"original": 8, "reused": 4, "newSamples": 4, "blocked": 0})
        self.assertEqual([row["disposition"] for row in plan["samples"]], ["reuse"] * 4 + ["pending"] * 4)
        self.assertEqual([row["sampleId"] for row in plan["samples"]], [f"sample-{index:06}" for index in range(1, 9)])
        self.assertEqual([row["sourceBatchId"] for row in plan["samples"]],
                         [self.child["sourceBatchId"]] * 2 + [self.batch["batchId"]] * 6)
        self.assertEqual(plan["sourceResumeResult"], str(self.source))
        self.assertEqual(plan["sourceBatchResult"], str(self.batch_path))
        self.assertEqual(plan["planFingerprint"], self.plan(max_samples=4)["planFingerprint"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.fixture.called, [])

    def execute(self, source=None):
        source = source or self.source
        plan = plan_experiment_resume(source)
        return resume_experiment(source, self.fixture.directory / "again", expected_plan_sha256=plan["planFingerprint"]["sha256"])

    def test_repeated_execution_runs_only_four_remaining_samples_and_reports_all_eight(self):
        before = self.snapshot()
        result = self.execute()
        self.assertEqual(result["experimentResumeResultFormatVersion"], 2)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(len(self.fixture.called), 4)
        self.assertEqual(result["combinedSummary"]["planned"], 8)
        self.assertEqual(result["newlyExecutedSummary"]["planned"], 4)
        path = Path(result["resumeDirectory"]) / "experiment-resume-result.json"
        report = generate_report(path, self.fixture.directory / "reports")
        self.assertEqual(report["comparisonReportFormatVersion"], 3)
        self.assertEqual(len(report["batchIds"]), 3)
        self.assertEqual(report["summary"]["sourceCounts"], {"synthetic": 8})
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual(report["reusedSummary"]["planned"], 4)
        self.assertEqual(report["newlyExecutedSummary"]["planned"], 4)
        self.assertEqual([row["pairedSamples"] for row in report["comparisons"]], [2, 2])
        after = self.snapshot()
        self.assertTrue(all(after.get(path) == digest for path, digest in before.items()))
        self.assertFalse(self.plan()["eligibleForResume"])

    def test_another_interruption_can_continue_a_four_batch_chain(self):
        def stop(directory, report):
            _checkpoint(directory, report)
            if report["status"] == "running" and report["entries"][1]["status"] == "finished":
                raise KeyboardInterrupt
        with patch("dsh_eval.batch._checkpoint", side_effect=stop):
            second = self.execute()
        path = Path(second["resumeDirectory"]) / "experiment-resume-result.json"
        plan = plan_experiment_resume(path, max_samples=2)
        self.assertEqual(plan["counts"], {"original": 8, "reused": 6, "newSamples": 2, "blocked": 0})
        self.fixture.called.clear()
        third = self.execute(path)
        self.assertEqual(len(self.fixture.called), 2)
        report = generate_report(Path(third["resumeDirectory"]) / "experiment-resume-result.json", self.fixture.directory / "reports")
        self.assertEqual(len(report["batchIds"]), 4)
        self.assertEqual(len(report["resumeChain"]), 3)
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        before = self.snapshot()
        browser = ArtifactBrowser(ROOT / "fixtures/evaluation", self.fixture.directory)
        pending = [browser.reference(Path(report["reportDirectory"]) / "report.json")]
        visited = set()
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("browse must not recheck")):
            while pending:
                identifier = pending.pop()
                if identifier in visited:
                    continue
                visited.add(identifier)
                document = browser.document(identifier)
                pending.extend(link["id"] for link in document["links"] if link["id"])
        self.assertEqual(sum(path.endswith(".jsonl") for path in visited), 8)
        self.assertTrue(all(browser.reference(Path(item)) in visited for item in report["batchResultPaths"]))
        self.assertEqual(self.snapshot(), before)

    def test_abrupt_exit_keeps_binding_and_can_resume_running_wrappers(self):
        def crash(directory, report):
            _checkpoint(directory, report)
            if report["entries"][0]["status"] == "finished":
                self.abrupt_batch = directory / "batch-result.json"
                raise fixtures.SimulatedCrash
        with patch("dsh_eval.batch._checkpoint", side_effect=crash), self.assertRaises(fixtures.SimulatedCrash):
            self.execute()
        child_path = self.abrupt_batch.parents[2] / "resume-result.json"
        child = load_json(child_path)
        self.assertEqual(child["status"], "running")
        self.assertIsNone(child["batchResultPath"])
        self.assertEqual(child["batchBinding"]["batchId"], load_json(self.abrupt_batch)["batchId"])
        source = child_path.parents[2] / "experiment-resume-result.json"
        plan = plan_experiment_resume(source)
        self.assertEqual(plan["counts"], {"original": 8, "reused": 5, "newSamples": 3, "blocked": 0})
        self.fixture.called.clear()
        result = self.execute(source)
        self.assertEqual(len(self.fixture.called), 3)
        report = generate_report(Path(result["resumeDirectory"]) / "experiment-resume-result.json", self.fixture.directory / "reports")
        self.assertEqual(report["verificationCounts"], {"verified": 8})

    def test_stale_checkpoint_is_recovered_without_repeating_its_execution(self):
        changed = copy.deepcopy(self.batch)
        row = changed["entries"][1]
        row["status"] = "running"
        for key in ("evaluationPath", "evidencePath", "runtimeReport", "runDir", "runId", "sessionId", "configuration",
                    "executionStatus", "recordingOutcome", "assertionOutcome", "outcome", "source", "metrics"):
            row[key] = None
        self.fixture.save(self.batch_path, changed)
        plan = self.plan()
        self.assertTrue(plan["samples"][3]["recoveredCheckpoint"])
        result = self.execute()
        self.assertEqual(len(self.fixture.called), 4)
        report = generate_report(Path(result["resumeDirectory"]) / "experiment-resume-result.json", self.fixture.directory / "reports")
        self.assertEqual(report["verificationCounts"], {"verified": 8})

    def test_fingerprint_mismatch_and_duplicate_claim_reject_before_allocating(self):
        plan = self.plan(max_samples=4)
        before = self.snapshot()
        with patch("dsh_eval.experiment_resume_chain.uuid4", side_effect=AssertionError("must reject before allocation")), \
                self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            resume_experiment(self.source, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(self.snapshot(), before)
        self.execute()
        with patch("dsh_eval.experiment_resume_chain.uuid4", side_effect=AssertionError("must reject before allocation")), \
                self.assertRaisesRegex(ValueError, "already has a continuation claim"):
            self.execute()

    def test_finalization_keeps_latest_batch_locked_until_wrapper_is_saved(self):
        import dsh_eval.experiment_resume_chain as chain
        summarize = chain.summarize
        def locked(rows):
            claim = load_json(self.batch_path.parent / CLAIM_NAME)
            child_path = Path(claim["resumeDirectory"]) / "resume-result.json"
            child = load_json(child_path)
            new_batch = child_path.parent / child["batchBinding"]["resultPath"]
            with self.assertRaisesRegex(ValueError, "active or locked"):
                plan_batch_resume(new_batch)
            return summarize(rows)
        with patch("dsh_eval.experiment_resume_chain.summarize", side_effect=locked):
            result = self.execute()
        child = load_json(Path(result["resumeDirectory"]) / result["batchResumeResultPath"])
        with batch_lock((Path(child["resumeDirectory"]) / child["batchBinding"]["resultPath"]).parent):
            pass

    def test_cyclic_chain_and_external_child_paths_are_rejected_without_inspect(self):
        result = self.execute()
        path = Path(result["resumeDirectory"]) / "experiment-resume-result.json"
        for mutation in ("cycle", "external", "version"):
            saved = copy.deepcopy(result)
            if mutation == "cycle":
                saved["sourceResumeResult"] = str(path)
            elif mutation == "external":
                saved["batchResumeResultPath"] = "../outside/resume-result.json"
            else:
                saved["experimentResumeResultFormatVersion"] = True
            self.fixture.save(path, saved)
            with patch("dsh_eval.resume.evaluate", side_effect=AssertionError("must reject before inspection")), \
                    self.subTest(mutation=mutation), self.assertRaises(ValueError):
                plan_experiment_resume(path)
        self.fixture.save(path, result)

    def test_legacy_terminal_child_is_supported_but_running_child_needs_a_binding(self):
        old = copy.deepcopy(self.child)
        old.pop("batchBinding")
        self.fixture.save(self.child_path, old)
        self.assertTrue(self.plan()["eligibleForResume"])
        parent = load_json(self.source)
        parent.update(status="running", finishedAt=None, outcome=None, newlyExecutedSummary=None)
        old.update(status="running", finishedAt=None, outcome=None, batchResultPath=None)
        self.fixture.save(self.source, parent)
        self.fixture.save(self.child_path, old)
        with self.assertRaisesRegex(ValueError, "legacy continuation lacks an explicit batch binding"):
            self.plan()

    def test_historical_failures_remain_failed_when_the_last_new_sample_passes(self):
        other = fixtures.ExperimentResumeTests()
        other.setUp()
        self.addCleanup(other.doCleanups)
        other.manifest["repetitions"] = 1
        other.save(other.path, other.manifest)
        case_path = other.directory / "first.json"
        case = load_json(case_path)
        next(row for row in case["assertions"] if row["type"] == "final_text")["equals"] = "expected-failure"
        other.save(case_path, case)
        other.crash()
        def stop(directory, report):
            _checkpoint(directory, report)
            if report["status"] == "running" and report["entries"][0]["status"] == "finished":
                raise KeyboardInterrupt
        with patch("dsh_eval.batch._checkpoint", side_effect=stop):
            first = other.execute()
        source = Path(first["resumeDirectory"]) / "experiment-resume-result.json"
        plan = plan_experiment_resume(source)
        result = resume_experiment(source, other.directory / "again", expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["newlyExecutedSummary"]["outcomes"]["passed"], 1)
        report = generate_report(Path(result["resumeDirectory"]) / "experiment-resume-result.json", other.directory / "reports")
        self.assertEqual(report["summary"]["outcomes"], {"failed": 2, "passed": 2, "unevaluable": 0})

    def test_original_stop_policy_still_blocks_a_failed_continuation(self):
        other = fixtures.ExperimentResumeTests()
        other.setUp()
        self.addCleanup(other.doCleanups)
        other.manifest["failurePolicy"] = "stop"
        other.save(other.path, other.manifest)
        case_path = other.directory / "second.json"
        case = load_json(case_path)
        next(row for row in case["assertions"] if row["type"] == "final_text")["equals"] = "expected-failure"
        other.save(case_path, case)
        other.crash()
        first = other.execute()
        source = Path(first["resumeDirectory"]) / "experiment-resume-result.json"
        plan = plan_experiment_resume(source)
        self.assertFalse(plan["eligibleForResume"])
        self.assertIn("Original failure policy prohibits further execution", plan["reasons"])
        with patch("dsh_eval.experiment_resume_chain.uuid4", side_effect=AssertionError("must not allocate")), self.assertRaises(ValueError):
            resume_experiment(source, expected_plan_sha256=plan["planFingerprint"]["sha256"])

    def test_chain_limit_and_final_write_failure_do_not_allocate_extra_tasks_or_keep_locks(self):
        with patch("dsh_eval.experiment_resume_chain.MAX_CONTINUATIONS", 1):
            self.assertFalse(self.plan()["eligibleForResume"])
            with patch("dsh_eval.experiment_resume_chain.uuid4", side_effect=AssertionError("must not allocate")), self.assertRaises(ValueError):
                self.execute()
        import dsh_eval.experiment_resume_chain as chain
        save = chain.save_json
        def fail(path, data):
            if path.name.startswith(".experiment-resume-result-"):
                self.unfinished = path.parent / "experiment-resume-result.json"
                raise OSError("Synthetic final checkpoint failure")
            save(path, data)
        with patch("dsh_eval.experiment_resume_chain.save_json", side_effect=fail), self.assertRaisesRegex(OSError, "final checkpoint failure"):
            self.execute()
        self.assertEqual(load_json(self.unfinished)["status"], "running")
        plan = plan_experiment_resume(self.unfinished)
        self.assertFalse(plan["eligibleForResume"])
        self.assertEqual(plan["counts"]["reused"], 8)
        with self.assertRaisesRegex(ValueError, "terminal continuation"):
            generate_report(self.unfinished, self.fixture.directory / "reports")

    def test_both_ancestor_and_latest_batch_locks_are_required(self):
        for path in (self.fixture.batch_source, self.batch_path):
            with self.subTest(batch=path), batch_lock(path.parent), self.assertRaisesRegex(ValueError, "active or locked"):
                self.plan()

    def test_corrupt_historical_or_latest_recordings_block_only_their_samples(self):
        for path in (self.fixture.batch_source, self.batch_path):
            saved = load_json(path)
            trace = next((path.parent / saved["entries"][0]["runDir"]).glob("*.jsonl"))
            before = trace.read_bytes()
            try:
                trace.write_bytes(before + b"broken\n")
                plan = self.plan()
                self.assertFalse(plan["eligibleForResume"])
                self.assertEqual(plan["counts"]["blocked"], 1)
                self.assertEqual(plan["counts"]["newSamples"], 4)
            finally:
                trace.write_bytes(before)

    def test_latest_claim_and_unknown_execution_block_repreflight(self):
        claim = self.batch_path.parent / CLAIM_NAME
        claim.write_text("{}", encoding="utf-8")
        self.assertFalse(self.plan()["eligibleForResume"])
        claim.unlink()
        changed = copy.deepcopy(self.batch)
        case_id = str(uuid4())
        changed["entries"][2].update(status="error", outcome="unevaluable", caseRunId=case_id, caseDirectory=f"cases/{case_id}")
        self.fixture.save(self.batch_path, changed)
        plan = self.plan()
        self.assertFalse(plan["eligibleForResume"])
        self.assertEqual(plan["samples"][4]["disposition"], "blocked")

    def test_task_cap_applies_only_to_latest_unstarted_samples(self):
        self.assertEqual(self.plan(max_samples=4)["counts"]["newSamples"], 4)
        with self.assertRaisesRegex(ValueError, "exceeds max_samples"):
            self.plan(max_samples=3)
        self.assertNotEqual(self.plan()["planFingerprint"], self.plan(max_samples=4)["planFingerprint"])

    def test_running_parent_and_mismatched_frozen_input_are_rejected_before_inspect(self):
        for mutate in ("running", "frozen"):
            with self.subTest(change=mutate):
                path = self.source if mutate == "running" else self.batch_path.parent / self.batch["entries"][0]["casePath"]
                original = path.read_bytes()
                data = load_json(path)
                if mutate == "running":
                    data.update(status="running", finishedAt=None)
                else:
                    data["input"] += " changed"
                self.fixture.save(path, data)
                try:
                    with patch("dsh_eval.report.evaluate", side_effect=AssertionError("must reject before inspection")), \
                            patch("dsh_eval.resume.evaluate", side_effect=AssertionError("must reject before inspection")), \
                            self.assertRaises(ValueError):
                        self.plan()
                finally:
                    path.write_bytes(original)

    def test_cli_preview_execution_and_offline_report_use_versioned_utf8_json(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--resume-experiment", str(self.source), "--plan", "--max-samples", "4"]), 0)
        self.assertTrue(json.loads(output.getvalue())["executionSupported"])
        before = self.snapshot()
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--resume-experiment", str(self.source), "--plan"],
                                 cwd=ROOT, capture_output=True, timeout=30, check=True)
        self.assertEqual(json.loads(process.stdout.decode("utf-8"))["counts"]["reused"], 4)
        self.assertEqual(process.stderr, b"")
        self.assertEqual(self.snapshot(), before)
        output = io.StringIO()
        plan = self.plan()
        with redirect_stdout(output):
            code = main(["--resume-experiment", str(self.source), "--run", "--expected-plan-sha256", plan["planFingerprint"]["sha256"],
                         "--runs-root", str(self.fixture.directory / "cli")])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["experimentResumeResultFormatVersion"], 2)
        self.assertEqual(len(self.fixture.called), 4)
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--report",
            str(Path(result["resumeDirectory"]) / "experiment-resume-result.json"),
            "--reports-root", str(self.fixture.directory / "cli-reports")], cwd=ROOT, capture_output=True, timeout=30, check=True)
        report = json.loads(process.stdout.decode("utf-8"))
        self.assertEqual(report["comparisonReportFormatVersion"], 3)
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual(process.stderr, b"")


if __name__ == "__main__":
    unittest.main()
