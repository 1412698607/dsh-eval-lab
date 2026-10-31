"""Eight-task comparison preparation; all executed adapters are synthetic."""
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT


TEMPLATE = ROOT / "fixtures/evaluation/core/guarded-comparison.experiment.template.json"


class GuardedComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-comparison-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = load_json(TEMPLATE)
        for entry in self.manifest["cases"]:
            shutil.copyfile(TEMPLATE.parent / entry["casePath"], self.root / entry["casePath"])
        # Synthetic identifiers must never be offered as real provider/model recommendations.
        for config in self.manifest["configurations"]:
            config["configRef"].update(provider="synthetic", model=config["configurationId"])
        self.path = self.root / "experiment.json"
        self.save(self.path, self.manifest)

    def save(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def digest(self, directory):
        return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.rglob("*") if p.is_file()}

    def execute(self):
        plan = plan_experiment(self.path, max_samples=8)
        with patch("dsh_eval.output_paths.check_output_root"), patch("dsh_eval.runner._prepare"), \
                patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js"):
            saved = run_experiment(self.path, self.root / "experiments", max_samples=8,
                                   expected_plan_sha256=plan["planFingerprint"]["sha256"])
        base = Path(saved["experimentDirectory"])
        batch_path = base / saved["batchResultPath"]
        batch = load_json(batch_path)
        for sample, entry in zip(saved["samples"], batch["entries"]):
            if sample["evidencePath"]:
                sample["source"] = entry["source"] = "synthetic"
                for key in ("evidencePath", "evaluationPath"):
                    path = base / sample[key]
                    artifact = load_json(path)
                    artifact["source"] = "synthetic"
                    self.save(path, artifact)
        # Relabel after the real runner's checks; keep every archived source view consistent.
        saved["summary"]["sourceCounts"] = dict(Counter(s["source"] or "unknown" for s in saved["samples"]))
        for group in saved["groups"]:
            group["summary"]["sourceCounts"] = dict(Counter(
                s["source"] or "unknown" for s in saved["samples"]
                if s["caseEntryId"] == group["caseEntryId"] and s["configurationId"] == group["configurationId"]))
        self.save(base / "experiment-result.json", saved)
        self.save(batch_path, batch)
        return saved, base

    def test_unselected_template_rejects_before_output_or_process_creation(self):
        original = load_json(TEMPLATE)
        self.assertEqual(original["configurations"], [
            {"configurationId": "baseline", "configRef": {"provider": "deepseek-official", "model": "deepseek-flash",
                                                         "profile": "headless", "pluginVersion": "0.1.2"}},
            {"configurationId": "candidate", "configRef": {"provider": None, "model": None,
                                                          "profile": "headless", "pluginVersion": "0.1.2"}}])
        outputs = self.root / "forbidden"
        with ExitStack() as stack:
            for target in ("dsh_eval.experiment.uuid4", "dsh_eval.experiment.run_batch", "subprocess.Popen"):
                stack.enter_context(patch(target, side_effect=AssertionError("Must not execute")))
            for supplied in ({}, {"provider": "synthetic"}, {"model": "candidate"}):
                with self.subTest(supplied=supplied):
                    unselected = load_json(TEMPLATE)
                    unselected["configurations"][1]["configRef"].update(supplied)
                    path = self.root / "unselected.json"
                    self.save(path, unselected)
                    for operation in (lambda: plan_experiment(path, max_samples=8),
                                      lambda: run_experiment(path, outputs, max_samples=8)):
                        with self.assertRaisesRegex(ValueError, "Configuration values must be nonempty strings"):
                            operation()
        self.assertFalse(outputs.exists())

    def test_archived_synthetic_sources_agree_for_success_and_stop_results(self):
        for stop in (False, True):
            with self.subTest(stop=stop):
                if stop:
                    path = self.root / "direct-read.case.json"
                    case = load_json(path)
                    next(a for a in case["assertions"] if a["type"] == "final_text")["equals"] = "deliberate-failure"
                    self.save(path, case)
                saved, base = self.execute()
                batch = load_json(base / saved["batchResultPath"])
                for sample, entry in zip(saved["samples"], batch["entries"]):
                    if sample["status"] == "skipped":
                        self.assertIsNone(sample["source"])
                        self.assertIsNone(entry["source"])
                        continue
                    self.assertEqual((sample["source"], entry["source"]), ("synthetic", "synthetic"))
                    for key in ("evidencePath", "evaluationPath"):
                        self.assertEqual(load_json(base / sample[key])["source"], "synthetic")
                expected = {"synthetic": 1, "unknown": 7} if stop else {"synthetic": 8}
                self.assertEqual(saved["summary"]["sourceCounts"], expected)
                expected_groups = ([{"synthetic": 1, "unknown": 1}] + [{"unknown": 2}] * 3
                                   if stop else [{"synthetic": 2}] * 4)
                self.assertEqual([group["summary"]["sourceCounts"] for group in saved["groups"]], expected_groups)
                before = self.digest(base)
                report = generate_report(base / "experiment-result.json", self.root / "reports")
                self.assertEqual(report["savedSummary"]["sourceCounts"], report["summary"]["sourceCounts"])
                self.assertEqual(before, self.digest(base))

    def test_filled_plan_orders_eight_tasks_and_guards_candidate_changes(self):
        plan = plan_experiment(self.path, max_samples=8)
        self.assertEqual(plan["counts"], {"cases": 2, "configurations": 2, "samples": 8})
        self.assertEqual((plan["repetitions"], plan["failurePolicy"], plan["maxSamples"]), (2, "stop", 8))
        self.assertEqual([(s["caseEntryId"], s["configurationId"], s["repeatIndex"]) for s in plan["samples"]],
                         [(case, config, repeat) for repeat in (1, 2)
                          for case in ("direct-read", "retry-once") for config in ("baseline", "candidate")])
        self.assertFalse(plan["modelCalled"])
        self.assertEqual(plan["estimates"], {"modelCalls": None, "totalTokens": None, "cost": None})
        outputs = self.root / "forbidden"
        with patch("dsh_eval.experiment.run_batch", side_effect=AssertionError("Must not execute")):
            with self.assertRaisesRegex(ValueError, "Planned sample count 8 exceeds max_samples 7"):
                run_experiment(self.path, outputs, max_samples=7)
            self.manifest["configurations"][1]["configRef"]["model"] = "changed-candidate"
            self.save(self.path, self.manifest)
            with self.assertRaisesRegex(ValueError, "Experiment plan fingerprint mismatch"):
                run_experiment(self.path, outputs, max_samples=8,
                               expected_plan_sha256=plan["planFingerprint"]["sha256"])
        self.assertFalse(outputs.exists())

    def test_eight_synthetic_tasks_pair_by_case_repeat_and_preserve_missing_metrics(self):
        saved, base = self.execute()
        self.assertEqual((saved["status"], saved["outcome"]), ("completed", "passed"))
        for sample, elapsed in zip(saved["samples"], (1, 2, 10, 14, 3, 6, 20, 26)):
            runtime_path = base / sample["runtimeReport"]
            runtime = load_json(runtime_path)
            runtime["elapsedSeconds"] = elapsed  # Explicit deterministic inputs, not measured speed.
            self.save(runtime_path, runtime)
        before = self.digest(base)
        report = generate_report(base / "experiment-result.json", self.root / "reports")
        self.assertEqual(report["planVerification"]["status"], "verified")
        self.assertEqual(report["verificationCounts"], {"verified": 8})
        self.assertEqual(report["summary"]["sourceCounts"], {"synthetic": 8})
        self.assertEqual(report["summary"]["outcomes"]["passed"], 8)
        self.assertTrue(all(s["configurationMatch"] == "matched" for s in report["samples"]))
        self.assertEqual(len(report["groups"]), 4)
        self.assertTrue(all(g["summary"]["planned"] == 2 for g in report["groups"]))
        self.assertEqual(len(report["comparisons"]), 2)
        for comparison, difference in zip(report["comparisons"], (2, 5)):
            self.assertEqual((comparison["source"], comparison["plannedPairs"], comparison["pairedSamples"],
                              comparison["excludedPairs"], comparison["repeatIndices"]), ("synthetic", 2, 2, 0, [1, 2]))
            self.assertEqual(comparison["metrics"]["elapsedSeconds"]["meanDifference"], difference)
            for metric in ("totalTokens", "cost"):
                self.assertEqual(comparison["metrics"][metric]["missingPairs"], 2)
                self.assertIsNone(comparison["metrics"][metric]["meanDifference"])
        for key in ("caseRunId", "runId", "sessionId"):
            self.assertEqual(len({s[key] for s in saved["samples"]}), 8)
        self.assertEqual(before, self.digest(base))

    def test_bad_route_source_or_recording_excludes_only_the_affected_case_pair(self):
        saved, base = self.execute()
        for scenario in ("route", "source", "recording"):
            with self.subTest(scenario=scenario):
                copied = self.root / scenario
                shutil.copytree(base, copied)
                result_path = copied / "experiment-result.json"
                result = load_json(result_path)
                sample = result["samples"][1]  # Candidate/direct-read/repeat 1.
                evidence_path = copied / sample["evidencePath"]
                evidence = load_json(evidence_path)
                if scenario == "route":
                    batch_path = copied / result["batchResultPath"]
                    batch = load_json(batch_path)
                    wrong = {**evidence["configuration"], "model": "wrong-route"}
                    evidence["configuration"] = sample["configuration"] = batch["entries"][1]["configuration"] = wrong
                    self.save(batch_path, batch)
                    self.save(result_path, result)
                    self.save(evidence_path, evidence)
                elif scenario == "source":
                    # Deliberate conflicting declaration; this remains a synthetic negative test.
                    evidence["source"] = "live"
                    self.save(evidence_path, evidence)
                else:
                    trace = next((copied / sample["runDir"]).glob("*.jsonl"))
                    trace.write_bytes(trace.read_bytes()[:-1])
                before = self.digest(copied)
                report = generate_report(result_path, self.root / "reports")
                self.assertEqual(report["summary"]["planned"], 8)
                self.assertEqual(report["comparisons"][0]["repeatIndices"], [2])
                self.assertEqual(report["comparisons"][0]["excludedPairs"], 1)
                self.assertEqual(report["comparisons"][1]["repeatIndices"], [1, 2])
                self.assertEqual(report["planVerification"]["status"], "verified")
                if scenario == "route":
                    self.assertEqual(report["samples"][1]["configurationMatch"], "mismatched")
                elif scenario == "source":
                    self.assertEqual(report["samples"][1]["verification"], "rejected")
                    self.assertIsNone(report["samples"][1]["source"])
                else:
                    self.assertEqual(report["samples"][1]["recordingOutcome"], "invalid")
                    self.assertEqual(report["samples"][1]["outcome"], "unevaluable")
                self.assertEqual(before, self.digest(copied))

    def test_stop_policy_keeps_all_eight_planned_samples_and_unattempted_groups(self):
        case_path = self.root / "direct-read.case.json"
        case = load_json(case_path)
        next(a for a in case["assertions"] if a["type"] == "final_text")["equals"] = "deliberate-failure"
        self.save(case_path, case)
        saved, base = self.execute()
        report = generate_report(base / "experiment-result.json", self.root / "reports")
        self.assertEqual((saved["status"], report["summary"]["planned"], report["summary"]["attempted"],
                          report["summary"]["skipped"]), ("stopped", 8, 1, 7))
        self.assertEqual(report["summary"]["outcomes"], {"passed": 0, "failed": 1, "unevaluable": 0})
        self.assertTrue(all(group["summary"]["planned"] == 2 for group in report["groups"]))
        self.assertEqual([g["summary"]["attempted"] for g in report["groups"]], [1, 0, 0, 0])
        self.assertTrue(all(c["pairedSamples"] == 0 and c["excludedPairs"] == 2 for c in report["comparisons"]))
        self.assertTrue(all(c["rateDifferences"]["attemptedPassRate"] is None for c in report["comparisons"]))


if __name__ == "__main__":
    unittest.main()
