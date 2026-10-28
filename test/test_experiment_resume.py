"""Synthetic experiment continuation preserves identities and prevents duplicate work."""
import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.batch import _checkpoint
from dsh_eval.batch_lock import batch_lock
from dsh_eval.evaluate import evaluate
from dsh_eval.experiment import run_experiment
from dsh_eval.experiment_resume import plan_experiment_resume
from dsh_eval import experiment_resume
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.resume import CLAIM_NAME, plan_batch_resume, resume_batch
from dsh_eval.runner import ROOT, run_case


class SimulatedCrash(BaseException):
    pass


class ExperimentResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-experiment-resume-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.manifest = {"experimentFormatVersion": 1, "experimentName": "resume matrix", "repetitions": 2,
                         "failurePolicy": "continue", "cases": [], "configurations": []}
        case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        case["configRef"].update(provider="synthetic", model="baseline")
        for entry_id in ("first", "second"):
            data = {**copy.deepcopy(case), "caseId": "resume-" + entry_id}
            self.save(self.directory / f"{entry_id}.json", data)
            self.manifest["cases"].append({"entryId": entry_id, "casePath": f"{entry_id}.json"})
        for config_id in ("baseline", "candidate"):
            self.manifest["configurations"].append({"configurationId": config_id,
                "configRef": {**case["configRef"], "model": config_id}})
        self.path = self.directory / "experiment.json"
        self.save(self.path, self.manifest)
        self.called = []
        for mock in (patch("dsh_eval.runner._prepare"),
                     patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js"),
                     patch("dsh_eval.batch.run_case", side_effect=self.synthetic_case)):
            mock.start()
            self.addCleanup(mock.stop)

    def save(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def synthetic_case(self, *args, **kwargs):
        result = run_case(*args, **kwargs)
        self.called.append(result["caseRunId"])
        evidence_path = Path(result["association"]["evidencePath"])
        evidence = load_json(evidence_path)
        evidence["source"] = "synthetic"
        self.save(evidence_path, evidence)
        fresh = evaluate(result["association"]["casePath"], evidence_path)
        self.save(evidence_path.parent / "evaluation.json", fresh)
        return fresh

    def crash(self, boundary="finished"):
        def checkpoint(directory, report):
            third = report["entries"][2]
            stop = (third["status"] == "running" if boundary == "unknown" else
                    report["entries"][1]["status"] == "finished" and third["status"] == "pending")
            snapshot = copy.deepcopy(report)
            if stop and boundary == "saved-evaluation":
                row = snapshot["entries"][1]
                row["status"] = "running"
                for key in ("evaluationPath", "evidencePath", "runtimeReport", "runDir", "runId", "sessionId", "configuration",
                            "executionStatus", "recordingOutcome", "assertionOutcome", "outcome", "source", "metrics"):
                    row[key] = None
            _checkpoint(directory, snapshot)
            if stop:
                self.batch_source = directory / "batch-result.json"
                self.source = directory.parents[1] / "experiment-result.json"
                raise SimulatedCrash

        with patch("dsh_eval.batch._checkpoint", side_effect=checkpoint), self.assertRaises(SimulatedCrash):
            run_experiment(self.path, self.directory / "outputs", max_samples=8)
        self.called.clear()
        return self.source

    def snapshot(self):
        return {path.relative_to(self.source.parent).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.source.parent.rglob("*") if path.is_file()}

    def test_interrupted_matrix_maps_case_configuration_and_repeat_without_side_effects(self):
        self.crash()
        before = self.snapshot()
        with ExitStack() as stack:
            for target in ("dsh_eval.experiment.run_batch", "dsh_eval.batch.run_case", "dsh_eval.resume.run_batch",
                           "dsh_eval.resume.uuid4", "dsh_eval.experiment.uuid4"):
                stack.enter_context(patch(target, side_effect=AssertionError("preflight must not schedule or allocate")))
            plan = plan_experiment_resume(self.source, max_samples=6)
        self.assertTrue(plan["eligibleForResume"])
        self.assertFalse(plan["modelCalled"])
        self.assertTrue(plan["executionSupported"])
        self.assertEqual(plan["counts"], {"original": 8, "reused": 2, "newSamples": 6, "blocked": 0})
        self.assertEqual(plan["planVerification"]["status"], "verified")
        self.assertEqual([(row["caseEntryId"], row["configurationId"], row["repeatIndex"]) for row in plan["samples"]],
                         [(case, config, repeat) for repeat in (1, 2) for case in ("first", "second")
                          for config in ("baseline", "candidate")])
        self.assertEqual([row["disposition"] for row in plan["samples"]], ["reuse"] * 2 + ["pending"] * 6)
        self.assertTrue(all(row["source"] == "synthetic" for row in plan["samples"][:2]))
        self.assertTrue(all(row["source"] is None and row["caseRunId"] is None for row in plan["samples"][2:]))
        self.assertEqual(plan["planFingerprint"], plan_experiment_resume(self.source, max_samples=6)["planFingerprint"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.called, [])

    def test_unknown_running_sample_blocks_the_entire_experiment(self):
        self.crash("unknown")
        plan = plan_experiment_resume(self.source)
        self.assertFalse(plan["eligibleForResume"])
        self.assertEqual(plan["counts"], {"original": 8, "reused": 2, "newSamples": 5, "blocked": 1})
        self.assertEqual(plan["samples"][2]["disposition"], "blocked")
        self.assertEqual(plan["samples"][2]["caseEntryId"], "second")

    def test_complete_evaluation_with_stale_checkpoint_is_reused(self):
        self.crash("saved-evaluation")
        plan = plan_experiment_resume(self.source)
        self.assertTrue(plan["eligibleForResume"])
        self.assertEqual(plan["samples"][1]["disposition"], "reuse")
        self.assertTrue(plan["samples"][1]["recoveredCheckpoint"])

    def test_original_files_are_not_reread_after_freezing(self):
        self.crash()
        self.save(self.path, {"invalid": True})
        self.save(self.directory / "second.json", {"invalid": True})
        self.assertTrue(plan_experiment_resume(self.source)["eligibleForResume"])

    def test_local_plugin_upgrade_still_blocks_continuation_preflight_and_execution(self):
        self.crash()
        plan = plan_experiment_resume(self.source, max_samples=6)
        before = self.snapshot()

        def upgraded_package(path):
            data = load_json(path)
            return {**data, "version": data["version"] + "-upgrade-test"} if path == ROOT / "package.json" else data

        with patch("dsh_eval.runner.load_json", side_effect=upgraded_package):
            with self.assertRaisesRegex(ValueError, "different recorder version"):
                plan_experiment_resume(self.source, max_samples=6)
            with self.assertRaisesRegex(ValueError, "different recorder version"):
                self.execute(plan)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.called, [])
        self.assertFalse((self.directory / "resumes").exists())

    def test_reordered_duplicate_or_wrong_repeat_sample_metadata_rejects(self):
        self.crash()
        saved = load_json(self.source)
        for mutate in (lambda data: data["samples"].reverse(),
                       lambda data: data["samples"][1].update(sampleId=data["samples"][0]["sampleId"]),
                       lambda data: data["samples"][0].update(repeatIndex=True),
                       lambda data: data["samples"][0].update(configurationId="candidate")):
            changed = copy.deepcopy(saved)
            mutate(changed)
            self.save(self.source, changed)
            with self.assertRaisesRegex(ValueError, "position/identity"):
                plan_experiment_resume(self.source)

    def test_original_snapshot_expansion_and_batch_input_must_agree(self):
        self.crash()
        root = self.source.parent
        saved = load_json(self.source)
        snapshot_path = root / saved["planInputPath"]
        snapshot = load_json(snapshot_path)
        snapshot["cases"][0]["input"] += " changed"
        original = snapshot_path.read_bytes()
        self.save(snapshot_path, snapshot)
        with self.assertRaises(ValueError):
            plan_experiment_resume(self.source)
        snapshot_path.write_bytes(original)
        expanded_case = root / "expanded/sample-000003.case.json"
        case = load_json(expanded_case)
        for mutation in ({"input": case["input"] + " changed"}, {"caseFormatVersion": 2.0}):
            self.save(expanded_case, {**case, **mutation})
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "original plan"):
                plan_experiment_resume(self.source)

    def test_legacy_binding_and_missing_actual_batch_are_rejected(self):
        self.crash()
        saved = load_json(self.source)
        legacy = copy.deepcopy(saved)
        legacy.pop("resumeSupportVersion")
        self.save(self.source, legacy)
        with self.assertRaisesRegex(ValueError, "legacy"):
            plan_experiment_resume(self.source)
        changed = copy.deepcopy(saved)
        changed["batchBinding"]["resultPath"] = "../outside/batch-result.json"
        self.save(self.source, changed)
        with self.assertRaisesRegex(ValueError, "binding path"):
            plan_experiment_resume(self.source)
        self.save(self.source, saved)
        self.batch_source.rename(self.batch_source.with_name("preserved-result.json"))
        with self.assertRaises(OSError):
            plan_experiment_resume(self.source)

    def test_source_batch_lock_prevents_preview(self):
        self.crash()
        before = self.snapshot()
        with batch_lock(self.batch_source.parent), self.assertRaisesRegex(ValueError, "active or locked"):
            plan_experiment_resume(self.source)
        with batch_lock(self.batch_source.parent), self.assertRaisesRegex(ValueError, "active or locked"):
            experiment_resume.resume_experiment(self.source, self.directory / "resumes", expected_plan_sha256="0" * 64)
        self.assertEqual(self.snapshot(), before)

    def test_bad_recording_is_classified_as_blocked_without_relabeling_source(self):
        self.crash()
        row = load_json(self.batch_source)["entries"][0]
        trace = next((self.batch_source.parent / row["runDir"]).glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-3])
        before = self.snapshot()
        plan = plan_experiment_resume(self.source)
        self.assertFalse(plan["eligibleForResume"])
        self.assertEqual(plan["samples"][0]["disposition"], "blocked")
        self.assertEqual(self.snapshot(), before)

    def test_cap_rejects_and_is_part_of_the_preview_digest(self):
        self.crash()
        with self.assertRaisesRegex(ValueError, "exceeds"):
            plan_experiment_resume(self.source, max_samples=5)
        for value in (True, 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan_experiment_resume(self.source, max_samples=value)
        self.assertNotEqual(plan_experiment_resume(self.source)["planFingerprint"],
                            plan_experiment_resume(self.source, max_samples=6)["planFingerprint"])

    def test_completed_experiment_stays_terminal_and_remains_reportable(self):
        result = run_experiment(self.path, self.directory / "outputs")
        self.source = Path(result["experimentDirectory"]) / "experiment-result.json"
        self.assertEqual(result["batchBinding"]["batchId"], result["batchId"])
        self.assertEqual(result["batchBinding"]["resultPath"], result["batchResultPath"])
        before = self.snapshot()
        plan = plan_experiment_resume(self.source)
        self.assertFalse(plan["eligibleForResume"])
        self.assertEqual(plan["counts"], {"original": 8, "reused": 8, "newSamples": 0, "blocked": 0})
        with self.assertRaisesRegex(ValueError, "No unstarted"):
            experiment_resume.resume_experiment(self.source, self.directory / "resumes",
                expected_plan_sha256=plan["planFingerprint"]["sha256"])
        report = generate_report(self.source, self.directory / "reports")
        self.assertEqual(report["planVerification"]["status"], "verified")
        self.assertEqual(self.snapshot(), before)

    def test_failed_stop_policy_remains_a_global_block(self):
        self.manifest["failurePolicy"] = "stop"
        self.save(self.path, self.manifest)
        case_path = self.directory / "first.json"
        case = load_json(case_path)
        next(item for item in case["assertions"] if item["type"] == "final_text")["equals"] = "wrong"
        self.save(case_path, case)
        result = run_experiment(self.path, self.directory / "outputs")
        self.source = Path(result["experimentDirectory"]) / "experiment-result.json"
        plan = plan_experiment_resume(self.source)
        self.assertFalse(plan["eligibleForResume"])
        self.assertEqual(plan["samples"][0]["outcome"], "failed")
        self.assertEqual(plan["counts"]["newSamples"], 7)
        self.assertTrue(any("failure policy" in reason for reason in plan["reasons"]))
        self.called.clear()
        with self.assertRaisesRegex(ValueError, "failure policy"):
            experiment_resume.resume_experiment(self.source, self.directory / "resumes",
                expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertEqual(self.called, [])
        self.assertFalse((self.directory / "resumes").exists())

    def test_real_cli_preview_and_invalid_execution_controls_do_not_schedule(self):
        self.crash()
        before = self.snapshot()
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--resume-experiment", str(self.source),
                                  "--plan", "--max-samples", "6"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertFalse(json.loads(process.stdout)["modelCalled"])
        for arguments in (["--resume-experiment", str(self.source), "--plan", "--expected-plan-sha256", "0" * 64],
                          ["--resume-experiment", str(self.source)],
                          ["--resume-experiment", str(self.source), "--plan", "--runs-root", "forbidden"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.called, [])

    def execute(self, plan=None, **kwargs):
        plan = plan or plan_experiment_resume(self.source, max_samples=6)
        return experiment_resume.resume_experiment(self.source, self.directory / "resumes", max_samples=6,
            expected_plan_sha256=plan["planFingerprint"]["sha256"].upper(), **kwargs)

    def test_execution_reuses_two_and_runs_six_with_shared_lock_and_original_evidence(self):
        self.crash()
        before = self.snapshot()
        plan = plan_experiment_resume(self.source, max_samples=6)
        original_runs = {row["caseRunId"] for row in plan["samples"][:2]}

        def locked_case(*args, **kwargs):
            with self.assertRaisesRegex(ValueError, "active or locked"):
                plan_batch_resume(self.batch_source)
            return self.synthetic_case(*args, **kwargs)

        with patch("dsh_eval.batch.run_case", side_effect=locked_case):
            result = self.execute(plan)
        self.assertEqual((result["status"], result["outcome"]), ("completed", "passed"))
        self.assertEqual(result["experimentResumeResultFormatVersion"], 1)
        self.assertEqual(result["samplePlan"], plan["samples"])
        self.assertEqual(result["counts"], plan["counts"])
        self.assertEqual(result["newlyExecutedSummary"]["planned"], 6)
        self.assertEqual(result["newlyExecutedSummary"]["sourceCounts"], {"synthetic": 6})
        self.assertEqual(len(self.called), 6)
        self.assertEqual(len(set(self.called)), 6)
        self.assertTrue(original_runs.isdisjoint(self.called))
        directory = Path(result["resumeDirectory"])
        child_path = directory / result["batchResumeResultPath"]
        child = load_json(child_path)
        batch = load_json(child_path.parent / child["batchResultPath"])
        self.assertEqual([row["entryId"] for row in batch["entries"]],
                         [row["sampleId"] for row in plan["samples"] if row["disposition"] == "pending"])
        self.assertEqual(child["combinedSummary"]["planned"], 8)
        self.assertEqual(child["combinedSummary"]["sourceCounts"], {"synthetic": 8})
        self.assertEqual(load_json(directory / "experiment-resume-result.json"), result)
        self.assertEqual(load_json(directory / "resume-plan.json"), plan)
        after = self.snapshot()
        self.assertTrue(all(after[name] == digest for name, digest in before.items()))
        claim_path = self.batch_source.parent / CLAIM_NAME
        self.assertEqual(set(after) - set(before), {claim_path.relative_to(self.source.parent).as_posix()})
        self.assertEqual(Path(load_json(claim_path)["resumeDirectory"]), child_path.parent)
        with self.assertRaisesRegex(ValueError, "claim"):
            resume_batch(self.batch_source, self.directory / "duplicate", expected_plan_sha256=child["planFingerprint"]["sha256"])
        with self.assertRaisesRegex(ValueError, "claim"):
            self.execute(plan)

    def test_invalid_digest_cap_or_changed_source_rejects_before_identity_or_output(self):
        self.crash()
        before = self.snapshot()
        plan = plan_experiment_resume(self.source, max_samples=6)
        with patch("dsh_eval.experiment_resume.uuid4", side_effect=AssertionError("must reject before allocating")):
            batch_digest = plan["batchPlanFingerprint"]["sha256"]
            for digest in (None, "invalid", "0" * 64, batch_digest):
                with self.subTest(digest=digest), self.assertRaises(ValueError):
                    experiment_resume.resume_experiment(self.source, self.directory / "resumes", max_samples=6,
                                                        expected_plan_sha256=digest)
            for cap in (True, 0, -1, 1.5):
                with self.subTest(cap=cap), self.assertRaises(ValueError):
                    experiment_resume.resume_experiment(self.source, self.directory / "resumes", max_samples=cap,
                                                        expected_plan_sha256=plan["planFingerprint"]["sha256"])
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                experiment_resume.resume_experiment(self.source, self.directory / "resumes",
                    expected_plan_sha256=plan["planFingerprint"]["sha256"])
            with self.assertRaisesRegex(ValueError, "exceeds"):
                experiment_resume.resume_experiment(self.source, self.directory / "resumes", max_samples=5,
                    expected_plan_sha256=plan["planFingerprint"]["sha256"])
            # A byte-only change is semantically valid but invalidates the approved preview.
            self.source.write_bytes(self.source.read_bytes() + b"\n")
            changed = self.snapshot()
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                self.execute(plan)
        self.assertEqual(self.snapshot(), changed)
        self.assertFalse((self.directory / "resumes").exists())
        self.assertEqual(self.called, [])
        self.assertEqual(set(changed), set(before))

    def test_unknown_execution_blocks_execution_before_claim(self):
        self.crash("unknown")
        plan = plan_experiment_resume(self.source, max_samples=6)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "cannot resume"):
            self.execute(plan)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.directory / "resumes").exists())
        self.assertEqual(self.called, [])

    def test_bad_recording_cannot_be_executed_using_an_old_preview(self):
        self.crash()
        plan = plan_experiment_resume(self.source, max_samples=6)
        row = load_json(self.batch_source)["entries"][0]
        trace = next((self.batch_source.parent / row["runDir"]).glob("*.jsonl"))
        trace.write_bytes(trace.read_bytes()[:-3])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "cannot resume"):
            self.execute(plan)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.directory / "resumes").exists())

    def test_batch_entry_point_claim_also_blocks_experiment_entry_point(self):
        self.crash()
        plan = plan_experiment_resume(self.source, max_samples=6)
        batch_plan = plan_batch_resume(self.batch_source, max_samples=6)
        resume_batch(self.batch_source, self.directory / "batch-resumes", max_samples=6,
                     expected_plan_sha256=batch_plan["planFingerprint"]["sha256"])
        self.called.clear()
        with self.assertRaisesRegex(ValueError, "claim"):
            self.execute(plan)
        self.assertEqual(self.called, [])
        self.assertFalse((self.directory / "resumes").exists())

    def test_crash_after_claim_preserves_explicit_child_path_and_blocks_retry(self):
        self.crash()
        plan = plan_experiment_resume(self.source, max_samples=6)
        with patch("dsh_eval.resume.run_batch", side_effect=SimulatedCrash), self.assertRaises(SimulatedCrash):
            self.execute(plan)
        directory = next((self.directory / "resumes").iterdir())
        result = load_json(directory / "experiment-resume-result.json")
        child_path = directory / result["batchResumeResultPath"]
        self.assertEqual(result["status"], "running")
        self.assertIsNone(result["outcome"])
        self.assertEqual(result["samplePlan"], plan["samples"])
        self.assertEqual(load_json(child_path)["status"], "running")
        self.assertEqual(Path(load_json(self.batch_source.parent / CLAIM_NAME)["resumeDirectory"]), child_path.parent)
        with self.assertRaisesRegex(ValueError, "claim"):
            self.execute(plan)
        self.assertEqual(self.called, [])

    def test_recovered_evaluation_is_not_executed_again(self):
        self.crash("saved-evaluation")
        result = self.execute()
        self.assertEqual(result["outcome"], "passed")
        self.assertTrue(result["samplePlan"][1]["recoveredCheckpoint"])
        self.assertEqual(len(self.called), 6)

    def test_reused_failure_is_preserved_when_all_new_tasks_pass(self):
        self.manifest["repetitions"] = 1
        self.save(self.path, self.manifest)
        case_path = self.directory / "first.json"
        case = load_json(case_path)
        next(item for item in case["assertions"] if item["type"] == "final_text")["equals"] = "wrong"
        self.save(case_path, case)
        self.crash()
        result = self.execute()
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["newlyExecutedSummary"]["outcomes"], {"passed": 2, "failed": 0, "unevaluable": 0})
        self.assertEqual([row["outcome"] for row in result["samplePlan"][:2]], ["failed", "failed"])
        self.assertEqual(len(self.called), 2)

    def test_new_runner_error_stops_remaining_tasks_without_claim_release(self):
        self.crash()
        plan = plan_experiment_resume(self.source, max_samples=6)
        with patch("dsh_eval.batch.run_case", side_effect=ValueError("synthetic runner error")):
            result = self.execute(plan)
        self.assertEqual((result["status"], result["outcome"]), ("error", "unevaluable"))
        summary = result["newlyExecutedSummary"]
        self.assertEqual((summary["attempted"], summary["errors"], summary["skipped"]), (1, 1, 5))
        self.assertEqual(summary["sourceCounts"], {"unknown": 6})
        with self.assertRaisesRegex(ValueError, "claim"):
            self.execute(plan)

    def test_cli_execution_returns_versioned_result(self):
        self.crash()
        plan = plan_experiment_resume(self.source, max_samples=6)
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--resume-experiment", str(self.source), "--run", "--max-samples", "6",
                         "--expected-plan-sha256", plan["planFingerprint"]["sha256"],
                         "--runs-root", str(self.directory / "resumes")])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["experimentResumeResultFormatVersion"], 1)
        self.assertEqual(len(self.called), 6)

    def test_real_cli_execution_with_wrong_digest_cannot_claim_or_schedule(self):
        self.crash()
        before = self.snapshot()
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--resume-experiment", str(self.source),
                                  "--run", "--expected-plan-sha256", "0" * 64,
                                  "--runs-root", str(self.directory / "resumes")],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["experimentResumeResultFormatVersion"], 1)
        self.assertEqual(result["outcome"], "unevaluable")
        self.assertIn("fingerprint mismatch", result["error"])
        self.assertEqual(process.stderr, "")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.directory / "resumes").exists())

    def test_blocked_cli_preview_has_versioned_json_and_exit_two(self):
        self.crash("unknown")
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--resume-experiment", str(self.source), "--plan"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["experimentResumePlanFormatVersion"], 1)
        self.assertFalse(json.loads(output.getvalue())["eligibleForResume"])
