"""Offline plan verification binds fingerprint inputs to the frozen experiment."""
import copy
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


class ReportPlanSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-plan-report-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.outputs = self.directory / "reports"
        case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        case["configRef"].update(provider="synthetic", model="first")
        self.cases = [case, {**copy.deepcopy(case), "caseId": "later-case", "recorder": {}}]
        for index, item in enumerate(self.cases):
            self.save(self.directory / f"case-{index}.json", item)
        self.manifest = {"experimentFormatVersion": 1, "experimentName": "计划快照", "repetitions": 1,
                         "failurePolicy": "continue",
                         "cases": [{"entryId": f"entry-{index}", "casePath": f"case-{index}.json"} for index in range(2)],
                         "configurations": [{"configurationId": "first", "configRef": case["configRef"]}]}
        self.source = self.directory / "experiment.json"
        self.save(self.source, self.manifest)
        self.preview = plan_experiment(self.source, max_samples=2)
        with patch("dsh_eval.runner._prepare"), patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js"):
            self.saved = run_experiment(self.source, self.directory / "experiments", max_samples=2,
                                        expected_plan_sha256=self.preview["planFingerprint"]["sha256"])
        self.assertEqual(self.saved["outcome"], "passed")
        self.base = Path(self.saved["experimentDirectory"])
        self.path = self.base / "experiment-result.json"
        self.snapshot_path = self.base / "plan-input.json"
        batch_path = self.base / self.saved["batchResultPath"]
        batch = load_json(batch_path)
        for sample, row in zip(self.saved["samples"], batch["entries"]):
            evidence_path = self.base / sample["evidencePath"]
            evidence = load_json(evidence_path)
            evidence["source"] = sample["source"] = row["source"] = "synthetic"
            self.save(evidence_path, evidence)
        self.save(self.path, self.saved)
        self.save(batch_path, batch)

    def save(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def digest(self, directory):
        return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.rglob("*") if path.is_file()}

    def report(self):
        return generate_report(self.path, self.outputs)

    def reject_before_inspect(self):
        with patch("dsh_eval.report.evaluate", side_effect=AssertionError("Must reject before inspect")), \
                self.assertRaises((ValueError, OSError)):
            self.report()
        self.assertFalse(self.outputs.exists())

    def test_new_snapshot_matches_preview_and_report_verifies_without_modifying_inputs(self):
        self.assertEqual(self.saved["planInputPath"], "plan-input.json")
        payload = load_json(self.snapshot_path)
        self.assertEqual(payload, {"version": 1, "manifest": self.manifest, "cases": self.cases,
                                   "maxSamples": 2, "order": "repeat-case-configuration"})
        before = self.digest(self.base)
        with patch("dsh_eval.experiment.run_batch", side_effect=AssertionError("Report must not execute tasks")):
            result = self.report()
        self.assertEqual(result["planVerification"], {"status": "verified", "fingerprint": self.preview["planFingerprint"],
                         "expectedPlanSha256": self.preview["planFingerprint"]["sha256"],
                         "inputPath": "plan-input.json", "reason": None})
        self.assertEqual(result["summary"]["outcomes"]["passed"], 2)
        self.assertEqual(self.digest(self.base), before)
        markdown = (Path(result["reportDirectory"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("计划指纹复核：verified", markdown)

    def test_report_works_after_relocation_without_original_sources(self):
        relocated = self.directory / "relocated"
        shutil.copytree(self.base, relocated)
        self.source.unlink()
        for index in range(2):
            (self.directory / f"case-{index}.json").unlink()
        before = self.digest(relocated)
        result = generate_report(relocated / "experiment-result.json", self.outputs)
        self.assertEqual(result["planVerification"]["status"], "verified")
        self.assertEqual(result["summary"]["outcomes"]["passed"], 2)
        self.assertEqual(self.digest(relocated), before)

    def test_legacy_results_without_snapshot_remain_explicitly_unverified(self):
        original = copy.deepcopy(self.saved)
        for old_metadata in (True, False):
            self.saved = copy.deepcopy(original)
            self.saved.pop("planInputPath", None)
            if not old_metadata:
                for key in ("planFingerprint", "expectedPlanSha256", "maxSamples"):
                    self.saved.pop(key, None)
            self.save(self.path, self.saved)
            with self.subTest(old_metadata=old_metadata):
                result = self.report()
                self.assertEqual(result["planVerification"]["status"], "unverified")
                self.assertIn("No saved plan input snapshot", result["planVerification"]["reason"])
                self.assertEqual(result["summary"]["outcomes"]["passed"], 2)
                markdown = (Path(result["reportDirectory"]) / "report.md").read_text(encoding="utf-8")
                self.assertIn("计划指纹复核：unverified", markdown)

    def test_declared_missing_snapshot_is_rejected_before_inspect_or_output(self):
        self.snapshot_path.unlink()
        self.reject_before_inspect()

    def test_bad_payload_versions_shapes_order_and_limits_are_rejected(self):
        original = load_json(self.snapshot_path)
        changes = ({"version": True}, {"version": 2}, {"extra": 1}, {"order": "other"},
                   {"maxSamples": True}, {"maxSamples": 1}, {"cases": []}, {"cases": {}},
                   {"cases": [self.cases[0], {"invalid": True}]})
        for change in changes:
            self.save(self.snapshot_path, {**original, **change})
            with self.subTest(change=change):
                self.reject_before_inspect()

    def test_changed_snapshot_and_recomputed_hash_still_must_match_frozen_inputs(self):
        original = load_json(self.snapshot_path)
        original_saved = copy.deepcopy(self.saved)
        for part in ("case", "manifest"):
            payload = copy.deepcopy(original)
            if part == "case":
                payload["cases"][1]["input"] = "changed task with the same count"
            else:
                payload["manifest"]["failurePolicy"] = "stop"
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.saved = {**original_saved, "planFingerprint": {"version": 1, "sha256": digest},
                          "expectedPlanSha256": digest}
            self.save(self.path, self.saved)
            self.save(self.snapshot_path, payload)
            with self.subTest(part=part):
                self.reject_before_inspect()

    def test_result_metadata_mismatch_and_unsafe_snapshot_paths_are_rejected(self):
        original = copy.deepcopy(self.saved)
        for change in ({"planFingerprint": {"version": True, "sha256": "a" * 64}},
                       {"planFingerprint": {"version": 1, "sha256": "a" * 64}},
                       {"expectedPlanSha256": "b" * 64}, {"expectedPlanSha256": True}, {"maxSamples": 3},
                       {"planInputPath": "../plan-input.json"}, {"planInputPath": str(self.snapshot_path)},
                       {"planInputPath": ""}):
            self.saved = {**original, **change}
            self.save(self.path, self.saved)
            with self.subTest(change=change):
                self.reject_before_inspect()

    def test_verified_plan_does_not_turn_bad_recording_into_task_success(self):
        sample = self.saved["samples"][0]
        trace = next((self.base / sample["runDir"]).glob("*.jsonl"))
        trace.write_bytes(b"broken\n")
        result = self.report()
        self.assertEqual(result["planVerification"]["status"], "verified")
        self.assertEqual(result["summary"]["outcomes"]["passed"], 1)
        self.assertEqual(result["summary"]["outcomes"]["unevaluable"], 1)

    def test_huge_repeat_count_is_rejected_before_enumerating_new_or_legacy_plans(self):
        manifest_path = self.base / self.saved["manifestPath"]
        manifest = load_json(manifest_path)
        manifest["repetitions"] = self.saved["repetitions"] = 10 ** 100
        self.save(manifest_path, manifest)
        for legacy in (False, True):
            if legacy:
                for key in ("planInputPath", "planFingerprint", "expectedPlanSha256", "maxSamples"):
                    self.saved.pop(key, None)
            self.save(self.path, self.saved)
            with self.subTest(legacy=legacy), \
                    patch("dsh_eval.report.range", side_effect=AssertionError("Must reject before enumerating"), create=True), \
                    patch("dsh_eval.report.evaluate", side_effect=AssertionError("Must not inspect")), \
                    self.assertRaisesRegex(ValueError, "Experiment sample count mismatch"):
                self.report()
            self.assertFalse(self.outputs.exists())

    def test_invalid_saved_sample_containers_are_rejected_before_enumeration(self):
        batch_path = self.base / self.saved["batchResultPath"]
        batch = load_json(batch_path)
        for samples, entries in ((None, batch["entries"]), ({}, batch["entries"]), ([], batch["entries"]),
                                 (self.saved["samples"], None), (self.saved["samples"], {}), (self.saved["samples"], [])):
            self.save(self.path, {**self.saved, "samples": samples})
            self.save(batch_path, {**batch, "entries": entries})
            with self.subTest(samples=type(samples).__name__, entries=type(entries).__name__), \
                    patch("dsh_eval.report.range", side_effect=AssertionError("Must reject before enumerating"), create=True), \
                    self.assertRaisesRegex(ValueError, "Experiment sample count mismatch"):
                self.report()
            self.assertFalse(self.outputs.exists())


if __name__ == "__main__":
    unittest.main()
