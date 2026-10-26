"""Experiment continuation previews preserve sample identities without scheduling."""
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
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT, run_case


class SimulatedCrash(BaseException):
    pass


class ExperimentResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-experiment-resume-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
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
        self.assertFalse(plan["executionSupported"])
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

    def test_real_cli_preview_and_forbidden_execution_do_not_schedule(self):
        self.crash()
        before = self.snapshot()
        process = subprocess.run([sys.executable, "-m", "dsh_eval", "--resume-experiment", str(self.source),
                                  "--plan", "--max-samples", "6"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertFalse(json.loads(process.stdout)["modelCalled"])
        for arguments in (["--resume-experiment", str(self.source), "--run"],
                          ["--resume-experiment", str(self.source)],
                          ["--resume-experiment", str(self.source), "--plan", "--runs-root", "forbidden"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(arguments)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.called, [])

    def test_blocked_cli_preview_has_versioned_json_and_exit_two(self):
        self.crash("unknown")
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--resume-experiment", str(self.source), "--plan"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["experimentResumePlanFormatVersion"], 1)
        self.assertFalse(json.loads(output.getvalue())["eligibleForResume"])
