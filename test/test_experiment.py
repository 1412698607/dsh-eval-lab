import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval.batch import run_batch
from dsh_eval.experiment import plan_experiment, run_experiment
from dsh_eval.formats import load_json, validate_experiment
from dsh_eval.runner import ROOT


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dsh-experiment-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.outputs = self.directory / "outputs"
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["configRef"].update(provider="synthetic", model="first")
        self.case_path = self.save("case.json", self.case)
        self.manifest = {"experimentFormatVersion": 1, "experimentName": "test", "repetitions": 2,
                         "failurePolicy": "continue", "cases": [{"entryId": "retry", "casePath": "case.json"}],
                         "configurations": [{"configurationId": "first", "configRef": self.case["configRef"]}]}
        self.path = self.directory / "experiment.json"
        preparation = patch("dsh_eval.runner._prepare")
        adapter = patch("dsh_eval.runner.ADAPTER", ROOT / "scripts/fixtures/batch-adapter.js")
        preparation.start()
        adapter.start()
        self.addCleanup(preparation.stop)
        self.addCleanup(adapter.stop)

    def save(self, name, data):
        path = self.directory / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def run_experiment(self, **options):
        self.save("experiment.json", self.manifest)
        return run_experiment(self.path, self.outputs, **options)

    def test_format_rejects_ambiguous_counts_configs_and_paths(self):
        self.assertIs(validate_experiment(self.manifest), self.manifest)
        for change in ({"experimentFormatVersion": True}, {"experimentFormatVersion": 2}, {"repetitions": True},
                       {"repetitions": 0}, {"repetitions": -1}, {"repetitions": 1.5}, {"configurations": []},
                       {"configurations": self.manifest["configurations"] * 2}, {"cases": []}, {"typo": 1},
                       {"cases": [{"entryId": "a", "casePath": "C:/x.json"}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_experiment({**self.manifest, **change})

    def test_preflight_checks_all_cases_and_configuration_overrides_before_running(self):
        invalid = copy.deepcopy(self.manifest["configurations"][0])
        invalid["configurationId"] = "unsupported"
        invalid["configRef"]["profile"] = "web"
        self.manifest["configurations"].append(invalid)
        with patch("dsh_eval.experiment.run_batch") as batch, self.assertRaises(ValueError):
            self.run_experiment()
        batch.assert_not_called()
        self.assertFalse(self.outputs.exists())
        self.manifest["configurations"].pop()
        self.save("invalid.json", {"invalid": True})
        self.manifest["cases"].append({"entryId": "later", "casePath": "invalid.json"})
        with patch("dsh_eval.experiment.run_batch") as batch, self.assertRaises(ValueError):
            self.run_experiment()
        batch.assert_not_called()

    def test_repeats_configs_and_saved_inputs_remain_linked_and_isolated(self):
        config = copy.deepcopy(self.manifest["configurations"][0])
        config["configurationId"] = "second"
        config["configRef"]["model"] = "second"
        self.manifest["configurations"].append(config)
        self.case["recorder"] = {"maxPendingBytes": 4194304}
        self.save("case.json", self.case)
        preview = plan_experiment(self.save("experiment.json", self.manifest))
        report = self.run_experiment()
        self.assertEqual((report["status"], report["outcome"]), ("completed", "passed"))
        rows = report["samples"]
        self.assertEqual([(row["repeatIndex"], row["configurationId"]) for row in rows],
                         [(1, "first"), (1, "second"), (2, "first"), (2, "second")])
        for key in ("caseRunId", "runId", "sessionId"):
            self.assertEqual(len({row[key] for row in rows}), 4)
        base = Path(report["experimentDirectory"])
        self.assertEqual(preview["counts"]["samples"], len(rows))
        for planned, row in zip(preview["samples"], rows):
            for key in ("sampleId", "caseEntryId", "caseId", "configurationId", "repeatIndex", "requestedConfiguration"):
                self.assertEqual(planned[key], row[key])
            expanded = load_json(base / f"expanded/{row['sampleId']}.case.json")
            self.assertEqual(expanded["configRef"], planned["requestedConfiguration"])
            self.assertEqual(expanded["budget"], planned["budget"])
            self.assertEqual(expanded["recorder"], planned["recorderOverrides"])
        self.assertEqual(load_json(base / "experiment-result.json"), report)
        self.assertTrue((base / report["batchResultPath"]).is_file())
        for row in rows:
            result = load_json(base / row["evaluationPath"])
            self.assertEqual(result["caseRunId"], row["caseRunId"])
            self.assertEqual(result["batchId"], report["batchId"])
            self.assertEqual(row["configuration"]["model"], row["configurationId"])
            self.assertEqual(row["configurationMatch"], "matched")
            self.assertEqual((row["metrics"]["toolCalls"], row["metrics"]["modelCalls"]), (2, 1))
            self.assertGreaterEqual(row["metrics"]["elapsedSeconds"], 0)
            self.assertIsNone(row["metrics"]["inputTokens"])
        self.assertEqual([group["summary"]["planned"] for group in report["groups"]], [2, 2])
        self.assertEqual(report["summary"]["metrics"]["inputTokens"]["missingSamples"], 4)
        original = (base / "experiment-result.json").read_bytes()
        repeated = run_experiment(base / "experiment.json", self.outputs)
        self.assertNotEqual(report["experimentId"], repeated["experimentId"])
        self.assertEqual(repeated["outcome"], "passed")
        self.assertEqual((base / "experiment-result.json").read_bytes(), original)

    def test_original_inputs_are_frozen_before_batch_starts(self):
        def edit_original(*args, **kwargs):
            self.save("case.json", {"invalid": True})
            self.save("experiment.json", {"invalid": True})
            return run_batch(*args, **kwargs)
        with patch("dsh_eval.experiment.run_batch", side_effect=edit_original):
            report = self.run_experiment()
        self.assertEqual(report["outcome"], "passed")

    def test_failed_and_skipped_trials_keep_explicit_denominators(self):
        next(item for item in self.case["assertions"] if item["type"] == "final_text")["equals"] = "wrong"
        self.save("case.json", self.case)
        for policy, attempted, skipped in (("continue", 2, 0), ("stop", 1, 1)):
            with self.subTest(policy=policy):
                self.manifest["failurePolicy"] = policy
                report = self.run_experiment()
                summary = report["summary"]
                self.assertEqual(report["outcome"], "failed")
                self.assertEqual((summary["planned"], summary["attempted"], summary["skipped"]), (2, attempted, skipped))
                self.assertEqual(summary["evaluablePassRate"], {"numerator": 0, "denominator": attempted, "value": 0})
                self.assertEqual(summary["metrics"]["elapsedSeconds"]["missingSamples"], skipped)

    def test_cancelled_trials_and_startup_errors_remain_unevaluable(self):
        self.case["input"] = "WAIT_FOR_CANCEL"
        self.save("case.json", self.case)
        report = self.run_experiment(cancel_after_stream=True)
        self.assertEqual(report["summary"]["executionStatusCounts"], {"cancelled": 2})
        self.assertEqual(report["summary"]["outcomes"]["unevaluable"], 2)
        self.assertIsNone(report["summary"]["evaluablePassRate"]["value"])
        with patch("dsh_eval.runner._prepare", side_effect=ValueError("no host")):
            report = self.run_experiment()
        self.assertEqual(report["summary"]["executionStatusCounts"], {"runtime_error": 2})
        self.assertEqual(report["summary"]["configurationMatchCounts"], {"unknown": 2})
        self.assertEqual(report["summary"]["metrics"]["modelCalls"]["observedSamples"], 0)

    def test_interrupt_stops_all_remaining_repeats(self):
        with patch("dsh_eval.runner._prepare", side_effect=KeyboardInterrupt):
            report = self.run_experiment()
        self.assertEqual((report["status"], report["stopReason"]), ("interrupted", "user_interrupt"))
        self.assertEqual(report["summary"]["skipped"], 1)
        self.assertIsNone(report["samples"][1]["caseRunId"])

    def test_mismatched_batch_associations_are_rejected(self):
        def wrong_batch(*args, **kwargs):
            result = run_batch(*args, **kwargs)
            result["entries"][0]["entryId"] = "wrong-sample"
            return result
        with patch("dsh_eval.experiment.run_batch", side_effect=wrong_batch), self.assertRaises(ValueError):
            self.run_experiment()
        saved = load_json(next(self.outputs.glob("*/experiment-result.json")))
        self.assertEqual(saved["status"], "running")
        self.assertIsNone(saved["outcome"])

    def test_cli_requires_run_and_preserves_result_exit_codes(self):
        self.save("experiment.json", self.manifest)
        for args in (["--experiment", str(self.path)], ["--experiment", str(self.path), "--case", "x"],
                     ["--experiment", str(self.path), "--run", "--output", "x"],
                     ["--experiment", str(self.path), "--run", "--evidence", "x"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)
        for outcome, expected in (("passed", 0), ("failed", 1), ("unevaluable", 2)):
            with patch("dsh_eval.experiment.run_experiment", return_value={"experimentResultFormatVersion": 1, "outcome": outcome}), \
                    redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--experiment", str(self.path), "--run"]), expected)
            self.assertEqual(json.loads(output.getvalue())["experimentResultFormatVersion"], 1)
        self.save("experiment.json", {"invalid": True})
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--experiment", str(self.path), "--run"]), 2)
        self.assertIn("error", json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
