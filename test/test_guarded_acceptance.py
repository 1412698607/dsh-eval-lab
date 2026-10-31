"""No-model regression for the bounded live acceptance experiment."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.formats import load_json
from dsh_eval.report import generate_report
from dsh_eval.runner import ROOT


MANIFEST = ROOT / "fixtures/evaluation/core/guarded-acceptance.experiment.json"


class GuardedAcceptanceTests(unittest.TestCase):
    def test_manifest_has_four_ordered_tasks_one_configuration_and_stop_policy(self):
        plan = plan_experiment(MANIFEST, max_samples=4)
        self.assertEqual(plan["counts"], {"cases": 2, "configurations": 1, "samples": 4})
        self.assertEqual((plan["repetitions"], plan["failurePolicy"], plan["maxSamples"]), (2, "stop", 4))
        self.assertEqual([(row["caseEntryId"], row["repeatIndex"]) for row in plan["samples"]],
                         [("direct-read", 1), ("retry-once", 1), ("direct-read", 2), ("retry-once", 2)])
        self.assertEqual(plan["configurations"], [{"configurationId": "deepseek-flash", "configRef": {
            "provider": "deepseek-official", "model": "deepseek-flash", "profile": "headless", "pluginVersion": "0.1.2"}}])
        self.assertTrue(plan["valid"])
        self.assertFalse(plan["modelCalled"])
        self.assertEqual(plan["estimates"], {"modelCalls": None, "totalTokens": None, "cost": None})
        for row in plan["samples"]:
            self.assertEqual(row["budget"], {"timeoutSeconds": 120})
            self.assertIsNone(row["recorderOverrides"])

    def test_bad_cap_and_fingerprint_reject_before_any_model_or_output(self):
        with tempfile.TemporaryDirectory(prefix="dsh-guarded-preflight-") as temporary:
            outputs = Path(temporary) / "outputs"
            with ExitStack() as stack:
                for target in ("dsh_eval.experiment.uuid4", "dsh_eval.experiment.run_batch", "subprocess.Popen"):
                    stack.enter_context(patch(target, side_effect=AssertionError("Must not execute")))
                with self.assertRaisesRegex(ValueError, "Planned sample count 4 exceeds max_samples 3"):
                    run_experiment(MANIFEST, outputs, max_samples=3)
                with self.assertRaisesRegex(ValueError, "Experiment plan fingerprint mismatch"):
                    run_experiment(MANIFEST, outputs, max_samples=4, expected_plan_sha256="0" * 64)
            self.assertFalse(outputs.exists())

    def test_synthetic_run_and_offline_report_preserve_the_complete_guarded_plan(self):
        plan = plan_experiment(MANIFEST, max_samples=4)
        with tempfile.TemporaryDirectory(prefix="dsh-guarded-flow-") as temporary:
            root = Path(temporary)
            # Only the adapter is synthetic; the real runner, bridge, recorder and inspect execute.
            with patch("dsh_eval.output_paths.check_output_root"), patch("dsh_eval.runner._prepare"), \
                    patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js"):
                saved = run_experiment(MANIFEST, root / "experiments", max_samples=4,
                                       expected_plan_sha256=plan["planFingerprint"]["sha256"])
            self.assertEqual((saved["status"], saved["outcome"]), ("completed", "passed"))
            base = Path(saved["experimentDirectory"])
            batch_path = base / saved["batchResultPath"]
            batch = load_json(batch_path)
            for sample, row in zip(saved["samples"], batch["entries"]):
                evidence_path = base / sample["evidencePath"]
                evidence = load_json(evidence_path)
                evidence["source"] = sample["source"] = row["source"] = "synthetic"
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            (base / "experiment-result.json").write_text(json.dumps(saved), encoding="utf-8")
            batch_path.write_text(json.dumps(batch), encoding="utf-8")
            before = {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in base.rglob("*") if p.is_file()}
            report = generate_report(base / "experiment-result.json", root / "reports")
            self.assertEqual(report["planVerification"]["status"], "verified")
            self.assertEqual(report["planVerification"]["fingerprint"], plan["planFingerprint"])
            self.assertEqual(report["verificationCounts"], {"verified": 4})
            self.assertEqual(report["summary"]["outcomes"]["passed"], 4)
            self.assertEqual(report["summary"]["sourceCounts"], {"synthetic": 4})
            self.assertEqual(report["comparisons"], [])
            self.assertEqual(before, {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in base.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
