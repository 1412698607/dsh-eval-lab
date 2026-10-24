"""Offline experiment preflight: shared ordering, explicit unknowns and no execution."""
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


class ExperimentPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-plan-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.case = load_json(ROOT / "fixtures/evaluation/retry-read.case.json")
        self.case["configRef"].update(provider="unavailable-provider", model="unavailable-model")
        self.save("case.json", self.case)
        self.manifest = {"experimentFormatVersion": 1, "experimentName": "预检", "repetitions": 2,
                         "failurePolicy": "continue", "cases": [{"entryId": "retry", "casePath": "case.json"}],
                         "configurations": [{"configurationId": "first", "configRef": self.case["configRef"]}]}
        self.path = self.save("experiment.json", self.manifest)

    def save(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def snapshot(self):
        return {path.relative_to(self.directory).as_posix(): path.read_bytes()
                for path in self.directory.rglob("*") if path.is_file()}

    def test_sixty_tasks_have_exact_order_counts_and_unknown_estimates(self):
        self.manifest.update(repetitions=3, failurePolicy="stop", cases=[])
        config = copy.deepcopy(self.manifest["configurations"][0])
        config.update(configurationId="second")
        config["configRef"]["model"] = "other-unavailable-model"
        self.manifest["configurations"].append(config)
        for index in range(10):
            case = copy.deepcopy(self.case)
            case["caseId"] = f"case-{index}"
            case["budget"]["timeoutSeconds"] = index + 1
            case["recorder"] = {"maxEventBytes": 2048 + index}
            path = f"case-{index}.json"
            self.save(path, case)
            self.manifest["cases"].append({"entryId": f"entry-{index}", "casePath": path})
        self.save("experiment.json", self.manifest)
        report = experiment.plan_experiment(self.path)
        self.assertEqual(report["counts"], {"cases": 10, "configurations": 2, "samples": 60})
        self.assertEqual(report["order"], "repeat-case-configuration")
        self.assertEqual((report["repetitions"], report["failurePolicy"]), (3, "stop"))
        self.assertEqual(report["estimates"], {"modelCalls": None, "totalTokens": None, "cost": None})
        self.assertEqual(len(report["samples"]), 60)
        for offset, row in enumerate(report["samples"]):
            case_index = (offset % 20) // 2
            self.assertEqual((row["sampleId"], row["repeatIndex"], row["caseEntryId"], row["caseId"]),
                             (f"sample-{offset + 1:06}", offset // 20 + 1, f"entry-{case_index}", f"case-{case_index}"))
            config = self.manifest["configurations"][offset % 2]
            self.assertEqual(row["configurationId"], config["configurationId"])
            self.assertEqual(row["requestedConfiguration"], config["configRef"])
            self.assertEqual(row["budget"], {"timeoutSeconds": case_index + 1})
            self.assertEqual(row["recorderOverrides"], {"maxEventBytes": 2048 + case_index})

    def test_preflight_is_read_only_and_never_reaches_runtime_or_identifiers(self):
        before = self.snapshot()
        with ExitStack() as stack:
            for target in ("dsh_eval.experiment.run_batch", "dsh_eval.runner.run_case", "dsh_eval.runner._prepare",
                           "dsh_eval.runner.prepare_workspace", "subprocess.Popen", "dsh_eval.experiment.uuid4"):
                stack.enter_context(patch(target, side_effect=AssertionError(f"Plan must not call {target}")))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--experiment", str(self.path), "--plan"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual((report["experimentPlanFormatVersion"], report["valid"], report["modelCalled"]), (1, True, False))
        self.assertEqual(report["sourceManifest"], str(self.path.resolve()))
        for key in ("outcome", "status", "experimentId", "batchId", "caseRunId", "runId", "sessionId"):
            self.assertNotIn(key, report)
            for row in report["samples"]:
                self.assertNotIn(key, row)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({path.name for path in self.directory.iterdir()}, {"case.json", "experiment.json"})

    def test_recorder_declarations_preserve_omitted_empty_partial_and_explicit_values(self):
        for declaration in (None, {}, {"maxPendingBytes": 8192}, {"maxEventBytes": 1048576, "maxPendingBytes": 16777216}):
            with self.subTest(declaration=declaration):
                case = copy.deepcopy(self.case)
                if declaration is not None:
                    case["recorder"] = declaration
                self.save("case.json", case)
                before = self.snapshot()
                report = experiment.plan_experiment(self.path)
                self.assertEqual(report["samples"][0]["recorderOverrides"], declaration)
                self.assertEqual(self.snapshot(), before)

    def test_all_cases_and_configuration_overrides_are_checked(self):
        invalid_config = copy.deepcopy(self.manifest["configurations"][0])
        invalid_config.update(configurationId="later")
        for changes in ({"profile": "web"}, {"pluginVersion": "unknown"}):
            with self.subTest(changes=changes):
                invalid_config["configRef"] = {**self.case["configRef"], **changes}
                self.save("experiment.json", {**self.manifest, "configurations": [*self.manifest["configurations"], invalid_config]})
                with self.assertRaises(ValueError):
                    experiment.plan_experiment(self.path)
        self.save("invalid.json", {"invalid": True})
        for path in ("invalid.json", "missing.json"):
            self.save("experiment.json", {**self.manifest, "cases": [*self.manifest["cases"], {"entryId": "later", "casePath": path}]})
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                experiment.plan_experiment(self.path)

    def test_bad_input_returns_plan_error_without_task_outcome_or_output(self):
        for change in ({"repetitions": True}, {"repetitions": 0}, {"configurations": []}, {"typo": 1}):
            self.save("experiment.json", {**self.manifest, **change})
            before = self.snapshot()
            with self.subTest(change=change), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--experiment", str(self.path), "--plan"]), 2)
            report = json.loads(output.getvalue())
            self.assertEqual((report["experimentPlanFormatVersion"], report["valid"]), (1, False))
            self.assertIn("error", report)
            self.assertNotIn("outcome", report)
            self.assertEqual(self.snapshot(), before)

    def test_cli_rejects_other_modes_execution_and_output_controls(self):
        conflicts = (["--run"], ["--evidence", "x"], ["--output", "x"], ["--runs-root", "x"],
                     ["--host-modules", "x"], ["--cancel-after-stream"], ["--reports-root", "x"],
                     ["--cases-root", "x"], ["--port", "0"])
        for extra in conflicts:
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--experiment", str(self.path), "--plan", *extra])
            self.assertEqual(error.exception.code, 2)
        for option in ("--evidence", "--output", "--runs-root", "--host-modules", "--reports-root", "--cases-root"):
            with self.subTest(empty=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--experiment", str(self.path), "--plan", option, ""])
            self.assertEqual(error.exception.code, 2)
        for selection in (["--case", "x"], ["--batch", "x"], ["--report", "x"], ["--browse"]):
            with self.subTest(selection=selection), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main([*selection, "--plan"])
            self.assertEqual(error.exception.code, 2)

    def test_invalid_case_budget_and_recorder_are_rejected_without_side_effects(self):
        for change in ({"budget": {"timeoutSeconds": 0}}, {"recorder": None},
                       {"recorder": {"maxEventBytes": True}}, {"recorder": {"typo": 1}}):
            self.save("case.json", {**self.case, **change})
            before = self.snapshot()
            with self.subTest(change=change), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["--experiment", str(self.path), "--plan"]), 2)
            self.assertFalse(json.loads(output.getvalue())["valid"])
            self.assertEqual(self.snapshot(), before)

    def test_real_cli_stdout_is_utf8_and_valid_json(self):
        before = self.snapshot()
        result = subprocess.run([sys.executable, "-m", "dsh_eval", "--experiment", str(self.path), "--plan"],
                                cwd=ROOT, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(result.stderr, b"")
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(report["experimentName"], "预检")
        self.assertEqual(report["counts"]["samples"], 2)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
