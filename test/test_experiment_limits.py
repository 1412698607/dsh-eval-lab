"""Optional experiment sample caps reject oversized plans before execution or expansion."""
import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dsh_eval.__main__ import main
from dsh_eval import experiment
from dsh_eval.formats import load_json
from dsh_eval.runner import ROOT


class ExperimentLimitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-sample-limit-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.outputs = self.directory / "outputs"
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["configRef"].update(provider="unavailable-provider", model="unavailable-model")
        self.save("case.json", self.case)
        self.manifest = {"experimentFormatVersion": 1, "experimentName": "任务上限", "repetitions": 3,
                         "failurePolicy": "continue",
                         "cases": [{"entryId": name, "casePath": "case.json"} for name in ("one", "two")],
                         "configurations": [{"configurationId": name, "configRef": copy.deepcopy(self.case["configRef"])}
                                            for name in ("first", "second")]}
        self.path = self.save("experiment.json", self.manifest)

    def save(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def snapshot(self):
        return {path.relative_to(self.directory).as_posix(): path.read_bytes()
                for path in self.directory.rglob("*") if path.is_file()}

    def test_count_includes_all_entries_configurations_and_repetitions_with_inclusive_limit(self):
        before = self.snapshot()
        for limit in (None, 12, 13):
            with self.subTest(limit=limit):
                result = experiment.plan_experiment(self.path, max_samples=limit)
                self.assertEqual(result["counts"], {"cases": 2, "configurations": 2, "samples": 12})
                self.assertEqual(len(result["samples"]), 12)
                self.assertEqual(result["maxSamples"], limit)
                self.assertEqual(result["estimates"], {"modelCalls": None, "totalTokens": None, "cost": None})
        self.assertEqual(experiment.plan_experiment(self.path)["maxSamples"], None)
        self.assertEqual(self.snapshot(), before)

    def test_over_limit_rejects_before_case_reads_expansion_identifiers_and_output(self):
        self.manifest["cases"][1]["casePath"] = "not-present.json"
        self.save("experiment.json", self.manifest)
        before = self.snapshot()
        for mode in ("plan", "run"):
            with self.subTest(mode=mode), ExitStack() as stack:
                reader = stack.enter_context(patch("dsh_eval.experiment.load_json", wraps=load_json))
                for target in ("dsh_eval.experiment._expand_samples", "dsh_eval.experiment.run_batch",
                               "dsh_eval.experiment.uuid4", "dsh_eval.runner._prepare", "subprocess.Popen"):
                    stack.enter_context(patch(target, side_effect=AssertionError(f"Limit must precede {target}")))
                with self.assertRaisesRegex(ValueError, "Planned sample count 12 exceeds max_samples 11"):
                    if mode == "plan":
                        experiment.plan_experiment(self.path, max_samples=11)
                    else:
                        experiment.run_experiment(self.path, self.outputs, max_samples=11)
                reader.assert_called_once_with(self.path.resolve())
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(self.outputs.exists())

    def test_huge_repeat_count_is_rejected_without_enumerating_samples(self):
        self.manifest["repetitions"] = 10 ** 100
        self.save("experiment.json", self.manifest)
        with patch("dsh_eval.experiment._expand_samples", side_effect=AssertionError("Must not enumerate")):
            for function in (experiment.plan_experiment, experiment.run_experiment):
                with self.subTest(function=function.__name__), self.assertRaisesRegex(ValueError, "exceeds max_samples 10"):
                    function(self.path, max_samples=10)

    def test_run_rechecks_current_inputs_after_a_successful_preview(self):
        preview = experiment.plan_experiment(self.path, max_samples=12)
        self.assertEqual(preview["counts"]["samples"], 12)
        self.manifest["repetitions"] = 4
        self.save("experiment.json", self.manifest)
        before = self.snapshot()
        with patch("dsh_eval.experiment.run_batch", side_effect=AssertionError("Must not execute")), \
                self.assertRaisesRegex(ValueError, "Planned sample count 16 exceeds max_samples 12"):
            experiment.run_experiment(self.path, self.outputs, max_samples=12)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.outputs.exists())

    def test_api_rejects_nonpositive_boolean_and_noninteger_limits(self):
        before = self.snapshot()
        for value in (0, -1, True, False, 1.5, "12", {}, []):
            for function in (experiment.plan_experiment, experiment.run_experiment):
                with self.subTest(value=value, function=function.__name__), \
                        patch("dsh_eval.experiment.load_json", side_effect=AssertionError("Must validate cap first")), \
                        self.assertRaisesRegex(ValueError, "max_samples must be a positive integer"):
                    function(self.path, max_samples=value)
        self.assertEqual(self.snapshot(), before)

    def test_allowed_count_still_validates_later_cases_and_configurations(self):
        invalid = copy.deepcopy(self.manifest)
        invalid["configurations"][1]["configRef"]["profile"] = "web"
        self.save("bad-case.json", {"invalid": True})
        missing_case = copy.deepcopy(self.manifest)
        missing_case["cases"][1]["casePath"] = "bad-case.json"
        for manifest in (invalid, missing_case):
            self.save("experiment.json", manifest)
            for mode in ("plan", "run"):
                with self.subTest(mode=mode, manifest=manifest), \
                        patch("dsh_eval.experiment.run_batch", side_effect=AssertionError("Must not execute")), \
                        self.assertRaises(ValueError):
                    if mode == "plan":
                        experiment.plan_experiment(self.path, max_samples=12)
                    else:
                        experiment.run_experiment(self.path, self.outputs, max_samples=12)
                self.assertFalse(self.outputs.exists())

    def test_cli_rejects_invalid_caps_and_unrelated_modes(self):
        invalid = [["--experiment", str(self.path), "--plan", "--max-samples", value]
                   for value in ("0", "-1", "1.5", "True", "")]
        invalid.append(["--experiment", str(self.path), "--plan", "--max-samples"])
        for selection in (["--case", "x", "--run"], ["--case", "x", "--evidence", "x"],
                          ["--batch", "x", "--run"], ["--report", "x"], ["--browse"],
                          ["--experiment", str(self.path)]):
            invalid.append([*selection, "--max-samples", "12"])
        for args in invalid:
            with self.subTest(args=args), redirect_stdout(io.StringIO()) as output, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.getvalue(), "")

    def test_cli_passes_cap_to_plan_and_run(self):
        for mode in ("plan", "run"):
            result = ({"experimentPlanFormatVersion": 1, "valid": True, "modelCalled": False} if mode == "plan" else
                      {"experimentResultFormatVersion": 1, "outcome": "passed"})
            with self.subTest(mode=mode), patch(f"dsh_eval.experiment.{mode}_experiment", return_value=result) as function, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--experiment", str(self.path), f"--{mode}", "--max-samples", "12"]), 0)
            self.assertEqual(function.call_args.kwargs["max_samples"], 12)

    def test_real_cli_cap_boundary_and_utf8_errors_leave_no_outputs(self):
        before = self.snapshot()
        for mode, limit, expected in (("plan", 12, 0), ("plan", 11, 2), ("run", 11, 2)):
            args = [sys.executable, "-m", "dsh_eval", "--experiment", str(self.path), f"--{mode}",
                    "--max-samples", str(limit)]
            if mode == "run":
                args.extend(["--runs-root", str(self.outputs)])
            with self.subTest(mode=mode, limit=limit):
                result = subprocess.run(args, cwd=ROOT, capture_output=True, check=False)
                self.assertEqual(result.returncode, expected, result.stderr.decode("utf-8", errors="replace"))
                self.assertEqual(result.stderr, b"")
                report = json.loads(result.stdout.decode("utf-8"))
                if expected == 0:
                    self.assertEqual(report["experimentName"], "任务上限")
                    self.assertEqual(report["maxSamples"], 12)
                else:
                    self.assertIn("Planned sample count 12 exceeds max_samples 11", report["error"])
                    if mode == "plan":
                        self.assertFalse(report["valid"])
                        self.assertFalse(report["modelCalled"])
                        self.assertNotIn("outcome", report)
                    else:
                        self.assertEqual(report["outcome"], "unevaluable")
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.outputs.exists())


if __name__ == "__main__":
    unittest.main()
