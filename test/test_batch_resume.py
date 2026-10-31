"""No-model continuation through the real synthetic adapter, recorder and inspect."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.batch import _checkpoint, run_batch
from dsh_eval.batch_lock import batch_lock
from dsh_eval.evaluate import evaluate
from dsh_eval.formats import load_json
from dsh_eval.resume import CLAIM_NAME, plan_batch_resume, resume_batch
from dsh_eval.runner import ROOT, run_case


class SimulatedCrash(BaseException):
    pass


class BatchResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-batch-resume-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.outputs = self.directory / "continuations"
        case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        case["configRef"].update(provider="synthetic", model="none")
        self.cases = {}
        for entry_id in ("one", "two", "three"):
            self.cases[entry_id] = {**copy.deepcopy(case), "caseId": "resume-" + entry_id}
            self.save(self.directory / f"{entry_id}.json", self.cases[entry_id])
        self.manifest = {"batchFormatVersion": 1, "batchName": "resume fixture", "failurePolicy": "continue",
                         "cases": [{"entryId": key, "casePath": f"{key}.json"} for key in self.cases]}
        self.path = self.directory / "batch.json"
        self.called = []
        for mock in (patch("dsh_eval.runner._prepare"),
                     patch("dsh_eval.resume._check_resume_output_root"),  # Synthetic adapter never installs Harness.
                     patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js"),
                     patch("dsh_eval.batch.run_case", side_effect=self.synthetic_case)):
            mock.start()
            self.addCleanup(mock.stop)

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def synthetic_case(self, *args, **kwargs):
        result = run_case(*args, **kwargs)
        self.called.append(result["caseId"])
        evidence_path = Path(result["association"]["evidencePath"])
        evidence = load_json(evidence_path)
        evidence["source"] = "synthetic"
        self.save(evidence_path, evidence)
        fresh = evaluate(result["association"]["casePath"], evidence_path)
        self.save(evidence_path.parent / "evaluation.json", fresh)
        return fresh

    def crash(self, boundary="finished"):
        self.save(self.path, self.manifest)

        def checkpoint(directory, report):
            first, second = report["entries"][:2]
            stop = (first["status"] == "finished" and second["status"] == "pending" if boundary != "unknown" else
                    second["status"] == "running")
            snapshot = copy.deepcopy(report)
            if stop and boundary == "saved-evaluation":
                row = snapshot["entries"][0]
                row["status"] = "running"
                for key in ("evaluationPath", "evidencePath", "runtimeReport", "runDir", "runId", "sessionId", "configuration",
                            "executionStatus", "recordingOutcome", "assertionOutcome", "outcome", "source", "metrics"):
                    row[key] = None
            _checkpoint(directory, snapshot)
            if stop:
                self.source = directory / "batch-result.json"
                raise SimulatedCrash

        with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint), self.assertRaises(SimulatedCrash):
            run_batch(self.path, self.directory / "initial")
        self.called.clear()
        return self.source

    def snapshot(self):
        return {p.relative_to(self.source.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.source.parent.rglob("*") if p.is_file()}

    def test_preview_rechecks_and_executes_only_unstarted_cases_in_a_new_batch(self):
        source = self.crash()
        before = self.snapshot()
        with patch("dsh_eval.resume.uuid4", side_effect=AssertionError("preview cannot create an identity")):
            plan = plan_batch_resume(source, max_samples=2)
        self.assertTrue(plan["canResume"])
        self.assertEqual(plan["counts"], {"original": 3, "reused": 1, "newSamples": 2, "blocked": 0})
        self.assertEqual(plan["pendingEntryIds"], ["two", "three"])
        self.assertEqual(plan["reusedEntries"][0]["source"], "synthetic")
        self.assertEqual(self.snapshot(), before)
        result = resume_batch(source, self.outputs, max_samples=2, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(self.called, ["resume-two", "resume-three"])
        self.assertEqual((result["status"], result["outcome"]), ("completed", "passed"))
        self.assertEqual(result["newlyExecutedSummary"]["planned"], 2)
        self.assertEqual(result["combinedSummary"]["planned"], 3)
        self.assertEqual(result["combinedSummary"]["sourceCounts"], {"synthetic": 3})
        after = self.snapshot()
        self.assertTrue(all(after[name] == digest for name, digest in before.items()))
        self.assertEqual(set(after) - set(before), {CLAIM_NAME})
        child = load_json(Path(result["resumeDirectory"]) / result["batchResultPath"])
        self.assertNotEqual(child["batchId"], load_json(source)["batchId"])
        self.assertTrue(all(row["caseRunId"] != plan["reusedEntries"][0]["caseRunId"] for row in child["entries"]))
        self.assertEqual(load_json(Path(result["resumeDirectory"]) / "resume-result.json"), result)

    def test_crash_after_final_evaluation_recovers_without_repeating_that_case(self):
        source = self.crash("saved-evaluation")
        plan = plan_batch_resume(source)
        self.assertTrue(plan["canResume"])
        self.assertTrue(plan["reusedEntries"][0]["recoveredCheckpoint"])
        result = resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(self.called, ["resume-two", "resume-three"])

    def test_unknown_running_case_blocks_all_execution(self):
        source = self.crash("unknown")
        before = self.snapshot()
        plan = plan_batch_resume(source)
        self.assertFalse(plan["canResume"])
        self.assertEqual(plan["counts"]["blocked"], 1)
        self.assertEqual(plan["blockedEntries"][0]["entryId"], "two")
        with patch("dsh_eval.resume.uuid4", side_effect=AssertionError("blocked resume cannot allocate")):
            with self.assertRaisesRegex(ValueError, "cannot resume"):
                resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.called, [])
        self.assertFalse(self.outputs.exists())

    def test_modified_recording_or_unconfirmed_cleanup_cannot_be_reused(self):
        source = self.crash()
        row = load_json(source)["entries"][0]
        runtime_path = source.parent / row["runtimeReport"]
        runtime = load_json(runtime_path)
        original_runtime = runtime_path.read_bytes()
        runtime["host"]["childClosed"] = False
        self.save(runtime_path, runtime)
        self.assertFalse(plan_batch_resume(source)["canResume"])
        runtime_path.write_bytes(original_runtime)
        run_directory = source.parent / row["runDir"]
        trace = next(run_directory.glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-5])
        plan = plan_batch_resume(source)
        self.assertFalse(plan["canResume"])
        with self.assertRaises(ValueError):
            resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(self.called, [])

    def test_frozen_input_mutation_rejects_even_before_a_new_preview(self):
        source = self.crash()
        row = load_json(source)["entries"][1]
        path = source.parent / row["casePath"]
        case = load_json(path)
        case["input"] += " changed"
        self.save(path, case)
        with self.assertRaisesRegex(ValueError, "input fingerprint mismatch"):
            plan_batch_resume(source)
        self.assertFalse((source.parent / CLAIM_NAME).exists())

    def test_saved_recording_classification_must_agree_with_fresh_inspection(self):
        source = self.crash()
        row = load_json(source)["entries"][0]
        path = source.parent / row["evaluationPath"]
        saved = load_json(path)
        saved["recording"]["outcome"] = "invalid"
        self.save(path, saved)
        plan = plan_batch_resume(source)
        self.assertFalse(plan["canResume"])
        self.assertIn("recording result", plan["blockedEntries"][0]["reason"])

    def test_stale_digest_and_cap_reject_before_claim_or_execution(self):
        source = self.crash()
        before = self.snapshot()
        for digest in (None, "0" * 64, "invalid"):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                resume_batch(source, self.outputs, expected_plan_sha256=digest)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            plan_batch_resume(source, max_samples=1)
        plan = plan_batch_resume(source, max_samples=2)
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.outputs.exists())

    def test_one_source_can_be_claimed_only_once(self):
        source = self.crash()
        plan = plan_batch_resume(source)
        resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.called.clear()
        second = plan_batch_resume(source)
        self.assertFalse(second["canResume"])
        with self.assertRaisesRegex(ValueError, "claim"):
            resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(self.called, [])

    def test_crash_after_claim_cannot_implicitly_launch_a_second_continuation(self):
        source = self.crash()
        plan = plan_batch_resume(source)
        with patch("dsh_eval.resume.run_batch", side_effect=SimulatedCrash), self.assertRaises(SimulatedCrash):
            resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertTrue((source.parent / CLAIM_NAME).is_file())
        self.assertFalse(plan_batch_resume(source)["canResume"])
        self.assertEqual(self.called, [])

    def test_source_checkpoint_change_invalidates_the_preview_before_claim(self):
        source = self.crash()
        plan = plan_batch_resume(source)
        saved = load_json(source)
        saved["startedAt"] = "2000-01-01T00:00:00+00:00"
        self.save(source, saved)
        with patch("dsh_eval.resume.uuid4", side_effect=AssertionError("must reject before allocating")):
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertFalse((source.parent / CLAIM_NAME).exists())

    def test_cli_preview_and_execution_keep_the_same_cap_and_digest(self):
        source = self.crash()
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--resume-batch", str(source), "--plan", "--max-samples", "2"])
        self.assertEqual(code, 0)
        plan = json.loads(output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--resume-batch", str(source), "--run", "--max-samples", "2",
                         "--expected-plan-sha256", plan["planFingerprint"]["sha256"], "--runs-root", str(self.outputs)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["newlyExecutedSummary"]["attempted"], 2)
        self.assertEqual(self.called, ["resume-two", "resume-three"])

    def test_live_scheduler_lock_blocks_preview_without_creating_files(self):
        source = self.crash()
        before = self.snapshot()
        with batch_lock(source.parent):
            with self.assertRaisesRegex(ValueError, "active or locked"):
                plan_batch_resume(source)
        self.assertEqual(self.snapshot(), before)

    def test_original_stop_policy_and_failed_results_are_preserved(self):
        wrong = self.cases["one"]
        next(row for row in wrong["assertions"] if row["type"] == "final_text")["equals"] = "wrong"
        self.save(self.directory / "one.json", wrong)
        source = self.crash()
        plan = plan_batch_resume(source)
        self.assertTrue(plan["canResume"])
        self.assertEqual(plan["reusedEntries"][0]["outcome"], "failed")
        result = resume_batch(source, self.outputs, expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["combinedSummary"]["outcomes"], {"passed": 2, "failed": 1, "unevaluable": 0})
        self.assertNotIn("resume-one", self.called)

    def test_stop_policy_failure_does_not_authorize_skipped_tasks(self):
        self.manifest["failurePolicy"] = "stop"
        wrong = self.cases["one"]
        next(row for row in wrong["assertions"] if row["type"] == "final_text")["equals"] = "wrong"
        self.save(self.directory / "one.json", wrong)
        self.save(self.path, self.manifest)
        result = run_batch(self.path, self.directory / "initial")
        self.source = Path(result["batchDirectory"]) / "batch-result.json"
        self.assertFalse(plan_batch_resume(self.source)["canResume"])

    def test_legacy_metadata_and_escaping_paths_reject(self):
        source = self.crash()
        saved = load_json(source)
        legacy = copy.deepcopy(saved)
        legacy.pop("resumeSupportVersion")
        self.save(source, legacy)
        with self.assertRaisesRegex(ValueError, "legacy"):
            plan_batch_resume(source)
        saved["entries"][1]["casePath"] = "../outside.json"
        self.save(source, saved)
        with self.assertRaisesRegex(ValueError, "position/path mismatch"):
            plan_batch_resume(source)

    def test_cli_preview_is_read_only_and_blocked_preview_returns_two(self):
        source = self.crash("unknown")
        before = self.snapshot()
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--resume-batch", str(source), "--plan"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["modelCalled"])
        self.assertEqual(self.snapshot(), before)
        for arguments in (["--resume-batch", str(source)], ["--resume-batch", str(source), "--plan", "--host-modules", "x"],
                          ["--resume-batch", str(source), "--run", "--evidence", "x"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)


class BatchLockProcessTests(unittest.TestCase):
    def test_kernel_releases_lock_when_the_owned_process_is_killed(self):
        with tempfile.TemporaryDirectory(prefix="dsh-batch-lock-") as temporary:
            directory = Path(temporary)
            script = ("from pathlib import Path\nimport sys,time\nfrom dsh_eval.batch_lock import batch_lock\n"
                      "directory=Path(sys.argv[1])\nwith batch_lock(directory,create=True):\n"
                      " (directory/'ready').write_text('ready')\n time.sleep(30)\n")
            child = subprocess.Popen([sys.executable, "-c", script, str(directory)], cwd=ROOT,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (directory / "ready").exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((directory / "ready").is_file())
                with self.assertRaisesRegex(ValueError, "active or locked"):
                    with batch_lock(directory):
                        self.fail("must not acquire another scheduler's lock")
                child.kill()
                child.wait(timeout=5)
                with batch_lock(directory):
                    pass
                self.assertEqual((directory / ".batch-execution.lock").read_bytes(), b"\0")
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
